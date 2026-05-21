// axis_config.hpp — PDO 매핑 + 축 상태 + 에러코드 맵
// =====================================================
//
// [역할]
//   EtherCAT 통신에서 모터 ↔ PC 간 교환되는 데이터(PDO)의 구조를 정의하고,
//   축(모터)의 런타임 상태를 관리하며, EPOS4 에러코드를 사람이 읽을 수 있는
//   문자열로 변환하는 유틸리티를 제공.
//
// [PDO (Process Data Object)]
//   EtherCAT은 마스터(PC)와 슬레이브(모터)가 매 사이클(1ms) 고정 크기의
//   데이터를 교환함. 이때 교환되는 데이터의 레이아웃을 PDO라 함.
//
//   OutPDO (PC → 모터):  제어명령 (control_word, 목표 위치/속도/토크, 동작모드)
//   InPDO  (모터 → PC):  피드백   (status_word, 실제 위치/속도/토크)
//
//   ⚠️ 핵심: PDO 구조체의 멤버 순서와 크기가 epos_setup()에서 설정한
//   SDO 매핑(0x1601, 0x1A01)과 정확히 일치해야 함.
//   1바이트라도 어긋나면 WKC(Working Counter) 에러 발생 → 통신 불가.
//   __attribute__((packed))로 컴파일러 패딩 방지.
//
// [더블 버퍼링 (Lock-Free Waveform Config)]
//   RT 스레드(1000Hz)와 ROS2 콜백 스레드가 WaveformConfig를 공유해야 함.
//   mutex를 쓰면 RT 스레드가 블로킹될 수 있으므로,
//   2개의 버퍼를 번갈아 사용하는 더블 버퍼링으로 lock-free 교환:
//
//     Non-RT 스레드: 비활성 버퍼에 쓰기 → atomic index 스위치
//     RT 스레드:     활성 버퍼에서 읽기 (항상 즉시 완료)
//
//   acquire/release 메모리 오더링으로 데이터 가시성 보장:
//     - store(release): 데이터 쓰기 완료 후 인덱스 변경
//     - load(acquire):  인덱스 읽기 시 데이터가 확실히 보임
//
#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include "ethercat/epos_registers.hpp"
#include "waveform/waveform_generator.hpp"

// ══════════════════════════════════════════════════════════════════
// 1. EtherCAT PDO 구조체
// ══════════════════════════════════════════════════════════════════
//
// [OutPDO — RxPDO 0x1601: PC가 모터에 보내는 명령]
//   바이트 레이아웃 (총 11바이트):
//     offset 0:  control_word     (2 bytes, 0x6040)
//     offset 2:  mode_of_operation(1 byte,  0x6060)
//     offset 3:  target_position  (4 bytes, 0x607A)
//     offset 7:  target_velocity  (4 bytes, 0x60FF)
//     offset 11: target_torque    (2 bytes, 0x6071)
//
//   ⚠️ packed 필수: 컴파일러가 mode_of_operation(1byte) 뒤에 패딩을 넣으면
//   target_position이 offset 4에 위치하게 되어 모터가 잘못된 값을 읽음.
struct __attribute__((packed)) OutPDO {
  uint16_t control_word;       // 0x6040 — CiA402 상태 머신 제어
                               //   0x0006: Shutdown (비활성)
                               //   0x0007: Switch On
                               //   0x000F: Enable Operation (모터 활성)
                               //   0x0080: Fault Reset (에러 해제)
  int8_t   mode_of_operation;  // 0x6060 — 동작 모드 선택
                               //   8: CSP (Cyclic Synchronous Position)
                               //   9: CSV (Cyclic Synchronous Velocity)
                               //  10: CST (Cyclic Synchronous Torque)
  int32_t  target_position;    // 0x607A — 목표 위치 [encoder tick] (CSP 모드용)
  int32_t  target_velocity;    // 0x60FF — 목표 속도 [RPM] (CSV 모드용)
  int16_t  target_torque;      // 0x6071 — 목표 토크 [‰ rated torque] (CST 모드용)
};

// [InPDO — TxPDO 0x1A01: 모터가 PC에 보내는 피드백]
//   바이트 레이아웃 (총 12바이트):
//     offset 0:  status_word     (2 bytes, 0x6041)
//     offset 2:  actual_position (4 bytes, 0x6064)
//     offset 6:  actual_velocity (4 bytes, 0x606C)
//     offset 10: actual_torque   (2 bytes, 0x6077)
struct __attribute__((packed)) InPDO {
  uint16_t status_word;        // 0x6041 — CiA402 상태 머신 피드백
                               //   bit 0: Ready to Switch On
                               //   bit 1: Switched On
                               //   bit 2: Operation Enabled
                               //   bit 3: Fault (1이면 에러 상태)
                               //   bit 5: Quick Stop Active
  int32_t  actual_position;    // 0x6064 — 실제 위치 [encoder tick]
  int32_t  actual_velocity;    // 0x606C — 실제 속도 [RPM]
  int16_t  actual_torque;      // 0x6077 — 실제 토크 [‰ rated torque]
};

// ══════════════════════════════════════════════════════════════════
// 2. 축 상태 구조체 (AxisState)
// ══════════════════════════════════════════════════════════════════
// 단일 모터 축의 설정 + 런타임 상태를 관리.
// RT 스레드와 non-RT 스레드 양쪽에서 접근하므로 atomic 사용.
struct AxisState {
  // ── 설정값 (노드 시작 시 초기화, 이후 변경 가능) ─────────────────
  int slave_index = 1;         // EtherCAT 슬레이브 번호 (ec_slave[n])
  std::atomic<int8_t> op_mode{9}; // 현재 동작 모드 (기본: CSV 속도 제어)
  std::string name = "axis0";

  // ── 속도/위치 파형용 더블 버퍼 ────────────────────────────────────
  // [0]과 [1] 두 개의 버퍼 중 하나가 "활성"이고 하나가 "대기".
  // RT 스레드는 활성 버퍼만 읽고, non-RT 스레드는 대기 버퍼에 쓴 뒤 스위치.
  WaveformConfig wf_buffers[2];
  std::atomic<int> active_idx{0};  // 현재 RT가 읽는 버퍼 인덱스

  // ── 실시간 상태 (RT 스레드가 쓰고, non-RT가 읽음) ─────────────────
  // atomic으로 원자적 접근 보장. relaxed ordering 사용 가능
  // (최신 값이 아닌 약간 이전 값을 읽어도 GUI 표시에 문제없으므로).
  std::atomic<int32_t>  last_pos{0};
  std::atomic<int32_t>  last_vel{0};
  std::atomic<int16_t>  last_trq{0};
  std::atomic<uint16_t> last_status{0};
  std::atomic<int32_t>  last_error_code{0};

  // ── 힘 제어용 파형 더블 버퍼 ──────────────────────────────────────
  // 속도 파형과 동일한 더블 버퍼 패턴이지만, 별도 인덱스로 독립 운용.
  // → 속도 파형과 힘 파형이 동시에 각각 다른 설정을 가질 수 있음.
  WaveformConfig force_wf_buf_[2]{};
  std::atomic<int> force_wf_idx_{0};

  // RT 스레드에서 호출: 현재 활성 힘 파형 설정을 값 복사로 가져옴.
  // 복사 시점의 스냅샷이므로, 복사 후 non-RT가 변경해도 안전.
  WaveformConfig get_force_wf_copy() {
    return force_wf_buf_[force_wf_idx_.load(std::memory_order_acquire)];
  }

  // non-RT 스레드에서 호출: 새 힘 파형 설정 적용.
  void set_force_waveform(const WaveformConfig& wf) {
    int next = 1 - force_wf_idx_.load(std::memory_order_relaxed);
    force_wf_buf_[next] = wf;                              // 대기 버퍼에 쓰기
    force_wf_idx_.store(next, std::memory_order_release);  // 활성 전환
  }

  // non-RT 스레드에서 호출: 힘 파형 정지.
  // 기존 설정을 복사한 뒤 type만 NONE으로 변경 → 주파수 등 설정은 보존.
  void stop_force_waveform() {
    int cur = force_wf_idx_.load(std::memory_order_relaxed);
    int next = 1 - cur;
    force_wf_buf_[next] = force_wf_buf_[cur];              // 현재 설정 복사
    force_wf_buf_[next].type = WaveformType::NONE;         // 파형만 끄기
    force_wf_idx_.store(next, std::memory_order_release);
  }

  // ── 속도/위치 파형 더블 버퍼 접근 (위와 동일한 패턴) ───────────────
  WaveformConfig get_waveform_copy() {
    return wf_buffers[active_idx.load(std::memory_order_acquire)];
  }

  void set_waveform(const WaveformConfig& wf) {
    int next_idx = 1 - active_idx.load(std::memory_order_relaxed);
    wf_buffers[next_idx] = wf;
    active_idx.store(next_idx, std::memory_order_release);
  }

  void stop_waveform() {
    int current = active_idx.load(std::memory_order_relaxed);
    int next_idx = 1 - current;
    wf_buffers[next_idx] = wf_buffers[current];
    wf_buffers[next_idx].type = WaveformType::NONE;
    active_idx.store(next_idx, std::memory_order_release);
  }
};

// ══════════════════════════════════════════════════════════════════
// 3. EPOS4 에러코드 → 문자열 변환
// ══════════════════════════════════════════════════════════════════
// EPOS4 매뉴얼의 0x603F (Error Code Register) 값을 사람이 읽을 수 있는 문자열로 변환.
// Fault 발생 시 터미널 로그와 GUI에 표시하기 위해 사용.
// 반환값은 문자열 리터럴 포인터 → 메모리 해제 불필요, 항상 유효.
inline const char* epos_error_str(uint16_t code) {
  switch (code) {
    case 0x0000: return "No error";
    case 0x1000: return "Generic error";
    case 0x2310: return "Over Current";                  // 모터 전류 초과
    case 0x2320: return "Short Circuit / Earth Leakage"; // 단락/누전
    case 0x3210: return "DC Link Over Voltage";          // DC 버스 과전압
    case 0x3220: return "DC Link Under Voltage";         // DC 버스 저전압
    case 0x4210: return "Over Temperature (Drive)";      // 드라이브 과열
    case 0x4380: return "Over Temperature (Motor)";      // 모터 과열
    case 0x5113: return "Supply Voltage Too Low";        // 전원 부족
    case 0x5280: return "Supply Voltage Too High";
    case 0x6100: return "Internal Software Error";       // EPOS4 내부 에러
    case 0x6320: return "Software Parameter Error";
    case 0x7121: return "Motor Blocked (Stall)";         // 모터 구속 — 과부하 or 기계적 막힘
    case 0x7305: return "Incremental Sensor Error";      // 엔코더 에러
    case 0x7306: return "SSI Sensor Error";
    case 0x8110: return "CAN Overrun (Object Lost)";
    case 0x8120: return "CAN in Error Passive Mode";
    case 0x8130: return "CAN Life Guard / Heartbeat";
    case 0x8150: return "CAN PDO COB-ID Collision";
    case 0x8180: return "EtherCAT Communication Error";  // EtherCAT 통신 에러
    case 0x8181: return "EtherCAT PDO Error";            // PDO 크기/매핑 불일치
    case 0x8182: return "EtherCAT RX Queue Overflow (burst)"; // 수신 큐 오버플로
    case 0x8210: return "PDO Not Processed (Length)";    // PDO 길이 에러
    case 0x8611: return "Following Error";               // 위치 추종 에러 (CSP 모드)
    case 0x9000: return "External Error";
    case 0xFF01: return "Hall Sensor Error";             // 홀센서 에러
    case 0xFF0B: return "System Overloaded";             // 시스템 과부하
    default:     return "Unknown Error";
  }
}

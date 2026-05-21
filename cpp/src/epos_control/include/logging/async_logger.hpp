// async_logger.hpp — 비동기 CSV 로거 (RT 스레드 안전)
// ====================================================
//
// [역할]
//   1000Hz RT 루프에서 생성되는 제어 데이터를 CSV 파일로 기록.
//   RT 루프 안에서 직접 파일 I/O를 하면 수십~수백 μs의 지연이 발생하여
//   1000μs(1ms) 주기를 못 맞추게 됨. 이를 해결하기 위해:
//
//     RT 스레드 → 링버퍼에 push (lock-free, ~수십 ns)
//     로거 스레드 → 10ms마다 깨어나서 링버퍼에서 drain → 파일 쓰기
//
//   이렇게 RT 스레드와 파일 I/O를 완전히 분리.
//
// [구조]
//   ┌─────────────┐     push()      ┌──────────────┐     drain()     ┌──────────┐
//   │  RT 스레드   │ ──────────────→ │  RingBuffer  │ ──────────────→ │ CSV 파일  │
//   │  (1000Hz)   │   lock-free     │  (4096 슬롯) │   10ms 간격    │ (디스크)  │
//   └─────────────┘                 └──────────────┘                └──────────┘
//
// [SPSC (Single Producer, Single Consumer) 링버퍼]
//   - Producer: RT 스레드 (push만 호출)
//   - Consumer: 로거 스레드 (drain만 호출)
//   - write_idx만 atomic → push 시 락 불필요
//   - read_idx는 consumer만 접근 → atomic 불필요
//   - 버퍼 크기 4096: 1000Hz에서 약 4초분 데이터 보관 가능
//     → 로거 스레드가 10ms 간격이므로 최대 10~20개만 쌓임 (여유 충분)
//
// [로깅 활성화 흐름]
//   GUI "CSV 로깅 시작" → ROS2 /epos/log_cmd "start /path" → handle_log_cmd()
//     → logger_.start_logging(path) → log_active_ = true
//     → 이후 push_record()로 들어온 데이터가 파일에 기록됨
//
#pragma once

#include <atomic>
#include <chrono>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <ctime>
#include <cstdio>
#include <iostream>
#include <sys/stat.h>    // chmod() — CSV 파일 권한 변경용
#include <unistd.h>      // getuid() — 실제 사용자 UID 확인용
#include <pwd.h>         // getpwuid() — UID → 사용자 정보 변환용

// ══════════════════════════════════════════════════════════════════
// 1. 로그 데이터 구조체 (LogRecord)
// ══════════════════════════════════════════════════════════════════
// RT 루프의 매 사이클 상태를 하나의 레코드로 묶음.
// 모든 멤버가 POD이므로 memcpy로 복사 가능 → 링버퍼 전달에 적합.
struct LogRecord {
  int64_t timestamp_ns;   // 절대 시각 [ns, CLOCK_MONOTONIC]
                          // → CSV에서는 시작 시점 기준 상대 시간(초)으로 변환
  int8_t  op_mode;        // 현재 제어 모드 (8:CSP위치, 9:CSV속도, 10:CST토크)
  int32_t target_pos;     // 모터에 보낸 목표 위치 [encoder tick]
  int32_t actual_pos;     // 모터가 보고한 실제 위치 [encoder tick]
  int32_t target_vel;     // 모터에 보낸 목표 속도 [RPM]
  int32_t actual_vel;     // 모터가 보고한 실제 속도 [RPM]
  int16_t target_trq;     // 모터에 보낸 목표 토크 [‰ rated torque]
  int16_t actual_trq;     // 모터가 보고한 실제 토크 [‰ rated torque]
  int32_t dt_us;          // 이번 제어 주기 실측 [μs] — 이상적으로 1000
  uint16_t status_word;   // EPOS4 상태 워드 (CiA402 상태 머신)
  int32_t error_code;     // EPOS4 에러 코드 (0x603F 레지스터)
  int     wf_type;        // 현재 동작 중인 파형 타입 (WaveformType 캐스팅)
  float   load_cell_N;    // 로드셀 힘 [N] — 선택된 피드백 채널
  float   lc_ch0_N;       // 로드셀 CH0 [N] (시작 쪽)
  float   lc_ch1_N;       // 로드셀 CH1 [N] (끝 쪽)
  float   load_cell_abs_N; // 선택된 피드백 채널 장력 크기 [N]
  float   lc_ch0_abs_N;    // CH0 장력 크기 [N]
  float   lc_ch1_abs_N;    // CH1 장력 크기 [N]
  int32_t linear_encoder_count; // 외부 리니어 엔코더 위치 [count]
  float   linear_encoder_mm;    // 외부 리니어 엔코더 위치 [mm]
};

// ══════════════════════════════════════════════════════════════════
// 2. SPSC 링버퍼 (Single Producer Single Consumer)
// ══════════════════════════════════════════════════════════════════
// 왜 std::queue나 std::deque를 안 쓰는가?
//   → 이들은 내부에서 mutex 또는 동적 메모리 할당을 사용.
//   → RT 스레드에서 호출하면 우선순위 역전(priority inversion)이나
//     페이지 폴트로 인한 예측 불가능한 지연이 발생할 수 있음.
//   → 고정 크기 배열 + atomic index로 lock-free 구현.
//
// [동작 원리]
//   push(): buf_[write_idx % N]에 쓰고, write_idx를 1 증가 (atomic)
//   drain(): read_idx부터 write_idx까지 모든 데이터를 vector에 복사
//            → 한 번에 모아서 파일에 쓰면 시스템 콜 횟수가 줄어 효율적
//
// [오버플로 처리]
//   write가 read보다 N 이상 앞서가면 오래된 데이터가 덮어씌워짐.
//   drain()에서 이를 감지하면 dropped 카운트에 반영.
//   → 로거 스레드가 정상 동작하면 오버플로는 거의 발생하지 않음.
template <typename T, size_t N>
class RingBuffer {
public:
  // RT 스레드에서 호출. lock-free, O(1), 할당 없음.
  void push(const T& val) {
    buf_[write_idx_ % N] = val;   // 현재 쓰기 위치에 데이터 복사
    write_idx_++;                  // atomic increment → consumer에게 새 데이터 알림
  }

  // 로거 스레드에서 호출. 모든 미소비 데이터를 out에 복사.
  // @param dropped 오버플로로 손실된 레코드 수 (선택적 출력)
  // @return 실제로 복사된 레코드 수
  size_t drain(std::vector<T>& out, size_t* dropped = nullptr) {
    size_t w = write_idx_.load();   // 현재 쓰기 위치 (snapshot)
    size_t r = read_idx_;           // 현재 읽기 위치 (이 스레드만 접근)
    if (w <= r) { if (dropped) *dropped = 0; return 0; }

    size_t count = w - r;
    size_t drop = 0;
    if (count > N) {
      // 오버플로: 읽지 못한 데이터가 N개를 초과 → 오래된 것은 이미 덮어씌워짐
      drop = count - N;
      r = w - N;                    // 읽을 수 있는 가장 오래된 위치로 점프
      count = N;
    }
    if (dropped) *dropped = drop;

    out.clear();
    out.reserve(count);
    for (size_t i = r; i < w; i++) {
      out.push_back(buf_[i % N]);  // 링 인덱스로 접근
    }
    read_idx_ = w;                  // 여기까지 소비 완료 표시
    return count;
  }

private:
  T buf_[N]{};                           // 고정 크기 배열 (스택 또는 힙 — 클래스 멤버이므로 힙)
  std::atomic<size_t> write_idx_{0};     // producer만 write, consumer가 read
  size_t read_idx_{0};                   // consumer만 접근 → atomic 불필요
};

// ══════════════════════════════════════════════════════════════════
// 3. 비동기 로거 클래스 (AsyncLogger)
// ══════════════════════════════════════════════════════════════════
// 노드 시작 시 init() → 백그라운드 스레드 생성
// GUI에서 "로깅 시작" → start_logging() → CSV 헤더 기록
// RT 루프 매 사이클 → push_record() → 링버퍼에 삽입
// 백그라운드 스레드 → 10ms마다 drain() → CSV에 batch write
// GUI에서 "로깅 중지" → stop_logging() → 파일 닫기
// 노드 종료 시 → stop() → 스레드 join
class AsyncLogger {
public:
  AsyncLogger() : running_(false), log_active_(false), log_row_count_(0), dropped_count_(0) {}

  ~AsyncLogger() {
    stop();
  }

  // ── 로거 스레드 시작 (노드 생성 시 1번만 호출) ────────────────────
  // 로깅 여부와 무관하게 스레드를 미리 띄워둠.
  // → start_logging()이 호출되면 즉시 기록 시작 가능.
  void init() {
    if (running_.load()) return;
    running_.store(true);
    logger_thread_ = std::thread(&AsyncLogger::process_loop, this);
  }

  // ── 로거 스레드 완전 종료 (노드 소멸 시 호출) ────────────────────
  void stop() {
    running_.store(false);
    if (logger_thread_.joinable()) {
      logger_thread_.join();       // 스레드가 끝날 때까지 대기
    }
    stop_logging();                // 혹시 열린 파일이 있으면 닫기
  }

  // ── CSV 기록 시작 ────────────────────────────────────────────────
  // @param path CSV 파일 경로 (GUI에서 생성하여 전달)
  // @return 성공 시 true
  bool start_logging(const std::string& path) {
    return start_logging_window(path, now_ns(), 0);
  }

  bool start_logging_window(const std::string& path, int64_t start_ns, int64_t end_ns) {
    std::lock_guard<std::mutex> lock(log_mutex_);
    if (log_file_.is_open()) close_file_locked();

    log_file_.open(path, std::ios::out | std::ios::trunc);
    if (!log_file_.is_open()) return false;

    log_path_ = path;
    log_start_ns_ = start_ns;      // CSV 시간 기준점: 로깅 시작 시각
    log_end_ns_ = end_ns;          // 0이면 수동 stop까지 계속 기록
    log_row_count_ = 0;
    dropped_count_.store(0, std::memory_order_relaxed);
    log_active_.store(true, std::memory_order_release);
    // release → process_loop의 acquire와 쌍: 파일이 열린 후에만 쓰기 시작

    // CSV 헤더 한 줄 기록
    log_file_ << "time_s,op_mode,target_pos,actual_pos,target_vel,actual_vel,"
                 "target_trq,actual_trq,cycle_dt_us,status_word,error_code,"
                 "waveform_type,load_cell_N,lc_ch0_N,lc_ch1_N,"
                 "load_cell_abs_N,lc_ch0_abs_N,lc_ch1_abs_N,"
                 "linear_encoder_count,linear_encoder_mm\n";
    log_file_.flush();
    return true;
  }

  // ── CSV 기록 중지 ────────────────────────────────────────────────
  void stop_logging() {
    std::lock_guard<std::mutex> lock(log_mutex_);
    log_active_.store(false, std::memory_order_release);
    close_file_locked();
  }

  // ── RT 루프에서 호출: 데이터를 링버퍼에 넣기만 함 ─────────────────
  // 파일 I/O 없음 → 수십 나노초만 소요.
  // 로깅 비활성 시에도 호출 가능 (process_loop에서 무시됨).
  void push_record(const LogRecord& rec) {
    log_queue_.push(rec);
  }

  bool is_active() const { return log_active_.load(std::memory_order_acquire); }
  uint64_t get_row_count() const { return log_row_count_; }
  uint64_t get_dropped_count() const { return dropped_count_.load(std::memory_order_relaxed); }

private:
  std::mutex log_mutex_;                    // start/stop 시에만 사용 (RT 경로 아님)
  std::ofstream log_file_;
  std::string log_path_;
  std::atomic<bool> log_active_;
  int64_t log_start_ns_{0};                // CSV 시간 기준점
  int64_t log_end_ns_{0};                  // 0이면 시간창 제한 없음
  uint64_t log_row_count_{0};              // 기록된 총 행 수
  std::atomic<uint64_t> dropped_count_;    // 링버퍼 오버플로로 손실된 레코드 수

  RingBuffer<LogRecord, 4096> log_queue_;  // RT → 로거 데이터 전달 경로
  std::thread logger_thread_;
  std::atomic<bool> running_;

  void close_file_locked() {
    if (log_file_.is_open()) {
      log_file_.flush();
      log_file_.close();
    }
    // C++ 노드가 sudo(root)로 실행되므로 CSV 파일이 root 소유로 생성됨.
    // → 일반 사용자가 파일을 열 수 없어 파일 탐색기에서 자물쇠 표시가 나타남.
    // 해결: 파일 권한을 644로 바꾸고, 소유자를 sudo 실행 전 원래 사용자로 변경.
    if (!log_path_.empty()) {
      if (::chmod(log_path_.c_str(), 0644) != 0) {
        std::cerr << "[AsyncLogger] chmod failed: " << log_path_ << "\n";
      }
      // SUDO_UID: sudo로 실행할 때 원래 사용자의 UID가 환경변수에 자동 저장됨.
      // 예: user(UID=1000)가 sudo로 실행 → SUDO_UID="1000"
      const char* sudo_uid = getenv("SUDO_UID");
      const char* sudo_gid = getenv("SUDO_GID");
      if (sudo_uid && sudo_gid) {
        if (::chown(log_path_.c_str(), std::atoi(sudo_uid), std::atoi(sudo_gid)) != 0) {
          std::cerr << "[AsyncLogger] chown failed: " << log_path_ << "\n";
        }
      }
    }
  }

  static int64_t now_ns() {
    timespec ts{};
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000000000LL + ts.tv_nsec;
  }

  // ── 백그라운드 파일 저장 루프 ────────────────────────────────────
  // 10ms마다 깨어나서 링버퍼를 비우고 파일에 기록.
  // batch write: 여러 레코드를 모아서 한 번에 write → 시스템 콜 최소화.
  void process_loop() {
    std::vector<LogRecord> batch;
    batch.reserve(2000);           // 최대 2초분 데이터 (1000Hz × 2s)

    while (running_.load()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));  // 10ms 간격

      size_t dropped = 0;
      size_t count = log_queue_.drain(batch, &dropped);
      if (dropped > 0) dropped_count_.fetch_add(dropped, std::memory_order_relaxed);

      if (count > 0) {
        std::lock_guard<std::mutex> lock(log_mutex_);
        // acquire: start_logging의 release와 쌍 → 파일이 확실히 열린 상태에서만 쓰기
        if (log_active_.load(std::memory_order_acquire) && log_file_.is_open()) {
          char buf[640];
          bool reached_end = false;
          for (const auto& row : batch) {
            if (row.timestamp_ns < log_start_ns_) {
              continue;
            }
            if (log_end_ns_ > 0 && row.timestamp_ns >= log_end_ns_) {
              reached_end = true;
              continue;
            }
            // timestamp_ns를 로깅 시작 기준 상대 시간(초)으로 변환
            double t = static_cast<double>(row.timestamp_ns - log_start_ns_) / 1.0e9;
            int len = std::snprintf(buf, sizeof(buf),
                "%.6f,%d,%d,%d,%d,%d,%d,%d,%d,%u,%d,%d,%.4f,%.4f,%.4f,%.4f,%.4f,%.4f,%d,%.4f\n",
                t, row.op_mode, row.target_pos, row.actual_pos,
                row.target_vel, row.actual_vel, row.target_trq, row.actual_trq,
                row.dt_us, row.status_word, row.error_code, row.wf_type,
                row.load_cell_N, row.lc_ch0_N, row.lc_ch1_N,
                row.load_cell_abs_N, row.lc_ch0_abs_N, row.lc_ch1_abs_N,
                row.linear_encoder_count, row.linear_encoder_mm);
            if (len > 0) {
                log_file_.write(buf, len);
            }
            log_row_count_++;
          }
          if (reached_end) {
            log_active_.store(false, std::memory_order_release);
            close_file_locked();
          } else {
            // 1000행마다 flush → 디스크 반영 보장 (크래시 시 데이터 손실 최소화)
            if (log_row_count_ > 0 && log_row_count_ % 1000 == 0) {
               log_file_.flush();
            }
          }
        }
      }
      batch.clear();
    }
  }
};

// waveform_generator.hpp — 실시간 파형 생성기
// =====================================================
//
// [역할]
//   사인(sine), 사각(square), 삼각(triangle), 처프(chirp) 파형을 생성하여
//   모터 속도 명령(RPM) 또는 힘 목표(mN)로 사용.
//   1000Hz RT 루프에서 매 사이클 호출되므로, 동적 메모리 할당 없이
//   순수 수학 함수(sin, fmod)만 사용.
//
// [파형 종류]
//   - SINE:     정현파. 가장 기본적인 진동 파형. 주파수 응답 분석에 적합.
//   - SQUARE:   사각파. 급격한 방향 전환 테스트용. 시스템 응답 시간 측정.
//   - TRIANGLE: 삼각파. 일정 속도로 가감속. 선형 동작 특성 확인.
//   - CHIRP:    주파수가 시간에 따라 f0→f1로 선형 증가. 주파수 스윕 실험용.
//               → 한 번의 실험으로 넓은 주파수 대역의 응답을 측정할 수 있음.
//
// [사용 경로]
//   GUI → ROS2 토픽(/epos/waveform_cmd) → handle_waveform_cmd()
//     → parse_command()로 문자열 파싱 → WaveformConfig 생성
//     → AxisState의 더블버퍼에 저장 → RT루프에서 compute()로 값 계산
//
// [단위]
//   - 속도 파형: amp_rpm, offset_rpm [RPM], freq_hz [Hz]
//   - 힘 파형:   amp=mN, offset=mN (force_pid 경로에서 사용 시)
//
#pragma once
#include <cmath>
#include <cstdint>
#include <algorithm>
#include <string>
#include <sstream>

// M_PI가 정의되지 않은 컴파일러 대비 (MSVC 등)
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

// ── 파형 타입 열거형 ────────────────────────────────────────────────
// int로 캐스팅 가능하도록 기반 타입 지정 → CSV 로깅 시 숫자로 기록됨
enum class WaveformType : int {
  NONE     = 0,   // 파형 없음 (수동 제어 모드)
  SINE     = 1,
  SQUARE   = 2,
  TRIANGLE = 3,
  CHIRP    = 4,
  POSITION_SINE = 5
};

// ── 문자열 ↔ WaveformType 변환 ─────────────────────────────────────
// GUI에서 "sine 1.0 500 0" 같은 문자열 명령을 보내므로 파싱 시 필요.
inline WaveformType waveform_type_from_string(const std::string& s) {
  if (s == "sine")     return WaveformType::SINE;
  if (s == "square")   return WaveformType::SQUARE;
  if (s == "triangle") return WaveformType::TRIANGLE;
  if (s == "chirp")    return WaveformType::CHIRP;
  return WaveformType::NONE;
}

inline const char* waveform_type_to_string(WaveformType t) {
  switch (t) {
    case WaveformType::SINE:     return "sine";
    case WaveformType::SQUARE:   return "square";
    case WaveformType::TRIANGLE: return "triangle";
    case WaveformType::CHIRP:    return "chirp";
    case WaveformType::POSITION_SINE: return "position_sine";
    default:                     return "none";
  }
}

// ── 파형 설정 구조체 ────────────────────────────────────────────────
// RT루프와 non-RT 스레드 간에 AxisState의 더블버퍼를 통해 교환됨.
// 모든 멤버가 POD(Plain Old Data)이므로 memcpy 안전, atomic 없이 더블버퍼로 교환 가능.
struct WaveformConfig {
  WaveformType type = WaveformType::NONE;
  double freq_hz     = 1.0;     // 기본 주파수 [Hz]
  double amp_rpm     = 500.0;   // 진폭 [RPM 또는 mN] — 파형의 최대 크기
  double offset_rpm  = 0.0;     // 오프셋 [RPM 또는 mN] — 파형의 중심값
  int64_t start_ns   = 0;       // 파형 시작 시각 [나노초, CLOCK_MONOTONIC 기준]
                                // → elapsed = now_ns - start_ns 로 경과 시간 계산
  double amp_pos_ticks = 0.0;   // 위치 사인파 진폭 [encoder tick]
  double offset_pos_ticks = 0.0;// 위치 사인파 오프셋 [encoder tick]
  double max_pos_tps = 0.0;     // 위치 사인파 추종 속도 제한 [tick/s]
  // chirp 전용 파라미터
  double freq_end_hz = 10.0;    // chirp 종료 주파수 [Hz]
  double duration_s  = 0.0;     // 0이면 무한 지속. 0보다 크면 지속 시간 후 자동 정지.
};

namespace waveform {

// ── 파형 값 계산 (RT 루프에서 매 사이클 호출) ───────────────────────
// @param wf     현재 파형 설정 (더블버퍼에서 복사해 온 것)
// @param now_ns 현재 시각 [나노초, CLOCK_MONOTONIC]
// @return       이번 사이클의 파형 값 [RPM 또는 mN]
inline int32_t compute(const WaveformConfig& wf, int64_t now_ns) {
  if (wf.type == WaveformType::NONE) return 0;

  // 경과 시간(초) = (현재 - 시작) / 10^9
  const double elapsed = static_cast<double>(now_ns - wf.start_ns) / 1.0e9;
  if (elapsed < 0.0) return 0;  // 미래 시작 예약: 시작 전에는 정지 상태 유지
  if (wf.duration_s > 0.0 && elapsed >= wf.duration_s) return 0;

  // phase = freq * elapsed → 1.0이 한 주기 완료를 의미
  const double phase = wf.freq_hz * elapsed;
  double value = 0.0;

  switch (wf.type) {
    case WaveformType::SINE:
      // 표준 정현파: offset + amp * sin(2π * f * t)
      value = wf.offset_rpm + wf.amp_rpm * std::sin(2.0 * M_PI * phase);
      break;

    case WaveformType::SQUARE:
      // 사각파: 주기의 전반부 +1, 후반부 -1
      // fmod(phase, 1.0) → 0~1 범위의 주기 내 위치
      value = wf.offset_rpm + wf.amp_rpm * ((std::fmod(phase, 1.0) < 0.5) ? 1.0 : -1.0);
      break;

    case WaveformType::TRIANGLE: {
      // 삼각파: 0→0.25 구간 상승, 0.25→0.75 구간 하강, 0.75→1.0 구간 재상승
      // 총 4구간으로 나눠 선형 보간하여 -1~+1 범위의 삼각파 생성
      const double t = std::fmod(phase, 1.0);
      const double tri = (t < 0.25) ? 4.0 * t              // 0→1 상승
                       : (t < 0.75) ? 2.0 - 4.0 * t        // 1→-1 하강
                       : 4.0 * t - 4.0;                     // -1→0 재상승
      value = wf.offset_rpm + wf.amp_rpm * tri;
      break;
    }

    case WaveformType::CHIRP: {
      // 처프(Chirp): 주파수가 f0에서 f1으로 선형 증가하는 사인파.
      // 용도: 한 번의 실험으로 넓은 주파수 범위의 시스템 응답을 측정.
      //
      // 순시 주파수 f(t) = f0 + (f1 - f0) * t / duration
      // 누적 위상 φ(t) = f0*t + (f1-f0)*t²/(2*duration)
      //   → 위상을 적분해야 연속적인 파형이 됨 (순시주파수를 직접 sin에 넣으면 불연속)
      const double cum_phase = wf.freq_hz * elapsed
                             + (wf.freq_end_hz - wf.freq_hz) * elapsed * elapsed / (2.0 * wf.duration_s);
      value = wf.offset_rpm + wf.amp_rpm * std::sin(2.0 * M_PI * cum_phase);
      break;
    }

    default: value = 0.0; break;
  }
  return static_cast<int32_t>(std::lround(value));
}

// ── 문자열 명령 파싱 결과 ───────────────────────────────────────────
struct ParseResult {
  WaveformConfig config;
  bool is_stop = false;         // "none" 또는 "stop" 명령인 경우 true
  std::string error_msg;        // 파싱 실패 시 에러 메시지
};

// ── 문자열 명령 파싱 ────────────────────────────────────────────────
// GUI에서 ROS2 토픽으로 보내는 문자열을 WaveformConfig로 변환.
//
// 명령 형식:
//   일반 파형: "sine 1.0 500 0"          → type freq amp offset
//   처프:      "chirp 0.1 10.0 500 0 30" → type f0 f1 amp offset duration
//   정지:      "none" 또는 "stop"
//
// @param cmd    명령 문자열
// @param max_abs 최대 허용 진폭/오프셋 (안전 제한)
// @param now_ns 현재 시각 (파형 시작 시각으로 기록)
inline ParseResult parse_command(const std::string& cmd, int max_abs, int64_t now_ns) {
  ParseResult result;
  std::istringstream iss(cmd);
  std::string type_str;
  iss >> type_str;

  // 정지 명령
  if (type_str == "none" || type_str == "stop") {
    result.config.type = WaveformType::NONE;
    result.is_stop = true;
    return result;
  }

  WaveformType wtype = waveform_type_from_string(type_str);
  if (wtype == WaveformType::NONE) {
    result.error_msg = "Unknown waveform type: " + type_str;
    return result;
  }

  result.config.type = wtype;
  result.config.start_ns = now_ns;  // 지금부터 파형 시작

  if (wtype == WaveformType::CHIRP) {
    // chirp는 시작/종료 주파수, 지속시간이 추가로 필요
    double f0 = 0.1, f1 = 10.0, dur = 30.0;
    double amp = 500.0, offset = 0.0;
    iss >> f0 >> f1 >> amp >> offset >> dur;
    // 각 값을 안전 범위로 클램프 (비정상 입력 방어)
    result.config.freq_hz     = std::max(0.001, std::min(500.0, f0));
    result.config.freq_end_hz = std::max(0.001, std::min(500.0, f1));
    result.config.duration_s  = std::max(1.0, std::min(3600.0, dur));
    result.config.amp_rpm     = std::max(0.0, std::min(static_cast<double>(max_abs), amp));
    result.config.offset_rpm  = std::max(static_cast<double>(-max_abs), std::min(static_cast<double>(max_abs), offset));
  } else {
    // 일반 파형: freq amp offset [duration_s]
    double freq = 1.0, dur = 0.0;
    double amp = 500.0, offset = 0.0;
    iss >> freq >> amp >> offset;
    if (iss >> dur) {
      result.config.duration_s = std::max(0.0, std::min(3600.0, dur));
    }
    result.config.freq_hz    = std::max(0.001, std::min(1000.0, freq));
    result.config.amp_rpm    = std::max(0.0, std::min(static_cast<double>(max_abs), amp));
    result.config.offset_rpm = std::max(static_cast<double>(-max_abs), std::min(static_cast<double>(max_abs), offset));
  }
  return result;
}
} // namespace waveform

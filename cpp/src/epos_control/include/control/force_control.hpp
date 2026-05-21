// force_control.hpp — RT-safe force feedback selection and controller dispatch
// =============================================================================
//
// [역할]
//   RT 루프에서 사용하는 힘 제어 보조 함수들을 모아둔다.
//   - CH0/CH1/평균/큰 채널 중 어떤 힘 값을 제어에 사용할지 선택
//   - PID 또는 Tanh 제어기를 호출하여 최종 모터 RPM 명령 계산
//
// [주의]
//   이 파일의 함수는 1000Hz RT 루프 안에서 호출된다.
//   동적 할당, 로그 출력, ROS 호출 없이 순수 산술만 수행해야 한다.
//
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "control/force_pid.hpp"
#include "waveform/waveform_generator.hpp"

namespace epos_control {

struct ForceFeedbackSelection {
  int32_t signed_mN = 0;   // 선택된 힘. 부호를 유지한다.
  int32_t abs_mN = 0;      // 선택된 힘의 절댓값 계열. CSV/절대값 제어에 사용한다.
  int32_t control_mN = 0;  // 실제 제어기에 들어갈 힘 값.
};

inline ForceFeedbackSelection select_force_feedback(
    int32_t force_ch0_mN,
    int32_t force_ch1_mN,
    int32_t feedback_mode,
    bool force_abs_mode) {
  ForceFeedbackSelection selected;

  switch (feedback_mode) {
    case 1:  // CH1
      selected.signed_mN = force_ch1_mN;
      selected.abs_mN = std::abs(force_ch1_mN);
      break;
    case 2:  // CH0/CH1 평균
      selected.signed_mN = (force_ch0_mN + force_ch1_mN) / 2;
      selected.abs_mN = (std::abs(force_ch0_mN) + std::abs(force_ch1_mN)) / 2;
      break;
    case 3:  // 절댓값이 큰 채널
      selected.signed_mN = (std::abs(force_ch1_mN) > std::abs(force_ch0_mN))
                         ? force_ch1_mN
                         : force_ch0_mN;
      selected.abs_mN = std::max(std::abs(force_ch0_mN), std::abs(force_ch1_mN));
      break;
    case 0:  // CH0
    default:
      selected.signed_mN = force_ch0_mN;
      selected.abs_mN = std::abs(force_ch0_mN);
      break;
  }

  selected.control_mN = force_abs_mode ? selected.abs_mN : selected.signed_mN;
  return selected;
}

struct ForceControlParams {
  int32_t target_force_mN = 0;
  int32_t direction = 1;
  int32_t max_rpm = 0;
  int32_t ctrl_mode = 0;  // 0=PID, 1=Tanh
  int32_t fallback_max_rpm = 3000;
  double kp = 0.0;
  double ki = 0.0;
  double kd = 0.0;
  double tanh_sensitivity_mN = 1000.0;
  double tanh_deadband_mN = 10.0;
  double output_alpha = 0.3;
};

struct ForceControlOutput {
  double target_mN = 0.0;
  double actual_mN = 0.0;
  double axis_rpm = 0.0;      // 힘 증가 방향을 기준으로 한 제어 출력
  double motor_rpm = 0.0;     // direction을 반영한 실제 모터 RPM
  double filtered_rpm = 0.0;  // IIR 필터 후 RPM
  int32_t target_rpm = 0;
};

inline ForceControlOutput compute_force_control_command(
    const WaveformConfig& force_waveform,
    int64_t now_ns,
    int32_t actual_force_mN,
    const ForceControlParams& params,
    double previous_filtered_rpm,
    int64_t dt_ns,
    ::ForcePID& pid,
    ::ForceTanh& tanh) {
  ForceControlOutput out;

  if (force_waveform.type != WaveformType::NONE) {
    out.target_mN = static_cast<double>(waveform::compute(force_waveform, now_ns));
  } else {
    out.target_mN = static_cast<double>(params.target_force_mN);
  }

  out.actual_mN = static_cast<double>(actual_force_mN);
  const double max_rpm = static_cast<double>(
      params.max_rpm > 0 ? params.max_rpm : params.fallback_max_rpm);

  if (params.ctrl_mode == 1) {
    tanh.max_rpm = max_rpm;
    tanh.sensitivity_mN = params.tanh_sensitivity_mN;
    tanh.deadband_mN = params.tanh_deadband_mN;
    out.axis_rpm = tanh.compute(out.target_mN, out.actual_mN);
  } else {
    pid.kp = params.kp;
    pid.ki = params.ki;
    pid.kd = params.kd;
    pid.output_limit = max_rpm;
    const double dt_s = static_cast<double>(dt_ns) / 1.0e9;
    out.axis_rpm = pid.compute(out.target_mN, out.actual_mN, dt_s);
  }

  out.motor_rpm = static_cast<double>(params.direction) * out.axis_rpm;

  // Tanh 제어가 데드밴드 안에 들어온 경우 필터 잔류값도 즉시 제거해 정지감을 만든다.
  if (params.ctrl_mode == 1 && std::abs(out.axis_rpm) < 1e-9) {
    out.filtered_rpm = 0.0;
  } else {
    out.filtered_rpm = params.output_alpha * out.motor_rpm
                     + (1.0 - params.output_alpha) * previous_filtered_rpm;
  }

  out.target_rpm = static_cast<int32_t>(std::lround(out.filtered_rpm));
  return out;
}

}  // namespace epos_control

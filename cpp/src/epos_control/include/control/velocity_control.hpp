// velocity_control.hpp — CSV 속도 제어 명령 계산
// =================================================
//
// [역할]
//   RT 루프의 mode 9(CSV, Cyclic Synchronous Velocity) 출력 계산을 담당한다.
//   - 파형이 활성화된 경우: C++ 파형 생성기 값을 그대로 RPM 명령으로 사용
//   - 일반 속도 제어인 경우: 목표 RPM으로 slew-rate limiter를 적용해 부드럽게 접근
//
// [주의]
//   1000Hz RT 루프에서 호출되므로 동적 할당 없이 순수 계산만 수행한다.
//
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "control/slew_rate_limiter.hpp"
#include "waveform/waveform_generator.hpp"

namespace epos_control {

struct VelocityControlResult {
  int32_t target_rpm = 0;       // EPOS CSV target_velocity [RPM]
  int32_t hold_position = 0;    // CSV 모드에서 target_position에 넣을 현재 위치
  double filtered_rpm = 0.0;    // 다음 사이클 slew-rate 상태로 이어갈 값
  bool waveform_active = false;
};

inline VelocityControlResult compute_velocity_csv_command(
    const WaveformConfig& wf,
    int64_t now_ns,
    int32_t current_pos,
    int32_t requested_target_rpm,
    int32_t accel_limit_rpm_s,
    int32_t max_abs_rpm,
    double previous_filtered_rpm,
    int64_t dt_ns)
{
  VelocityControlResult result;
  result.hold_position = current_pos;
  result.waveform_active = (wf.type != WaveformType::NONE);

  if (result.waveform_active) {
    // 파형 실험에서는 파형 충실도를 우선한다. 가속도 제한은 적용하지 않는다.
    result.target_rpm = waveform::compute(wf, now_ns);
    result.filtered_rpm = static_cast<double>(result.target_rpm);
  } else {
    result.filtered_rpm = apply_slew_rate_limit(
        previous_filtered_rpm,
        static_cast<double>(requested_target_rpm),
        static_cast<double>(accel_limit_rpm_s),
        dt_ns);
    result.target_rpm = static_cast<int32_t>(std::lround(result.filtered_rpm));
  }

  const int32_t limit = std::max(0, max_abs_rpm);
  result.target_rpm = std::max(-limit, std::min(limit, result.target_rpm));
  return result;
}

}  // namespace epos_control

// position_control.hpp — 위치 목표를 CSV 속도 명령으로 변환
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "waveform/waveform_generator.hpp"

namespace epos_control {

struct PositionControlState {
  int64_t active_wave_start_ns = 0;  // 현재 위치 사인파 시작 시각
  int32_t wave_base_pos = 0;         // 위치 사인파 기준 시작 위치 [tick]
};

struct PositionControlResult {
  int32_t target_pos = 0;        // RT 루프가 target_pos_에 다시 저장할 목표 위치 [tick]
  int32_t target_rpm = 0;        // EPOS CSV target_velocity [RPM]
  bool wave_active = false;
  bool wave_finished = false;
};

inline PositionControlResult compute_position_csv_command(const WaveformConfig& wf,
                                                          int64_t now_ns,
                                                          int32_t current_pos,
                                                          int32_t requested_target_pos,
                                                          int32_t speed_limit_tps,
                                                          double p_gain,
                                                          int motor_ticks_per_rev,
                                                          PositionControlState& state)
{
  PositionControlResult result;
  result.target_pos = requested_target_pos;

  double pos_ff_tps = 0.0;
  result.wave_active = (wf.type == WaveformType::POSITION_SINE);

  if (result.wave_active) {
    const double elapsed_raw = static_cast<double>(now_ns - wf.start_ns) / 1.0e9;
    if (elapsed_raw < 0.0) {
      result.target_pos = current_pos;
    } else {
      if (state.active_wave_start_ns != wf.start_ns) {
        state.active_wave_start_ns = wf.start_ns;
        state.wave_base_pos = current_pos;
      }

      double elapsed = elapsed_raw;
      if (wf.duration_s > 0.0 && elapsed >= wf.duration_s) {
        elapsed = wf.duration_s;
        result.wave_finished = true;
      }

      const double angle = 2.0 * M_PI * wf.freq_hz * elapsed;
      const double desired_pos = static_cast<double>(state.wave_base_pos)
                               + wf.offset_pos_ticks
                               + wf.amp_pos_ticks * (1.0 - std::cos(angle));
      result.target_pos = static_cast<int32_t>(std::lround(desired_pos));

      if (!result.wave_finished) {
        pos_ff_tps = wf.amp_pos_ticks * 2.0 * M_PI * wf.freq_hz * std::sin(angle);
      }
    }
  } else {
    state.active_wave_start_ns = 0;
  }

  int32_t max_tps = speed_limit_tps;
  if (max_tps <= 0) max_tps = 10000;
  if (result.wave_active && wf.max_pos_tps > 1.0) {
    max_tps = std::max(max_tps, static_cast<int32_t>(std::lround(wf.max_pos_tps)));
  }

  const int32_t pos_error = result.target_pos - current_pos;
  double calc_tps = static_cast<double>(pos_error) * p_gain + pos_ff_tps;
  calc_tps = std::max(static_cast<double>(-max_tps), std::min(static_cast<double>(max_tps), calc_tps));

  // 목표 근처에서 미세 왕복을 줄인다. 위치 사인파 진행 중에는 feed-forward를 유지한다.
  if ((!result.wave_active || result.wave_finished) && std::abs(pos_error) <= 3) {
    calc_tps = 0.0;
  }

  const double rpm_per_tps = 60.0 / static_cast<double>(std::max(1, motor_ticks_per_rev));
  result.target_rpm = static_cast<int32_t>(std::lround(calc_tps * rpm_per_tps));
  return result;
}

}  // namespace epos_control

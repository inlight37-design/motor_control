// hysteresis_plan.hpp — 히스테리시스 테스트 파형과 로깅 시간창 계산
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>

#include "commands/command_parsing.hpp"
#include "waveform/waveform_generator.hpp"

namespace epos_control {

inline constexpr int64_t HYST_START_LEAD_NS = 250000000LL;

struct HysteresisPlan {
  bool ok = false;
  std::string error;
  std::string path;
  WaveformConfig waveform;
  int64_t log_start_ns = 0;
  int64_t log_end_ns = 0;

  double freq_hz = 0.0;
  double amp = 0.0;
  double offset = 0.0;
  double max_tps = 0.0;
  int settle_cycles = 0;
  int record_cycles = 0;
};

inline bool invalid_hyst_common(double freq_hz, int settle_cycles, int record_cycles, const std::string& path)
{
  return path.empty() || !std::isfinite(freq_hz) || settle_cycles < 0 || record_cycles < 1;
}

inline void fill_hyst_timing(HysteresisPlan& plan, int64_t now_ns)
{
  const double period_s = 1.0 / plan.freq_hz;
  const double settle_s = static_cast<double>(plan.settle_cycles) * period_s;
  const double record_s = static_cast<double>(plan.record_cycles) * period_s;
  const double total_s = settle_s + record_s;

  const int64_t waveform_start_ns = now_ns + HYST_START_LEAD_NS;
  plan.log_start_ns = waveform_start_ns + static_cast<int64_t>(std::llround(settle_s * 1.0e9));
  plan.log_end_ns = plan.log_start_ns + static_cast<int64_t>(std::llround(record_s * 1.0e9));
  plan.waveform.start_ns = waveform_start_ns;
  plan.waveform.duration_s = total_s;
}

inline HysteresisPlan make_hyst_velocity_plan(const commands::HystVelocityCommand& cmd,
                                              int max_abs_target,
                                              int64_t now_ns)
{
  HysteresisPlan plan;
  if (invalid_hyst_common(cmd.freq_hz, cmd.settle_cycles, cmd.record_cycles, cmd.path) ||
      !std::isfinite(cmd.amp_rpm) || !std::isfinite(cmd.offset_rpm)) {
    plan.error = "hyst_sine 파라미터가 유효하지 않습니다.";
    return plan;
  }

  plan.path = cmd.path;
  plan.freq_hz = std::max(0.001, std::min(1000.0, cmd.freq_hz));
  plan.amp = std::max(0.0, std::min(static_cast<double>(max_abs_target), cmd.amp_rpm));
  plan.offset = std::max(static_cast<double>(-max_abs_target), std::min(static_cast<double>(max_abs_target), cmd.offset_rpm));
  plan.settle_cycles = std::max(0, std::min(1000, cmd.settle_cycles));
  plan.record_cycles = std::max(1, std::min(10000, cmd.record_cycles));

  plan.waveform.type = WaveformType::SINE;
  plan.waveform.freq_hz = plan.freq_hz;
  plan.waveform.amp_rpm = plan.amp;
  plan.waveform.offset_rpm = plan.offset;
  fill_hyst_timing(plan, now_ns);
  plan.ok = true;
  return plan;
}

inline HysteresisPlan make_hyst_position_plan(const commands::HystPositionCommand& cmd,
                                              int64_t now_ns)
{
  HysteresisPlan plan;
  if (invalid_hyst_common(cmd.freq_hz, cmd.settle_cycles, cmd.record_cycles, cmd.path) ||
      !std::isfinite(cmd.amp_ticks) || !std::isfinite(cmd.offset_ticks) ||
      !std::isfinite(cmd.max_tps)) {
    plan.error = "hyst_pos_sine 파라미터가 유효하지 않습니다.";
    return plan;
  }

  plan.path = cmd.path;
  plan.freq_hz = std::max(0.001, std::min(1000.0, cmd.freq_hz));
  plan.amp = std::max(0.0, std::min(1.0e8, cmd.amp_ticks));
  plan.offset = std::max(-1.0e8, std::min(1.0e8, cmd.offset_ticks));
  plan.max_tps = std::max(1.0, std::min(1.0e8, cmd.max_tps));
  plan.settle_cycles = std::max(0, std::min(1000, cmd.settle_cycles));
  plan.record_cycles = std::max(1, std::min(10000, cmd.record_cycles));

  plan.waveform.type = WaveformType::POSITION_SINE;
  plan.waveform.freq_hz = plan.freq_hz;
  plan.waveform.amp_pos_ticks = plan.amp;
  plan.waveform.offset_pos_ticks = plan.offset;
  plan.waveform.max_pos_tps = plan.max_tps;
  fill_hyst_timing(plan, now_ns);
  plan.ok = true;
  return plan;
}

}  // namespace epos_control

// slew_rate_limiter.hpp — 속도 명령 변화율 제한 유틸리티
#pragma once

#include <algorithm>
#include <cstdint>

namespace epos_control {

inline double apply_slew_rate_limit(double current,
                                    double target,
                                    double accel_per_s,
                                    int64_t dt_ns)
{
  if (accel_per_s <= 0.0) {
    return target;  // 0은 "제한 없음"
  }

  double max_step = accel_per_s * (static_cast<double>(dt_ns) / 1.0e9);
  if (current < target) return std::min(current + max_step, target);
  if (current > target) return std::max(current - max_step, target);
  return current;
}

}  // namespace epos_control

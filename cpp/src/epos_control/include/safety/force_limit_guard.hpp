// force_limit_guard.hpp — 로드셀 힘 안전 한계 판단
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace epos_control {

struct ForceLimitCheck {
  bool has_valid_data = false;
  bool over_limit = false;
  int32_t peak_mN = 0;
};

inline bool is_recent_sample(int64_t now_ns, int64_t sample_ns, int64_t stale_ns)
{
  int64_t age_ns = now_ns - sample_ns;
  return sample_ns > 0 && age_ns >= 0 && age_ns < stale_ns;
}

inline ForceLimitCheck check_force_limit(int32_t limit_mN,
                                         int64_t now_ns,
                                         int32_t force_ch0_mN,
                                         int32_t force_ch1_mN,
                                         int64_t last_force_ch0_ns,
                                         int64_t last_force_ch1_ns,
                                         int64_t stale_ns = 500000000LL)
{
  ForceLimitCheck result;
  if (limit_mN <= 0) return result;

  bool valid0 = is_recent_sample(now_ns, last_force_ch0_ns, stale_ns);
  bool valid1 = is_recent_sample(now_ns, last_force_ch1_ns, stale_ns);
  result.has_valid_data = valid0 || valid1;
  if (!result.has_valid_data) return result;

  if (valid0) result.peak_mN = std::max(result.peak_mN, std::abs(force_ch0_mN));
  if (valid1) result.peak_mN = std::max(result.peak_mN, std::abs(force_ch1_mN));
  result.over_limit = result.peak_mN > limit_mN;
  return result;
}

}  // namespace epos_control

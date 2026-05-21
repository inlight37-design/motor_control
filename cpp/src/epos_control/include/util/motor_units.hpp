// motor_units.hpp — 모터 제어에서 반복해서 쓰는 단위 변환
#pragma once

#include <cmath>
#include <cstdint>

namespace epos_control {

inline constexpr double N_TO_MN = 1000.0;
inline constexpr double MN_TO_N = 1.0 / N_TO_MN;
inline constexpr double MM_TO_UM = 1000.0;

inline int32_t n_to_mN(double force_N)
{
  if (!std::isfinite(force_N)) return 0;
  return static_cast<int32_t>(std::lround(force_N * N_TO_MN));
}

inline float mN_to_N_float(int32_t force_mN)
{
  return static_cast<float>(static_cast<double>(force_mN) * MN_TO_N);
}

inline int32_t mm_to_um(double position_mm)
{
  if (!std::isfinite(position_mm)) return 0;
  return static_cast<int32_t>(std::lround(position_mm * MM_TO_UM));
}

}  // namespace epos_control


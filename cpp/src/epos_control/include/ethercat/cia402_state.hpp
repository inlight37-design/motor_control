// cia402_state.hpp — EPOS4/CiA402 상태 워드 판단 유틸리티
#pragma once

#include <cstdint>

namespace epos_control::cia402 {

inline constexpr uint16_t CONTROL_SHUTDOWN = 0x0006;
inline constexpr uint16_t CONTROL_SWITCH_ON = 0x0007;
inline constexpr uint16_t CONTROL_ENABLE_OPERATION = 0x000F;
inline constexpr uint16_t CONTROL_FAULT_RESET = 0x0080;

inline bool is_fault(uint16_t status_word)
{
  return (status_word & 0x0008) != 0;
}

inline bool is_operation_enabled(uint16_t status_word)
{
  return (status_word & 0x006F) == 0x0027;
}

inline bool is_switched_on(uint16_t status_word)
{
  return (status_word & 0x006F) == 0x0023;
}

inline bool is_ready_to_switch_on(uint16_t status_word)
{
  return (status_word & 0x006F) == 0x0021;
}

inline uint16_t next_control_word(uint16_t status_word, bool enable_desired)
{
  if (is_operation_enabled(status_word)) {
    return enable_desired ? CONTROL_ENABLE_OPERATION : CONTROL_SHUTDOWN;
  }
  if (is_switched_on(status_word)) {
    return enable_desired ? CONTROL_ENABLE_OPERATION : CONTROL_SHUTDOWN;
  }
  if (is_ready_to_switch_on(status_word)) {
    return enable_desired ? CONTROL_SWITCH_ON : CONTROL_SHUTDOWN;
  }
  return CONTROL_SHUTDOWN;
}

}  // namespace epos_control::cia402

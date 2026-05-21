// output_safety_guard.hpp — 최종 PDO 출력 안전장치
// ==================================================
//
// [역할]
//   모드별 제어 계산이 끝난 뒤, 실제 PDO에 쓰기 직전의 최종 출력에
//   공통 안전 조건을 적용한다.
//   - Fault 또는 disable 상태면 속도/토크 0
//   - 로드셀 힘 한계 초과 시 속도/토크 0
//   - 명령 타임아웃 또는 heartbeat 타임아웃 시 속도/토크 0
//   - 최종 속도 명령은 max_abs_rpm 범위로 클램프
//
// [주의]
//   1000Hz RT 루프에서 호출되므로 로그 출력이나 동적 할당 없이 순수 계산만 수행한다.
//
#pragma once

#include <algorithm>
#include <cstdint>

namespace epos_control {

struct OutputSafetyInput {
  int64_t now_ns = 0;
  bool is_fault = false;
  bool enable_desired = true;
  bool force_limit_tripped = false;
  int32_t cmd_timeout_ms = 0;
  int64_t last_cmd_ns = 0;
  int32_t heartbeat_timeout_ms = 0;
  int64_t last_heartbeat_ns = 0;
  int32_t max_abs_rpm = 3000;
};

struct OutputSafetyResult {
  int32_t target_velocity = 0;
  int16_t target_torque = 0;
  bool stopped = false;
  bool disabled_or_fault = false;
  bool force_limit = false;
  bool command_timeout = false;
  bool heartbeat_timeout = false;
};

inline bool timeout_expired(int64_t now_ns, int64_t last_ns, int32_t timeout_ms)
{
  if (timeout_ms <= 0 || last_ns <= 0) return false;
  const int64_t age_ns = now_ns - last_ns;
  return age_ns > static_cast<int64_t>(timeout_ms) * 1000000LL;
}

inline OutputSafetyResult apply_output_safety(int32_t target_velocity,
                                             int16_t target_torque,
                                             const OutputSafetyInput& input)
{
  OutputSafetyResult result;
  result.target_velocity = target_velocity;
  result.target_torque = target_torque;

  result.disabled_or_fault = input.is_fault || !input.enable_desired;
  result.force_limit = input.force_limit_tripped;
  result.command_timeout = timeout_expired(input.now_ns, input.last_cmd_ns, input.cmd_timeout_ms);
  result.heartbeat_timeout = timeout_expired(input.now_ns, input.last_heartbeat_ns, input.heartbeat_timeout_ms);
  result.stopped = result.disabled_or_fault
                || result.force_limit
                || result.command_timeout
                || result.heartbeat_timeout;

  if (result.stopped) {
    result.target_velocity = 0;
    result.target_torque = 0;
  }

  const int32_t limit = std::max<int32_t>(0, input.max_abs_rpm);
  result.target_velocity = std::max(-limit, std::min(limit, result.target_velocity));
  return result;
}

}  // namespace epos_control

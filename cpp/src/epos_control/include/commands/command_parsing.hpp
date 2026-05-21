// command_parsing.hpp — GUI/스크립트 문자열 명령을 구조화 값으로 변환
#pragma once

#include <algorithm>
#include <cstdint>
#include <cmath>
#include <sstream>
#include <string>

#include "epos_interfaces/msg/force_ctrl_cmd.hpp"
#include "epos_interfaces/msg/waveform_cmd.hpp"
#include "waveform/waveform_generator.hpp"

namespace epos_control::commands {

inline std::string first_token(const std::string& cmd)
{
  std::istringstream iss(cmd);
  std::string token;
  iss >> token;
  return token;
}

inline WaveformType waveform_type_from_msg(uint8_t type)
{
  using epos_interfaces::msg::WaveformCmd;
  switch (type) {
    case WaveformCmd::TYPE_SINE: return WaveformType::SINE;
    case WaveformCmd::TYPE_SQUARE: return WaveformType::SQUARE;
    case WaveformCmd::TYPE_TRIANGLE: return WaveformType::TRIANGLE;
    case WaveformCmd::TYPE_CHIRP: return WaveformType::CHIRP;
    case WaveformCmd::TYPE_POSITION_SINE: return WaveformType::POSITION_SINE;
    default: return WaveformType::NONE;
  }
}

struct HystVelocityCommand {
  double freq_hz = 1.0;
  double amp_rpm = 0.0;
  double offset_rpm = 0.0;
  int settle_cycles = 0;
  int record_cycles = 1;
  std::string path;
};

struct HystPositionCommand {
  double freq_hz = 1.0;
  double amp_ticks = 0.0;
  double offset_ticks = 0.0;
  double max_tps = 0.0;
  int settle_cycles = 0;
  int record_cycles = 1;
  std::string path;
};

template <typename T>
struct CommandParseResult {
  bool ok = false;
  T value{};
  std::string error;
};

inline CommandParseResult<HystVelocityCommand> parse_hyst_velocity(const std::string& cmd)
{
  CommandParseResult<HystVelocityCommand> result;
  std::istringstream iss(cmd);
  std::string action;
  if (!(iss >> action >> result.value.freq_hz >> result.value.amp_rpm >>
        result.value.offset_rpm >> result.value.settle_cycles >>
        result.value.record_cycles)) {
    result.error = "잘못된 hyst_sine 명령";
    return result;
  }
  std::getline(iss >> std::ws, result.value.path);
  result.ok = true;
  return result;
}

inline CommandParseResult<HystPositionCommand> parse_hyst_position(const std::string& cmd)
{
  CommandParseResult<HystPositionCommand> result;
  std::istringstream iss(cmd);
  std::string action;
  if (!(iss >> action >> result.value.freq_hz >> result.value.amp_ticks >>
        result.value.offset_ticks >> result.value.max_tps >>
        result.value.settle_cycles >> result.value.record_cycles)) {
    result.error = "잘못된 hyst_pos_sine 명령";
    return result;
  }
  std::getline(iss >> std::ws, result.value.path);
  result.ok = true;
  return result;
}

enum class WaveformCommandKind {
  UNKNOWN,
  INVALID,
  STOP,
  START_GENERAL,
  START_HYST_VELOCITY,
  START_HYST_POSITION
};

struct WaveformCommand {
  WaveformCommandKind kind = WaveformCommandKind::UNKNOWN;
  std::string error;
  WaveformConfig config;
  HystVelocityCommand hyst_velocity;
  HystPositionCommand hyst_position;
};

inline WaveformCommand waveform_command_from_msg(const epos_interfaces::msg::WaveformCmd& msg,
                                                 int max_abs_target,
                                                 int64_t now_ns)
{
  using epos_interfaces::msg::WaveformCmd;

  WaveformCommand result;
  switch (msg.action) {
    case WaveformCmd::ACTION_STOP:
      result.kind = WaveformCommandKind::STOP;
      return result;

    case WaveformCmd::ACTION_START_HYST_VELOCITY:
      result.kind = WaveformCommandKind::START_HYST_VELOCITY;
      result.hyst_velocity.freq_hz = msg.freq_hz;
      result.hyst_velocity.amp_rpm = msg.amp_rpm;
      result.hyst_velocity.offset_rpm = msg.offset_rpm;
      result.hyst_velocity.settle_cycles = msg.settle_cycles;
      result.hyst_velocity.record_cycles = msg.record_cycles;
      result.hyst_velocity.path = msg.log_path;
      return result;

    case WaveformCmd::ACTION_START_HYST_POSITION:
      result.kind = WaveformCommandKind::START_HYST_POSITION;
      result.hyst_position.freq_hz = msg.freq_hz;
      result.hyst_position.amp_ticks = msg.amp_pos_ticks;
      result.hyst_position.offset_ticks = msg.offset_pos_ticks;
      result.hyst_position.max_tps = msg.max_pos_tps;
      result.hyst_position.settle_cycles = msg.settle_cycles;
      result.hyst_position.record_cycles = msg.record_cycles;
      result.hyst_position.path = msg.log_path;
      return result;

    case WaveformCmd::ACTION_START:
      break;

    default:
      result.kind = WaveformCommandKind::INVALID;
      result.error = "알 수 없는 action=" + std::to_string(msg.action);
      return result;
  }

  WaveformType wtype = waveform_type_from_msg(msg.waveform_type);
  if (wtype == WaveformType::NONE || wtype == WaveformType::POSITION_SINE) {
    result.kind = WaveformCommandKind::INVALID;
    result.error = "일반 파형으로 사용할 수 없는 type=" + std::to_string(msg.waveform_type);
    return result;
  }

  WaveformConfig wf;
  wf.type = wtype;
  wf.start_ns = now_ns;

  if (wtype == WaveformType::CHIRP) {
    if (!std::isfinite(msg.freq_hz) || !std::isfinite(msg.freq_end_hz) ||
        !std::isfinite(msg.amp_rpm) || !std::isfinite(msg.offset_rpm) ||
        !std::isfinite(msg.duration_s)) {
      result.kind = WaveformCommandKind::INVALID;
      result.error = "잘못된 chirp 파라미터";
      return result;
    }
    wf.freq_hz = std::max(0.001, std::min(500.0, msg.freq_hz));
    wf.freq_end_hz = std::max(0.001, std::min(500.0, msg.freq_end_hz));
    wf.duration_s = std::max(1.0, std::min(3600.0, msg.duration_s));
  } else {
    if (!std::isfinite(msg.freq_hz) || !std::isfinite(msg.amp_rpm) ||
        !std::isfinite(msg.offset_rpm) || !std::isfinite(msg.duration_s)) {
      result.kind = WaveformCommandKind::INVALID;
      result.error = "잘못된 파형 파라미터";
      return result;
    }
    wf.freq_hz = std::max(0.001, std::min(1000.0, msg.freq_hz));
    wf.duration_s = std::max(0.0, std::min(3600.0, msg.duration_s));
  }
  wf.amp_rpm = std::max(0.0, std::min(static_cast<double>(max_abs_target), msg.amp_rpm));
  wf.offset_rpm = std::max(static_cast<double>(-max_abs_target), std::min(static_cast<double>(max_abs_target), msg.offset_rpm));

  result.kind = WaveformCommandKind::START_GENERAL;
  result.config = wf;
  return result;
}

inline WaveformCommand waveform_command_from_string(const std::string& cmd,
                                                    int max_abs_target,
                                                    int64_t now_ns)
{
  WaveformCommand result;
  const std::string action = first_token(cmd);

  if (action == "hyst_sine") {
    auto parsed = parse_hyst_velocity(cmd);
    if (!parsed.ok) {
      result.kind = WaveformCommandKind::INVALID;
      result.error = parsed.error;
      return result;
    }
    result.kind = WaveformCommandKind::START_HYST_VELOCITY;
    result.hyst_velocity = parsed.value;
    return result;
  }

  if (action == "hyst_pos_sine") {
    auto parsed = parse_hyst_position(cmd);
    if (!parsed.ok) {
      result.kind = WaveformCommandKind::INVALID;
      result.error = parsed.error;
      return result;
    }
    result.kind = WaveformCommandKind::START_HYST_POSITION;
    result.hyst_position = parsed.value;
    return result;
  }

  auto parsed = waveform::parse_command(cmd, max_abs_target, now_ns);
  if (!parsed.error_msg.empty()) {
    result.kind = WaveformCommandKind::INVALID;
    result.error = parsed.error_msg;
    return result;
  }
  if (parsed.is_stop) {
    result.kind = WaveformCommandKind::STOP;
    return result;
  }

  result.kind = WaveformCommandKind::START_GENERAL;
  result.config = parsed.config;
  return result;
}

enum class ForceCommandKind {
  UNKNOWN,
  INVALID,
  START,
  STOP,
  SET_TARGET,
  SET_DIRECTION,
  SET_FEEDBACK,
  SET_FORCE_ABS,
  SET_PID,
  SET_TANH,
  SET_TARE_OFFSET,
  TARE_RESET,
  SET_MAX_RPM,
  SET_LIMIT,
  SET_ALPHA,
  SET_WAVEFORM
};

struct ForceCommand {
  ForceCommandKind kind = ForceCommandKind::UNKNOWN;
  std::string error;

  double target_N = 0.0;
  int direction = 1;
  int feedback_mode = 0;
  std::string feedback_label;
  int enabled = 1;

  double kp = 0.5;
  double ki = 0.05;
  double kd = 0.01;

  double tanh_sens_N = 1.0;
  double tanh_dead_N = 0.01;

  int tare_channel = -1;
  double tare_offset_N = 0.0;

  int max_rpm = 100;
  double limit_N = 0.0;
  double alpha = 0.3;

  std::string waveform_payload;
};

inline int parse_feedback_mode(const std::string& mode)
{
  if (mode == "ch0" || mode == "0") return 0;
  if (mode == "ch1" || mode == "1") return 1;
  if (mode == "avg" || mode == "average") return 2;
  if (mode == "max" || mode == "absmax") return 3;
  return 0;
}

inline bool is_valid_feedback_mode(const std::string& mode)
{
  return mode == "ch0" || mode == "0" ||
         mode == "ch1" || mode == "1" ||
         mode == "avg" || mode == "average" ||
         mode == "max" || mode == "absmax";
}

inline void invalidate_force_command(ForceCommand& result, const std::string& error)
{
  result.kind = ForceCommandKind::INVALID;
  result.error = error;
}

inline ForceCommand parse_force_ctrl(const std::string& cmd)
{
  ForceCommand result;
  std::istringstream iss(cmd);
  std::string token;
  iss >> token;

  if (token == "start") {
    result.kind = ForceCommandKind::START;
  } else if (token == "stop") {
    result.kind = ForceCommandKind::STOP;
  } else if (token == "target") {
    result.kind = ForceCommandKind::SET_TARGET;
    if (!(iss >> result.target_N) || !std::isfinite(result.target_N)) {
      invalidate_force_command(result, "잘못된 target 명령");
    }
  } else if (token == "direction") {
    result.kind = ForceCommandKind::SET_DIRECTION;
    if (!(iss >> result.direction)) {
      invalidate_force_command(result, "잘못된 direction 명령");
    }
  } else if (token == "feedback") {
    result.kind = ForceCommandKind::SET_FEEDBACK;
    if (!(iss >> result.feedback_label) || !is_valid_feedback_mode(result.feedback_label)) {
      invalidate_force_command(result, "잘못된 feedback 명령");
    } else {
      result.feedback_mode = parse_feedback_mode(result.feedback_label);
    }
  } else if (token == "force_abs" || token == "abs_force" || token == "tension_abs") {
    result.kind = ForceCommandKind::SET_FORCE_ABS;
    if (!(iss >> result.enabled)) {
      invalidate_force_command(result, "잘못된 force_abs 명령");
    }
  } else if (token == "pid") {
    result.kind = ForceCommandKind::SET_PID;
    if (!(iss >> result.kp >> result.ki >> result.kd) ||
        !std::isfinite(result.kp) || !std::isfinite(result.ki) || !std::isfinite(result.kd)) {
      invalidate_force_command(result, "잘못된 PID 명령");
    }
  } else if (token == "tanh") {
    result.kind = ForceCommandKind::SET_TANH;
    if (!(iss >> result.tanh_sens_N >> result.tanh_dead_N) ||
        !std::isfinite(result.tanh_sens_N) || !std::isfinite(result.tanh_dead_N)) {
      invalidate_force_command(result, "잘못된 tanh 명령");
    }
  } else if (token == "tare_offset") {
    result.kind = ForceCommandKind::SET_TARE_OFFSET;
    if (!(iss >> result.tare_channel >> result.tare_offset_N) ||
        (result.tare_channel != 0 && result.tare_channel != 1) ||
        !std::isfinite(result.tare_offset_N)) {
      invalidate_force_command(result, "잘못된 tare_offset 명령");
    }
  } else if (token == "tare_reset") {
    result.kind = ForceCommandKind::TARE_RESET;
  } else if (token == "maxrpm") {
    result.kind = ForceCommandKind::SET_MAX_RPM;
    if (!(iss >> result.max_rpm)) {
      invalidate_force_command(result, "잘못된 maxrpm 명령");
    }
  } else if (token == "limit") {
    result.kind = ForceCommandKind::SET_LIMIT;
    if (!(iss >> result.limit_N) || !std::isfinite(result.limit_N)) {
      invalidate_force_command(result, "잘못된 limit 명령");
    }
  } else if (token == "alpha") {
    result.kind = ForceCommandKind::SET_ALPHA;
    if (!(iss >> result.alpha) || !std::isfinite(result.alpha)) {
      invalidate_force_command(result, "잘못된 alpha 명령");
    }
  } else if (token == "waveform") {
    result.kind = ForceCommandKind::SET_WAVEFORM;
    std::getline(iss >> std::ws, result.waveform_payload);
  }

  return result;
}

inline ForceCommand force_command_from_msg(const epos_interfaces::msg::ForceCtrlCmd& msg)
{
  using epos_interfaces::msg::ForceCtrlCmd;

  ForceCommand result;
  switch (msg.action) {
    case ForceCtrlCmd::ACTION_START:
      result.kind = ForceCommandKind::START;
      break;

    case ForceCtrlCmd::ACTION_STOP:
      result.kind = ForceCommandKind::STOP;
      break;

    case ForceCtrlCmd::ACTION_SET_TARGET:
      result.kind = ForceCommandKind::SET_TARGET;
      if (!std::isfinite(msg.target_n)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 target";
      } else {
        result.target_N = std::max(0.0, msg.target_n);
      }
      break;

    case ForceCtrlCmd::ACTION_SET_DIRECTION:
      result.kind = ForceCommandKind::SET_DIRECTION;
      result.direction = (msg.direction < 0) ? -1 : 1;
      break;

    case ForceCtrlCmd::ACTION_SET_FEEDBACK:
      result.kind = ForceCommandKind::SET_FEEDBACK;
      result.feedback_mode = std::max(0, std::min(3, static_cast<int>(msg.feedback)));
      result.feedback_label = std::to_string(result.feedback_mode);
      break;

    case ForceCtrlCmd::ACTION_SET_FORCE_ABS:
      result.kind = ForceCommandKind::SET_FORCE_ABS;
      result.enabled = msg.force_abs ? 1 : 0;
      break;

    case ForceCtrlCmd::ACTION_SET_PID:
      result.kind = ForceCommandKind::SET_PID;
      if (!std::isfinite(msg.kp) || !std::isfinite(msg.ki) || !std::isfinite(msg.kd)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 PID 파라미터";
      } else {
        result.kp = std::max(0.0, std::min(1000.0, msg.kp));
        result.ki = std::max(0.0, std::min(1000.0, msg.ki));
        result.kd = std::max(0.0, std::min(1000.0, msg.kd));
      }
      break;

    case ForceCtrlCmd::ACTION_SET_TANH:
      result.kind = ForceCommandKind::SET_TANH;
      if (!std::isfinite(msg.tanh_sensitivity_n) || !std::isfinite(msg.tanh_deadband_n)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 tanh 파라미터";
      } else {
        result.tanh_sens_N = std::max(0.01, std::min(50.0, msg.tanh_sensitivity_n));
        result.tanh_dead_N = std::max(0.0, std::min(10.0, msg.tanh_deadband_n));
      }
      break;

    case ForceCtrlCmd::ACTION_SET_TARE_OFFSET:
      result.kind = ForceCommandKind::SET_TARE_OFFSET;
      if ((msg.tare_channel != 0 && msg.tare_channel != 1) || !std::isfinite(msg.tare_offset_n)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 tare_offset";
      } else {
        result.tare_channel = msg.tare_channel;
        result.tare_offset_N = std::max(-100000.0, std::min(100000.0, msg.tare_offset_n));
      }
      break;

    case ForceCtrlCmd::ACTION_TARE_RESET:
      result.kind = ForceCommandKind::TARE_RESET;
      break;

    case ForceCtrlCmd::ACTION_SET_MAX_RPM:
      result.kind = ForceCommandKind::SET_MAX_RPM;
      result.max_rpm = msg.max_rpm;
      break;

    case ForceCtrlCmd::ACTION_SET_LIMIT:
      result.kind = ForceCommandKind::SET_LIMIT;
      if (!std::isfinite(msg.limit_n)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 limit";
      } else {
        result.limit_N = std::max(0.0, msg.limit_n);
      }
      break;

    case ForceCtrlCmd::ACTION_SET_OUTPUT_ALPHA:
      result.kind = ForceCommandKind::SET_ALPHA;
      if (!std::isfinite(msg.output_alpha)) {
        result.kind = ForceCommandKind::INVALID;
        result.error = "잘못된 output_alpha";
      } else {
        result.alpha = std::max(0.01, std::min(1.0, msg.output_alpha));
      }
      break;

    default:
      result.kind = ForceCommandKind::INVALID;
      result.error = "알 수 없는 action=" + std::to_string(msg.action);
      break;
  }

  return result;
}

}  // namespace epos_control::commands

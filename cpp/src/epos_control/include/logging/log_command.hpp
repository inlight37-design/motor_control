// log_command.hpp — CSV 로깅 명령 파싱과 기본 로그 경로 생성
#pragma once

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <filesystem>
#include <sstream>
#include <string>

namespace epos_control {

enum class LogCommandKind {
  UNKNOWN,
  START,
  STOP,
  INVALID
};

struct LogCommand {
  LogCommandKind kind = LogCommandKind::UNKNOWN;
  std::string path;
  std::string error;
};

inline std::string make_default_log_path(std::chrono::system_clock::time_point now = std::chrono::system_clock::now())
{
  auto t = std::chrono::system_clock::to_time_t(now);
  std::tm tm{};
  localtime_r(&t, &tm);

  char filename[128];
  std::snprintf(filename, sizeof(filename), "epos_%04d%02d%02d_%02d%02d%02d.csv",
                tm.tm_year + 1900,
                tm.tm_mon + 1,
                tm.tm_mday,
                tm.tm_hour,
                tm.tm_min,
                tm.tm_sec);

  const char* env_log_dir = std::getenv("EPOS_LOG_DIR");
  std::filesystem::path log_dir =
      (env_log_dir && env_log_dir[0] != '\0')
          ? std::filesystem::path(env_log_dir)
          : (std::filesystem::current_path() / "logs");
  return (log_dir / filename).string();
}

inline LogCommand parse_log_command(const std::string& cmd)
{
  LogCommand result;
  std::istringstream iss(cmd);
  std::string action;
  iss >> action;

  if (action.empty()) {
    return result;
  }
  if (action == "stop") {
    result.kind = LogCommandKind::STOP;
    return result;
  }
  if (action == "start") {
    result.kind = LogCommandKind::START;
    std::getline(iss >> std::ws, result.path);
    if (result.path.empty()) {
      result.path = make_default_log_path();
    }
    return result;
  }

  result.kind = LogCommandKind::INVALID;
  result.error = "알 수 없는 CSV 로깅 명령: " + action;
  return result;
}

}  // namespace epos_control

// net_utils.hpp — 실행 환경 의존 유틸리티
#pragma once

#include <algorithm>
#include <cstdlib>
#include <filesystem>
#include <string>
#include <system_error>
#include <vector>

namespace epos_control {

inline std::string detect_default_iface()
{
  const char* env_iface = std::getenv("EPOS_IFACE");
  if (env_iface && env_iface[0] != '\0') return std::string(env_iface);

  std::vector<std::string> candidates;
  std::error_code ec;
  for (const auto& entry : std::filesystem::directory_iterator("/sys/class/net", ec)) {
    const std::string name = entry.path().filename().string();
    if (name.rfind("enx", 0) == 0 || name.rfind("enp", 0) == 0) {
      candidates.push_back(name);
    }
  }
  std::sort(candidates.begin(), candidates.end());
  return candidates.empty() ? std::string{} : candidates.front();
}

}  // namespace epos_control


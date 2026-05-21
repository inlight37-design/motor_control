// file_utils.hpp — 로그 파일 경로와 디렉토리 보조 함수
#pragma once

#include <filesystem>
#include <string>
#include <system_error>

namespace epos_control {

struct EnsureParentDirResult {
  bool ok = true;
  std::string parent;
  std::string error;
};

inline EnsureParentDirResult ensure_parent_dir(const std::string& path)
{
  EnsureParentDirResult result;
  std::error_code ec;
  std::filesystem::path parent = std::filesystem::path(path).parent_path();
  if (parent.empty()) return result;

  std::filesystem::create_directories(parent, ec);
  result.parent = parent.string();
  if (ec) {
    result.ok = false;
    result.error = ec.message();
  }
  return result;
}

}  // namespace epos_control

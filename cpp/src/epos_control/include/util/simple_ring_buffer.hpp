// simple_ring_buffer.hpp — RT 루프에서 non-RT 진단 코드로 넘기는 단순 SPSC 버퍼
#pragma once

#include <atomic>
#include <cstddef>
#include <vector>

namespace epos_control {

// RT 루프 → push(cycle_dt_us) → publish_diag_summary에서 drain → 통계 계산
// N 슬롯만 보관하며, reader가 늦으면 가장 최근 N개만 유지한다.
template <typename T, size_t N>
class SimpleRingBuffer {
public:
  void push(const T& val)
  {
    buf_[write_idx_ % N] = val;
    write_idx_++;
  }

  size_t drain(std::vector<T>& out)
  {
    size_t w = write_idx_.load();
    size_t r = read_idx_;
    if (w <= r) return 0;

    size_t count = w - r;
    if (count > N) {
      r = w - N;
      count = N;
    }

    out.clear();
    out.reserve(count);
    for (size_t i = r; i < w; i++) out.push_back(buf_[i % N]);
    read_idx_ = w;
    return count;
  }

private:
  T buf_[N]{};
  std::atomic<size_t> write_idx_{0};
  size_t read_idx_{0};
};

}  // namespace epos_control


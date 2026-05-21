// realtime_config.hpp — Linux 실시간 스레드 설정 유틸리티
#pragma once

#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>

namespace epos_control {

struct RealtimeConfigResult {
  bool mlock_ok = false;
  bool scheduler_ok = false;
  bool affinity_requested = false;
  bool affinity_ok = false;
};

inline RealtimeConfigResult configure_realtime_thread(int rt_priority, int rt_cpu)
{
  RealtimeConfigResult result;

  // mlockall: 모든 메모리를 물리 RAM에 고정하여 RT 루프 중 페이지 폴트를 줄인다.
  result.mlock_ok = (mlockall(MCL_CURRENT | MCL_FUTURE) == 0);

  // SCHED_FIFO: 일반 프로세스보다 먼저 CPU를 할당받는 실시간 스케줄링 정책.
  sched_param param{};
  param.sched_priority = rt_priority;
  result.scheduler_ok = (sched_setscheduler(0, SCHED_FIFO, &param) == 0);

  // CPU affinity: 특정 CPU 코어에 스레드를 고정하여 코어 이동으로 인한 지연을 줄인다.
  if (rt_cpu >= 0) {
    result.affinity_requested = true;
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(rt_cpu, &cpuset);
    result.affinity_ok = (pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset) == 0);
  }

  return result;
}

}  // namespace epos_control

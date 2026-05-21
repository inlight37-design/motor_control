# -*- coding: utf-8 -*-
"""실시간 그래프가 쓰는 NumPy 버퍼와 큐 상태."""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

import numpy as np

from ..core.config import MAX_GRAPH_POINTS


@dataclass
class GraphBuffers:
    """속도/RT 그래프 데이터를 window 동적 속성 대신 한곳에 보관."""

    max_points: int = MAX_GRAPH_POINTS
    start_wall: float = field(default_factory=time.time)
    speed_queue: Deque[tuple[float, float, float]] = field(default_factory=deque)
    rt_queue: Deque[tuple[float, float]] = field(default_factory=deque)

    speed_time: np.ndarray = field(init=False)
    speed_target: np.ndarray = field(init=False)
    speed_actual: np.ndarray = field(init=False)
    ptr_speed: int = 0

    rt_time: np.ndarray = field(init=False)
    rt_dt: np.ndarray = field(init=False)
    ptr_rt: int = 0

    def __post_init__(self):
        self.speed_time = np.zeros(self.max_points, dtype=np.float64)
        self.speed_target = np.zeros(self.max_points, dtype=np.float32)
        self.speed_actual = np.zeros(self.max_points, dtype=np.float32)
        self.rt_time = np.zeros(self.max_points, dtype=np.float64)
        self.rt_dt = np.zeros(self.max_points, dtype=np.float32)

    def reset(self):
        """그래프 포인터와 입력 큐를 초기화한다."""
        self.start_wall = time.time()
        self.ptr_speed = 0
        self.ptr_rt = 0
        self.speed_queue.clear()
        self.rt_queue.clear()

    def copy_speed(self, new_t, new_target, new_actual, count: int):
        """속도 그래프용 time/target/actual 배열에 새 데이터를 링 버퍼 방식으로 추가."""
        if self.ptr_speed + count <= self.max_points:
            end = self.ptr_speed + count
            self.speed_time[self.ptr_speed:end] = new_t
            self.speed_target[self.ptr_speed:end] = new_target
            self.speed_actual[self.ptr_speed:end] = new_actual
            self.ptr_speed = end
            return

        shift = (self.ptr_speed + count) - self.max_points
        self.speed_time[:-shift] = self.speed_time[shift:]
        self.speed_target[:-shift] = self.speed_target[shift:]
        self.speed_actual[:-shift] = self.speed_actual[shift:]
        self.speed_time[-count:] = new_t
        self.speed_target[-count:] = new_target
        self.speed_actual[-count:] = new_actual
        self.ptr_speed = self.max_points

    def copy_rt(self, new_t, new_dt, count: int):
        """RT 그래프용 time/dt 배열에 새 데이터를 링 버퍼 방식으로 추가."""
        if self.ptr_rt + count <= self.max_points:
            end = self.ptr_rt + count
            self.rt_time[self.ptr_rt:end] = new_t
            self.rt_dt[self.ptr_rt:end] = new_dt
            self.ptr_rt = end
            return

        shift = (self.ptr_rt + count) - self.max_points
        self.rt_time[:-shift] = self.rt_time[shift:]
        self.rt_dt[:-shift] = self.rt_dt[shift:]
        self.rt_time[-count:] = new_t
        self.rt_dt[-count:] = new_dt
        self.ptr_rt = self.max_points

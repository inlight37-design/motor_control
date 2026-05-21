# -*- coding: utf-8 -*-
"""실시간 그래프 데이터 버퍼 갱신 헬퍼."""
import numpy as np


def reset_graph_buffers(window):
    """그래프 링 버퍼와 큐를 초기화하고 curve 데이터를 비운다."""
    buffers = window.graph_buffers
    widgets = window.graph_widgets
    buffers.reset()
    widgets.target_curve.setData([], [])
    widgets.actual_curve.setData([], [])
    widgets.rt_dt_curve.setData([], [])


def update_speed_graph(window, is_speed_mode: bool):
    """speed_queue를 비워 속도 그래프 링 버퍼와 curve를 갱신."""
    buffers = window.graph_buffers
    widgets = window.graph_widgets
    count = len(buffers.speed_queue)
    if count <= 0:
        return
    if count > buffers.max_points:
        for _ in range(count - buffers.max_points):
            buffers.speed_queue.popleft()
        count = buffers.max_points

    new_t = np.empty(count, dtype=np.float64)
    new_target = np.empty(count, dtype=np.float32)
    new_actual = np.empty(count, dtype=np.float32)
    for i in range(count):
        wall_time, target_rpm, actual_rpm = buffers.speed_queue.popleft()
        new_t[i] = wall_time - buffers.start_wall
        new_target[i] = target_rpm if is_speed_mode else 0
        new_actual[i] = actual_rpm

    buffers.copy_speed(new_t, new_target, new_actual, count)
    widgets.target_curve.setData(
        buffers.speed_time[:buffers.ptr_speed],
        buffers.speed_target[:buffers.ptr_speed],
    )
    widgets.actual_curve.setData(
        buffers.speed_time[:buffers.ptr_speed],
        buffers.speed_actual[:buffers.ptr_speed],
    )


def update_rt_graph(window):
    """rt_queue를 비워 RT 주기 그래프 링 버퍼와 curve를 갱신."""
    buffers = window.graph_buffers
    widgets = window.graph_widgets
    count = len(buffers.rt_queue)
    if count <= 0:
        return
    if count > buffers.max_points:
        for _ in range(count - buffers.max_points):
            buffers.rt_queue.popleft()
        count = buffers.max_points

    new_t = np.empty(count, dtype=np.float64)
    new_dt = np.empty(count, dtype=np.float32)
    for i in range(count):
        wall_time, dt_us = buffers.rt_queue.popleft()
        new_t[i] = wall_time - buffers.start_wall
        new_dt[i] = dt_us

    buffers.copy_rt(new_t, new_dt, count)
    widgets.rt_dt_curve.setData(
        buffers.rt_time[:buffers.ptr_rt],
        buffers.rt_dt[:buffers.ptr_rt],
    )

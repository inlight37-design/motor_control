# -*- coding: utf-8 -*-
"""GUI 런타임에서 붙잡는 스레드/장치 핸들 컨테이너."""
from dataclasses import dataclass


@dataclass
class RuntimeThreads:
    """ROS/C++ 제어에 필요한 런타임 객체 묶음."""

    node_runner: object
    commander: object
    monitor: object
    control: object


@dataclass
class DeviceReaders:
    """GUI 안에서 직접 읽는 센서 리더 묶음."""

    load_cell: object
    linear_encoder: object

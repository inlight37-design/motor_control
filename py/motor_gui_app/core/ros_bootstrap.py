# -*- coding: utf-8 -*-
"""rclpy import 전에 필요한 ROS2/DDS 환경 준비."""
from .ros_environment import configure_ros_environment, ensure_fastdds_udp_only_profile


def prepare_ros_environment() -> None:
    """ROS2 Python 모듈을 import하기 전에 DDS 환경을 고정한다."""
    configure_ros_environment()
    ensure_fastdds_udp_only_profile()


__all__ = ["prepare_ros_environment"]

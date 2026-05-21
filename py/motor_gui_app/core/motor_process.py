# -*- coding: utf-8 -*-
"""C++ EPOS 모터 노드 실행 명령 조립."""
import os
import shlex

from .config import (
    DDS_CONFIG_PATH,
    DEFAULT_ACCEL_RPM_S,
    DEFAULT_CMD_TIMEOUT_MS,
    DEFAULT_FORCE_ALPHA,
    DEFAULT_FORCE_KD,
    DEFAULT_FORCE_KI,
    DEFAULT_FORCE_KP,
    DEFAULT_FORCE_MAX_RPM,
    DEFAULT_FORCE_TANH_DEADBAND_N,
    DEFAULT_FORCE_TANH_SENS_N,
    DEFAULT_HEARTBEAT_TIMEOUT_MS,
    DEFAULT_POSITION_TICKS_PER_REV,
    DEFAULT_RT_CPU,
    LOG_DIR,
    MAX_RPM,
    ROS_SETUP,
    WORKSPACE_DIR,
    WS_SETUP,
)
from .topics import EPOS_NODE_EXECUTABLE


def ros_float(value: float) -> str:
    """ROS2 CLI가 double 파라미터를 integer로 오해하지 않도록 소수점 표기를 보장."""
    text = f"{float(value):.6g}"
    if "e" not in text.lower() and "." not in text:
        text += ".0"
    return text


def build_motor_cmd(iface: str, rt_cpu: int = DEFAULT_RT_CPU) -> str:
    """C++ 모터 노드 실행 명령어를 조립."""
    iface_arg = (
        f"--ros-args -p iface:={shlex.quote(iface)} "
        f"-p cmd_timeout_ms:={DEFAULT_CMD_TIMEOUT_MS} "
        f"-p heartbeat_timeout_ms:={DEFAULT_HEARTBEAT_TIMEOUT_MS} "
        f"-p rt_cpu:={rt_cpu} -p max_abs_target:={MAX_RPM} "
        f"-p motor_ticks_per_rev:={DEFAULT_POSITION_TICKS_PER_REV} "
        f"-p accel_limit_rpm_s:={DEFAULT_ACCEL_RPM_S} "
        f"-p force_max_rpm:={DEFAULT_FORCE_MAX_RPM} "
        f"-p force_out_alpha:={ros_float(DEFAULT_FORCE_ALPHA)} "
        f"-p force_kp:={ros_float(DEFAULT_FORCE_KP)} "
        f"-p force_ki:={ros_float(DEFAULT_FORCE_KI)} "
        f"-p force_kd:={ros_float(DEFAULT_FORCE_KD)} "
        f"-p force_tanh_sensitivity_N:={ros_float(DEFAULT_FORCE_TANH_SENS_N)} "
        f"-p force_tanh_deadband_N:={ros_float(DEFAULT_FORCE_TANH_DEADBAND_N)}"
    )
    inner = (
        f"source {shlex.quote(ROS_SETUP)} && "
        f"source {shlex.quote(WS_SETUP)} && "
        f"export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST && "
        f"export ROS_DOMAIN_ID={shlex.quote(os.environ.get('ROS_DOMAIN_ID','0'))} && "
        f"export RMW_IMPLEMENTATION=rmw_fastrtps_cpp && "
        f"export FASTRTPS_DEFAULT_PROFILES_FILE={shlex.quote(DDS_CONFIG_PATH)} && "
        f"export EPOS_WORKSPACE_DIR={shlex.quote(str(WORKSPACE_DIR))} && "
        f"export EPOS_LOG_DIR={shlex.quote(str(LOG_DIR))} && "
        f"chrt -f 50 ros2 run epos_control {EPOS_NODE_EXECUTABLE} {iface_arg}"
    )
    return f"sudo bash -lc {shlex.quote(inner)}"

__all__ = ["build_motor_cmd", "ros_float"]

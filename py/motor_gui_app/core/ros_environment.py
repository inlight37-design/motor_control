# -*- coding: utf-8 -*-
"""ROS2/DDS 실행 환경과 EtherCAT 인터페이스 감지."""
import glob
import os
import shlex
import subprocess
import sys
from typing import List

from .config import DDS_CONFIG_PATH


def configure_ros_environment() -> None:
    """rclpy import 전에 필요한 DDS 환경변수를 기본값으로 고정."""
    # LOCALHOST로 제한하여 같은 PC 내 통신만 허용 (네트워크 노이즈 차단)
    os.environ.setdefault("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    # 도메인 ID 0번 사용 (동일 PC에서 여러 ROS2 시스템 분리용)
    os.environ.setdefault("ROS_DOMAIN_ID", "0")
    # FastRTPS(eProsima)를 DDS 미들웨어로 지정 — EtherCAT RT와 궁합 좋음
    os.environ.setdefault("RMW_IMPLEMENTATION", "rmw_fastrtps_cpp")


def detect_interfaces() -> List[str]:
    """EtherCAT 통신에 사용 가능한 네트워크 인터페이스 목록을 자동 감지."""
    result = []
    for pattern in ["/sys/class/net/enx*", "/sys/class/net/enp*"]:
        for path in sorted(glob.glob(pattern)):
            result.append(os.path.basename(path))
    return result


def _sudo_shell(cmd: str) -> subprocess.CompletedProcess:
    """sudo 권한으로 셸 명령을 실행하는 헬퍼."""
    full = f"sudo bash -lc {shlex.quote(cmd)}"
    return subprocess.run(full, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def ensure_fastdds_udp_only_profile() -> None:
    """FastDDS가 UDP만 사용하도록 강제하는 XML 프로파일을 생성."""
    try:
        _sudo_shell(f"rm -f {shlex.quote(DDS_CONFIG_PATH)}")
    except Exception:
        pass
    xml = """<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor>
      <transport_id>udp_transport</transport_id>
      <type>UDPv4</type>
    </transport_descriptor>
  </transport_descriptors>
  <participant profile_name="participant_profile" is_default_profile="true">
    <rtps>
      <userTransports><transport_id>udp_transport</transport_id></userTransports>
      <useBuiltinTransports>false</useBuiltinTransports>
    </rtps>
  </participant>
</profiles>
"""
    try:
        with open(DDS_CONFIG_PATH, "w", encoding="utf-8") as f:
            f.write(xml)
        os.environ["FASTRTPS_DEFAULT_PROFILES_FILE"] = DDS_CONFIG_PATH
    except Exception as exc:
        print(f"[WARN] DDS 설정 실패: {exc}", file=sys.stderr)


__all__ = [
    "configure_ros_environment",
    "detect_interfaces",
    "ensure_fastdds_udp_only_profile",
]

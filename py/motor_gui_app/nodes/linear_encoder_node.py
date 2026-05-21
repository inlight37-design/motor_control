#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
linear_encoder_node.py — Phidget 리니어 엔코더 → ROS2 브릿지 노드
================================================================

모터 GUI와 별개로 실행할 수 있는 리니어 엔코더 퍼블리셔입니다.
GUI 내장 LinearEncoderReader와 같은 토픽을 퍼블리시하므로,
epos_motor_node가 CSV 로그에 리니어 엔코더 값을 함께 기록할 수 있습니다.

퍼블리시 토픽
-------------
  /linear_encoder/position_count  (std_msgs/Int32)   — 영점 보정된 엔코더 카운트
  /linear_encoder/position_mm     (std_msgs/Float32) — 영점 보정된 직선 위치 [mm]
  /linear_encoder/status          (std_msgs/String)  — JSON 상태

ROS2 파라미터
-------------
  channel                 : int   — Phidget 엔코더 채널 (기본값: 0)
  counts_per_mm           : float — 엔코더 count/mm 보정값 (기본값: 314.4)
  invert                  : bool  — 부호 반전 여부 (기본값: false)
  publish_hz              : int   — ROS2 토픽 퍼블리시 주기 [Hz] (기본값: 100)
  debug_print_hz          : float — 터미널 출력 주기 [Hz], 0이면 출력 끔 (기본값: 0)
  position_change_trigger : int   — Phidget 카운트 변화 트리거 (기본값: 1)
  zero_on_start           : bool  — 시작 시 현재 위치를 0으로 볼지 여부 (기본값: true)

서비스
------
  /linear_encoder/zero (std_srvs/Trigger) — 현재 raw count를 새 영점으로 설정.

실행 예시
---------
  # 리니어 엔코더 노드 실행, ROS2 토픽 100 Hz, 터미널 출력 10 Hz
  python3 motor_gui_app/nodes/linear_encoder_node.py --ros-args \
    -p channel:=0 \
    -p counts_per_mm:=314.4 \
    -p publish_hz:=100 \
    -p debug_print_hz:=10

  # ROS2 토픽이 실제 몇 Hz로 나오는지 확인
  ros2 topic hz /linear_encoder/position_mm

  # 현재 위치를 0으로 재설정
  ros2 service call /linear_encoder/zero std_srvs/srv/Trigger "{}"
"""

import json
import sys
import threading
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Int32, String
from std_srvs.srv import Trigger

try:
    from motor_gui_app.core.linear_encoder_math import (
        normalize_counts_per_mm,
        position_count,
        position_mm,
    )
    from motor_gui_app.core.phidget_support import Encoder, PHIDGET_AVAILABLE
    from motor_gui_app.core.topics import (
        SERVICE_LINEAR_ENCODER_ZERO,
        TOPIC_LINEAR_ENCODER_COUNT,
        TOPIC_LINEAR_ENCODER_MM,
        TOPIC_LINEAR_ENCODER_STATUS,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from motor_gui_app.core.linear_encoder_math import (
        normalize_counts_per_mm,
        position_count,
        position_mm,
    )
    from motor_gui_app.core.phidget_support import Encoder, PHIDGET_AVAILABLE
    from motor_gui_app.core.topics import (
        SERVICE_LINEAR_ENCODER_ZERO,
        TOPIC_LINEAR_ENCODER_COUNT,
        TOPIC_LINEAR_ENCODER_MM,
        TOPIC_LINEAR_ENCODER_STATUS,
    )

class EncoderState:
    def __init__(self, counts_per_mm: float, invert: bool):
        self._lock = threading.Lock()
        self.counts_per_mm = normalize_counts_per_mm(counts_per_mm)
        self.invert = bool(invert)
        self.raw_count = 0
        self.zero_raw = 0
        self.has_sample = False
        self.connected = False
        self.serial = None
        self.device_name = ""
        self.last_error = ""
        self.last_update_t = 0.0

    def on_position_change(self, dev, _position_change, _time_change, _index_triggered):
        with self._lock:
            try:
                self.raw_count = int(dev.getPosition())
                self.has_sample = True
                self.last_update_t = time.time()
                self.last_error = ""
            except Exception as e:
                self.last_error = str(e)

    def set_initial_count(self, raw_count: int, zero_on_start: bool):
        with self._lock:
            self.raw_count = int(raw_count)
            if zero_on_start:
                self.zero_raw = int(raw_count)
            self.has_sample = True
            self.last_update_t = time.time()

    def zero(self):
        with self._lock:
            self.zero_raw = self.raw_count

    def snapshot(self) -> dict:
        with self._lock:
            count = position_count(self.raw_count, self.zero_raw, self.invert)
            mm = position_mm(self.raw_count, self.zero_raw, self.counts_per_mm, self.invert)
            return {
                "connected": self.connected,
                "has_sample": self.has_sample,
                "raw_count": int(self.raw_count),
                "zero_raw": int(self.zero_raw),
                "position_count": count,
                "position_mm": mm,
                "counts_per_mm": self.counts_per_mm,
                "invert": self.invert,
                "serial": self.serial,
                "device_name": self.device_name,
                "last_error": self.last_error,
                "last_update_t": self.last_update_t,
            }


class LinearEncoderNode(Node):
    def __init__(self):
        super().__init__("linear_encoder_node")

        self.declare_parameter("channel", 0)
        self.declare_parameter("counts_per_mm", 314.4)
        self.declare_parameter("invert", False)
        self.declare_parameter("publish_hz", 100)
        self.declare_parameter("debug_print_hz", 0.0)
        self.declare_parameter("position_change_trigger", 1)
        self.declare_parameter("zero_on_start", True)

        self.channel = int(self.get_parameter("channel").value)
        self.publish_hz = int(self.get_parameter("publish_hz").value)
        self.debug_print_hz = max(0.0, float(self.get_parameter("debug_print_hz").value))
        self.position_change_trigger = int(self.get_parameter("position_change_trigger").value)
        self.zero_on_start = bool(self.get_parameter("zero_on_start").value)
        self._last_debug_print_t = 0.0
        self.state = EncoderState(
            counts_per_mm=float(self.get_parameter("counts_per_mm").value),
            invert=bool(self.get_parameter("invert").value),
        )

        self._device = None
        self._pub_count = self.create_publisher(Int32, TOPIC_LINEAR_ENCODER_COUNT, 10)
        self._pub_mm = self.create_publisher(Float32, TOPIC_LINEAR_ENCODER_MM, 10)
        self._pub_status = self.create_publisher(String, TOPIC_LINEAR_ENCODER_STATUS, 10)
        self._zero_srv = self.create_service(Trigger, SERVICE_LINEAR_ENCODER_ZERO, self._srv_zero)

        if not PHIDGET_AVAILABLE:
            self.get_logger().error("Phidget22 라이브러리를 찾을 수 없습니다. pip install Phidget22")
        else:
            self._connect_encoder()

        period = 1.0 / max(1, self.publish_hz)
        self._timer = self.create_timer(period, self._publish_callback)
        self.get_logger().info(
            f"linear_encoder_node 시작 — CH{self.channel}, "
            f"{self.state.counts_per_mm:g} cnt/mm, publish_hz={self.publish_hz}, "
            f"debug_print_hz={self.debug_print_hz:g}"
        )

    def _connect_encoder(self):
        try:
            dev = Encoder()
            dev.setChannel(self.channel)
            dev.setOnPositionChangeHandler(self.state.on_position_change)
            dev.openWaitForAttachment(3000)
            try:
                dev.setEnabled(True)
            except Exception:
                pass
            try:
                dev.setDataInterval(dev.getMinDataInterval())
            except Exception:
                pass
            try:
                dev.setPositionChangeTrigger(max(1, self.position_change_trigger))
            except Exception:
                pass
            raw = int(dev.getPosition())
            self.state.set_initial_count(raw, self.zero_on_start)
            self.state.connected = True
            try:
                self.state.serial = dev.getDeviceSerialNumber()
                self.state.device_name = dev.getDeviceName()
            except Exception:
                pass
            self._device = dev
            self.get_logger().info(
                f"엔코더 CH{self.channel} 연결됨 raw={raw}, 시작영점={self.zero_on_start}"
            )
        except Exception as e:
            self.state.connected = False
            self.state.last_error = str(e)
            self.get_logger().error(f"Encoder CH{self.channel} 연결 실패: {e}")

    def _srv_zero(self, _request, response):
        self.state.zero()
        snap = self.state.snapshot()
        response.success = True
        response.message = f"영점 설정 완료 raw_count={snap['raw_count']}"
        self.get_logger().info(response.message)
        return response

    def _publish_callback(self):
        snap = self.state.snapshot()
        self._pub_count.publish(Int32(data=int(snap["position_count"])))
        self._pub_mm.publish(Float32(data=float(snap["position_mm"])))
        status = dict(snap)
        if status["last_update_t"]:
            status["age_ms"] = round((time.time() - status["last_update_t"]) * 1000.0, 1)
        else:
            status["age_ms"] = None
        self._pub_status.publish(String(data=json.dumps(status)))
        self._debug_print(status)

    def _debug_print(self, status: dict):
        if self.debug_print_hz <= 0.0:
            return
        now = time.time()
        period = 1.0 / self.debug_print_hz
        if (now - self._last_debug_print_t) < period:
            return
        self._last_debug_print_t = now
        self.get_logger().info(
            "위치={position_count:+d} cnt, {position_mm:+.4f} mm, "
            "raw={raw_count}, 갱신={age_ms} ms 전, 연결={connected}".format(**status)
        )

    def destroy_node(self):
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None
        super().destroy_node()


def main():
    rclpy.init(args=sys.argv)
    node = LinearEncoderNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
load_cell_node.py — Phidget 1046 로드셀 → ROS2 브릿지 노드
============================================================

[역할]
  Phidget 1046 (Wheatstone Bridge 인터페이스) 로드셀에서 힘 데이터를 읽어
  ROS2 토픽으로 퍼블리시하는 독립 실행 노드.
  motor_gui.py(GUI)와 별개로 실행 가능하며,
  GUI의 내장 LoadCellReader와는 독립적으로 동작한다.

  ┌──────────────┐     USB      ┌──────────────┐     ROS2 토픽     ┌──────────────┐
  │ Phidget 1046 │ ───────────→ │  이 노드      │ ───────────────→ │ GUI / C++    │
  │ (로드셀)      │   콜백 방식    │ (Python)      │  /load_cell/*   │  노드         │
  └──────────────┘              └──────────────┘                  └──────────────┘

[데이터 흐름]
  1. Phidget 라이브러리가 USB로 전압비(Voltage Ratio) 변화를 감지
  2. 콜백(on_voltage_change)이 호출됨 → IIR 필터 적용 → 캘리브레이션 변환
  3. 타이머(publish_hz)마다 현재 값을 ROS2 토픽으로 퍼블리시

[단위 변환 경로]
  전압비(V/V) → IIR 필터링 → scale_g × ratio + offset_g → 그램(g) → 뉴턴(N)
  그램 → 뉴턴 변환: N = (g / 1000) × 9.80665

퍼블리시 토픽
-------------
  /load_cell/ch0_N  (std_msgs/Float32)  — 채널 0 힘 [N] (뉴턴)
  /load_cell/ch1_N  (std_msgs/Float32)  — 채널 1 힘 [N]
  /load_cell/ch0_g  (std_msgs/Float32)  — 채널 0 힘 [g] (그램)
  /load_cell/ch1_g  (std_msgs/Float32)  — 채널 1 힘 [g]
  /load_cell/status (std_msgs/String)   — JSON 상태 (연결, peak, raw 등)

ROS2 파라미터
-------------
  cal_file   : str   — 캘리브레이션 JSON 파일 경로 (기본값: "")
                        load_cell_gui.py에서 생성한 JSON을 지정.
                        비어있으면 scale=1, offset=0 (원시 값 그대로).
  iir_alpha  : float — IIR 저역통과 필터 계수 0~1 (기본값: 0.1)
                        작을수록 부드럽지만 반응 느림. 0.1 = 새 값의 10%만 반영.
  n_channels : int   — 사용 채널 수 1 또는 2 (기본값: 1)
  publish_hz : int   — 상태 토픽 퍼블리시 주기 [Hz] (기본값: 200)
  debug_print_hz : float — 터미널 출력 주기 [Hz], 0이면 비활성 (기본값: 0)

실행 예시
---------
  # 2채널 로드셀 노드 실행, ROS2 토픽 200 Hz, 터미널 출력 10 Hz
  python3 motor_gui_app/nodes/load_cell_node.py --ros-args \
    -p n_channels:=2 \
    -p publish_hz:=200 \
    -p debug_print_hz:=10

  # 캘리브레이션 파일을 지정해서 실행
  python3 motor_gui_app/nodes/load_cell_node.py --ros-args \
    -p cal_file:=/path/to/cal.json \
    -p n_channels:=2 \
    -p debug_print_hz:=10

  # ROS2 토픽이 실제 몇 Hz로 나오는지 확인
  ros2 topic hz /load_cell/ch0_N
"""

import json
import sys
import threading
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

try:
    from motor_gui_app.core.iir_filter import IIRFilter
    from motor_gui_app.core.load_cell_calibration import (
        calibration_to_grams,
        load_calibration_channels,
        select_channel_calibration,
    )
    from motor_gui_app.core.phidget_support import GRAVITY, PHIDGET_AVAILABLE, VoltageRatioInput
    from motor_gui_app.core.topics import (
        TOPIC_LOAD_CELL_CH0_G,
        TOPIC_LOAD_CELL_CH0_N,
        TOPIC_LOAD_CELL_CH1_G,
        TOPIC_LOAD_CELL_CH1_N,
        TOPIC_LOAD_CELL_STATUS,
    )
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from motor_gui_app.core.iir_filter import IIRFilter
    from motor_gui_app.core.load_cell_calibration import (
        calibration_to_grams,
        load_calibration_channels,
        select_channel_calibration,
    )
    from motor_gui_app.core.phidget_support import GRAVITY, PHIDGET_AVAILABLE, VoltageRatioInput
    from motor_gui_app.core.topics import (
        TOPIC_LOAD_CELL_CH0_G,
        TOPIC_LOAD_CELL_CH0_N,
        TOPIC_LOAD_CELL_CH1_G,
        TOPIC_LOAD_CELL_CH1_N,
        TOPIC_LOAD_CELL_STATUS,
    )

# ══════════════════════════════════════════════════════════════════
# 채널 상태 관리 (ChannelState)
# ══════════════════════════════════════════════════════════════════
# 각 로드셀 채널(CH0, CH1)의 캘리브레이션, 필터, 측정값을 관리.
#
# [스레드 안전성]
#   Phidget 콜백은 별도 스레드에서 호출되고, 퍼블리시 타이머는 ROS2 스레드에서 호출.
#   → 데이터 접근 시 threading.Lock으로 보호 필요.
#   (C++ AxisState의 atomic 변수와 같은 목적이지만, Python에서는 Lock이 더 자연스러움)
class ChannelState:
    def __init__(self, ch_num: int, alpha: float = 0.1):
        self.ch_num    = ch_num     # 채널 번호 (0 또는 1)
        self.scale_g   = 1.0       # 캘리브레이션 기울기 [g/(V/V)]
        self.offset_g  = 0.0       # 캘리브레이션 절편 [g]
        self.tare_g    = 0.0       # 영점(Tare) 오프셋 [g]
        self.iir       = IIRFilter(alpha=alpha)  # 노이즈 필터
        self.connected = False     # Phidget 연결 상태

        # ── 실시간 측정값 (Phidget 콜백에서 갱신) ─────────────────────
        self.raw_ratio  = 0.0      # 원시 전압비 [V/V] — 필터 전
        self.filt_ratio = 0.0      # 필터링된 전압비 [V/V]
        self.grams      = 0.0      # 영점 보정된 힘 [g]
        self.newtons    = 0.0      # 영점 보정된 힘 [N]
        self.peak_n     = 0.0      # 최대 힘 기록 [N] (절대값)

        self._lock = threading.Lock()  # Phidget 콜백 ↔ 퍼블리시 간 데이터 보호

    def on_voltage_change(self, _, ratio: float):
        """Phidget 콜백 — 전압비 변화 시 자동 호출.

        데이터 흐름:
          raw ratio → IIR 필터 → 캘리브레이션(scale × ratio + offset) → tare 보정 → N 변환

        Args:
            _:     Phidget 디바이스 객체 (미사용)
            ratio: 새 전압비 측정값 [V/V]
        """
        with self._lock:
            filtered = self.iir.process(ratio)                    # ① IIR 필터링
            abs_g    = self.scale_g * filtered + self.offset_g    # ② 캘리브레이션 적용 → 절대 그램
            net_g    = abs_g - self.tare_g                        # ③ 영점(tare) 보정 → 순수 측정 그램
            net_n    = (net_g / 1000.0) * GRAVITY                 # ④ 그램 → 뉴턴 변환

            # 값 저장
            self.raw_ratio  = ratio
            self.filt_ratio = filtered
            self.grams      = net_g
            self.newtons    = net_n
            if abs(net_n) > self.peak_n:
                self.peak_n = abs(net_n)                          # 피크 갱신

    def snapshot(self) -> dict:
        """현재 측정값의 스냅샷을 딕셔너리로 반환 (lock 보호).

        퍼블리시 콜백에서 호출 — 한 번의 lock 획득으로 모든 값을 복사하여
        퍼블리시 도중 값이 바뀌는 것을 방지.
        """
        with self._lock:
            return {
                "raw":       self.raw_ratio,
                "filtered":  self.filt_ratio,
                "grams":     self.grams,
                "newtons":   self.newtons,
                "peak_n":    self.peak_n,
                "connected": self.connected,
            }

    def set_calibration(self, scale_g: float, offset_g: float):
        """캘리브레이션 파라미터 업데이트.

        scale_g, offset_g는 load_cell_gui.py의 선형회귀 결과에서 나온 값.
        변경 시 IIR 필터를 리셋하여 이전 캘리브레이션의 잔여 값이 영향을 주지 않도록 함.
        """
        with self._lock:
            self.scale_g  = scale_g
            self.offset_g = offset_g
            self.iir.reset()  # 필터 히스토리 초기화 — 새 캘리브레이션에 이전 값이 섞이지 않게

    def set_alpha(self, alpha: float):
        """IIR 필터 계수를 실시간 변경 (ROS2 파라미터 콜백 등에서 사용)."""
        self.iir.alpha = alpha


# ══════════════════════════════════════════════════════════════════
# 3. ROS2 노드 (LoadCellNode)
# ══════════════════════════════════════════════════════════════════
# 전체 동작 흐름:
#   1. 노드 생성 → 파라미터 읽기 → 채널 상태 초기화
#   2. 캘리브레이션 JSON 로드 (있으면)
#   3. Phidget USB 연결 → 콜백 등록
#   4. 타이머(publish_hz)로 주기적으로 ROS2 토픽 퍼블리시
#   5. 종료 시 Phidget 닫기
class LoadCellNode(Node):
    def __init__(self):
        super().__init__("load_cell_node")

        # ── ROS2 파라미터 선언 및 읽기 ────────────────────────────────
        # declare_parameter(): 이 노드가 받을 수 있는 파라미터를 등록.
        # 명령줄 --ros-args -p key:=value 또는 launch 파일에서 값을 전달 가능.
        self.declare_parameter("cal_file",   "")     # 캘리브레이션 JSON 경로
        self.declare_parameter("iir_alpha",  0.1)    # IIR 필터 계수
        self.declare_parameter("n_channels", 1)      # 사용 채널 수 (1 or 2)
        self.declare_parameter("publish_hz", 200)    # 퍼블리시 주기
        self.declare_parameter("debug_print_hz", 0.0) # 터미널 출력 주기, 0=끄기

        cal_file   = self.get_parameter("cal_file").value
        iir_alpha  = float(self.get_parameter("iir_alpha").value)
        n_channels = int(self.get_parameter("n_channels").value)
        publish_hz = int(self.get_parameter("publish_hz").value)
        self._debug_print_hz = max(0.0, float(self.get_parameter("debug_print_hz").value))
        self._last_debug_print_t = 0.0

        # ── 채널 상태 객체 생성 ───────────────────────────────────────
        # 최소 1개, 최대 2개 채널 (Phidget 1046은 4채널이지만 여기서는 2채널까지 지원)
        self._n_channels = max(1, min(n_channels, 2))
        self._channels = [ChannelState(i, alpha=iir_alpha) for i in range(self._n_channels)]
        self._devices  = [None] * self._n_channels  # Phidget 디바이스 핸들

        # ── 캘리브레이션 JSON 로드 ────────────────────────────────────
        if cal_file:
            self._load_calibration(cal_file)
        else:
            self.get_logger().warn("cal_file 파라미터가 없습니다. scale=1, offset=0 사용.")

        # ── ROS2 퍼블리셔 생성 ────────────────────────────────────────
        # 각 채널에 대해 N(뉴턴)과 g(그램) 토픽을 따로 퍼블리시.
        # queue size 10: 구독자가 느리면 최신 10개만 유지.
        self._pub_ch0_N  = self.create_publisher(Float32, TOPIC_LOAD_CELL_CH0_N, 10)
        self._pub_ch1_N  = self.create_publisher(Float32, TOPIC_LOAD_CELL_CH1_N, 10)
        self._pub_ch0_g  = self.create_publisher(Float32, TOPIC_LOAD_CELL_CH0_G, 10)
        self._pub_ch1_g  = self.create_publisher(Float32, TOPIC_LOAD_CELL_CH1_G, 10)
        self._pub_status = self.create_publisher(String,  TOPIC_LOAD_CELL_STATUS, 10)

        # ── Phidget USB 연결 ──────────────────────────────────────────
        if not PHIDGET_AVAILABLE:
            self.get_logger().error("Phidget22 라이브러리를 찾을 수 없습니다. pip install Phidget22")
        else:
            self._connect_phidgets()

        # ── 퍼블리시 타이머 ───────────────────────────────────────────
        # ROS2 타이머: 지정된 주기(period)마다 _publish_callback()을 자동 호출.
        # 200Hz이면 5ms마다 한 번씩 퍼블리시.
        period = 1.0 / max(1, publish_hz)
        self._timer = self.create_timer(period, self._publish_callback)

        self.get_logger().info(
            f"load_cell_node 시작 — 채널: {self._n_channels}, "
            f"alpha: {iir_alpha}, publish_hz: {publish_hz}, "
            f"debug_print_hz: {self._debug_print_hz:g}"
        )

    # ── 캘리브레이션 JSON 파일 로드 ───────────────────────────────────
    def _load_calibration(self, path: str):
        """load_cell_gui.py에서 생성한 캘리브레이션 JSON을 읽어 각 채널에 적용.

        JSON 구조 예시:
        {
            "channels": {
                "0": {"scale_g": 12345.6, "offset_g": -0.5, "r2": 0.9999},
                "1": {"scale_g": 12300.0, "offset_g": -0.3, "r2": 0.9998}
            }
        }
        """
        try:
            channels = load_calibration_channels(path)
            for ch_idx, ch in enumerate(self._channels):
                selected = select_channel_calibration(ch_idx, channels)
                if selected is None:
                    self.get_logger().warn(f"캘리브레이션 파일에 CH{ch_idx} 데이터 없음")
                    continue

                src_key, calibration, copied = selected
                scale_g, offset_g = calibration_to_grams(calibration)
                ch.set_calibration(scale_g=scale_g, offset_g=offset_g)
                if copied:
                    self.get_logger().warn(
                        f"캘리브레이션 파일에 CH{ch_idx} 데이터 없음 → CH{src_key} 캘리브레이션을 복사 적용"
                    )
                else:
                    self.get_logger().info(
                        f"CH{ch_idx} 캘리브레이션 로드: "
                        f"scale_g={scale_g:.4f}, "
                        f"offset_g={offset_g:.4f}, "
                        f"R²={calibration.get('r2', 'N/A')}"
                    )
        except Exception as e:
            self.get_logger().error(f"캘리브레이션 파일 로드 실패: {e}")

    # ── Phidget USB 연결 ──────────────────────────────────────────────
    def _connect_phidgets(self):
        """각 채널의 Phidget 디바이스를 열고 콜백을 등록.

        openWaitForAttachment(3000): 최대 3초 동안 USB 연결을 기다림.
        setDataInterval(min): 가능한 최소 주기(보통 1ms)로 데이터 수신.
        setOnVoltageRatioChangeHandler: 전압비가 변하면 콜백 함수 호출.
        """
        for i, ch in enumerate(self._channels):
            try:
                dev = VoltageRatioInput()
                dev.setChannel(i)                   # 채널 번호 설정
                dev.openWaitForAttachment(3000)      # USB 연결 대기 (최대 3초)
                dev.setDataInterval(dev.getMinDataInterval())  # 최소 주기로 수신
                dev.setOnVoltageRatioChangeHandler(ch.on_voltage_change)  # 콜백 등록
                self._devices[i] = dev
                ch.connected = True
                self.get_logger().info(f"CH{i} Phidget 연결됨 (interval={dev.getDataInterval()}ms)")
            except Exception as e:
                ch.connected = False
                self.get_logger().error(f"CH{i} Phidget 연결 실패: {e}")

    # ── 퍼블리시 타이머 콜백 ──────────────────────────────────────────
    def _publish_callback(self):
        """타이머에 의해 주기적으로 호출 — 현재 측정값을 ROS2 토픽으로 전송.

        각 채널의 snapshot()을 호출하여 스레드 안전하게 값을 복사한 뒤,
        N(뉴턴), g(그램), JSON 상태를 각각의 토픽으로 퍼블리시.
        """
        snaps = [ch.snapshot() for ch in self._channels]

        # CH0 (항상 존재)
        s0 = snaps[0]
        self._pub_ch0_N.publish(Float32(data=float(s0["newtons"])))
        self._pub_ch0_g.publish(Float32(data=float(s0["grams"])))

        # CH1 (2채널 모드일 때만)
        if self._n_channels > 1:
            s1 = snaps[1]
            self._pub_ch1_N.publish(Float32(data=float(s1["newtons"])))
            self._pub_ch1_g.publish(Float32(data=float(s1["grams"])))

        # JSON 상태 토픽 — GUI에서 전체 상태를 한 번에 파악하기 위한 용도
        status = {
            "channels": [
                {
                    "ch": i,
                    "connected": s["connected"],
                    "newtons":   round(s["newtons"], 4),
                    "grams":     round(s["grams"], 3),
                    "peak_n":    round(s["peak_n"], 4),
                    "raw_ratio": round(s["raw"], 8),
                }
                for i, s in enumerate(snaps)
            ],
        }
        self._pub_status.publish(String(data=json.dumps(status)))
        self._debug_print(status)

    def _debug_print(self, status: dict):
        """debug_print_hz가 켜져 있을 때 터미널에 힘 값을 간단히 출력."""
        if self._debug_print_hz <= 0.0:
            return
        now = time.time()
        period = 1.0 / self._debug_print_hz
        if (now - self._last_debug_print_t) < period:
            return
        self._last_debug_print_t = now
        parts = []
        for ch in status.get("channels", []):
            conn = "OK" if ch.get("connected") else "--"
            parts.append(
                f"CH{ch.get('ch')}={ch.get('newtons'):+.4f} N "
                f"({ch.get('grams'):+.2f} g, {conn})"
            )
        self.get_logger().info(" | ".join(parts))

    def destroy_node(self):
        """노드 종료 시 Phidget 디바이스를 정리."""
        for dev in self._devices:
            if dev is not None:
                try:
                    dev.close()
                except Exception:
                    pass
        super().destroy_node()


# ══════════════════════════════════════════════════════════════════
# 4. 메인 엔트리포인트
# ══════════════════════════════════════════════════════════════════
# rclpy.init()  → ROS2 초기화
# rclpy.spin()  → 이벤트 루프 실행 (타이머 콜백이 주기적으로 호출됨)
# KeyboardInterrupt(Ctrl+C) → 정상 종료
def main():
    rclpy.init(args=sys.argv)
    node = LoadCellNode()
    try:
        rclpy.spin(node)        # ROS2 이벤트 루프 — 타이머/구독 콜백 처리
    except KeyboardInterrupt:
        pass                    # Ctrl+C로 정상 종료
    finally:
        node.destroy_node()     # Phidget 정리
        rclpy.shutdown()        # ROS2 정리


if __name__ == "__main__":
    main()

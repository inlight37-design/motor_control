# -*- coding: utf-8 -*-
"""ROS2 명령 퍼블리셔 스레드와 안전 출력 로직."""
import os
import threading
import time
from collections import deque
from typing import Optional

import rclpy
from PyQt5.QtCore import QThread, pyqtSignal
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, Int32, String

from .command_builders import build_force_ctrl_msg, build_waveform_msg
from .config import (
    DEFAULT_ACCEL_RPM_S,
    DEFAULT_CMD_HZ,
    DEFAULT_FORCE_SOFT_LIMIT_N,
    DEFAULT_FORCE_SOFT_START_PCT,
    DEFAULT_MANUAL_RPM_LIMIT,
)
from .ros_messages import (
    ForceCtrlCmd,
    FORCE_CTRL_MSG_AVAILABLE,
    WaveformCmd,
    WAVEFORM_MSG_AVAILABLE,
)
from .time_utils import now_str
from .topics import (
    TARGET_TOPIC,
    TOPIC_FORCE_CTRL_CMD,
    TOPIC_FORCE_CTRL_CMD_V2,
    TOPIC_HEARTBEAT,
    TOPIC_LINEAR_ENCODER_COUNT,
    TOPIC_LINEAR_ENCODER_MM,
    TOPIC_LOAD_CELL_CH0_N,
    TOPIC_LOAD_CELL_CH1_N,
    TOPIC_LOG_CMD,
    TOPIC_OP_MODE,
    TOPIC_TARGET_FORCE,
    TOPIC_TARGET_POS,
    TOPIC_TARGET_TRQ,
    TOPIC_WAVEFORM_CMD,
    TOPIC_WAVEFORM_CMD_V2,
)
from ..logic.motion_script import MotionScript

class CommandThread(QThread):
    log_signal = pyqtSignal(str)           # GUI 로그에 메시지 전달
    script_error_signal = pyqtSignal(str)  # 스크립트 실행 오류를 GUI에 전달

    def __init__(self, cmd_hz: int = DEFAULT_CMD_HZ):
        super().__init__()
        self.cmd_hz = int(cmd_hz)      # 제어 명령 발행 주파수 (Hz)
        self.running = True            # 스레드 실행 플래그
        self._lock = threading.Lock()  # 멤버 변수 접근 보호 (GUI 스레드 ↔ 이 스레드)
        self._mode = "manual"  # manual | script | waveform — 현재 동작 모드
        self._manual_target_rpm = 0.0  # 수동 모드 목표 RPM
        self._accel_rpm_per_s = float(DEFAULT_ACCEL_RPM_S) # 가속도 제한 (rpm/s), C++ 노드에도 전달됨
        self._rpm_limit = float(DEFAULT_MANUAL_RPM_LIMIT)  # 절대 RPM 상한 (양방향)
        self._op_mode = 9  # 8: CSP(위치), 9: CSV(속도), 10: CST(토크) — CiA 402 운전 모드
        self._manual_target_pos = 0    # 수동 모드 목표 위치 (encoder tick)
        self._manual_target_trq = 0    # 수동 모드 목표 토크 (‰)
        self.error_code = 0            # 현재 에러 코드
        self.last_error_code = 0       # 자동 리셋되어도 에러 코드를 기억할 변수

        # ── 스크립트 모드 관련 ──
        self._script: Optional[MotionScript] = None  # 현재 로드된 스크립트
        self._script_update_hz = 200     # 스크립트 평가 주파수 (Hz)
        self._script_target_rpm = 0.0    # 스크립트가 계산한 현재 목표 RPM
        self._script_t0 = None           # 스크립트 시작 시각 (perf_counter)
        self._next_script_eval_t = 0.0   # 다음 스크립트 평가 시점 (경과 시간)

        # ── 비동기 명령 큐 (GUI 스레드에서 넣고, 이 스레드에서 꺼내서 발행) ──
        self._waveform_cmd_queue: deque = deque(maxlen=10)      # 파형 명령 (WaveformCmd 또는 문자열)
        self._log_cmd_queue: deque = deque(maxlen=10)           # CSV 로깅 명령
        self._force_ctrl_cmd_queue: deque = deque(maxlen=20)    # 힘 제어 명령 (ForceCtrlCmd 또는 문자열)

        # ── 소프트 리미트 (로드셀 기반 자동 감속) ──
        self._lc_reader: Optional["LoadCellReader"] = None  # 로드셀 리더 참조
        self._linear_encoder_reader: Optional["LinearEncoderReader"] = None
        self._soft_limit_enabled = False    # 소프트 리미트 활성 여부
        self._force_limit_N      = float(DEFAULT_FORCE_SOFT_LIMIT_N)    # 힘 한계값 (N) — 이 값에서 속도 0
        self._soft_start_pct     = float(DEFAULT_FORCE_SOFT_START_PCT)  # 한계의 몇 %에서 감속 시작
        self._soft_limit_tripped = False    # 한계 초과 로그 중복 방지
        self._external_publisher_warnings = set()  # GUI 내장 센서와 독립 노드 동시 발행 경고 중복 방지

        # ── ROS2 퍼블리셔 (run()에서 초기화) ──
        self.node = None               # ROS2 노드
        self.pub = None                # 목표 속도 퍼블리셔
        self.pub_waveform = None       # 파형 명령 퍼블리셔
        self.pub_waveform_v2 = None    # 파형 구조화 메시지 퍼블리셔
        self.pub_log_cmd = None        # 로깅 명령 퍼블리셔
        self.pub_heartbeat = None      # 하트비트 퍼블리셔
        self.pub_mode = None           # 운전 모드 퍼블리셔
        self.pub_pos = None            # 목표 위치 퍼블리셔
        self.pub_trq = None            # 목표 토크 퍼블리셔
        self.pub_load_cell_ch0 = None  # GUI 내장 로드셀 CH0 퍼블리셔
        self.pub_load_cell_ch1 = None  # GUI 내장 로드셀 CH1 퍼블리셔
        self.pub_linear_count = None    # GUI 내장 리니어 엔코더 카운트 퍼블리셔
        self.pub_linear_mm = None       # GUI 내장 리니어 엔코더 mm 퍼블리셔
        self.pub_force_ctrl_v2 = None   # 힘 제어 구조화 메시지 퍼블리셔

    # ==========================================================
    # 값 설정 함수들 — GUI 스레드에서 호출, _lock으로 스레드 안전 보장
    # ==========================================================
    def set_manual_target_rpm(self, rpm: float):
        """수동 목표 RPM 설정 — 스레드 루프에서 가속도를 적용하며 발행됨."""
        with self._lock: self._manual_target_rpm = float(rpm)

    def set_accel(self, rpm_per_s: float):
        """가속도 제한 설정 (rpm/s) — C++ 노드에도 토픽으로 전달."""
        with self._lock: self._accel_rpm_per_s = max(0.0, float(rpm_per_s))
        # C++ 노드의 가속도 제한도 동기화
        if hasattr(self, 'pub_accel') and self.pub_accel:
            m = Int32()
            m.data = int(self._accel_rpm_per_s)
            self.pub_accel.publish(m)

    def set_rpm_limit(self, rpm_limit: float):
        """절대 RPM 상한 설정 — 양방향(±) 제한."""
        with self._lock: self._rpm_limit = max(0.0, float(rpm_limit))

    def set_op_mode(self, mode: int):
        """운전 모드 변경 (8=CSP 위치, 9=CSV 속도, 10=CST 토크).

        C++ 노드에 즉시 토픽으로 전달하여 모드 전환을 수행한다.
        """
        with self._lock: self._op_mode = mode
        if hasattr(self, 'pub_mode') and self.pub_mode:
            m = Int32(); m.data = mode
            self.pub_mode.publish(m)

    def set_manual_target_pos(self, pos: int):
        """수동 목표 위치 설정 (encoder tick) — 즉시 C++ 노드에 전달."""
        with self._lock: self._manual_target_pos = int(pos)
        if hasattr(self, 'pub_pos') and self.pub_pos:
            m = Int32(); m.data = int(pos)
            self.pub_pos.publish(m)

    def set_pos_speed_limit(self, tps: int):
        """위치 제어 시 이동 속도 제한 (Tick/s) — C++ 노드에 전달."""
        if hasattr(self, 'pub_pos_speed') and self.pub_pos_speed:
            m = Int32(); m.data = int(tps)
            self.pub_pos_speed.publish(m)

    def set_manual_target_trq(self, trq: int):
        """수동 목표 토크 설정 (‰, 천분율) — 즉시 C++ 노드에 전달."""
        with self._lock: self._manual_target_trq = int(trq)
        if hasattr(self, 'pub_trq') and self.pub_trq:
            m = Int32(); m.data = int(trq)
            self.pub_trq.publish(m)

    def set_script_update_hz(self, hz: int):
        """스크립트 평가 주파수 변경 (1~1000 Hz)."""
        with self._lock: self._script_update_hz = int(max(1, min(1000, hz)))

    def start_script(self, script: MotionScript):
        """모션 스크립트를 시작 — 모드를 "script"로 전환하고 시작 시각을 기록."""
        with self._lock:
            self._script = script
            self._mode = "script"
            self._script_t0 = time.perf_counter()
            self._next_script_eval_t = 0.0
        self.log_signal.emit(f"[{now_str()}] 스크립트 시작: {os.path.basename(script.path)}")

    def stop_script(self):
        """모션 스크립트를 종료하고 수동 모드로 복귀."""
        with self._lock:
            self._mode = "manual"
            self._script = None
            self._script_target_rpm = 0.0
        self.log_signal.emit(f"[{now_str()}] 스크립트 종료 -> 수동 모드")

    def send_waveform_cmd(self, cmd):
        """파형 명령을 큐에 넣어 다음 루프에서 C++ 노드에 발행.

        WaveformCmd 객체를 우선 사용하고, 메시지 패키지가 없는 환경에서는 문자열을 사용한다.
        정지 명령이면 수동 모드로 복귀한다.
        파형 생성 자체는 C++ RT 루프에서 수행 (정밀한 타이밍 보장).
        """
        self._waveform_cmd_queue.append(cmd)
        with self._lock:
            if self._is_waveform_stop_cmd(cmd):
                self._mode = "manual"
            else:
                self._mode = "waveform"

    def send_log_cmd(self, cmd: str):
        """CSV 로깅 명령을 큐에 넣어 C++ 노드에 전달 ("start <path>" / "stop")."""
        self._log_cmd_queue.append(cmd)

    def send_force_ctrl_cmd(self, cmd):
        """힘 제어 명령을 큐에 넣어 C++ 노드에 전달 ("start"/"stop"/"pid ..."등)."""
        self._force_ctrl_cmd_queue.append(cmd)

    def _is_waveform_stop_cmd(self, cmd) -> bool:
        """문자열/구조화 메시지 양쪽의 파형 정지 명령을 판별한다."""
        if isinstance(cmd, str):
            return cmd.strip().lower() in ("none", "stop")
        return (
            WAVEFORM_MSG_AVAILABLE
            and WaveformCmd is not None
            and isinstance(cmd, WaveformCmd)
            and cmd.action == WaveformCmd.ACTION_STOP
        )

    def set_force_reader(self, reader: "LoadCellReader"):
        """LoadCellReader 인스턴스 연결 — 소프트 리미트에 사용."""
        self._lc_reader = reader

    def set_linear_encoder_reader(self, reader: "LinearEncoderReader"):
        """LinearEncoderReader 인스턴스 연결 — CSV 기록/후속 위치 제어에 사용."""
        self._linear_encoder_reader = reader

    def set_soft_limit(self, enabled: bool, limit_N: float, start_pct: float):
        """소프트 리미트 파라미터 설정.

        로드셀 측정 힘이 start_pct% 부터 선형 감속하여 limit_N에서 속도 0으로 만든다.
        """
        with self._lock:
            self._soft_limit_enabled = enabled
            self._force_limit_N      = max(1.0, limit_N)
            self._soft_start_pct     = max(0.0, min(99.0, start_pct))

    def emergency_stop(self):
        """비상 정지 — 모든 목표를 0으로, 파형/힘 제어 중지, 수동 모드 복귀."""
        with self._lock:
            self._manual_target_rpm = 0.0
            self._script_target_rpm = 0.0
            self._mode = "manual"
        self._waveform_cmd_queue.append("none")
        self._force_ctrl_cmd_queue.append("stop")
        self.log_signal.emit(f"[{now_str()}] 비상정지")

    def _publish_heartbeat_if_due(self, now_t: float, last_hb_t: float, hb_counter: int, interval: float):
        """Heartbeat를 주기적으로 발행하고 갱신된 타이밍 상태를 반환한다."""
        if (now_t - last_hb_t) < interval:
            return last_hb_t, hb_counter
        self.pub_heartbeat.publish(Int32(data=hb_counter))
        return now_t, hb_counter + 1

    def _publish_load_cell_feedback(self):
        """GUI 내장 로드셀 값을 C++ 노드가 구독하는 ROS2 토픽으로 발행한다."""
        reader = self._lc_reader
        if reader is None or not any(reader.connected):
            return False
        forces_n = reader.get_all_forces_N()
        if len(forces_n) > 0 and reader.connected[0]:
            self._warn_if_external_sensor_publisher(TOPIC_LOAD_CELL_CH0_N, "로드셀 CH0")
            self.pub_load_cell_ch0.publish(Float32(data=float(forces_n[0])))
        if len(forces_n) > 1 and reader.connected[1]:
            self._warn_if_external_sensor_publisher(TOPIC_LOAD_CELL_CH1_N, "로드셀 CH1")
            self.pub_load_cell_ch1.publish(Float32(data=float(forces_n[1])))
        return True

    def _publish_linear_encoder_feedback(self):
        """GUI 내장 리니어 엔코더 값을 C++ 노드/로그용 ROS2 토픽으로 발행한다."""
        reader = self._linear_encoder_reader
        if reader is None or not reader.connected:
            return False
        self._warn_if_external_sensor_publisher(TOPIC_LINEAR_ENCODER_COUNT, "리니어 엔코더 count")
        self._warn_if_external_sensor_publisher(TOPIC_LINEAR_ENCODER_MM, "리니어 엔코더 mm")
        self.pub_linear_count.publish(Int32(data=int(reader.get_position_count())))
        self.pub_linear_mm.publish(Float32(data=float(reader.get_position_mm())))
        return True

    def _warn_if_external_sensor_publisher(self, topic: str, label: str):
        """같은 센서 토픽에 GUI 외 발행자가 있으면 한 번만 경고한다."""
        if self.node is None or topic in self._external_publisher_warnings:
            return
        try:
            publisher_count = int(self.node.count_publishers(topic))
        except Exception:
            return
        if publisher_count <= 1:
            return
        self._external_publisher_warnings.add(topic)
        self.log_signal.emit(
            f"[{now_str()}] 경고: {label} 토픽({topic})에 publisher가 {publisher_count}개 있습니다. "
            "GUI 내장 센서 리더와 독립 센서 노드를 동시에 켜면 데이터가 섞일 수 있습니다."
        )

    def _drain_command_queues(self):
        """GUI/CLI 스레드가 넣은 비동기 명령 큐를 ROS2 토픽으로 비운다."""
        while self._waveform_cmd_queue:
            waveform_cmd = self._waveform_cmd_queue.popleft()
            if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None and isinstance(waveform_cmd, WaveformCmd):
                waveform_msg = waveform_cmd
            else:
                waveform_msg = build_waveform_msg(waveform_cmd)
            if waveform_msg is not None and self.pub_waveform_v2 is not None:
                self.pub_waveform_v2.publish(waveform_msg)
            else:
                self.pub_waveform.publish(String(data=str(waveform_cmd)))

        while self._log_cmd_queue:
            self.pub_log_cmd.publish(String(data=self._log_cmd_queue.popleft()))

        while self._force_ctrl_cmd_queue:
            force_cmd = self._force_ctrl_cmd_queue.popleft()
            if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None and isinstance(force_cmd, ForceCtrlCmd):
                force_msg = force_cmd
            else:
                force_msg = build_force_ctrl_msg(force_cmd)
            if force_msg is not None and self.pub_force_ctrl_v2 is not None:
                self.pub_force_ctrl_v2.publish(force_msg)
            else:
                self.pub_force_ctrl.publish(String(data=str(force_cmd)))

    def _current_mode(self) -> str:
        with self._lock:
            return self._mode

    def _compute_mode_target_rpm(self, now_t: float, mode: str):
        """현재 수동/스크립트 상태에서 목표 RPM과 소프트 리미트 설정을 계산한다."""
        with self._lock:
            rpm_limit = self._rpm_limit
            manual_target = self._manual_target_rpm
            script_obj = self._script
            script_hz = self._script_update_hz
            script_t0 = self._script_t0
            soft_enabled = self._soft_limit_enabled
            force_limit_N = self._force_limit_N
            soft_start_pct = self._soft_start_pct

            if mode == "script" and script_obj is not None and script_t0 is not None:
                script_elapsed = now_t - script_t0
                script_period = 1.0 / float(script_hz)
                if script_elapsed >= self._next_script_eval_t:
                    try:
                        val = float(script_obj.func(script_elapsed, script_obj.state))
                        self._script_target_rpm = max(-rpm_limit, min(rpm_limit, val))
                    except Exception as e:
                        self._script_target_rpm = 0.0
                        self._mode = "manual"
                        self._script = None
                        self.script_error_signal.emit(f"스크립트 오류: {e}")
                    self._next_script_eval_t = script_elapsed + script_period
                desired = self._script_target_rpm
            else:
                desired = manual_target

        return float(desired), soft_enabled, force_limit_N, soft_start_pct

    def _apply_soft_limit(self, cmd_rpm: float, enabled: bool, limit_N: float, start_pct: float) -> float:
        """로드셀 기반 소프트 리미트를 적용해 최종 RPM을 줄인다."""
        reader = self._lc_reader
        if not enabled or reader is None or not any(reader.connected):
            return cmd_rpm

        force_abs_N = reader.get_soft_limit_force_N()
        start_N = limit_N * start_pct / 100.0
        if force_abs_N >= limit_N:
            if not self._soft_limit_tripped:
                self._soft_limit_tripped = True
                self.log_signal.emit(f"[{now_str()}] 소프트 리미트 STOP: max|F|={force_abs_N:.2f} N")
            return 0.0
        if force_abs_N >= start_N:
            scale = 1.0 - (force_abs_N - start_N) / max(limit_N - start_N, 1e-6)
            self._soft_limit_tripped = False
            return cmd_rpm * max(0.0, min(1.0, scale))

        self._soft_limit_tripped = False
        return cmd_rpm

    def _sleep_until_next_cycle(self, started_t: float, target_dt: float):
        elapsed = time.perf_counter() - started_t
        sleep_t = target_dt - elapsed
        if sleep_t > 0:
            time.sleep(sleep_t)
        else:
            time.sleep(0.0002)  # 최소 대기 (CPU 양보)

    # ==========================================================
    # 메인 스레드 루프 — ROS2 퍼블리셔 생성 후 무한 루프 실행
    # ==========================================================
    def run(self):
        """CommandThread 진입점 — ROS2 노드 생성, 퍼블리셔 등록, 제어 루프 실행.

        루프 주기: cmd_hz(기본 200Hz)
        루프 내에서 수행하는 작업:
          1. Heartbeat 발행 (10Hz 간격)
          2. 로드셀 힘 값 발행 (200Hz 간격)
          3. 큐에 쌓인 파형/로깅/힘제어 명령 발행
          4. 현재 모드에 따른 목표 속도 계산 및 발행
        """
        if not rclpy.ok(): return

        self.node = rclpy.create_node("gui_commander")

        # 모든 제어 명령은 Reliable QoS 사용 — 명령 유실 방지
        qos_cmd = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST, depth=10,
            durability=DurabilityPolicy.VOLATILE)

        # ── 제어 명령 퍼블리셔 생성 ──
        self.pub = self.node.create_publisher(Int32, TARGET_TOPIC, qos_cmd)               # 목표 속도
        self.pub_waveform = self.node.create_publisher(String, TOPIC_WAVEFORM_CMD, qos_cmd) # 파형 명령
        if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None:
            self.pub_waveform_v2 = self.node.create_publisher(WaveformCmd, TOPIC_WAVEFORM_CMD_V2, qos_cmd)
        self.pub_log_cmd = self.node.create_publisher(String, TOPIC_LOG_CMD, qos_cmd)       # 로깅 명령
        self.pub_mode = self.node.create_publisher(Int32, TOPIC_OP_MODE, qos_cmd)           # 운전 모드
        self.pub_pos = self.node.create_publisher(Int32, TOPIC_TARGET_POS, qos_cmd)         # 목표 위치
        self.pub_trq = self.node.create_publisher(Int32, TOPIC_TARGET_TRQ, qos_cmd)         # 목표 토크
        self.pub_pos_speed = self.node.create_publisher(Int32, '/pos_speed_limit', qos_cmd) # 위치 제어 속도 제한
        self.pub_accel = self.node.create_publisher(Int32, "/accel_limit_rpm_s", qos_cmd)   # 가속도 제한
        self.pub_force_ctrl = self.node.create_publisher(String, TOPIC_FORCE_CTRL_CMD, qos_cmd) # 힘 제어 명령
        if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
            self.pub_force_ctrl_v2 = self.node.create_publisher(ForceCtrlCmd, TOPIC_FORCE_CTRL_CMD_V2, qos_cmd)
        self.pub_target_force = self.node.create_publisher(Float32, TOPIC_TARGET_FORCE, qos_cmd) # 목표 힘

        # 로드셀 힘 값을 C++ 노드에 전달 (GUI에서 Phidget 직접 읽은 값)
        # BestEffort QoS: 힘 피드백은 최신 값만 중요하므로 유실 허용
        qos_force_fb = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST, depth=1,
            durability=DurabilityPolicy.VOLATILE)
        self.pub_load_cell_ch0 = self.node.create_publisher(Float32, TOPIC_LOAD_CELL_CH0_N, qos_force_fb)
        self.pub_load_cell_ch1 = self.node.create_publisher(Float32, TOPIC_LOAD_CELL_CH1_N, qos_force_fb)
        self.pub_linear_count = self.node.create_publisher(Int32, TOPIC_LINEAR_ENCODER_COUNT, qos_force_fb)
        self.pub_linear_mm = self.node.create_publisher(Float32, TOPIC_LINEAR_ENCODER_MM, qos_force_fb)

        # Heartbeat 퍼블리셔 — BestEffort QoS (최신 값만 중요)
        qos_hb = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST, depth=1,
            durability=DurabilityPolicy.VOLATILE)
        self.pub_heartbeat = self.node.create_publisher(Int32, TOPIC_HEARTBEAT, qos_hb)

        target_dt = 1.0 / float(self.cmd_hz)  # 루프 목표 주기 (예: 200Hz → 5ms)
        hb_counter = 0              # 단조 증가 카운터 — C++ 노드가 연속성을 검증
        hb_interval = 0.1           # 100ms = 10Hz
        last_hb_t = time.perf_counter()
        last_force_pub_t = time.perf_counter()
        force_pub_interval = 0.005  # 5ms = 200Hz 로드셀 값 발행
        last_linear_pub_t = time.perf_counter()
        linear_pub_interval = 0.01  # 10ms = 100Hz 리니어 엔코더 값 발행

        # ── 메인 제어 루프 ──
        while self.running and rclpy.ok():
            t0 = time.perf_counter()

            # ── (1) Heartbeat 발행 (10Hz) ──
            # C++ 노드는 이 heartbeat가 일정 시간 이상 끊기면 모터를 안전 정지시킴
            last_hb_t, hb_counter = self._publish_heartbeat_if_due(t0, last_hb_t, hb_counter, hb_interval)

            # ── (2) 로드셀 힘 값을 ROS2로 발행 (200Hz) ──
            # C++ 노드의 힘 제어 PID 루프가 이 값을 피드백으로 사용
            if (t0 - last_force_pub_t) >= force_pub_interval and self._publish_load_cell_feedback():
                last_force_pub_t = t0

            # ── (2b) 리니어 엔코더 값을 ROS2로 발행 (100Hz) ──
            if (t0 - last_linear_pub_t) >= linear_pub_interval and self._publish_linear_encoder_feedback():
                last_linear_pub_t = t0

            # ── (3) 큐에 쌓인 비동기 명령 처리 ──
            # 파형/로깅/힘제어 명령은 GUI 스레드에서 큐에 넣고, 여기서 꺼내서 발행
            self._drain_command_queues()
            mode = self._current_mode()

            # ── (4) 파형 모드: C++ 측에서 파형을 생성하므로 Python은 대기만 함 ──
            if mode == "waveform":
                time.sleep(max(target_dt - (time.perf_counter() - t0), 0.001))
                continue

            # ── (5) 수동/스크립트 모드: 목표 RPM 계산 및 발행 ──
            cmd_rpm, soft_enabled, force_limit_N, soft_start_pct = self._compute_mode_target_rpm(t0, mode)
            cmd_rpm = self._apply_soft_limit(cmd_rpm, soft_enabled, force_limit_N, soft_start_pct)

            # 계산된 최종 RPM을 ROS2 토픽으로 발행
            msg = Int32()
            msg.data = int(cmd_rpm)
            self.pub.publish(msg)

            # 정확한 루프 주기 유지 — 남은 시간만큼 sleep
            self._sleep_until_next_cycle(t0, target_dt)

        # ── 스레드 종료 시 ROS2 노드 정리 ──
        try:
            if self.node: self.node.destroy_node()
        except Exception: pass

    def stop(self):
        """스레드 종료 요청 및 대기."""
        self.running = False
        self.wait()

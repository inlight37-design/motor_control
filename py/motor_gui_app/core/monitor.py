# -*- coding: utf-8 -*-
"""ROS2 피드백과 진단 토픽을 감시하는 스레드."""
import json
import time
from collections import deque

from .ros_bootstrap import prepare_ros_environment

# rclpy import 전에 DDS 설정이 끝나야 한다.
prepare_ros_environment()

import rclpy
from PyQt5.QtCore import QThread, pyqtSignal
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32, Int32, String
from std_srvs.srv import Trigger

from .epos_errors import EPOS_ERROR_MAP
from .feedback_state import (
    LinearEncoderFeedback,
    LoadCellFeedback,
    MotorFeedback,
    RealtimeDiagnostics,
)
from .time_utils import now_str
from .topics import (
    EPOS_NODE_EXECUTABLE,
    FEEDBACK_TOPIC,
    TARGET_TOPIC,
    TOPIC_ACTUAL_POS,
    TOPIC_ACTUAL_TRQ,
    TOPIC_CYCLE_DT,
    TOPIC_DIAG_SUMMARY,
    TOPIC_ERROR_CODE,
    TOPIC_JITTER,
    TOPIC_LINEAR_ENCODER_COUNT,
    TOPIC_LINEAR_ENCODER_MM,
    TOPIC_LOAD_CELL_CH0_N,
    TOPIC_LOAD_CELL_CH1_N,
    TOPIC_LOAD_CELL_STATUS,
    TOPIC_OVERRUN,
    TOPIC_STATUS_WORD,
    TOPIC_WKC_ERR,
)

class MonitorThread(QThread):
    feedback_signal = pyqtSignal(int)           # 실측 속도 피드백 (현재 미사용)
    resend_targets_signal = pyqtSignal()        # Fault 복구 후 목표값 재전송 요청
    log_signal = pyqtSignal(str)                # GUI 로그에 메시지 전달
    fault_signal = pyqtSignal(bool)             # Fault 상태 변경 알림 (True=Fault 발생)

    def __init__(self, speed_queue: deque, rt_queue: deque):
        super().__init__()
        self.speed_queue = speed_queue  # 속도 그래프 데이터 전달 큐 (time, target, actual)
        self.rt_queue = rt_queue        # RT 주기 그래프 데이터 전달 큐 (time, dt_us)
        self.running = True

        # ── 최신 수신 데이터 저장 (GUI 타이머에서 읽어감) ──
        self.motor_feedback = MotorFeedback()
        self.realtime_diagnostics = RealtimeDiagnostics()
        self.load_cell_feedback = LoadCellFeedback()
        self.linear_encoder_feedback = LinearEncoderFeedback()

        # ── Fault 자동 복구 관련 ──
        self._fault_reset_requested = False  # fault_reset 서비스 호출 요청 플래그
        self._auto_fault_reset = False       # 자동 Fault 복구 활성 여부
        self._last_fault_reset_time = 0.0    # 마지막 fault_reset 시도 시각 (과도한 재시도 방지)

        self.node = None                    # ROS2 노드
        self._fault_reset_client = None     # fault_reset 서비스 클라이언트

    # ── 기존 호출부 호환용 alias. 새 코드는 *_feedback 객체나 StateView를 우선 사용한다. ──

    @property
    def latest_target(self):
        return self.motor_feedback.target_rpm

    @latest_target.setter
    def latest_target(self, value):
        self.motor_feedback.target_rpm = int(value)

    @property
    def latest_status_word(self):
        return self.motor_feedback.status_word

    @latest_status_word.setter
    def latest_status_word(self, value):
        self.motor_feedback.status_word = int(value)

    @property
    def latest_error_code(self):
        return self.motor_feedback.error_code

    @latest_error_code.setter
    def latest_error_code(self, value):
        self.motor_feedback.error_code = int(value)

    @property
    def memorized_error_code(self):
        return self.motor_feedback.memorized_error_code

    @memorized_error_code.setter
    def memorized_error_code(self, value):
        self.motor_feedback.memorized_error_code = int(value)

    @property
    def memorized_error_time(self):
        return self.motor_feedback.memorized_error_time

    @memorized_error_time.setter
    def memorized_error_time(self, value):
        self.motor_feedback.memorized_error_time = float(value)

    @property
    def latest_actual_pos(self):
        return self.motor_feedback.actual_position_ticks

    @latest_actual_pos.setter
    def latest_actual_pos(self, value):
        self.motor_feedback.actual_position_ticks = int(value)

    @property
    def latest_actual_trq(self):
        return self.motor_feedback.actual_torque_permille

    @latest_actual_trq.setter
    def latest_actual_trq(self, value):
        self.motor_feedback.actual_torque_permille = int(value)

    @property
    def latest_jitter(self):
        return self.realtime_diagnostics.jitter_us

    @latest_jitter.setter
    def latest_jitter(self, value):
        self.realtime_diagnostics.jitter_us = int(value)

    @property
    def latest_overrun(self):
        return self.realtime_diagnostics.overrun_count

    @latest_overrun.setter
    def latest_overrun(self, value):
        self.realtime_diagnostics.overrun_count = int(value)

    @property
    def latest_wkc_err(self):
        return self.realtime_diagnostics.wkc_error_count

    @latest_wkc_err.setter
    def latest_wkc_err(self, value):
        self.realtime_diagnostics.wkc_error_count = int(value)

    @property
    def diag_dt_mean(self):
        return self.realtime_diagnostics.dt_mean_us

    @diag_dt_mean.setter
    def diag_dt_mean(self, value):
        self.realtime_diagnostics.dt_mean_us = int(value)

    @property
    def diag_jitter_mean(self):
        return self.realtime_diagnostics.jitter_mean_us

    @diag_jitter_mean.setter
    def diag_jitter_mean(self, value):
        self.realtime_diagnostics.jitter_mean_us = int(value)

    @property
    def diag_jitter_max(self):
        return self.realtime_diagnostics.jitter_max_us

    @diag_jitter_max.setter
    def diag_jitter_max(self, value):
        self.realtime_diagnostics.jitter_max_us = int(value)

    @property
    def diag_overrun(self):
        return self.realtime_diagnostics.diag_overrun_count

    @diag_overrun.setter
    def diag_overrun(self, value):
        self.realtime_diagnostics.diag_overrun_count = int(value)

    @property
    def diag_wkc_err(self):
        return self.realtime_diagnostics.diag_wkc_error_count

    @diag_wkc_err.setter
    def diag_wkc_err(self, value):
        self.realtime_diagnostics.diag_wkc_error_count = int(value)

    @property
    def latest_force_ch0_N(self):
        return self.load_cell_feedback.force_n(0)

    @latest_force_ch0_N.setter
    def latest_force_ch0_N(self, value):
        self.load_cell_feedback.forces_n[0] = float(value)

    @property
    def latest_force_ch1_N(self):
        return self.load_cell_feedback.force_n(1)

    @latest_force_ch1_N.setter
    def latest_force_ch1_N(self, value):
        self.load_cell_feedback.forces_n[1] = float(value)

    @property
    def lc_safety_tripped(self):
        return self.load_cell_feedback.safety_tripped

    @lc_safety_tripped.setter
    def lc_safety_tripped(self, value):
        self.load_cell_feedback.safety_tripped = bool(value)

    @property
    def last_lc_recv_t(self):
        return self.load_cell_feedback.last_recv_t

    @last_lc_recv_t.setter
    def last_lc_recv_t(self, value):
        self.load_cell_feedback.last_recv_t = float(value)

    @property
    def latest_linear_count(self):
        return self.linear_encoder_feedback.count

    @latest_linear_count.setter
    def latest_linear_count(self, value):
        self.linear_encoder_feedback.count = int(value)

    @property
    def latest_linear_mm(self):
        return self.linear_encoder_feedback.mm

    @latest_linear_mm.setter
    def latest_linear_mm(self, value):
        self.linear_encoder_feedback.mm = float(value)

    @property
    def last_linear_recv_t(self):
        return self.linear_encoder_feedback.last_recv_t

    @last_linear_recv_t.setter
    def last_linear_recv_t(self, value):
        self.linear_encoder_feedback.last_recv_t = float(value)

    def run(self):
        """MonitorThread 진입점 — ROS2 노드 생성, 구독 등록, spin 루프.

        spin_once()를 5ms 타임아웃으로 호출하여, 콜백을 처리하면서
        Fault 복구 로직도 주기적으로 실행한다.
        """
        if not rclpy.ok():
            return
        self.node = rclpy.create_node("gui_monitor")

        # BestEffort QoS — 피드백 데이터는 최신 값만 중요, 유실 허용
        qos = QoSProfile(reliability=ReliabilityPolicy.BEST_EFFORT,
                         history=HistoryPolicy.KEEP_LAST, depth=1,
                         durability=DurabilityPolicy.VOLATILE)

        # Reliable QoS — C++ 노드의 퍼블리셔와 QoS를 일치시켜야 통신 가능
        qos_reliable = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST, depth=10,
            durability=DurabilityPolicy.VOLATILE)

        # ── 실시간 그래프용 구독 (속도, RT 주기) ──
        self.node.create_subscription(Int32, TARGET_TOPIC, self._cb_target, qos_reliable)
        self.node.create_subscription(Int32, FEEDBACK_TOPIC, self._cb_actual, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_CYCLE_DT, self._cb_cycle_dt, qos_reliable)

        # ── 상태 및 진단 구독 ──
        self.node.create_subscription(Int32, TOPIC_STATUS_WORD, self._cb_status, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_ERROR_CODE, self._cb_error_code, qos_reliable)

        self.node.create_subscription(Int32, TOPIC_JITTER, self._cb_jitter, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_OVERRUN, self._cb_overrun, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_WKC_ERR, self._cb_wkc_err, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_ACTUAL_POS, self._cb_pos, qos_reliable)
        self.node.create_subscription(Int32, TOPIC_ACTUAL_TRQ, self._cb_trq, qos_reliable)

        # v3: 진단 요약 JSON 구독 (10Hz, C++ 노드에서 통합 진단 데이터 전송)
        self.node.create_subscription(String, TOPIC_DIAG_SUMMARY, self._cb_diag_summary, qos_reliable)

        # 로드셀 구독 (load_cell_node.py 실행 중일 때만 데이터 수신, 없어도 정상 동작)
        self.node.create_subscription(Float32, TOPIC_LOAD_CELL_CH0_N, self._cb_force_ch0, qos)
        self.node.create_subscription(Float32, TOPIC_LOAD_CELL_CH1_N, self._cb_force_ch1, qos)
        self.node.create_subscription(String, TOPIC_LOAD_CELL_STATUS, self._cb_lc_status, qos)
        self.node.create_subscription(Int32, TOPIC_LINEAR_ENCODER_COUNT, self._cb_linear_count, qos)
        self.node.create_subscription(Float32, TOPIC_LINEAR_ENCODER_MM, self._cb_linear_mm, qos)

        # fault_reset 서비스 클라이언트 — C++ 노드의 Fault 복구 서비스 호출용
        self._fault_reset_client = self.node.create_client(Trigger, f"/{EPOS_NODE_EXECUTABLE}/fault_reset")

        # ── 메인 spin 루프 ──
        while self.running and rclpy.ok():
            # spin_once로 콜백 처리 (5ms 타임아웃으로 빠르게 반환)
            rclpy.spin_once(self.node, timeout_sec=0.005)
            # Fault 감지 및 자동 복구 처리
            self._process_fault_reset()
            time.sleep(0.0001)  # CPU 양보

        try:
            if self.node: self.node.destroy_node()
        except Exception:
            pass

    def _process_fault_reset(self):
        """Fault 상태를 확인하고 자동 복구를 수행.

        1. 상태 워드의 bit3(Fault) 확인 → fault_signal로 GUI에 알림
        2. 자동 복구 활성화 시, 3초 쿨다운 후 fault_reset 서비스 호출
        3. Fault 해제 후 목표값 재전송 트리거 (위치/토크 모드에서 필요)
        """
        now = time.time()
        # CiA 402 상태 워드 bit3 = Fault 비트
        is_fault = self.motor_feedback.is_fault()
        self.fault_signal.emit(is_fault)

        if self._auto_fault_reset and is_fault:
            # 과도한 재시도 방지: 최소 3초 간격으로만 시도
            if (now - self._last_fault_reset_time) > 3.0:
                # 에러 코드 확인 — 자동 리셋으로 이미 0이 되었을 수 있으므로 기억된 코드도 확인
                err_code = self.motor_feedback.error_code
                if err_code == 0:
                    err_code = self.motor_feedback.memorized_error_code

                err_name = EPOS_ERROR_MAP.get(err_code, "Unknown Error")
                # 터미널과 GUI 로그 양쪽에 에러 정보 출력
                print(f"\n[에러 감지] 🚨 FAULT 발생! 코드: 0x{err_code:04X} ({err_name})\n")
                self.log_signal.emit(f"[{now_str()}] 🚨 FAULT 발생! 코드: 0x{err_code:04X} ({err_name})")

                self._fault_reset_requested = True
                self.log_signal.emit(f"[{now_str()}] 자동 Fault Reset 시도 중...")

        if self._fault_reset_requested:
            self._fault_reset_requested = False
            self._last_fault_reset_time = now
            self._need_resend_after_fault = True  # Fault 해제 후 목표값 재전송 예약
            if self._fault_reset_client:
                # 비동기 서비스 호출 — 결과를 기다리지 않고 바로 반환
                self._fault_reset_client.call_async(Trigger.Request())
                self.log_signal.emit(f"[{now_str()}] fault_reset 호출 완료")

        # Fault 해제 후 위치/토크 재전송 — 모터가 복구된 후 GUI의 현재 설정값으로 다시 전송
        if hasattr(self, '_need_resend_after_fault') and self._need_resend_after_fault and not is_fault:
            self._need_resend_after_fault = False
            self.resend_targets_signal.emit()

    def request_fault_reset(self):
        """수동 Fault Reset 요청 — GUI의 "Fault Reset" 버튼 클릭 시 호출."""
        self._fault_reset_requested = True

    def set_auto_fault_reset(self, enabled: bool):
        """자동 Fault 복구 활성/비활성 — GUI의 "자동복구" 체크박스에서 호출."""
        self._auto_fault_reset = enabled

    def get_memorized_error(self) -> tuple[int, float]:
        """자동 리셋 후에도 잠깐 표시할 최근 에러 코드와 발생 시각을 반환."""
        return (
            self.motor_feedback.memorized_error_code,
            self.motor_feedback.memorized_error_time,
        )

    def clear_memorized_error(self):
        """최근 에러 표시 상태를 초기화."""
        self.motor_feedback.memorized_error_code = 0
        self.motor_feedback.memorized_error_time = 0.0

    # ── ROS2 콜백 함수들 (ROS2 spin 스레드에서 호출됨) ──

    def _cb_force_ch0(self, msg):
        """로드셀 채널 0 힘 값 수신 콜백."""
        self.load_cell_feedback.set_force_n(0, msg.data)

    def _cb_force_ch1(self, msg):
        """로드셀 채널 1 힘 값 수신 콜백."""
        self.load_cell_feedback.set_force_n(1, msg.data)

    def _cb_lc_status(self, msg):
        """로드셀 상태 JSON 수신 콜백 — 안전 차단 상태를 파싱."""
        try:
            d = json.loads(msg.data)
            self.load_cell_feedback.safety_tripped = bool(d.get("safety_tripped", False))
        except (json.JSONDecodeError, KeyError):
            pass

    def _cb_linear_count(self, msg):
        """리니어 엔코더 카운트 수신 콜백."""
        self.linear_encoder_feedback.count = int(msg.data)
        self.linear_encoder_feedback.last_recv_t = time.time()

    def _cb_linear_mm(self, msg):
        """리니어 엔코더 mm 위치 수신 콜백."""
        self.linear_encoder_feedback.mm = float(msg.data)
        self.linear_encoder_feedback.last_recv_t = time.time()

    def _cb_target(self, msg): self.motor_feedback.target_rpm = int(msg.data)
    def _cb_pos(self, msg): self.motor_feedback.actual_position_ticks = int(msg.data)
    def _cb_trq(self, msg): self.motor_feedback.actual_torque_permille = int(msg.data)
    def _cb_jitter(self, msg): self.realtime_diagnostics.jitter_us = int(msg.data)
    def _cb_overrun(self, msg): self.realtime_diagnostics.overrun_count = int(msg.data)
    def _cb_wkc_err(self, msg): self.realtime_diagnostics.wkc_error_count = int(msg.data)
    def _cb_actual(self, msg):
        """실측 속도 수신 → 속도 그래프용 deque에 (시각, 목표, 실측) 저장."""
        self.speed_queue.append((time.time(), int(self.motor_feedback.target_rpm), int(msg.data)))
    def _cb_cycle_dt(self, msg):
        """RT 루프 주기 수신 → RT 그래프용 deque에 (시각, dt_us) 저장."""
        self.rt_queue.append((time.time(), int(msg.data)))
    def _cb_status(self, msg): self.motor_feedback.status_word = int(msg.data)
    def _cb_error_code(self, msg):
        """에러 코드 수신 콜백 — 0이 아닌 코드는 별도로 기억 (자동 리셋 시 참조)."""
        self.motor_feedback.error_code = int(msg.data)
        if msg.data != 0:
            self.motor_feedback.memorized_error_code = int(msg.data)
            self.motor_feedback.memorized_error_time = time.time()  # 에러 발생 시각 기록

    def _cb_diag_summary(self, msg):
        """v3: 진단 요약 JSON 파싱 콜백 — C++ 노드가 10Hz로 발행하는 통합 진단.

        JSON 구조 예시: {"avg_dt": 1000, "avg_jitter": 15, "max_dt": 1050}
        """
        try:
            d = json.loads(msg.data)
            self.realtime_diagnostics.dt_mean_us = int(d.get("avg_dt", 0))
            self.realtime_diagnostics.jitter_mean_us = int(d.get("avg_jitter", 0))
            self.realtime_diagnostics.jitter_max_us = int(d.get("max_dt", 0))
            self.realtime_diagnostics.diag_overrun_count = int(
                d.get("overrun", self.realtime_diagnostics.diag_overrun_count)
            )
            self.realtime_diagnostics.diag_wkc_error_count = int(
                d.get("wkc_err", self.realtime_diagnostics.diag_wkc_error_count)
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    def get_jitter_avg_us(self):
        """평균 지터 값 반환 (μs). 0도 유효한 데이터이므로 None이 아닌 0을 반환."""
        return self.realtime_diagnostics.jitter_mean_us

    def get_motor_state_str(self) -> str:
        """EPOS4 상태 워드를 사람이 읽을 수 있는 한글 문자열로 변환.

        CiA 402 상태 머신 기반:
        - 0x0008 bit: Fault
        - 0x0027: Operation Enabled (정상 운전)
        - 0x0023: Switched On
        - 0x0021: Ready to Switch On
        - 0x0040: Switch On Disabled
        """
        sw = self.motor_feedback.status_word
        if sw == 0: return "대기"
        if (sw & 0x0008) != 0: return "FAULT"
        elif (sw & 0x006F) == 0x0027: return "정상 (Enabled)"
        elif (sw & 0x006F) == 0x0023: return "스위치 ON"
        elif (sw & 0x006F) == 0x0021: return "전원 대기"
        elif (sw & 0x004F) == 0x0040: return "시작 대기"
        else: return f"0x{sw:04X}"

    def get_error_str(self) -> str:
        """현재 에러 코드를 "0xHHHH 설명" 형식의 문자열로 반환. 정상 시 빈 문자열."""
        code = self.motor_feedback.error_code
        if code == 0: return ""
        name = EPOS_ERROR_MAP.get(code, f"Unknown(0x{code:04X})")
        return f"0x{code:04X} {name}"

    def stop(self):
        """스레드 종료 요청 및 대기."""
        self.running = False
        self.wait()

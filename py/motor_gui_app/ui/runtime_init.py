# -*- coding: utf-8 -*-
"""MasterWindow 런타임 객체, signal, 타이머 초기화 헬퍼."""
import os

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from ..core.config import (
    DEFAULT_CMD_HZ,
    DEFAULT_FORCE_ABS_MODE,
    DEFAULT_LINEAR_COUNTS_PER_MM,
    DEFAULT_LINEAR_ENCODER_CHANNEL,
    DEFAULT_LINEAR_INVERT,
    WORKSPACE_DIR,
)
from ..core.ros_environment import detect_interfaces
from ..devices.load_cell import LoadCellReader
from ..devices.linear_encoder import LinearEncoderReader
from ..core.node_runner import NodeRunner
from ..core.commander import CommandThread
from ..core.monitor import MonitorThread
from ..core.control_client import ControlClient
from ..core.session import MotorSession, SessionFlags, StateView
from ..core.experiments import HysteresisExperiment, HysteresisPreconditions
from ..actions import script_actions, system_actions
from .graph_buffers import GraphBuffers
from .log_buffer import LogBuffer
from . import visibility_actions
from .runtime_components import DeviceReaders, RuntimeThreads
from .window_state import WindowState


def configure_window(window):
    """창 제목과 기본 크기를 설정."""
    window.setWindowTitle(f"EPOS Motor Control - {WORKSPACE_DIR.name} (Heartbeat + 진단 요약)")
    screen = QApplication.primaryScreen()
    if screen:
        avail = screen.availableGeometry()
        window.resize(
            min(1200, max(900, avail.width() - 80)),
            min(1020, max(700, avail.height() - 80)),
        )
    else:
        window.resize(1200, 900)


def init_runtime_objects(window) -> tuple[list[str], str]:
    """그래프 버퍼, ROS 스레드, 센서 리더를 생성하고 기본 인터페이스를 반환."""
    _init_ui_state(window)
    ifaces, default_iface = _detect_default_interface()
    _init_runtime_threads(window, default_iface)
    _init_session(window)
    _init_devices(window)
    return ifaces, default_iface


def _init_ui_state(window):
    """GUI 내부 상태 컨테이너를 만든다."""
    window.graph_buffers = GraphBuffers()
    window.ui_state = WindowState(force_abs_mode=DEFAULT_FORCE_ABS_MODE)
    # 직접 append하지 않고 타이머로 flush하여 로그가 많을 때 UI 끊김을 줄인다.
    window.log_buffer = LogBuffer()


def _detect_default_interface() -> tuple[list[str], str]:
    """사용 가능한 네트워크 인터페이스와 기본값을 고른다."""
    ifaces = detect_interfaces()
    default_iface = os.environ.get("EPOS_IFACE", "")
    if not default_iface and ifaces:
        default_iface = ifaces[0]
    return ifaces, default_iface


def _init_runtime_threads(window, default_iface: str):
    """ROS/C++ 노드 실행과 통신 스레드 객체를 만든다."""
    node_runner = NodeRunner(iface=default_iface)
    commander = CommandThread(cmd_hz=DEFAULT_CMD_HZ)
    control = ControlClient(commander)
    monitor = MonitorThread(window.graph_buffers.speed_queue, window.graph_buffers.rt_queue)
    window.runtime_threads = RuntimeThreads(
        node_runner=node_runner,
        commander=commander,
        monitor=monitor,
        control=control,
    )
    # 기존 actions/panels가 직접 참조하던 이름은 alias로 유지한다.
    # 새 코드는 runtime_threads를 우선 사용하면 런타임 의존성을 한곳에서 볼 수 있다.
    window.node_runner = node_runner
    window.commander = commander
    window.control = control
    window.monitor = monitor


def _init_session(window):
    """GUI/CLI 공용 세션 컨테이너와 실험 실행기를 연결한다."""
    window.session = MotorSession(
        control=window.control,
        state=StateView(window.monitor),
        flags=SessionFlags(),
    )
    window.session.hysteresis = HysteresisExperiment(
        window.control,
        window.session.flags,
        scheduler=lambda delay_ms, callback: QTimer.singleShot(int(delay_ms), callback),
        preconditions=HysteresisPreconditions(require_motor_running=True),
    )


def _init_devices(window):
    """GUI 내장 센서 리더를 생성하고 Commander에 연결한다."""
    load_cell = LoadCellReader(n_channels=2, alpha=0.1)
    linear_encoder = LinearEncoderReader(
        channel=DEFAULT_LINEAR_ENCODER_CHANNEL,
        counts_per_mm=DEFAULT_LINEAR_COUNTS_PER_MM,
        invert=DEFAULT_LINEAR_INVERT,
    )
    window.device_readers = DeviceReaders(
        load_cell=load_cell,
        linear_encoder=linear_encoder,
    )
    # 기존 actions가 쓰는 센서 이름은 alias로 유지한다.
    # 새 센서는 DeviceReaders에 추가한 뒤 필요한 alias만 단계적으로 둔다.
    window.lc_reader = load_cell
    window.linear_encoder = linear_encoder
    window.commander.set_force_reader(load_cell)
    window.commander.set_linear_encoder_reader(linear_encoder)


def connect_runtime_signals(window):
    """런타임 스레드 signal과 위젯→런타임 설정 변경을 연결."""
    _connect_thread_signals(window)
    _connect_top_status_signals(window)
    _connect_command_setting_signals(window)
    _connect_panel_visibility_signals(window)


def _connect_thread_signals(window):
    """NodeRunner/Commander/Monitor에서 올라오는 signal을 연결."""
    window.node_runner.log_signal.connect(window.update_log)
    window.node_runner.state_signal.connect(lambda running: system_actions.on_motor_state(window, running))
    window.commander.log_signal.connect(window.update_log)
    window.commander.script_error_signal.connect(lambda msg: script_actions.on_script_error(window, msg))
    window.monitor.log_signal.connect(window.update_log)
    window.monitor.fault_signal.connect(lambda is_fault: system_actions.on_fault_state(window, is_fault))
    window.monitor.resend_targets_signal.connect(lambda: system_actions.resend_after_fault(window))


def _connect_top_status_signals(window):
    """상단 상태/진단 위젯과 런타임 객체를 연결."""
    top_status = window.top_status_widgets
    top_status.iface_combo.currentTextChanged.connect(window.node_runner.set_iface)
    top_status.fault_reset_button.clicked.connect(lambda _checked=False: window.monitor.request_fault_reset())
    top_status.auto_reset_checkbox.toggled.connect(window.monitor.set_auto_fault_reset)
    window.monitor.set_auto_fault_reset(top_status.auto_reset_checkbox.isChecked())


def _connect_command_setting_signals(window):
    """명령 주기 중 즉시 반영되는 설정 위젯을 연결."""
    manual_motion = window.manual_motion_widgets
    manual_motion.accel_spin.valueChanged.connect(lambda v: window.control.set_accel_limit(float(v)))
    manual_motion.limit_spin.valueChanged.connect(lambda v: window.control.set_rpm_limit(float(v)))
    window.script_log_widgets.script_hz_spin.valueChanged.connect(lambda v: window.control.set_script_update_hz(int(v)))


def _connect_panel_visibility_signals(window):
    """패널 표시 체크박스 묶음을 연결."""
    for checkbox in window.panel_visibility_widgets.checkboxes():
        checkbox.toggled.connect(lambda _checked=False: visibility_actions.toggle_panel_visibility(window))
    visibility_actions.toggle_panel_visibility(window)


def start_runtime_loops(window):
    """그래프 타이머와 ROS 통신 스레드를 시작."""
    window.render_timer = QTimer()
    window.render_timer.timeout.connect(window.update_graphs)
    window.render_timer.start(33)

    window.log_buffer.timer = QTimer()
    window.log_buffer.timer.timeout.connect(window.flush_log_buffer)
    window.log_buffer.timer.start(100)

    window.commander.start()
    window.monitor.start()


def init_state_flags(window):
    """실행 상태 플래그와 위치 입력 보조 상태를 초기화."""
    window.session.flags.reset_runtime()
    window.ui_state.reset_runtime()

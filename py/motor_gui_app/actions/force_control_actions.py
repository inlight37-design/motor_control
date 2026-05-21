# -*- coding: utf-8 -*-
"""힘 제어 시작/정지, PID/Tanh 파라미터 적용 UI 동작."""
from ..core.control_client import (
    ForceControlSettings,
    ForcePidSettings,
    ForceTanhSettings,
)
from ..core.time_utils import now_str
from . import load_cell_actions


def start_force_ctrl(window):
    """힘 제어 시작. UI 입력을 ControlClient 설정 객체로 변환한다."""
    widgets = window.force_control_widgets
    target_N = float(widgets.target_spin.value())
    max_rpm = float(widgets.max_rpm_spin.value())
    dir_idx = widgets.direction_combo.currentIndex()
    direction = 1 if dir_idx == 0 else -1
    feedback_modes = ["ch0", "ch1", "avg", "max"]
    feedback = feedback_modes[widgets.feedback_combo.currentIndex()]
    mode = window.ui_state.force_ctrl_mode

    load_cell_actions.sync_force_tare_offsets(window)
    load_cell_actions.sync_force_abs_mode(window, log=False)
    settings = ForceControlSettings(
        target_n=target_N,
        max_rpm=max_rpm,
        direction=direction,
        feedback=feedback,
        mode=mode,
        pid=ForcePidSettings(
            kp=float(widgets.kp_spin.value()),
            ki=float(widgets.ki_spin.value()),
            kd=float(widgets.kd_spin.value()),
            output_alpha=float(widgets.alpha_spin.value()),
        ),
        tanh=ForceTanhSettings(
            sensitivity_n=float(widgets.tanh_sens_spin.value()),
            deadband_n=float(widgets.tanh_dead_spin.value()),
            output_alpha=float(widgets.alpha_spin.value()),
        ),
    )
    window.control.start_force_control(settings)
    window.force_control_running = True

    widgets.start_button.setEnabled(False)
    widgets.stop_button.setEnabled(True)
    widgets.status_label.setText(f"활성 ({target_N:.1f} N, {feedback})")
    widgets.status_label.setStyleSheet("color: #4caf50; font-weight: bold;")
    window.update_log(f"[{now_str()}] 힘 제어 시작: {target_N:.1f} N, max={max_rpm}rpm, dir={direction}, fb={feedback}")


def stop_force_ctrl(window):
    """힘 제어 정지 명령을 전송하고 UI를 비활성 상태로 되돌린다."""
    widgets = window.force_control_widgets
    window.control.stop_force_control()
    window.force_control_running = False
    widgets.start_button.setEnabled(True)
    widgets.stop_button.setEnabled(False)
    widgets.status_label.setText("비활성")
    widgets.status_label.setStyleSheet("color: #888;")
    window.update_log(f"[{now_str()}] 힘 제어 정지")


def on_force_ctrl_mode_changed(window, mode: str):
    """힘 제어 모드 선택 변경 시 필요한 설정 줄만 표시한다."""
    window.ui_state.force_ctrl_mode = "tanh" if mode.lower().startswith("tanh") else "pid"
    sync_force_ctrl_mode_ui(window)
    widgets = getattr(window, "force_control_widgets", None)
    if widgets is not None and window.force_control_running:
        if window.ui_state.force_ctrl_mode == "tanh":
            apply_force_tanh(window)
        else:
            apply_force_pid(window)


def sync_force_ctrl_mode_ui(window):
    """PID/Tanh 중 현재 모드에 필요한 설정 줄만 표시한다."""
    widgets = getattr(window, "force_control_widgets", None)
    if widgets is None:
        return

    is_tanh = window.ui_state.force_ctrl_mode == "tanh"
    widgets.pid_panel.setVisible(not is_tanh)
    widgets.tanh_panel.setVisible(is_tanh)
    target_text = "Tanh" if is_tanh else "PID"
    if widgets.ctrl_mode_combo.currentText() != target_text:
        widgets.ctrl_mode_combo.blockSignals(True)
        widgets.ctrl_mode_combo.setCurrentText(target_text)
        widgets.ctrl_mode_combo.blockSignals(False)


def apply_force_pid(window):
    """현재 GUI의 PID 게인과 출력 alpha 값을 C++ 노드에 전송."""
    widgets = window.force_control_widgets
    window.control.apply_force_pid(
        ForcePidSettings(
            kp=float(widgets.kp_spin.value()),
            ki=float(widgets.ki_spin.value()),
            kd=float(widgets.kd_spin.value()),
            output_alpha=float(widgets.alpha_spin.value()),
        )
    )
    window.ui_state.force_ctrl_mode = "pid"
    sync_force_ctrl_mode_ui(window)


def apply_force_tanh(window):
    """Tanh 비선형 제어 파라미터와 출력 alpha 값을 C++ 노드에 전송."""
    widgets = window.force_control_widgets
    window.control.apply_force_tanh(
        ForceTanhSettings(
            sensitivity_n=float(widgets.tanh_sens_spin.value()),
            deadband_n=float(widgets.tanh_dead_spin.value()),
            output_alpha=float(widgets.alpha_spin.value()),
        )
    )
    window.ui_state.force_ctrl_mode = "tanh"
    sync_force_ctrl_mode_ui(window)

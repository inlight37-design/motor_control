# -*- coding: utf-8 -*-
"""메인 화면의 상태/진단/로드셀 표시 갱신 헬퍼."""
import math
import time

from PyQt5.QtWidgets import QLabel

from ..core.epos_errors import EPOS_ERROR_MAP
from ..actions import linear_encoder_actions, load_cell_actions, motion_actions


def update_status_labels(window):
    """QTimer 주기에서 호출되는 표시 갱신 진입점."""
    _update_motor_state(window)
    _update_error_code(window)
    _update_rt_labels(window)
    _update_heartbeat(window)
    _update_position_torque(window)
    _update_load_cell_panel(window)


def _update_motor_state(window):
    """모터 상태 문자열과 색상을 갱신."""
    top_status = window.top_status_widgets
    motor_state = window.session.state.motor_state_text()
    top_status.motor_state_label.setText(f"모터: {motor_state}")
    if "FAULT" in motor_state:
        top_status.motor_state_label.setStyleSheet("color: #ff4444; font-weight: bold;")
    elif "Enabled" in motor_state:
        top_status.motor_state_label.setStyleSheet("color: #44ff44; font-weight: bold;")
    else:
        top_status.motor_state_label.setStyleSheet("color: #aaa;")


def _update_error_code(window):
    """현재/최근 에러코드 표시와 중복 로그 억제를 처리."""
    top_status = window.top_status_widgets
    curr_err = window.session.state.error_code()
    mem_err, mem_time = window.session.state.memorized_error()

    if curr_err != 0:
        name = EPOS_ERROR_MAP.get(curr_err, "Unknown")
        err_str = f"에러: 0x{curr_err:04X} {name}"
        top_status.error_code_label.setStyleSheet("color: #ff4444; font-weight: bold;")
        if window.ui_state.last_logged_err != curr_err:
            window.ui_state.last_logged_err = curr_err
            window.update_log(f"[에러] 0x{curr_err:04X} {name}")
    elif mem_err != 0 and (time.time() - mem_time) < 2.0:
        err_str = "복구됨"
        top_status.error_code_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
        if window.ui_state.last_logged_err != 0:
            name = EPOS_ERROR_MAP.get(mem_err, "Unknown")
            window.update_log(f"[복구] 0x{mem_err:04X} {name} 해소됨")
            window.ui_state.last_logged_err = 0
    else:
        err_str = ""
        if mem_err != 0:
            window.session.state.clear_memorized_error()
            window.ui_state.last_logged_err = 0

    top_status.error_code_label.setText(err_str)
    top_status.error_code_label.setVisible(bool(err_str))


def _update_rt_labels(window):
    """지터/오버런/WKC 상태 라벨을 갱신."""
    top_status = window.top_status_widgets
    jitter = window.session.state.rt_jitter_us()
    color = "#44ff44" if jitter < 50 else ("#ffaa00" if jitter < 200 else "#ff4444")
    top_status.rt_jitter_label.setText(f"지터: {jitter} μs")
    top_status.rt_jitter_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    overrun = window.session.state.rt_overrun_count()
    color = "#44ff44" if overrun == 0 else ("#ffaa00" if overrun < 10 else "#ff4444")
    top_status.overrun_label.setText(f"오버런: {overrun}")
    top_status.overrun_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    wkc_err = window.session.state.rt_wkc_error_count()
    color = "#44ff44" if wkc_err == 0 else ("#ffaa00" if wkc_err < 50 else "#ff4444")
    top_status.wkc_error_label.setText(f"WKC: {wkc_err}")
    top_status.wkc_error_label.setStyleSheet(f"color: {color}; font-weight: bold;")


def _update_heartbeat(window):
    """GUI heartbeat 퍼블리셔 상태를 표시."""
    top_status = window.top_status_widgets
    commander = window.runtime_threads.commander
    if commander.running and getattr(commander, "pub_heartbeat", None):
        top_status.heartbeat_label.setText("HB: OK")
        top_status.heartbeat_label.setStyleSheet("color: #44ff44; font-weight: bold;")
    else:
        top_status.heartbeat_label.setText("HB: --")
        top_status.heartbeat_label.setStyleSheet("color: #aaa;")


def _update_position_torque(window):
    """현재 위치/토크와 리니어 엔코더 표시를 갱신."""
    widgets = window.position_torque_widgets
    actual_pos_disp = window.session.state.actual_position_ticks() - window.ui_state.pos_offset
    actual_pos_mm = motion_actions.pos_ticks_to_mm(window, actual_pos_disp)
    widgets.actual_pos_label.setText(f"현재 위치: {actual_pos_disp:,} tick ({actual_pos_mm:+.3f} mm)")

    trq_permille = window.session.state.actual_torque_permille()
    trq_mNm = trq_permille * 0.09123
    widgets.actual_trq_label.setText(f"현재 토크: {trq_mNm:.1f} mN·m ({trq_permille} ‰)")
    linear_encoder_actions.update_display(window)


def _set_tare_buttons_enabled(window, internal_connected: bool, external_fresh: bool):
    """데이터 소스에 따라 tare 버튼 활성 상태를 동기화."""
    widgets = window.load_cell_widgets
    load_cell = window.device_readers.load_cell
    if internal_connected:
        widgets.tare_ch0_button.setEnabled(load_cell.connected[0])
        widgets.tare_ch1_button.setEnabled(load_cell.connected[1])
        widgets.tare_all_button.setEnabled(True)
        widgets.tare_reset_button.setEnabled(True)
    elif external_fresh:
        widgets.tare_ch0_button.setEnabled(True)
        widgets.tare_ch1_button.setEnabled(True)
        widgets.tare_all_button.setEnabled(True)
        widgets.tare_reset_button.setEnabled(True)
    else:
        widgets.tare_ch0_button.setEnabled(False)
        widgets.tare_ch1_button.setEnabled(False)
        widgets.tare_all_button.setEnabled(False)
        widgets.tare_reset_button.setEnabled(False)


def _read_load_cell_forces(window, internal_connected: bool, external_fresh: bool):
    """현재 표시할 로드셀 force 값과 소스 라벨을 갱신."""
    widgets = window.load_cell_widgets
    load_cell = window.device_readers.load_cell
    if internal_connected:
        forces = load_cell.get_all_forces_N()
        f0 = forces[0] if len(forces) > 0 and load_cell.connected[0] else float("nan")
        f1 = forces[1] if len(forces) > 1 and load_cell.connected[1] else float("nan")
        connected_names = ",".join(
            f"CH{i}" for i, connected in enumerate(load_cell.connected) if connected
        )
        widgets.source_label.setText(f"소스: 내장 {connected_names}")
        widgets.source_label.setStyleSheet("color: #44ff44; font-size: 10px; font-weight: bold;")
        return f0, f1

    if external_fresh:
        f0 = window.session.state.force_n(0, window.ui_state.ext_tare_n)
        f1 = window.session.state.force_n(1, window.ui_state.ext_tare_n)
        widgets.source_label.setText("소스: 외부 토픽")
        widgets.source_label.setStyleSheet("color: #ffb74d; font-size: 10px; font-weight: bold;")
        return f0, f1

    widgets.source_label.setText("소스: --")
    widgets.source_label.setStyleSheet("color: #90a4ae; font-size: 10px;")
    return float("nan"), float("nan")


def _update_load_cell_panel(window):
    """로드셀 값, delta, max, 소프트 리미트 상태를 갱신."""
    widgets = window.load_cell_widgets
    factor, unit_suffix, _ = load_cell_actions.lc_unit_factor(window)
    limit_disp = widgets.force_limit_spin.value()
    start_disp = limit_disp * widgets.soft_start_spin.value() / 100.0
    decimals = 0 if unit_suffix == "g" else 2

    internal_connected = any(window.device_readers.load_cell.connected)
    external_fresh = window.session.state.load_cell_fresh()
    _set_tare_buttons_enabled(window, internal_connected, external_fresh)

    f0, f1 = _read_load_cell_forces(window, internal_connected, external_fresh)
    force_abs_mode = bool(widgets.force_abs_checkbox.isChecked())
    valid_disp = []

    def force_color(abs_value: float) -> str:
        if abs_value >= limit_disp:
            return "#ff4444"
        if abs_value >= start_disp:
            return "#ffaa00"
        return "#44ff44"

    def set_force_label(label: QLabel, prefix: str, value_N: float):
        if math.isnan(value_N):
            label.setText(f"{prefix}: --")
            label.setStyleSheet("color: #b0bec5; font-size: 13px;")
            return
        display_N = abs(value_N) if force_abs_mode else value_N
        value_disp = display_N * factor
        valid_disp.append(abs(value_disp))
        color = force_color(abs(value_disp))
        fmt = f"{value_disp:.{decimals}f}" if force_abs_mode else f"{value_disp:+.{decimals}f}"
        label.setText(f"{prefix}: {fmt} {unit_suffix}")
        label.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")

    set_force_label(widgets.ch0_label, "CH0 시작", f0)
    set_force_label(widgets.ch1_label, "CH1 끝", f1)
    _update_load_cell_delta(window, f0, f1, factor, unit_suffix, decimals, force_abs_mode)
    _update_load_cell_max(window, valid_disp, unit_suffix, decimals, force_color)
    _update_soft_limit_status(window, valid_disp, limit_disp, start_disp)


def _update_load_cell_delta(window, f0, f1, factor, unit_suffix, decimals, force_abs_mode):
    widgets = window.load_cell_widgets
    if not math.isnan(f0) and not math.isnan(f1):
        delta_base = (abs(f1) - abs(f0)) if force_abs_mode else (f1 - f0)
        delta_disp = delta_base * factor
        widgets.delta_label.setText(f"Δ: {delta_disp:+.{decimals}f} {unit_suffix}")
        widgets.delta_label.setStyleSheet("color: #cfd8dc; font-size: 12px; font-weight: bold;")
    else:
        widgets.delta_label.setText("Δ: --")
        widgets.delta_label.setStyleSheet("color: #b0bec5; font-size: 12px;")


def _update_load_cell_max(window, valid_disp, unit_suffix, decimals, force_color):
    widgets = window.load_cell_widgets
    if valid_disp:
        max_disp = max(valid_disp)
        widgets.max_label.setText(f"MAX: {max_disp:.{decimals}f} {unit_suffix}")
        widgets.max_label.setStyleSheet(
            f"color: {force_color(max_disp)}; font-size: 12px; font-weight: bold;"
        )
    else:
        widgets.max_label.setText("MAX: --")
        widgets.max_label.setStyleSheet("color: #b0bec5; font-size: 12px;")


def _update_soft_limit_status(window, valid_disp, limit_disp, start_disp):
    widgets = window.load_cell_widgets
    if not valid_disp:
        widgets.soft_status_label.setText("미연결")
        widgets.soft_status_label.setStyleSheet("color: #b0bec5;")
        return

    af_disp = max(valid_disp)
    if not widgets.soft_limit_checkbox.isChecked():
        widgets.soft_status_label.setText("비활성")
        widgets.soft_status_label.setStyleSheet("color: #b0bec5;")
        return

    pct = min(100.0, af_disp / max(limit_disp, 1e-6) * 100.0)
    if af_disp >= limit_disp:
        widgets.soft_status_label.setText("STOP")
        widgets.soft_status_label.setStyleSheet("color: #ff4444; font-weight: bold;")
    elif af_disp >= start_disp:
        scale = 1.0 - (af_disp - start_disp) / max(limit_disp - start_disp, 1e-6)
        widgets.soft_status_label.setText(f"감속 {scale*100:.0f}%")
        widgets.soft_status_label.setStyleSheet("color: #ffaa00; font-weight: bold;")
    else:
        widgets.soft_status_label.setText(f"정상 ({pct:.0f}%)")
        widgets.soft_status_label.setStyleSheet("color: #44ff44; font-weight: bold;")

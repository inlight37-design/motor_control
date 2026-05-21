# -*- coding: utf-8 -*-
"""히스테리시스 자동 테스트 UI 동작."""
import os
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import QMessageBox

from ..core.config import DEFAULT_POSITION_TICKS_PER_REV, LOG_DIR, MAX_RPM
from ..core.time_utils import now_str
from ..logic import hysteresis as hyst
from ..core.experiments import HysteresisExperimentSettings


# ══════════════════════════════════════════════════════════════════════
# 입력 단위/모드 표시
# ══════════════════════════════════════════════════════════════════════

def on_amp_unit_changed(window):
    """히스테리시스 진폭 입력 단위를 rpm/mm에 맞게 표시한다."""
    widgets = window.hysteresis_widgets
    unit = widgets.amp_unit_combo.currentData() or "rpm"
    widgets.amp_spin.blockSignals(True)
    if unit == "mm":
        widgets.amp_spin.setRange(0.001, 1000.0)
        widgets.amp_spin.setDecimals(3)
        widgets.amp_spin.setSingleStep(0.1)
        widgets.amp_spin.setSuffix(" mm")
        widgets.lead_spin.setEnabled(not getattr(window, "hyst_test_running", False))
    else:
        widgets.amp_spin.setRange(1.0, float(MAX_RPM))
        widgets.amp_spin.setDecimals(0)
        widgets.amp_spin.setSingleStep(10.0)
        widgets.amp_spin.setSuffix(" rpm")
        widgets.lead_spin.setEnabled(False)
    widgets.amp_spin.blockSignals(False)
    update_duration_label(window)


def on_motion_mode_changed(window):
    """속도 사인/위치 사인 선택에 따라 설명과 입력 활성화를 갱신."""
    widgets = window.hysteresis_widgets
    is_position = (widgets.motion_mode_combo.currentData() or "velocity") == "position"
    widgets.offset_spin.setEnabled(not is_position and not getattr(window, "hyst_test_running", False))
    widgets.offset_spin.setToolTip("위치 사인 모드에서는 오프셋 rpm을 사용하지 않습니다." if is_position else "")
    update_duration_label(window)


# ══════════════════════════════════════════════════════════════════════
# 진폭 변환과 라벨 생성
# ══════════════════════════════════════════════════════════════════════

def amp_to_rpm(window, freq: float) -> tuple[float, float, float, float, str]:
    """현재 진폭 입력을 C++ 노드가 받는 rpm 진폭으로 변환한다."""
    widgets = window.hysteresis_widgets
    unit = widgets.amp_unit_combo.currentData() or "rpm"
    requested_amp = abs(float(widgets.amp_spin.value()))
    lead_mm_rev = max(float(widgets.lead_spin.value()), 1e-9)
    amp = hyst.amplitude_to_rpm(freq, requested_amp, lead_mm_rev, unit)
    return amp.amp_rpm, amp.amp_rpm, amp.requested_amp, amp.lead_mm_rev, amp.unit


def amp_to_position_ticks(window, freq: float) -> tuple[float, float, float, float, str]:
    """현재 진폭 입력을 위치 사인파용 encoder tick 진폭으로 변환한다."""
    widgets = window.hysteresis_widgets
    unit = widgets.amp_unit_combo.currentData() or "rpm"
    requested_amp = abs(float(widgets.amp_spin.value()))
    lead_mm_rev = max(float(widgets.lead_spin.value()), 1e-9)
    pos = hyst.amplitude_to_position_ticks(
        freq,
        requested_amp,
        lead_mm_rev,
        unit,
        DEFAULT_POSITION_TICKS_PER_REV,
    )
    return pos.amp_ticks, pos.amp_mm, pos.requested_amp, pos.lead_mm_rev, pos.unit


def update_duration_label(window):
    """히스테리시스 테스트의 예상 시간을 cycle 설정에서 계산해 표시."""
    widgets = window.hysteresis_widgets
    freq = max(float(widgets.freq_spin.value()), 1e-9)
    requested_amp = abs(float(widgets.amp_spin.value()))
    lead_mm_rev = max(float(widgets.lead_spin.value()), 1e-9)
    unit = widgets.amp_unit_combo.currentData() or "rpm"
    offset_rpm = float(widgets.offset_spin.value())
    is_position = (widgets.motion_mode_combo.currentData() or "velocity") == "position"
    motion_mode = "position" if is_position else "velocity"
    widgets.duration_label.setText(
        hyst.duration_text(
            freq,
            widgets.settle_cycles_spin.value(),
            widgets.record_cycles_spin.value(),
        )
    )
    widgets.motion_label.setText(
        hyst.motion_summary(
            freq,
            requested_amp,
            lead_mm_rev,
            unit,
            offset_rpm,
            motion_mode,
            DEFAULT_POSITION_TICKS_PER_REV,
        )
    )
    if not widgets.label_edit.text().strip():
        widgets.label_edit.setPlaceholderText(f"auto: {auto_label(window)}")


def compact_label_number(value: float, decimals: int = 3) -> str:
    """파일명 토큰용 숫자 문자열. 1.000 -> 1, 0.125 -> 0.125."""
    return hyst.compact_number(value, decimals)


def label_target_force_N(window) -> float:
    """히스테리시스 파일명에 넣을 목표 장력."""
    try:
        return abs(float(window.force_control_widgets.target_spin.value()))
    except Exception:
        return 0.0


def auto_label(window) -> str:
    """기본 히스테리시스 로그 라벨: freq_tension_amp_cycles_mode."""
    widgets = window.hysteresis_widgets
    return hyst.auto_label(
        widgets.freq_spin.value(),
        label_target_force_N(window),
        widgets.amp_spin.value(),
        widgets.amp_unit_combo.currentData() or "rpm",
        int(widgets.record_cycles_spin.value()),
        widgets.motion_mode_combo.currentData() or "velocity",
    )


def safe_label(window) -> str:
    """로그 파일명에 넣기 안전한 ASCII 라벨을 만든다."""
    raw = window.hysteresis_widgets.label_edit.text().strip() or auto_label(window)
    return hyst.safe_label(raw)


# ══════════════════════════════════════════════════════════════════════
# 실행 중 UI 잠금
# ══════════════════════════════════════════════════════════════════════

def set_controls_enabled(window, enabled: bool):
    """자동 테스트 탭의 입력 위젯을 실행 상태에 맞게 잠금/해제."""
    widgets = window.hysteresis_widgets
    for widget in [
        widgets.label_edit,
        widgets.freq_spin,
        widgets.motion_mode_combo,
        widgets.amp_spin,
        widgets.amp_unit_combo,
        widgets.lead_spin,
        widgets.offset_spin,
        widgets.settle_cycles_spin,
        widgets.record_cycles_spin,
    ]:
        widget.setEnabled(enabled)
    if enabled:
        widgets.lead_spin.setEnabled((widgets.amp_unit_combo.currentData() or "rpm") == "mm")
        widgets.offset_spin.setEnabled((widgets.motion_mode_combo.currentData() or "velocity") != "position")
    widgets.start_button.setEnabled(enabled)
    widgets.abort_button.setEnabled(not enabled)


def set_owned_controls(window, running: bool):
    """자동 테스트가 사용하는 기존 파형/로깅 컨트롤의 충돌을 막는다."""
    script_log = window.script_log_widgets
    waveform = window.waveform_widgets
    manual_motion = window.manual_motion_widgets
    if running:
        waveform.start_button.setEnabled(False)
        waveform.stop_button.setEnabled(False)
        manual_motion.rpm_spin.setEnabled(False)
        script_log.script_button.setEnabled(False)
        script_log.log_start_button.setEnabled(False)
        script_log.log_stop_button.setEnabled(False)
        return

    waveform.start_button.setEnabled(True)
    waveform.stop_button.setEnabled(False)
    manual_motion.rpm_spin.setEnabled(True)
    script_log.script_button.setEnabled(bool(window.ui_state.loaded_script_path))
    script_log.log_start_button.setEnabled(True)
    script_log.log_stop_button.setEnabled(False)
    script_log.log_path_label.setText("로깅 대기")
    script_log.log_path_label.setStyleSheet("color: #666;")


# ══════════════════════════════════════════════════════════════════════
# 테스트 생명주기
# ══════════════════════════════════════════════════════════════════════

def start_test(window):
    """C++ 노드에 사인파 시작/CSV 기록 창/자동 정지를 한 번에 예약."""
    widgets = window.hysteresis_widgets
    freq = float(widgets.freq_spin.value())
    motion_mode = widgets.motion_mode_combo.currentData() or "velocity"
    mode_combo = window.position_torque_widgets.mode_combo
    if motion_mode == "position":
        if mode_combo.currentIndex() != 1:
            mode_combo.setCurrentIndex(1)
    else:
        if mode_combo.currentIndex() != 0:
            mode_combo.setCurrentIndex(0)

    amp, _amp_rpm_float, requested_amp, lead_mm_rev, amp_unit = amp_to_rpm(window, freq)

    offset = int(widgets.offset_spin.value())
    settle_cycles = int(widgets.settle_cycles_spin.value())
    record_cycles = int(widgets.record_cycles_spin.value())
    label = safe_label(window)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"hyst_{label}_{time.strftime('%Y%m%d_%H%M%S')}.csv"

    if motion_mode == "position":
        amp_ticks, _amp_mm, _requested, _lead, _unit = amp_to_position_ticks(window, freq)
        required_tps = hyst.position_required_tps(amp_ticks, freq)
        max_tps = hyst.position_max_tps(required_tps, MAX_RPM, DEFAULT_POSITION_TICKS_PER_REV)
    else:
        amp_ticks = 0.0
        max_tps = 0.0

    settings = HysteresisExperimentSettings(
        motion_mode=motion_mode,
        freq_hz=freq,
        amp_rpm=amp,
        offset_rpm=offset,
        settle_cycles=settle_cycles,
        record_cycles=record_cycles,
        log_path=log_path,
        amp_ticks=amp_ticks,
        max_tps=max_tps,
        requested_amp=requested_amp,
        lead_mm_rev=lead_mm_rev,
        amp_unit=amp_unit,
    )
    try:
        window.session.hysteresis.start(settings, on_status=lambda status: on_experiment_status(window, status))
    except RuntimeError as exc:
        QMessageBox.warning(window, "히스테리시스 테스트", str(exc))


def on_experiment_status(window, status):
    """core HysteresisExperiment 상태 이벤트를 GUI 표시로 변환."""
    widgets = window.hysteresis_widgets
    settings = status.settings
    log_path = status.log_path
    if status.phase == "armed":
        script_log = window.script_log_widgets
        set_controls_enabled(window, False)
        set_owned_controls(window, True)
        script_log.log_path_label.setText(f"히스테리시스 예약... ({os.path.basename(str(log_path))})")
        script_log.log_path_label.setStyleSheet("color: #0969da; font-weight: bold;")
        widgets.status_label.setText(f"armed: stable {settings.settle_cycles} cycles")
        widgets.status_label.setStyleSheet("color: #0969da; font-weight: bold;")
        window.update_log(
            f"[{now_str()}] 히스테리시스 테스트 예약: "
            f"{'pos_sine' if settings.is_position else 'vel_sine'} {settings.freq_hz:g}Hz, "
            f"amp={settings.amp_rpm:.1f}rpm / {settings.amp_ticks:.0f}tick, "
            f"max_tps={settings.max_tps:.0f}, offset={settings.offset_rpm}rpm, "
            f"input_amp={settings.requested_amp:g}{settings.amp_unit}, "
            f"lead={settings.lead_mm_rev:g}mm/rev, "
            f"stable={settings.settle_cycles} cycles, log={settings.record_cycles} cycles, file={log_path}"
        )
        return

    if status.phase == "logging":
        _show_logging_status(window, settings, log_path)
        return

    if status.phase == "done":
        _show_finished_status(window, log_path)
        return

    if status.phase == "aborted":
        _show_aborted_status(window, status.reason, log_path)


def _show_logging_status(window, settings, log_path):
    """C++ 기록 창 시작 시점에 맞춰 GUI 표시를 바꾸고 정리 타이머를 건다."""
    script_log = window.script_log_widgets
    widgets = window.hysteresis_widgets
    script_log.log_stop_button.setEnabled(False)
    script_log.log_path_label.setText(f"히스테리시스 기록 중... ({os.path.basename(str(log_path))})")
    script_log.log_path_label.setStyleSheet("color: #00aa00; font-weight: bold;")
    widgets.status_label.setText(f"logging {settings.record_cycles} cycles")
    widgets.status_label.setStyleSheet("color: #1a7f37; font-weight: bold;")


def _show_finished_status(window, log_path):
    """정상 종료 상태를 GUI에 반영."""
    widgets = window.hysteresis_widgets
    set_controls_enabled(window, True)
    set_owned_controls(window, False)
    name = os.path.basename(str(log_path)) if log_path else "unknown"
    widgets.status_label.setText(f"done: {name}")
    widgets.status_label.setStyleSheet("color: #1a7f37; font-weight: bold;")
    window.update_log(f"[{now_str()}] 히스테리시스 테스트 완료: {log_path}")


def _show_aborted_status(window, reason: str, log_path):
    """중지 상태를 GUI에 반영."""
    widgets = window.hysteresis_widgets
    set_controls_enabled(window, True)
    set_owned_controls(window, False)
    widgets.status_label.setText(f"stopped: {reason}")
    widgets.status_label.setStyleSheet("color: #cf222e; font-weight: bold;")
    window.update_log(f"[{now_str()}] 히스테리시스 테스트 중지: {reason}, file={log_path}")


def begin_logging(window, token: int, record_ms: int):
    """호환용 래퍼. 지연 타이머는 core HysteresisExperiment가 담당."""
    if window.session.hysteresis:
        window.session.hysteresis.begin_logging(token, record_ms)


def finish_test(window, token: Optional[int] = None):
    """호환용 래퍼. 테스트 정상 종료는 core HysteresisExperiment가 담당."""
    if window.session.hysteresis:
        window.session.hysteresis.finish(token)


def abort_test(window, checked=False, reason: str = "사용자 중지"):
    """자동 테스트를 즉시 중지."""
    _ = checked
    if window.session.hysteresis:
        window.session.hysteresis.abort(reason)

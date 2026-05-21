# -*- coding: utf-8 -*-
"""로드셀 패널 버튼/단위/소프트 리미트 동작 헬퍼."""
import math
import os
import threading

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox, QPushButton

from ..core.config import LOAD_CELL_CAL_DIR
from ..core.phidget_support import GRAVITY, PHIDGET_AVAILABLE
from ..core.time_utils import now_str
from ..ui.styles import LC_BUTTON_ERR_STYLE, LC_BUTTON_OK_STYLE, LC_BUTTON_STYLE


# ══════════════════════════════════════════════════════════════════════
# 캘리브레이션 파일 로드
# ══════════════════════════════════════════════════════════════════════

def load_lc_cal(window):
    """통합 캘리브레이션 JSON 파일을 로드."""
    fname, _ = QFileDialog.getOpenFileName(
        window,
        "통합 캘리브레이션 JSON",
        str(LOAD_CELL_CAL_DIR),
        "JSON (*.json)",
    )
    if not fname:
        return

    err = window.lc_reader.load_calibration(fname)
    if err:
        QMessageBox.critical(window, "캘파일 오류", err)
        return

    widgets = window.load_cell_widgets
    widgets.cal_label.setText(f"Cal: {os.path.basename(fname)} ({window.lc_reader.cal_note})")
    widgets.cal_label.setToolTip(window.lc_reader.cal_note)
    widgets.cal_label.setStyleSheet("color: #44bb44; font-size: 10px;")
    window.update_log(
        f"[{now_str()}] 로드셀 캘파일 로드: {os.path.basename(fname)} / {window.lc_reader.cal_note}"
    )


def load_lc_cal_channel(window, ch: int):
    """캘리브레이션 JSON 파일 하나를 지정한 로드셀 채널에만 적용."""
    fname, _ = QFileDialog.getOpenFileName(
        window,
        f"CH{ch} 캘리브레이션 JSON",
        str(LOAD_CELL_CAL_DIR),
        "JSON (*.json)",
    )
    if not fname:
        return

    err = window.lc_reader.load_calibration_channel(fname, ch)
    if err:
        QMessageBox.critical(window, f"CH{ch} 캘파일 오류", err)
        return

    widgets = window.load_cell_widgets
    widgets.cal_label.setText(f"Cal: {window.lc_reader.cal_note}")
    widgets.cal_label.setToolTip(window.lc_reader.cal_note)
    widgets.cal_label.setStyleSheet("color: #44bb44; font-size: 10px;")
    window.update_log(
        f"[{now_str()}] 로드셀 CH{ch} 캘파일 로드: {os.path.basename(fname)} / {window.lc_reader.cal_note}"
    )


# ══════════════════════════════════════════════════════════════════════
# Tare 처리
# ══════════════════════════════════════════════════════════════════════

def tare_lc(window, ch: int):
    """로드셀 한 채널 Tare를 적용하고 결과를 로그에 남긴다."""
    widgets = window.load_cell_widgets
    button = widgets.tare_ch0_button if ch == 0 else widgets.tare_ch1_button
    set_lc_tare_status(window, f"CH{ch} 클릭됨", "#ffd54f")

    if any(window.lc_reader.connected):
        ok, msg = window.lc_reader.tare(ch)
        if ok:
            set_ext_tare_offset(window, ch, 0.0)
    elif window.session.state.load_cell_fresh():
        current = window.session.state.force_n(ch)
        if not math.isnan(current):
            set_ext_tare_offset(window, ch, current)
            ok, msg = True, f"CH{ch} Tare 완료 (외부)"
        else:
            ok, msg = False, f"CH{ch} 값 없음"
    else:
        ok, msg = False, "데이터 소스 없음"

    if ok:
        set_lc_tare_status(window, msg, "#44ff44")
        flash_lc_button(window, button, "완료", ok=True)
        window.update_log(f"[{now_str()}] {msg}")
    else:
        set_lc_tare_status(window, msg, "#ff8a65")
        flash_lc_button(window, button, "실패", ok=False)
        window.update_log(f"[{now_str()}] Tare 실패: {msg}")
    window.flush_log_buffer()


def tare_lc_all(window):
    """연결된 모든 로드셀 채널에 Tare를 적용한다."""
    set_lc_tare_status(window, "전체 클릭됨", "#ffd54f")

    results = []
    if any(window.lc_reader.connected):
        results = window.lc_reader.tare_all()
        for ch, (ok, _) in enumerate(results):
            if ok:
                set_ext_tare_offset(window, ch, 0.0)
    elif window.session.state.load_cell_fresh():
        for ch, val in enumerate([window.session.state.force_n(0), window.session.state.force_n(1)]):
            if not math.isnan(val):
                set_ext_tare_offset(window, ch, val)
                results.append((True, f"CH{ch} Tare 완료 (외부)"))
            else:
                results.append((False, f"CH{ch} 값 없음"))

    if not results:
        set_lc_tare_status(window, "데이터 없음", "#ff8a65")
        flash_lc_button(window, window.load_cell_widgets.tare_all_button, "실패", ok=False)
        window.update_log(f"[{now_str()}] Tare 실패: 데이터 소스 없음")
        window.flush_log_buffer()
        return

    ok_all = all(ok for ok, _ in results)
    for ok, msg in results:
        prefix = "" if ok else "Tare 실패: "
        window.update_log(f"[{now_str()}] {prefix}{msg}")
    set_lc_tare_status(window, "전체 완료" if ok_all else "일부 실패", "#44ff44" if ok_all else "#ff8a65")
    flash_lc_button(window, window.load_cell_widgets.tare_all_button, "완료" if ok_all else "실패", ok=ok_all)
    window.flush_log_buffer()


def reset_lc_tare(window):
    """모든 로드셀 Tare를 해제한다."""
    flash_lc_button(window, window.load_cell_widgets.tare_reset_button, "해제됨", ok=True)
    window.lc_reader.reset_tare()
    window.ui_state.ext_tare_n = [0.0, 0.0]
    window.control.reset_force_tare_offsets()
    set_lc_tare_status(window, "Tare 해제", "#90caf9")
    window.update_log(f"[{now_str()}] 로드셀 Tare 해제")
    window.flush_log_buffer()


def set_ext_tare_offset(window, ch: int, offset_N: float):
    """외부 토픽 Tare 오프셋을 GUI와 C++ 힘 제어 노드에 함께 반영한다."""
    window.ui_state.ext_tare_n[ch] = float(offset_N)
    window.control.set_force_tare_offset(ch, offset_N)


def sync_force_tare_offsets(window):
    """힘 제어 시작 전 현재 GUI Tare 오프셋을 C++ 노드와 동기화한다."""
    window.control.sync_force_tare_offsets(window.ui_state.ext_tare_n)


def set_lc_tare_status(window, text: str, color: str):
    """Tare 상태 라벨의 문구와 색상을 갱신한다."""
    label = window.load_cell_widgets.tare_status_label
    label.setText(f"Tare: {text}")
    label.setStyleSheet(f"color: {color}; font-size: 10px; font-weight: bold;")


def flash_lc_button(window, button: QPushButton, text: str, ok: bool, delay_ms: int = 700):
    """Tare 버튼을 잠깐 성공/실패 색으로 바꾼 뒤 원래 스타일로 되돌린다."""
    old_text = button.text()
    button.setText(text)
    button.setStyleSheet(LC_BUTTON_OK_STYLE if ok else LC_BUTTON_ERR_STYLE)
    QTimer.singleShot(
        delay_ms,
        lambda b=button, t=old_text: (b.setText(t), b.setStyleSheet(LC_BUTTON_STYLE)),
    )


# ══════════════════════════════════════════════════════════════════════
# 연결/해제
# ══════════════════════════════════════════════════════════════════════

def _set_lc_connect_button(window, connected: bool, text: str | None = None, enabled: bool = True):
    """로드셀 연결 버튼의 공통 상태를 갱신한다."""
    button = window.load_cell_widgets.connect_button
    button.setEnabled(enabled)
    if connected:
        button.setText(text or "연결 해제")
        button.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; padding: 3px 6px;"
        )
    else:
        button.setText(text or "로드셀 연결")
        button.setStyleSheet(
            "background-color: #37474f; color: white; font-weight: bold; padding: 3px 6px;"
        )


def _set_lc_tare_buttons(
    window,
    ch0: bool = False,
    ch1: bool = False,
    all_channels: bool = False,
    reset: bool = False,
):
    """Tare 관련 버튼 활성 상태를 한곳에서 맞춘다."""
    widgets = window.load_cell_widgets
    widgets.tare_ch0_button.setEnabled(ch0)
    widgets.tare_ch1_button.setEnabled(ch1)
    widgets.tare_all_button.setEnabled(all_channels)
    widgets.tare_reset_button.setEnabled(reset)


def toggle_lc_connect(window):
    """로드셀 연결/해제 토글. 연결은 별도 스레드에서 수행한다."""
    if any(window.lc_reader.connected):
        window.lc_reader.disconnect()
        _set_lc_connect_button(window, connected=False)
        _set_lc_tare_buttons(window)
        window.update_log(f"[{now_str()}] 로드셀 연결 해제")
        return

    _set_lc_connect_button(window, connected=False, text="연결 중...", enabled=False)

    def try_connect():
        channels = window.lc_reader.connect()
        window.lc_connect_result_signal.emit(channels)

    threading.Thread(target=try_connect, daemon=True).start()


def on_lc_connect_result(window, channels: list):
    """로드셀 연결 결과 처리."""
    if channels:
        _set_lc_connect_button(window, connected=True)
        _set_lc_tare_buttons(window, ch0=0 in channels, ch1=1 in channels, all_channels=True, reset=True)
        window.update_log(f"[{now_str()}] 로드셀 연결됨 CH{channels}")
        missing = [i for i in range(window.lc_reader.n_channels) if i not in channels]
        for i in missing:
            detail = window.lc_reader.last_errors[i] or "알 수 없는 오류"
            window.update_log(f"[{now_str()}] 로드셀 CH{i} 미연결: {detail}")
        return

    _set_lc_connect_button(window, connected=False)
    _set_lc_tare_buttons(window)
    msg = "Phidget22 라이브러리 없음" if not PHIDGET_AVAILABLE else "Phidget 연결 실패 (USB 확인)"
    window.update_log(f"[{now_str()}] 로드셀 연결 실패: {msg}")
    for i, detail in enumerate(window.lc_reader.last_errors):
        if detail:
            window.update_log(f"[{now_str()}] 로드셀 CH{i} 실패: {detail}")


# ══════════════════════════════════════════════════════════════════════
# 단위와 소프트 리미트
# ══════════════════════════════════════════════════════════════════════

def lc_unit_factor(window) -> tuple:
    """현재 선택된 단위에 대한 (변환 계수, 접미사, 스핀 최대값) 반환."""
    unit = window.load_cell_widgets.unit_combo.currentText()
    if unit == "g":
        return (1000.0 / GRAVITY, "g", 100000.0)
    if unit == "kg":
        return (1.0 / GRAVITY, "kg", 1000.0)
    return (1.0, "N", 10000.0)


def on_lc_unit_changed(window):
    """단위 변경 시 한계값 스핀박스를 새 단위로 변환."""
    widgets = window.load_cell_widgets
    factor, suffix, spin_max = lc_unit_factor(window)
    old_unit = window.ui_state.prev_lc_unit
    old_factor = {"N": 1.0, "g": 1000.0 / GRAVITY, "kg": 1.0 / GRAVITY}.get(old_unit, 1.0)
    limit_N = widgets.force_limit_spin.value() / old_factor
    window.ui_state.prev_lc_unit = widgets.unit_combo.currentText()

    widgets.force_limit_spin.blockSignals(True)
    widgets.force_limit_spin.setRange(0.1, spin_max)
    widgets.force_limit_spin.setSuffix(f" {suffix}")
    widgets.force_limit_spin.setValue(round(limit_N * factor, 1))
    widgets.force_limit_spin.blockSignals(False)
    update_soft_limit(window)


def update_soft_limit(window):
    """소프트 리미트 파라미터를 현재 단위에서 N으로 변환해 CommandThread에 전달."""
    widgets = window.load_cell_widgets
    factor, _, _ = lc_unit_factor(window)
    limit_N = widgets.force_limit_spin.value() / factor
    enabled = widgets.soft_limit_checkbox.isChecked()
    window.control.set_force_limit(enabled, max(0.1, limit_N), widgets.soft_start_spin.value())


# ══════════════════════════════════════════════════════════════════════
# 힘 크기(|F|) 표시/제어 모드
# ══════════════════════════════════════════════════════════════════════

def sync_force_abs_mode(window, log: bool = True):
    """장력 크기(|F|) 표시/제어 모드를 C++ 힘 제어 루프에 전달한다."""
    enabled = bool(window.load_cell_widgets.force_abs_checkbox.isChecked())
    window.ui_state.force_abs_mode = enabled
    window.control.set_force_absolute_mode(enabled)
    if log:
        mode = "|F| 장력 크기" if enabled else "signed 힘"
        window.update_log(f"[{now_str()}] 힘 표시/제어 모드: {mode}")


def on_force_abs_mode_changed(window, _state: int):
    sync_force_abs_mode(window, log=True)

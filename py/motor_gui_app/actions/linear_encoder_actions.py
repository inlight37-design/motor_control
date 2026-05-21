# -*- coding: utf-8 -*-
"""리니어 엔코더 설정, 연결/해제, 표시 갱신 UI 동작."""
import threading

from ..core.time_utils import now_str


def _reader(window):
    """현재 GUI 세션의 리니어 엔코더 리더를 반환."""
    device_readers = getattr(window, "device_readers", None)
    return None if device_readers is None else device_readers.linear_encoder


def update_settings(window):
    """리니어 엔코더 환산/방향 설정을 Reader에 반영."""
    reader = _reader(window)
    if reader is None:
        return
    widgets = window.linear_encoder_widgets
    reader.configure(
        counts_per_mm=widgets.counts_per_mm_spin.value(),
        invert=widgets.invert_checkbox.isChecked(),
    )


def toggle_linear_encoder(window):
    """Phidget 리니어 엔코더를 연결하거나 해제한다."""
    widgets = window.linear_encoder_widgets
    reader = _reader(window)
    if reader is None:
        return
    if reader.connected:
        reader.disconnect()
        widgets.connect_button.setText("Linear Enc 연결")
        widgets.connect_button.setEnabled(True)
        widgets.zero_button.setEnabled(False)
        widgets.channel_spin.setEnabled(True)
        widgets.status_label.setText("LE: disconnected")
        widgets.status_label.setStyleSheet("color: #90a4ae; font-size: 10px;")
        window.update_log(f"[{now_str()}] 리니어 엔코더 연결 해제")
        return

    update_settings(window)
    channel = int(widgets.channel_spin.value())
    widgets.connect_button.setText("연결 중...")
    widgets.connect_button.setEnabled(False)
    widgets.channel_spin.setEnabled(False)
    widgets.status_label.setText("LE: connecting...")
    widgets.status_label.setStyleSheet("color: #ffb74d; font-size: 10px; font-weight: bold;")

    def try_connect():
        ok, msg = reader.connect(channel)
        window.linear_encoder_connect_result_signal.emit(ok, msg)

    threading.Thread(target=try_connect, daemon=True).start()


def on_linear_encoder_connect_result(window, ok: bool, msg: str):
    """백그라운드 리니어 엔코더 연결 결과를 GUI에 반영한다."""
    widgets = window.linear_encoder_widgets
    if ok:
        widgets.connect_button.setText("Linear Enc 해제")
        widgets.connect_button.setEnabled(True)
        widgets.zero_button.setEnabled(True)
        widgets.channel_spin.setEnabled(False)
        widgets.status_label.setText(msg)
        widgets.status_label.setStyleSheet("color: #44bb44; font-size: 10px; font-weight: bold;")
        window.update_log(f"[{now_str()}] 리니어 엔코더 연결: {msg}")
    else:
        widgets.connect_button.setText("Linear Enc 연결")
        widgets.connect_button.setEnabled(True)
        widgets.zero_button.setEnabled(False)
        widgets.channel_spin.setEnabled(True)
        widgets.status_label.setText(f"LE 실패: {msg[:80]}")
        widgets.status_label.setStyleSheet("color: #ff8a65; font-size: 10px; font-weight: bold;")
        window.update_log(f"[{now_str()}] 리니어 엔코더 연결 실패: {msg}")


def zero_linear_encoder(window):
    """현재 리니어 엔코더 위치를 0으로 설정."""
    reader = _reader(window)
    if reader is None:
        return
    reader.zero()
    window.update_log(f"[{now_str()}] 리니어 엔코더 Zero 설정")
    update_display(window)


def update_display(window):
    """GUI 내장 또는 외부 토픽 리니어 엔코더 값을 표시한다."""
    widgets = getattr(window, "linear_encoder_widgets", None)
    if widgets is None:
        return
    reader = _reader(window)
    if reader is not None and reader.connected:
        count = reader.get_position_count()
        mm = reader.get_position_mm()
        widgets.pos_label.setText(f"Linear: {count:+d} cnt / {mm:+.3f} mm")
        widgets.pos_label.setStyleSheet("color: #2e7d32; font-size: 11px; font-weight: bold;")
        if reader.serial:
            widgets.status_label.setText(f"LE: CH{reader.channel} S/N {reader.serial}")
            widgets.status_label.setStyleSheet("color: #44bb44; font-size: 10px; font-weight: bold;")
    elif window.session.state and window.session.state.linear_fresh():
        count = window.session.state.linear_count()
        mm = window.session.state.linear_mm()
        widgets.pos_label.setText(f"Linear: {count:+d} cnt / {mm:+.3f} mm")
        widgets.pos_label.setStyleSheet("color: #ffb74d; font-size: 11px; font-weight: bold;")
        widgets.status_label.setText("LE: 외부 토픽")
        widgets.status_label.setStyleSheet("color: #ffb74d; font-size: 10px; font-weight: bold;")
    else:
        widgets.pos_label.setText("Linear: --")
        widgets.pos_label.setStyleSheet("color: #607d8b; font-size: 11px;")

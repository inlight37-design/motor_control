# -*- coding: utf-8 -*-
"""C++ RT 파형 생성기 시작/정지 UI 동작."""
from ..core.control_client import WaveformSettings
from ..core.time_utils import now_str


def on_wf_type_changed(window, wf_type: str):
    """chirp 선택 시 종료 주파수/시간 위젯을 표시."""
    widgets = window.waveform_widgets
    is_chirp = wf_type == "chirp"
    for widget in [widgets.end_label, widgets.freq_end_spin, widgets.duration_label, widgets.duration_spin]:
        widget.setVisible(is_chirp)


def start_waveform(window):
    """UI 입력을 WaveformSettings로 변환하고 C++ 파형 생성기를 시작."""
    widgets = window.waveform_widgets
    wf_type = widgets.type_combo.currentText()
    settings = WaveformSettings(
        waveform_type=wf_type,
        freq_hz=float(widgets.freq_spin.value()),
        amp_rpm=float(widgets.amp_spin.value()),
        offset_rpm=float(widgets.offset_spin.value()),
        freq_end_hz=float(widgets.freq_end_spin.value()) if wf_type == "chirp" else 0.0,
        duration_s=float(widgets.duration_spin.value()) if wf_type == "chirp" else 0.0,
    )
    cmd_text = window.control.start_waveform(settings)

    window.waveform_running = True
    widgets.start_button.setEnabled(False)
    widgets.stop_button.setEnabled(True)
    window.manual_motion_widgets.rpm_spin.setEnabled(False)
    window.script_log_widgets.script_button.setEnabled(False)
    window.update_log(f"[{now_str()}] C++ 파형: {cmd_text}")


def stop_waveform(window):
    """C++ 파형 생성기를 정지하고 수동 모드 UI로 되돌린다."""
    widgets = window.waveform_widgets
    window.control.stop_waveform()
    window.waveform_running = False
    widgets.start_button.setEnabled(True)
    widgets.stop_button.setEnabled(False)
    window.manual_motion_widgets.rpm_spin.setEnabled(True)
    window.script_log_widgets.script_button.setEnabled(bool(window.ui_state.loaded_script_path))
    window.update_log(f"[{now_str()}] 파형 정지 -> 수동 모드")

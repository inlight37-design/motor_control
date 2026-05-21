# -*- coding: utf-8 -*-
"""모션 스크립트 선택/시작/중지 UI 동작 헬퍼."""
import os

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ..core.config import SCRIPT_DIR
from ..core.time_utils import now_str
from ..logic.motion_script import MotionScript, MotionScriptError


def browse_script(window):
    """파일 다이얼로그로 모션 스크립트(.py)를 선택하고 유효성 검증."""
    options = QFileDialog.Options() | QFileDialog.DontUseNativeDialog
    fname, _ = QFileDialog.getOpenFileName(
        window,
        "스크립트",
        str(SCRIPT_DIR),
        "Python (*.py)",
        options=options,
    )
    if not fname:
        return

    try:
        MotionScript.load(fname)
    except MotionScriptError as exc:
        QMessageBox.critical(window, "오류", str(exc))
        return

    window.ui_state.loaded_script_path = fname
    widgets = window.script_log_widgets
    widgets.script_label.setText(f"({os.path.basename(fname)})")
    widgets.script_button.setEnabled(True)
    window.update_log(f"[{now_str()}] 스크립트 로드: {os.path.basename(fname)}")


def toggle_script(window):
    """모션 스크립트 시작/중지 토글."""
    if not window.script_running:
        if not window.ui_state.loaded_script_path:
            return
        try:
            script = MotionScript.load(window.ui_state.loaded_script_path)
        except MotionScriptError as exc:
            QMessageBox.critical(window, "오류", str(exc))
            return

        window.script_running = True
        window.manual_motion_widgets.rpm_spin.setEnabled(False)
        window.waveform_widgets.start_button.setEnabled(False)
        window.script_log_widgets.script_button.setText("스크립트 중지")
        window.session.control.start_motion_script(script)
        return

    window.script_running = False
    window.manual_motion_widgets.rpm_spin.setEnabled(True)
    window.waveform_widgets.start_button.setEnabled(True)
    window.script_log_widgets.script_button.setText("스크립트 시작")
    window.session.control.stop_motion_script()


def on_script_error(window, msg: str):
    """스크립트 실행 중 오류가 발생했을 때 수동 모드로 복귀."""
    window.update_log(f"[{now_str()}] [ERROR] {msg}")
    QMessageBox.critical(window, "스크립트 오류", msg)
    window.script_running = False
    window.manual_motion_widgets.rpm_spin.setEnabled(True)
    window.waveform_widgets.start_button.setEnabled(True)
    window.script_log_widgets.script_button.setText("스크립트 시작")

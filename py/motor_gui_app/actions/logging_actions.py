# -*- coding: utf-8 -*-
"""CSV 로깅 시작/정지 UI 동작."""
import os
import time
from pathlib import Path

from PyQt5.QtWidgets import QMessageBox

from ..core.config import LOG_DIR
from ..core.time_utils import now_str


def start_logging_to(window, log_path: Path):
    """지정한 경로로 CSV 로깅을 시작하고 기존 로깅 UI 상태를 갱신."""
    widgets = window.script_log_widgets
    log_path.parent.mkdir(parents=True, exist_ok=True)
    window.session.control.start_csv_logging(log_path)
    window.manual_csv_logging_active = True
    widgets.log_start_button.setEnabled(False)
    widgets.log_stop_button.setEnabled(True)
    widgets.log_path_label.setText(f"로깅 중... ({os.path.basename(log_path)})")
    widgets.log_path_label.setStyleSheet("color: #00cc00; font-weight: bold;")
    window.update_log(f"[{now_str()}] CSV 로깅 시작: {log_path}")


def start_logging(window):
    """CSV 로깅 시작. Python에서 경로를 미리 만들고 C++에 전달한다."""
    if window.hyst_test_running:
        QMessageBox.warning(window, "CSV 로깅", "히스테리시스 테스트가 실행 중입니다.")
        return
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"epos_{time.strftime('%Y%m%d_%H%M%S')}.csv"

    start_logging_to(window, log_path)


def stop_logging(window):
    """CSV 로깅 정지 명령을 전송하고 UI 상태를 대기 상태로 되돌린다."""
    widgets = window.script_log_widgets
    window.session.control.stop_csv_logging()
    window.manual_csv_logging_active = False
    widgets.log_start_button.setEnabled(True)
    widgets.log_stop_button.setEnabled(False)
    widgets.log_path_label.setText("로깅 대기")
    widgets.log_path_label.setStyleSheet("color: #666;")
    window.update_log(f"[{now_str()}] CSV 로깅 중지")

# -*- coding: utf-8 -*-
"""GUI 로그 뷰어 영역 생성 함수."""
from PyQt5.QtWidgets import QTextEdit


def build_log_viewer_panel(window) -> QTextEdit:
    """터미널 스타일 로그 뷰어 위젯을 생성."""
    window.log_viewer = QTextEdit()
    window.log_viewer.setReadOnly(True)
    window.log_viewer.setFixedHeight(80)
    window.log_viewer.setStyleSheet("background-color: #222; color: #0f0;")
    return window.log_viewer

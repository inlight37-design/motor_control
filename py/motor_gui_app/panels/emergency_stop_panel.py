# -*- coding: utf-8 -*-
"""비상 정지 버튼 영역 생성 함수."""
from PyQt5.QtWidgets import QHBoxLayout, QPushButton

from ..actions import motion_actions


def build_emergency_stop_row(window) -> QHBoxLayout:
    """항상 보이는 전체 비상 정지 버튼 행을 생성."""
    row = QHBoxLayout()
    btn_stop = QPushButton("비상 정지 (ALL)")
    btn_stop.setStyleSheet(
        "background-color: red; color: white; font-weight: bold; "
        "padding: 6px 20px; font-size: 13px;"
    )
    btn_stop.clicked.connect(lambda _checked=False: motion_actions.emergency_stop(window))
    row.addWidget(btn_stop)
    row.addStretch()
    return row

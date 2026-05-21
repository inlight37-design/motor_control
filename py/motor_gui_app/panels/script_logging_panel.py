# -*- coding: utf-8 -*-
"""CSV 로깅과 Python 모션 스크립트 패널 생성 함수."""
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSpinBox, QVBoxLayout

from ..actions import logging_actions, script_actions
from ..ui.widget_groups import ScriptLogWidgets


def build_script_logging_panel(window) -> QFrame:
    """스크립트/로깅 패널을 만들고 버튼 동작을 actions 모듈에 연결."""
    panel = QFrame()
    panel.setFrameShape(QFrame.StyledPanel)
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    layout = QVBoxLayout(panel)
    layout.setSpacing(4)

    # CSV 로깅 행: C++ 노드에서 고속 CSV 기록을 시작/중지한다.
    log_row = QHBoxLayout()
    log_start_button = QPushButton("CSV 로깅 시작")
    log_start_button.setStyleSheet(
        "background-color: #009688; color: white; font-weight: bold; padding: 6px;"
    )
    log_start_button.clicked.connect(lambda _checked=False: logging_actions.start_logging(window))

    log_stop_button = QPushButton("로깅 중지")
    log_stop_button.setStyleSheet(
        "background-color: #666; color: white; font-weight: bold; padding: 6px;"
    )
    log_stop_button.clicked.connect(lambda _checked=False: logging_actions.stop_logging(window))
    log_stop_button.setEnabled(False)

    log_path_label = QLabel("로깅 대기")
    log_path_label.setStyleSheet("color: #666;")

    log_row.addWidget(QLabel("데이터 기록:"))
    log_row.addWidget(log_start_button)
    log_row.addWidget(log_stop_button)
    log_row.addWidget(log_path_label)
    log_row.addStretch()
    layout.addLayout(log_row)

    # Python 모션 스크립트 행: target_rpm(t, state)을 주기적으로 평가한다.
    script_row = QHBoxLayout()
    script_hz_spin = QSpinBox()
    script_hz_spin.setRange(1, 1000)
    script_hz_spin.setValue(200)
    script_hz_spin.setSuffix(" Hz")

    script_label = QLabel("(스크립트: 없음)")
    script_label.setStyleSheet("color: blue; font-weight: bold;")

    btn_browse = QPushButton("스크립트 열기")
    btn_browse.clicked.connect(lambda _checked=False: script_actions.browse_script(window))

    script_button = QPushButton("스크립트 시작")
    script_button.setEnabled(False)
    script_button.clicked.connect(lambda _checked=False: script_actions.toggle_script(window))

    script_row.addWidget(QLabel("Python 스크립트:"))
    script_row.addWidget(QLabel("평가:"))
    script_row.addWidget(script_hz_spin)
    script_row.addWidget(script_label)
    script_row.addWidget(btn_browse)
    script_row.addWidget(script_button)
    script_row.addStretch()
    layout.addLayout(script_row)
    layout.addStretch()

    window.script_log_widgets = ScriptLogWidgets(
        log_start_button=log_start_button,
        log_stop_button=log_stop_button,
        log_path_label=log_path_label,
        script_hz_spin=script_hz_spin,
        script_label=script_label,
        script_button=script_button,
    )

    return panel

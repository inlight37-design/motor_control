# -*- coding: utf-8 -*-
"""상단 시스템 제어와 진단 표시 영역 생성 함수."""
from typing import List

from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import DEFAULT_RT_CPU
from ..actions import system_actions
from ..ui import graph_update, visibility_actions
from ..ui.widget_groups import TopStatusWidgets


def build_top_status_area(window, layout: QVBoxLayout, ifaces: List[str], default_iface: str):
    """메인 윈도우 상단의 공통 상태/진단 영역을 생성해 layout에 추가."""
    # 상단 바: 인터페이스 선택, RT CPU 설정, 시스템 시작/종료
    top = QHBoxLayout()
    top.addWidget(QLabel("인터페이스:"))

    iface_combo = QComboBox()
    iface_combo.setMinimumWidth(200)
    for iface in ifaces:
        iface_combo.addItem(iface)
    if default_iface:
        if default_iface not in ifaces:
            iface_combo.addItem(default_iface)
        iface_combo.setCurrentText(default_iface)

    btn_refresh = QPushButton("새로고침")
    btn_refresh.setFixedWidth(70)
    btn_refresh.clicked.connect(lambda _checked=False: system_actions.refresh_ifaces(window))

    status_label = QLabel("OFF")
    status_label.setFont(QFont("Arial", 14, QFont.Bold))
    status_label.setStyleSheet("color: red;")

    motor_button = QPushButton("시스템 시작")
    motor_button.clicked.connect(lambda _checked=False: system_actions.toggle_motor(window))
    motor_button.setStyleSheet(
        "background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;"
    )

    btn_reset = QPushButton("그래프 초기화")
    btn_reset.clicked.connect(lambda _checked=False: graph_update.reset_graph_buffers(window))
    btn_reset.setStyleSheet(
        "background-color: #2196F3; color: white; font-weight: bold; padding: 8px;"
    )

    show_speed_checkbox = QCheckBox("속도")
    show_speed_checkbox.setChecked(True)
    show_speed_checkbox.toggled.connect(lambda _checked=False: visibility_actions.toggle_graph_visibility(window))

    show_rt_checkbox = QCheckBox("RT주기")
    show_rt_checkbox.setChecked(True)
    show_rt_checkbox.toggled.connect(lambda _checked=False: visibility_actions.toggle_graph_visibility(window))

    top.addWidget(show_speed_checkbox)
    top.addWidget(show_rt_checkbox)
    top.addSpacing(6)
    top.addWidget(iface_combo)
    top.addWidget(btn_refresh)
    top.addSpacing(6)
    top.addWidget(QLabel("RT CPU:"))

    rt_cpu_spin = QSpinBox()
    rt_cpu_spin.setRange(-1, 7)
    rt_cpu_spin.setValue(DEFAULT_RT_CPU)
    rt_cpu_spin.setFixedWidth(52)
    rt_cpu_spin.setToolTip("-1: 고정 없음 / 0-7: 특정 코어 고정")

    top.addWidget(rt_cpu_spin)
    top.addSpacing(10)
    top.addWidget(status_label)
    top.addWidget(motor_button)
    top.addWidget(btn_reset)
    top.addStretch()
    layout.addLayout(top)

    # 진단 바: 모터 상태, 에러, 지터, 오버런, WKC, Heartbeat 실시간 표시
    diag = QFrame()
    diag.setStyleSheet("background-color: #1a1a2e; border-radius: 6px; padding: 3px;")
    diag_layout = QHBoxLayout(diag)
    diag_layout.setContentsMargins(10, 4, 10, 4)

    motor_state_label = QLabel("모터: 대기")
    motor_state_label.setFont(QFont("Consolas", 11, QFont.Bold))
    motor_state_label.setStyleSheet("color: #aaa;")

    error_code_label = QLabel("")
    error_code_label.setFont(QFont("Consolas", 10, QFont.Bold))
    error_code_label.setStyleSheet("color: #ff6666;")

    rt_jitter_label = QLabel("지터: -- μs")
    rt_jitter_label.setFont(QFont("Consolas", 11, QFont.Bold))
    rt_jitter_label.setStyleSheet("color: #aaa;")

    overrun_label = QLabel("오버런: 0")
    overrun_label.setFont(QFont("Consolas", 11, QFont.Bold))
    overrun_label.setStyleSheet("color: #aaa;")

    wkc_error_label = QLabel("WKC: 0")
    wkc_error_label.setFont(QFont("Consolas", 11, QFont.Bold))
    wkc_error_label.setStyleSheet("color: #aaa;")

    heartbeat_label = QLabel("HB: --")
    heartbeat_label.setFont(QFont("Consolas", 10, QFont.Bold))
    heartbeat_label.setStyleSheet("color: #aaa;")

    fault_reset_button = QPushButton("Fault Reset")
    fault_reset_button.setStyleSheet(
        "background-color: #ff8800; color: white; font-weight: bold; padding: 3px 10px;"
    )
    fault_reset_button.setVisible(False)

    auto_reset_checkbox = QCheckBox("자동복구")
    auto_reset_checkbox.setStyleSheet("color: #ccc;")
    auto_reset_checkbox.setChecked(True)

    for widget in [
        motor_state_label,
        error_code_label,
        rt_jitter_label,
        overrun_label,
        wkc_error_label,
        heartbeat_label,
        fault_reset_button,
        auto_reset_checkbox,
    ]:
        diag_layout.addWidget(widget)
        diag_layout.addSpacing(8)
    diag_layout.addStretch()
    layout.addWidget(diag)

    window.top_status_widgets = TopStatusWidgets(
        iface_combo=iface_combo,
        status_label=status_label,
        motor_button=motor_button,
        show_speed_checkbox=show_speed_checkbox,
        show_rt_checkbox=show_rt_checkbox,
        rt_cpu_spin=rt_cpu_spin,
        motor_state_label=motor_state_label,
        error_code_label=error_code_label,
        rt_jitter_label=rt_jitter_label,
        overrun_label=overrun_label,
        wkc_error_label=wkc_error_label,
        heartbeat_label=heartbeat_label,
        fault_reset_button=fault_reset_button,
        auto_reset_checkbox=auto_reset_checkbox,
    )

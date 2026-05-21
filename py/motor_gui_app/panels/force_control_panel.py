# -*- coding: utf-8 -*-
"""힘 제어 시작/정지와 PID/Tanh 파라미터 패널 생성 함수."""
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.config import (
    DEFAULT_FORCE_ALPHA,
    DEFAULT_FORCE_KD,
    DEFAULT_FORCE_KI,
    DEFAULT_FORCE_KP,
    DEFAULT_FORCE_MAX_RPM,
    DEFAULT_FORCE_TANH_DEADBAND_N,
    DEFAULT_FORCE_TANH_SENS_N,
    DEFAULT_FORCE_TARGET_N,
    MAX_RPM,
)
from ..actions import force_control_actions
from ..ui.widget_groups import ForceControlWidgets


def build_force_control_panel(window) -> QFrame:
    """힘 제어 패널을 만들고 버튼 동작을 actions 모듈에 연결."""
    fc_frame = QFrame()
    fc_frame.setStyleSheet("""
        QFrame {
            background-color: #1a2e1a;
            border-radius: 4px;
        }
        QLabel {
            color: #e8eaed;
            background: transparent;
        }
        QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: #2b3a2b;
            color: #ffffff;
            border: 1px solid #5f7a5f;
            border-radius: 3px;
            padding: 2px 6px;
        }
    """)
    fc_outer = QVBoxLayout(fc_frame)
    fc_outer.setContentsMargins(8, 4, 8, 4)
    fc_outer.setSpacing(3)

    # 힘 제어 행 1: 시작/정지, 모드, 상태
    fc_row1 = QHBoxLayout()
    fc_row1b = QHBoxLayout()

    start_button = QPushButton("힘 제어 시작")
    start_button.setFixedWidth(110)
    start_button.setStyleSheet(
        "background-color: #2e7d32; color: white; font-weight: bold; padding: 3px 6px;"
    )
    start_button.clicked.connect(lambda _checked=False: force_control_actions.start_force_ctrl(window))

    stop_button = QPushButton("힘 제어 정지")
    stop_button.setFixedWidth(110)
    stop_button.setStyleSheet(
        "background-color: #c62828; color: white; font-weight: bold; padding: 3px 6px;"
    )
    stop_button.setEnabled(False)
    stop_button.clicked.connect(lambda _checked=False: force_control_actions.stop_force_ctrl(window))

    target_spin = QDoubleSpinBox()
    target_spin.setRange(-9999.0, 9999.0)
    target_spin.setValue(DEFAULT_FORCE_TARGET_N)
    target_spin.setDecimals(1)
    target_spin.setSuffix(" N")
    target_spin.setFixedWidth(110)
    target_spin.setToolTip("목표 힘 (양수=압축, 음수=인장)")

    direction_combo = QComboBox()
    direction_combo.addItems(["+1 (정방향)", "-1 (역방향)"])
    direction_combo.setFixedWidth(110)
    direction_combo.setToolTip("모터 양수 RPM일 때 힘이 증가하면 +1, 감소하면 -1")

    feedback_combo = QComboBox()
    feedback_combo.addItems(["CH0 시작", "CH1 끝", "평균", "큰값"])
    feedback_combo.setFixedWidth(92)
    feedback_combo.setToolTip("힘 PID가 사용할 로드셀 값")

    max_rpm_spin = QSpinBox()
    max_rpm_spin.setRange(10, MAX_RPM)
    max_rpm_spin.setValue(DEFAULT_FORCE_MAX_RPM)
    max_rpm_spin.setSuffix(" rpm")
    max_rpm_spin.setFixedWidth(100)
    max_rpm_spin.setToolTip("힘 제어 시 모터 최대 속도 제한")

    status_label = QLabel("비활성")
    status_label.setFont(QFont("Consolas", 11, QFont.Bold))
    status_label.setStyleSheet("color: #888;")
    status_label.setMinimumWidth(120)

    ctrl_mode_combo = QComboBox()
    ctrl_mode_combo.addItems(["PID", "Tanh"])
    ctrl_mode_combo.setFixedWidth(76)
    ctrl_mode_combo.setToolTip("힘 제어 알고리즘 선택")
    ctrl_mode_combo.currentTextChanged.connect(
        lambda mode: force_control_actions.on_force_ctrl_mode_changed(window, mode)
    )

    alpha_spin = QDoubleSpinBox()
    alpha_spin.setRange(0.01, 1.0)
    alpha_spin.setValue(DEFAULT_FORCE_ALPHA)
    alpha_spin.setDecimals(2)
    alpha_spin.setSingleStep(0.05)
    alpha_spin.setFixedWidth(80)
    alpha_spin.setToolTip("출력 부드러움 (0.01=매우 부드러움, 1.0=즉시 반영)")

    fc_row1.addWidget(QLabel("힘 제어:"))
    fc_row1.addWidget(QLabel("모드:"))
    fc_row1.addWidget(ctrl_mode_combo)
    fc_row1.addSpacing(8)
    fc_row1.addWidget(start_button)
    fc_row1.addWidget(stop_button)
    fc_row1.addSpacing(8)
    fc_row1.addWidget(status_label)
    fc_row1.addStretch()

    fc_row1b.addWidget(QLabel("목표:"))
    fc_row1b.addWidget(target_spin)
    fc_row1b.addSpacing(4)
    fc_row1b.addWidget(QLabel("최대:"))
    fc_row1b.addWidget(max_rpm_spin)
    fc_row1b.addSpacing(4)
    fc_row1b.addWidget(QLabel("방향:"))
    fc_row1b.addWidget(direction_combo)
    fc_row1b.addSpacing(4)
    fc_row1b.addWidget(QLabel("피드백:"))
    fc_row1b.addWidget(feedback_combo)
    fc_row1b.addSpacing(4)
    fc_row1b.addWidget(QLabel("부드러움:"))
    fc_row1b.addWidget(alpha_spin)
    fc_row1b.addStretch()

    # PID 파라미터 행: 모드가 PID일 때만 표시
    pid_panel = QWidget()
    fc_row2 = QHBoxLayout(pid_panel)
    fc_row2.setContentsMargins(0, 0, 0, 0)

    kp_spin = QDoubleSpinBox()
    kp_spin.setRange(0.0, 100.0)
    kp_spin.setValue(DEFAULT_FORCE_KP)
    kp_spin.setDecimals(3)
    kp_spin.setSuffix(" Kp")
    kp_spin.setFixedWidth(100)

    ki_spin = QDoubleSpinBox()
    ki_spin.setRange(0.0, 100.0)
    ki_spin.setValue(DEFAULT_FORCE_KI)
    ki_spin.setDecimals(4)
    ki_spin.setSuffix(" Ki")
    ki_spin.setFixedWidth(100)

    kd_spin = QDoubleSpinBox()
    kd_spin.setRange(0.0, 100.0)
    kd_spin.setValue(DEFAULT_FORCE_KD)
    kd_spin.setDecimals(4)
    kd_spin.setSuffix(" Kd")
    kd_spin.setFixedWidth(100)

    pid_apply_button = QPushButton("적용")
    pid_apply_button.setFixedWidth(60)
    pid_apply_button.setStyleSheet(
        "background-color: #37474f; color: white; padding: 3px 6px;"
    )
    pid_apply_button.clicked.connect(lambda _checked=False: force_control_actions.apply_force_pid(window))

    fc_row2.addWidget(QLabel("PID:"))
    fc_row2.addWidget(kp_spin)
    fc_row2.addWidget(ki_spin)
    fc_row2.addWidget(kd_spin)
    fc_row2.addWidget(pid_apply_button)
    fc_row2.addStretch()

    # Tanh 비선형 제어 파라미터 행: 모드가 Tanh일 때만 표시
    tanh_panel = QWidget()
    fc_row2b = QHBoxLayout(tanh_panel)
    fc_row2b.setContentsMargins(0, 0, 0, 0)

    tanh_sens_spin = QDoubleSpinBox()
    tanh_sens_spin.setRange(0.01, 50.0)
    tanh_sens_spin.setValue(DEFAULT_FORCE_TANH_SENS_N)
    tanh_sens_spin.setDecimals(2)
    tanh_sens_spin.setSingleStep(0.1)
    tanh_sens_spin.setSuffix(" N 민감도")
    tanh_sens_spin.setFixedWidth(120)
    tanh_sens_spin.setToolTip(
        "오차가 클 때 빠르게, 목표 근처에서는 천천히 접근\n"
        "작을수록 빠르고 민감, 클수록 느리고 안정적"
    )

    tanh_dead_spin = QDoubleSpinBox()
    tanh_dead_spin.setRange(0.0, 10.0)
    tanh_dead_spin.setValue(DEFAULT_FORCE_TANH_DEADBAND_N)
    tanh_dead_spin.setDecimals(2)
    tanh_dead_spin.setSingleStep(0.01)
    tanh_dead_spin.setSuffix(" N 데드밴드")
    tanh_dead_spin.setFixedWidth(130)
    tanh_dead_spin.setToolTip("목표힘과의 차이가 이 값 이하이면 정지")

    tanh_apply_button = QPushButton("Tanh 적용")
    tanh_apply_button.setFixedWidth(80)
    tanh_apply_button.setStyleSheet(
        "background-color: #1a5276; color: white; padding: 3px 6px;"
    )
    tanh_apply_button.clicked.connect(lambda _checked=False: force_control_actions.apply_force_tanh(window))

    fc_row2b.addWidget(QLabel("비선형:"))
    fc_row2b.addSpacing(2)
    fc_row2b.addWidget(tanh_sens_spin)
    fc_row2b.addWidget(tanh_dead_spin)
    fc_row2b.addWidget(tanh_apply_button)
    fc_row2b.addStretch()

    fc_outer.addLayout(fc_row1)
    fc_outer.addLayout(fc_row1b)
    fc_outer.addWidget(pid_panel)
    fc_outer.addWidget(tanh_panel)

    window.force_control_widgets = ForceControlWidgets(
        start_button=start_button,
        stop_button=stop_button,
        target_spin=target_spin,
        direction_combo=direction_combo,
        feedback_combo=feedback_combo,
        max_rpm_spin=max_rpm_spin,
        status_label=status_label,
        ctrl_mode_combo=ctrl_mode_combo,
        alpha_spin=alpha_spin,
        pid_panel=pid_panel,
        kp_spin=kp_spin,
        ki_spin=ki_spin,
        kd_spin=kd_spin,
        pid_apply_button=pid_apply_button,
        tanh_panel=tanh_panel,
        tanh_sens_spin=tanh_sens_spin,
        tanh_dead_spin=tanh_dead_spin,
        tanh_apply_button=tanh_apply_button,
    )
    force_control_actions.sync_force_ctrl_mode_ui(window)
    return fc_frame

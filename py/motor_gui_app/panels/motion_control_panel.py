# -*- coding: utf-8 -*-
"""수동 속도, 파형, 위치, 토크, 리니어 엔코더 패널 생성 함수."""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import (
    DEFAULT_ACCEL_RPM_S,
    DEFAULT_LINEAR_COUNTS_PER_MM,
    DEFAULT_LINEAR_ENCODER_CHANNEL,
    DEFAULT_LINEAR_INVERT,
    DEFAULT_MANUAL_RPM_LIMIT,
    DEFAULT_POSITION_LEAD_MM_REV,
    DEFAULT_WF_AMP_RPM,
    DEFAULT_WF_DURATION_S,
    DEFAULT_WF_FREQ_END_HZ,
    DEFAULT_WF_FREQ_HZ,
    DEFAULT_WF_OFFSET_RPM,
    MAX_RPM,
)
from ..actions import linear_encoder_actions, motion_actions, waveform_actions
from ..ui.widget_groups import (
    LinearEncoderWidgets,
    ManualMotionWidgets,
    PositionTorqueWidgets,
    WaveformWidgets,
)


def build_motion_control_panel(window) -> QFrame:
    """속도/위치/토크 제어 패널을 만들고 버튼 동작을 actions 모듈에 연결."""
    panel = QFrame()
    panel.setFrameShape(QFrame.StyledPanel)
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    tab_speed_layout = QVBoxLayout(panel)
    tab_speed_layout.setSpacing(4)

    # 수동 RPM 입력 행
    c1 = QHBoxLayout()
    rpm_spin = QDoubleSpinBox()
    rpm_spin.setRange(-MAX_RPM, MAX_RPM)
    rpm_spin.setSingleStep(100)
    rpm_spin.setDecimals(0)
    rpm_spin.setFont(QFont("Arial", 13))
    rpm_spin.setAlignment(Qt.AlignCenter)
    rpm_spin.lineEdit().returnPressed.connect(lambda: motion_actions.send_manual_rpm(window))

    btn_send = QPushButton("수동 입력")
    btn_send.clicked.connect(lambda _checked=False: motion_actions.send_manual_rpm(window))

    accel_spin = QSpinBox()
    accel_spin.setRange(0, 50000)
    accel_spin.setValue(DEFAULT_ACCEL_RPM_S)
    accel_spin.setSuffix(" rpm/s")
    accel_spin.setToolTip("0으로 설정하면 C++ 노드에서 가속도 제한 없이 목표 RPM을 바로 적용합니다.")

    limit_spin = QSpinBox()
    limit_spin.setRange(0, MAX_RPM)
    limit_spin.setValue(DEFAULT_MANUAL_RPM_LIMIT)
    limit_spin.setSuffix(" rpm")

    c1.addWidget(QLabel("수동 RPM:"))
    c1.addWidget(rpm_spin)
    c1.addWidget(btn_send)
    c1.addSpacing(15)
    c1.addWidget(QLabel("가속도:"))
    c1.addWidget(accel_spin)
    c1.addWidget(QLabel("한계:"))
    c1.addWidget(limit_spin)
    c1.addStretch()
    tab_speed_layout.addLayout(c1)

    window.manual_motion_widgets = ManualMotionWidgets(
        rpm_spin=rpm_spin,
        send_button=btn_send,
        accel_spin=accel_spin,
        limit_spin=limit_spin,
    )

    # C++ RT 루프에서 생성하는 속도 파형 설정 행
    c2 = QHBoxLayout()
    wf_type_combo = QComboBox()
    wf_type_combo.addItems(["sine", "square", "triangle", "chirp"])
    wf_type_combo.setFixedWidth(90)
    wf_type_combo.currentTextChanged.connect(lambda text: waveform_actions.on_wf_type_changed(window, text))

    wf_freq_spin = QDoubleSpinBox()
    wf_freq_spin.setRange(0.01, 500.0)
    wf_freq_spin.setValue(DEFAULT_WF_FREQ_HZ)
    wf_freq_spin.setDecimals(2)
    wf_freq_spin.setSuffix(" Hz")

    wf_end_label = QLabel("→")
    wf_freq_end_spin = QDoubleSpinBox()
    wf_freq_end_spin.setRange(0.01, 500.0)
    wf_freq_end_spin.setValue(DEFAULT_WF_FREQ_END_HZ)
    wf_freq_end_spin.setDecimals(2)
    wf_freq_end_spin.setSuffix(" Hz")

    wf_duration_label = QLabel("시간:")
    wf_duration_spin = QDoubleSpinBox()
    wf_duration_spin.setRange(1.0, 3600.0)
    wf_duration_spin.setValue(DEFAULT_WF_DURATION_S)
    wf_duration_spin.setDecimals(1)
    wf_duration_spin.setSuffix(" s")

    for widget in [
        wf_end_label,
        wf_freq_end_spin,
        wf_duration_label,
        wf_duration_spin,
    ]:
        widget.setVisible(False)

    wf_amp_spin = QSpinBox()
    wf_amp_spin.setRange(0, MAX_RPM)
    wf_amp_spin.setValue(DEFAULT_WF_AMP_RPM)
    wf_amp_spin.setSuffix(" rpm")

    wf_offset_spin = QSpinBox()
    wf_offset_spin.setRange(-MAX_RPM, MAX_RPM)
    wf_offset_spin.setValue(DEFAULT_WF_OFFSET_RPM)
    wf_offset_spin.setSuffix(" rpm")

    wf_start_button = QPushButton("파형 시작 (C++ RT)")
    wf_start_button.setStyleSheet(
        "background-color: #9C27B0; color: white; font-weight: bold; padding: 6px;"
    )
    wf_start_button.clicked.connect(lambda _checked=False: waveform_actions.start_waveform(window))

    wf_stop_button = QPushButton("파형 정지")
    wf_stop_button.setStyleSheet(
        "background-color: #666; color: white; font-weight: bold; padding: 6px;"
    )
    wf_stop_button.clicked.connect(lambda _checked=False: waveform_actions.stop_waveform(window))
    wf_stop_button.setEnabled(False)

    c2.addWidget(QLabel("C++ 파형:"))
    c2.addWidget(wf_type_combo)
    c2.addWidget(QLabel("주파수:"))
    c2.addWidget(wf_freq_spin)
    c2.addWidget(wf_end_label)
    c2.addWidget(wf_freq_end_spin)
    c2.addWidget(wf_duration_label)
    c2.addWidget(wf_duration_spin)
    c2.addWidget(QLabel("진폭:"))
    c2.addWidget(wf_amp_spin)
    c2.addWidget(QLabel("오프셋:"))
    c2.addWidget(wf_offset_spin)
    c2.addWidget(wf_start_button)
    c2.addWidget(wf_stop_button)
    c2.addStretch()
    tab_speed_layout.addLayout(c2)

    window.waveform_widgets = WaveformWidgets(
        type_combo=wf_type_combo,
        freq_spin=wf_freq_spin,
        end_label=wf_end_label,
        freq_end_spin=wf_freq_end_spin,
        duration_label=wf_duration_label,
        duration_spin=wf_duration_spin,
        amp_spin=wf_amp_spin,
        offset_spin=wf_offset_spin,
        start_button=wf_start_button,
        stop_button=wf_stop_button,
    )

    # CSP 위치 / CST 토크 직접 입력 행
    c0_status = QHBoxLayout()
    c0_targets = QHBoxLayout()

    mode_combo = QComboBox()
    mode_combo.addItems(["속도 제어 (CSV: 9)", "위치 제어 (CSP: 8)", "토크 제어 (CST: 10)"])
    mode_combo.currentIndexChanged.connect(lambda index: motion_actions.change_op_mode(window, index))

    actual_pos_label = QLabel("현재 위치: 0 틱")
    actual_pos_label.setStyleSheet("color: #2196F3; font-weight: bold;")
    actual_trq_label = QLabel("현재 토크: 0.0 mN·m (0 ‰)")
    actual_trq_label.setStyleSheet("color: #2196F3; font-weight: bold;")

    zero_pos_button = QPushButton("영점(0) 설정")
    zero_pos_button.clicked.connect(lambda _checked=False: motion_actions.set_zero_position(window))

    pos_spin = QSpinBox()
    pos_spin.setRange(-100000000, 100000000)
    pos_spin.setSingleStep(1000)
    pos_spin.setSuffix(" tick")
    pos_spin.setFixedWidth(130)
    pos_spin.valueChanged.connect(lambda _value: motion_actions.sync_pos_mm_from_ticks(window))

    pos_mm_spin = QDoubleSpinBox()
    pos_mm_spin.setRange(-250000.0, 250000.0)
    pos_mm_spin.setDecimals(3)
    pos_mm_spin.setSingleStep(1.0)
    pos_mm_spin.setSuffix(" mm")
    pos_mm_spin.setFixedWidth(115)
    pos_mm_spin.setToolTip("리드값과 motor tick/rev 기준으로 tick 위치 명령으로 변환")
    pos_mm_spin.valueChanged.connect(lambda _value: motion_actions.sync_pos_ticks_from_mm(window))

    pos_lead_spin = QDoubleSpinBox()
    pos_lead_spin.setRange(0.001, 1000.0)
    pos_lead_spin.setDecimals(3)
    pos_lead_spin.setSingleStep(0.1)
    pos_lead_spin.setValue(DEFAULT_POSITION_LEAD_MM_REV)
    pos_lead_spin.setSuffix(" mm/rev")
    pos_lead_spin.setFixedWidth(120)
    pos_lead_spin.setToolTip("위치제어 변환용 리드값: 모터 1회전당 이동거리")
    pos_lead_spin.valueChanged.connect(lambda _value: motion_actions.on_pos_lead_changed(window))

    btn_pos = QPushButton("위치 이동")
    btn_pos.clicked.connect(lambda _checked=False: motion_actions.send_manual_pos(window))

    pos_speed_spin = QSpinBox()
    pos_speed_spin.setRange(1, 1000000)
    pos_speed_spin.setValue(10000)
    pos_speed_spin.setSingleStep(1000)
    pos_speed_spin.setSuffix(" Tick/s")

    trq_spin = QSpinBox()
    trq_spin.setRange(-2000, 2000)
    trq_spin.setSingleStep(50)
    trq_spin.setSuffix(" ‰")

    btn_trq = QPushButton("토크 인가")
    btn_trq.clicked.connect(lambda _checked=False: motion_actions.send_manual_trq(window))

    c0_status.addWidget(QLabel("제어 모드:"))
    c0_status.addWidget(mode_combo)
    c0_status.addSpacing(15)
    c0_status.addWidget(actual_pos_label)
    c0_status.addWidget(zero_pos_button)
    c0_status.addSpacing(15)
    c0_status.addWidget(actual_trq_label)
    c0_status.addStretch()
    tab_speed_layout.addLayout(c0_status)

    c0_targets.addWidget(QLabel("목표 위치:"))
    c0_targets.addWidget(pos_spin)
    c0_targets.addWidget(pos_mm_spin)
    c0_targets.addWidget(QLabel("리드:"))
    c0_targets.addWidget(pos_lead_spin)
    c0_targets.addWidget(pos_speed_spin)
    c0_targets.addWidget(btn_pos)
    c0_targets.addSpacing(15)
    c0_targets.addWidget(QLabel("목표 토크:"))
    c0_targets.addWidget(trq_spin)
    c0_targets.addWidget(btn_trq)
    c0_targets.addStretch()
    tab_speed_layout.addLayout(c0_targets)

    window.position_torque_widgets = PositionTorqueWidgets(
        mode_combo=mode_combo,
        actual_pos_label=actual_pos_label,
        actual_trq_label=actual_trq_label,
        zero_pos_button=zero_pos_button,
        pos_spin=pos_spin,
        pos_mm_spin=pos_mm_spin,
        pos_lead_spin=pos_lead_spin,
        pos_speed_spin=pos_speed_spin,
        pos_move_button=btn_pos,
        trq_spin=trq_spin,
        trq_apply_button=btn_trq,
    )

    # GUI 내장 리니어 엔코더 확인/CSV 동기 기록용 설정 행
    lin_row = QHBoxLayout()
    linear_connect_button = QPushButton("Linear Enc 연결")
    linear_connect_button.setFixedWidth(120)
    linear_connect_button.setStyleSheet(
        "background-color: #37474f; color: white; font-weight: bold; padding: 3px 6px;"
    )
    linear_connect_button.clicked.connect(lambda _checked=False: linear_encoder_actions.toggle_linear_encoder(window))

    linear_channel_spin = QSpinBox()
    linear_channel_spin.setRange(0, 3)
    linear_channel_spin.setValue(DEFAULT_LINEAR_ENCODER_CHANNEL)
    linear_channel_spin.setFixedWidth(54)

    linear_counts_per_mm_spin = QDoubleSpinBox()
    linear_counts_per_mm_spin.setRange(0.001, 1.0e9)
    linear_counts_per_mm_spin.setDecimals(3)
    linear_counts_per_mm_spin.setValue(DEFAULT_LINEAR_COUNTS_PER_MM)
    linear_counts_per_mm_spin.setSuffix(" cnt/mm")
    linear_counts_per_mm_spin.setFixedWidth(130)
    linear_counts_per_mm_spin.valueChanged.connect(lambda _value: linear_encoder_actions.update_settings(window))

    linear_invert_checkbox = QCheckBox("반전")
    linear_invert_checkbox.setChecked(DEFAULT_LINEAR_INVERT)
    linear_invert_checkbox.toggled.connect(lambda _checked: linear_encoder_actions.update_settings(window))

    linear_zero_button = QPushButton("Zero")
    linear_zero_button.setFixedWidth(58)
    linear_zero_button.setEnabled(False)
    linear_zero_button.clicked.connect(lambda _checked=False: linear_encoder_actions.zero_linear_encoder(window))

    linear_pos_label = QLabel("Linear: --")
    linear_pos_label.setFont(QFont("Consolas", 11, QFont.Bold))
    linear_pos_label.setStyleSheet("color: #607d8b;")

    linear_status_label = QLabel("LE: --")
    linear_status_label.setStyleSheet("color: #607d8b; font-size: 10px;")

    lin_row.addWidget(QLabel("리니어 엔코더:"))
    lin_row.addWidget(QLabel("CH"))
    lin_row.addWidget(linear_channel_spin)
    lin_row.addWidget(linear_connect_button)
    lin_row.addWidget(linear_zero_button)
    lin_row.addSpacing(8)
    lin_row.addWidget(linear_counts_per_mm_spin)
    lin_row.addWidget(linear_invert_checkbox)
    lin_row.addSpacing(10)
    lin_row.addWidget(linear_pos_label)
    lin_row.addWidget(linear_status_label)
    lin_row.addStretch()
    tab_speed_layout.addLayout(lin_row)

    window.linear_encoder_widgets = LinearEncoderWidgets(
        connect_button=linear_connect_button,
        channel_spin=linear_channel_spin,
        counts_per_mm_spin=linear_counts_per_mm_spin,
        invert_checkbox=linear_invert_checkbox,
        zero_button=linear_zero_button,
        pos_label=linear_pos_label,
        status_label=linear_status_label,
    )

    tab_speed_layout.addStretch()
    return panel

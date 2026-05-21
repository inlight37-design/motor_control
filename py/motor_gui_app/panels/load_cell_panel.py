# -*- coding: utf-8 -*-
"""로드셀 표시와 소프트 리미트 패널 생성 함수."""
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import (
    DEFAULT_FORCE_ABS_MODE,
    DEFAULT_FORCE_SOFT_LIMIT_N,
    DEFAULT_FORCE_SOFT_START_PCT,
)
from ..actions import load_cell_actions
from ..ui.styles import LC_BUTTON_STYLE
from ..ui.widget_groups import LoadCellWidgets


def build_load_cell_panel(window) -> QFrame:
    """로드셀 표시, 캘리브레이션, tare, 소프트 리미트 패널을 생성."""
    # 패널 기본 프레임과 공통 스타일
    lc_frame = QFrame()
    lc_frame.setStyleSheet("""
        QFrame {
            background-color: #1a1a2e;
            border-radius: 4px;
        }
        QLabel {
            color: #e8eaed;
            background: transparent;
        }
        QCheckBox {
            color: #d0d7de;
            background: transparent;
        }
        QComboBox, QSpinBox, QDoubleSpinBox {
            background-color: #2b2f3a;
            color: #ffffff;
            border: 1px solid #5f6b7a;
            border-radius: 3px;
            padding: 2px 6px;
        }
    """)
    lc_outer = QVBoxLayout(lc_frame)
    lc_outer.setContentsMargins(8, 4, 8, 4)
    lc_outer.setSpacing(3)

    lc_row1 = QHBoxLayout()
    lc_row1b = QHBoxLayout()

    # 1행: 연결, 단위, 캘리브레이션, tare 제어
    connect_button = QPushButton("로드셀 연결")
    connect_button.setFixedWidth(110)
    connect_button.setStyleSheet(
        "background-color: #37474f; color: white; font-weight: bold; padding: 3px 6px;"
    )
    connect_button.clicked.connect(lambda _checked=False: load_cell_actions.toggle_lc_connect(window))

    cal_button = QPushButton("All Cal")
    cal_button.setFixedWidth(64)
    cal_button.setStyleSheet("background-color: #37474f; color: white; padding: 3px 6px;")
    cal_button.clicked.connect(lambda _checked=False: load_cell_actions.load_lc_cal(window))

    cal_ch0_button = QPushButton("CH0 Cal")
    cal_ch0_button.setFixedWidth(68)
    cal_ch0_button.setStyleSheet("background-color: #37474f; color: white; padding: 3px 6px;")
    cal_ch0_button.clicked.connect(lambda _checked=False: load_cell_actions.load_lc_cal_channel(window, 0))

    cal_ch1_button = QPushButton("CH1 Cal")
    cal_ch1_button.setFixedWidth(68)
    cal_ch1_button.setStyleSheet("background-color: #37474f; color: white; padding: 3px 6px;")
    cal_ch1_button.clicked.connect(lambda _checked=False: load_cell_actions.load_lc_cal_channel(window, 1))

    tare_ch0_button = QPushButton("Tare 0")
    tare_ch0_button.setFixedWidth(64)
    tare_ch0_button.setStyleSheet(LC_BUTTON_STYLE)
    tare_ch0_button.setEnabled(False)
    tare_ch0_button.clicked.connect(lambda _checked=False: load_cell_actions.tare_lc(window, 0))

    tare_ch1_button = QPushButton("Tare 1")
    tare_ch1_button.setFixedWidth(64)
    tare_ch1_button.setStyleSheet(LC_BUTTON_STYLE)
    tare_ch1_button.setEnabled(False)
    tare_ch1_button.clicked.connect(lambda _checked=False: load_cell_actions.tare_lc(window, 1))

    tare_all_button = QPushButton("Tare All")
    tare_all_button.setFixedWidth(76)
    tare_all_button.setStyleSheet(LC_BUTTON_STYLE)
    tare_all_button.setEnabled(False)
    tare_all_button.clicked.connect(lambda _checked=False: load_cell_actions.tare_lc_all(window))

    tare_reset_button = QPushButton("Tare Off")
    tare_reset_button.setFixedWidth(76)
    tare_reset_button.setStyleSheet(LC_BUTTON_STYLE)
    tare_reset_button.setEnabled(False)
    tare_reset_button.clicked.connect(lambda _checked=False: load_cell_actions.reset_lc_tare(window))

    unit_combo = QComboBox()
    unit_combo.addItems(["N", "g", "kg"])
    unit_combo.setFixedWidth(55)
    unit_combo.setToolTip("힘 표시 단위 / 한계값 단위")
    unit_combo.currentIndexChanged.connect(lambda _index: load_cell_actions.on_lc_unit_changed(window))

    # 1행 보조: 데이터 소스와 tare 상태
    cal_label = QLabel("Cal: none")
    cal_label.setStyleSheet("color: #666; font-size: 10px;")

    source_label = QLabel("소스: --")
    source_label.setStyleSheet("color: #90a4ae; font-size: 10px;")
    source_label.setMinimumWidth(115)

    tare_status_label = QLabel("Tare: --")
    tare_status_label.setStyleSheet("color: #90a4ae; font-size: 10px;")
    tare_status_label.setMinimumWidth(145)

    # 2행: 실시간 힘 표시
    ch0_label = QLabel("CH0 시작: --")
    ch0_label.setFont(QFont("Consolas", 13, QFont.Bold))
    ch0_label.setStyleSheet("color: #555;")
    ch0_label.setMinimumWidth(155)

    ch1_label = QLabel("CH1 끝: --")
    ch1_label.setFont(QFont("Consolas", 13, QFont.Bold))
    ch1_label.setStyleSheet("color: #555;")
    ch1_label.setMinimumWidth(145)

    delta_label = QLabel("Δ: --")
    delta_label.setFont(QFont("Consolas", 12, QFont.Bold))
    delta_label.setStyleSheet("color: #b0bec5;")
    delta_label.setMinimumWidth(110)

    max_label = QLabel("MAX: --")
    max_label.setFont(QFont("Consolas", 12, QFont.Bold))
    max_label.setStyleSheet("color: #b0bec5;")
    max_label.setMinimumWidth(110)

    for widget in [
        connect_button,
        unit_combo,
        cal_button,
        cal_ch0_button,
        cal_ch1_button,
        tare_ch0_button,
        tare_ch1_button,
        tare_all_button,
        tare_reset_button,
        source_label,
        tare_status_label,
    ]:
        lc_row1.addWidget(widget)
        lc_row1.addSpacing(6)
    lc_row1.addStretch()

    for widget in [
        ch0_label,
        ch1_label,
        delta_label,
        max_label,
        cal_label,
    ]:
        lc_row1b.addWidget(widget)
        lc_row1b.addSpacing(8)
    lc_row1b.addStretch()

    # 3행: |F| 표시/제어 모드와 로드셀 기반 소프트 리미트
    lc_row2 = QHBoxLayout()
    force_abs_checkbox = QCheckBox("장력 |F| 표시/제어")
    force_abs_checkbox.setChecked(DEFAULT_FORCE_ABS_MODE)
    force_abs_checkbox.setStyleSheet("color: #ccc;")
    force_abs_checkbox.setToolTip(
        "화면 표시와 힘 제어는 |F| 기준으로 동작하고, CSV에는 signed/abs 값이 모두 저장됩니다."
    )
    force_abs_checkbox.stateChanged.connect(lambda state: load_cell_actions.on_force_abs_mode_changed(window, state))

    soft_limit_checkbox = QCheckBox("소프트 리미트")
    soft_limit_checkbox.setStyleSheet("color: #ccc;")
    soft_limit_checkbox.toggled.connect(lambda _checked=False: load_cell_actions.update_soft_limit(window))

    force_limit_spin = QDoubleSpinBox()
    force_limit_spin.setRange(0.1, 10000.0)
    force_limit_spin.setValue(DEFAULT_FORCE_SOFT_LIMIT_N)
    force_limit_spin.setSuffix(" N")
    force_limit_spin.setDecimals(1)
    force_limit_spin.setFixedWidth(100)
    force_limit_spin.setToolTip("이 힘을 넘으면 속도 0 으로 강제")
    force_limit_spin.valueChanged.connect(lambda _value: load_cell_actions.update_soft_limit(window))

    soft_start_spin = QSpinBox()
    soft_start_spin.setRange(10, 99)
    soft_start_spin.setValue(DEFAULT_FORCE_SOFT_START_PCT)
    soft_start_spin.setSuffix(" %")
    soft_start_spin.setFixedWidth(70)
    soft_start_spin.setToolTip("한계의 몇 %부터 감속 시작\n예: 70% → 70N부터 서서히 줄고 100N에서 0")
    soft_start_spin.valueChanged.connect(lambda _value: load_cell_actions.update_soft_limit(window))

    soft_status_label = QLabel("비활성")
    soft_status_label.setFont(QFont("Consolas", 10, QFont.Bold))
    soft_status_label.setStyleSheet("color: #555;")
    soft_status_label.setMinimumWidth(100)

    lc_row2.addWidget(force_abs_checkbox)
    lc_row2.addSpacing(8)
    lc_row2.addWidget(soft_limit_checkbox)
    lc_row2.addSpacing(8)
    lc_row2.addWidget(QLabel("한계:"))
    lc_row2.addWidget(force_limit_spin)
    lc_row2.addSpacing(6)
    lc_row2.addWidget(QLabel("감속 시작:"))
    lc_row2.addWidget(soft_start_spin)
    lc_row2.addSpacing(10)
    lc_row2.addWidget(soft_status_label)
    lc_row2.addStretch()

    lc_outer.addLayout(lc_row1)
    lc_outer.addLayout(lc_row1b)
    lc_outer.addLayout(lc_row2)

    window.load_cell_widgets = LoadCellWidgets(
        connect_button=connect_button,
        cal_button=cal_button,
        cal_ch0_button=cal_ch0_button,
        cal_ch1_button=cal_ch1_button,
        tare_ch0_button=tare_ch0_button,
        tare_ch1_button=tare_ch1_button,
        tare_all_button=tare_all_button,
        tare_reset_button=tare_reset_button,
        unit_combo=unit_combo,
        cal_label=cal_label,
        source_label=source_label,
        tare_status_label=tare_status_label,
        ch0_label=ch0_label,
        ch1_label=ch1_label,
        delta_label=delta_label,
        max_label=max_label,
        force_abs_checkbox=force_abs_checkbox,
        soft_limit_checkbox=soft_limit_checkbox,
        force_limit_spin=force_limit_spin,
        soft_start_spin=soft_start_spin,
        soft_status_label=soft_status_label,
    )
    return lc_frame

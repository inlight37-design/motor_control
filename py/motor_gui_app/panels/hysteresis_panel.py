# -*- coding: utf-8 -*-
"""히스테리시스 테스트 패널 생성 함수.

이 함수는 메인 윈도우 객체를 받아 히스테리시스 자동 테스트 위젯을
생성하고 HysteresisWidgets 컨테이너로 묶는다.
"""
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
)

from ..core.config import (
    DEFAULT_HYST_AMP_MM,
    DEFAULT_HYST_AMP_RPM,
    DEFAULT_HYST_FREQ_HZ,
    DEFAULT_HYST_LEAD_MM_REV,
    DEFAULT_HYST_MOTION_MODE,
    DEFAULT_HYST_OFFSET_RPM,
    DEFAULT_HYST_RECORD_CYCLES,
    DEFAULT_HYST_SETTLE_CYCLES,
    DEFAULT_HYST_UNIT,
    MAX_RPM,
)
from ..actions import hysteresis_actions
from ..ui.widget_groups import HysteresisWidgets


def build_hysteresis_panel(window) -> QFrame:
    """히스테리시스 테스트 패널을 만들고 UI 콜백을 연결."""
    panel = QFrame()
    panel.setFrameShape(QFrame.StyledPanel)
    panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    tab_hyst_layout = QVBoxLayout(panel)
    tab_hyst_layout.setSpacing(6)

    hyst_frame = QFrame()
    hyst_frame.setFrameShape(QFrame.StyledPanel)
    hyst_frame.setStyleSheet(
        "QFrame { background-color: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px; }"
        "QLabel { border: none; background: transparent; }"
    )
    hyst_outer = QVBoxLayout(hyst_frame)
    hyst_outer.setSpacing(8)

    hyst_row1 = QHBoxLayout()
    label_edit = QLineEdit()
    label_edit.setPlaceholderText("비우면 자동: 1hz_15n_10mm_10cyc_pos")
    label_edit.setToolTip(
        "비워두면 주파수_시작장력_진폭_기록cycle_모드 형식으로 자동 저장합니다.\n"
        "직접 입력하면 입력한 라벨을 그대로 사용합니다."
    )
    label_edit.setFixedWidth(220)

    freq_spin = QDoubleSpinBox()
    freq_spin.setRange(0.001, 50.0)
    freq_spin.setDecimals(3)
    freq_spin.setValue(DEFAULT_HYST_FREQ_HZ)
    freq_spin.setSingleStep(0.1)
    freq_spin.setSuffix(" Hz")
    freq_spin.setFixedWidth(100)

    motion_mode_combo = QComboBox()
    motion_mode_combo.addItem("속도 사인", "velocity")
    motion_mode_combo.addItem("위치 사인", "position")
    motion_mode_combo.setCurrentIndex(1 if DEFAULT_HYST_MOTION_MODE.startswith("pos") else 0)
    motion_mode_combo.setFixedWidth(95)
    motion_mode_combo.setToolTip(
        "속도 사인: 기존 CSV 속도 파형 / 위치 사인: 목표 위치 사인을 feed-forward로 추종"
    )

    amp_spin = QDoubleSpinBox()
    amp_spin.setRange(1.0, float(MAX_RPM))
    amp_spin.setDecimals(0)
    amp_spin.setSingleStep(10.0)
    amp_spin.setValue(DEFAULT_HYST_AMP_RPM)
    amp_spin.setSuffix(" rpm")
    amp_spin.setFixedWidth(100)

    amp_unit_combo = QComboBox()
    amp_unit_combo.addItem("rpm", "rpm")
    amp_unit_combo.addItem("mm", "mm")
    amp_unit_combo.setCurrentIndex(1 if DEFAULT_HYST_UNIT == "mm" else 0)
    amp_unit_combo.setFixedWidth(70)

    lead_spin = QDoubleSpinBox()
    lead_spin.setRange(0.001, 1000.0)
    lead_spin.setDecimals(3)
    lead_spin.setSingleStep(0.1)
    lead_spin.setValue(DEFAULT_HYST_LEAD_MM_REV)
    lead_spin.setSuffix(" mm/rev")
    lead_spin.setFixedWidth(120)
    lead_spin.setToolTip("리니어 액추에이터 리드값: 모터 1회전당 이동거리")

    offset_spin = QSpinBox()
    offset_spin.setRange(-MAX_RPM, MAX_RPM)
    offset_spin.setValue(DEFAULT_HYST_OFFSET_RPM)
    offset_spin.setSuffix(" rpm")
    offset_spin.setFixedWidth(100)

    hyst_row1.addWidget(QLabel("로그 라벨:"))
    hyst_row1.addWidget(label_edit)
    hyst_row1.addSpacing(10)
    hyst_row1.addWidget(QLabel("사인 주파수:"))
    hyst_row1.addWidget(freq_spin)
    hyst_row1.addWidget(motion_mode_combo)
    hyst_row1.addWidget(QLabel("진폭:"))
    hyst_row1.addWidget(amp_spin)
    hyst_row1.addWidget(amp_unit_combo)
    hyst_row1.addWidget(QLabel("리드:"))
    hyst_row1.addWidget(lead_spin)
    hyst_row1.addWidget(QLabel("오프셋:"))
    hyst_row1.addWidget(offset_spin)
    hyst_row1.addStretch()

    hyst_row2 = QHBoxLayout()
    settle_cycles_spin = QSpinBox()
    settle_cycles_spin.setRange(0, 20)
    settle_cycles_spin.setValue(DEFAULT_HYST_SETTLE_CYCLES)
    settle_cycles_spin.setSuffix(" cycles")
    settle_cycles_spin.setFixedWidth(110)

    record_cycles_spin = QSpinBox()
    record_cycles_spin.setRange(1, 200)
    record_cycles_spin.setValue(DEFAULT_HYST_RECORD_CYCLES)
    record_cycles_spin.setSuffix(" cycles")
    record_cycles_spin.setFixedWidth(110)

    duration_label = QLabel("--")
    duration_label.setStyleSheet("color: #57606a; font-weight: bold;")

    start_button = QPushButton("테스트 시작")
    start_button.setStyleSheet(
        "background-color: #0969da; color: white; font-weight: bold; padding: 6px 12px;"
    )
    start_button.clicked.connect(lambda _checked=False: hysteresis_actions.start_test(window))

    abort_button = QPushButton("테스트 중지")
    abort_button.setStyleSheet(
        "background-color: #6e7781; color: white; font-weight: bold; padding: 6px 12px;"
    )
    abort_button.setEnabled(False)
    abort_button.clicked.connect(lambda checked=False: hysteresis_actions.abort_test(window, checked=checked))

    status_label = QLabel("대기")
    status_label.setStyleSheet("color: #57606a; font-weight: bold;")

    hyst_row2.addWidget(QLabel("안정화:"))
    hyst_row2.addWidget(settle_cycles_spin)
    hyst_row2.addWidget(QLabel("기록:"))
    hyst_row2.addWidget(record_cycles_spin)
    hyst_row2.addSpacing(10)
    hyst_row2.addWidget(QLabel("예상 시간:"))
    hyst_row2.addWidget(duration_label)
    hyst_row2.addSpacing(10)
    hyst_row2.addWidget(start_button)
    hyst_row2.addWidget(abort_button)
    hyst_row2.addWidget(status_label)
    hyst_row2.addStretch()

    motion_label = QLabel("--")
    motion_label.setStyleSheet("color: #8a5a00; font-size: 11px; font-weight: bold;")

    hyst_outer.addLayout(hyst_row1)
    hyst_outer.addLayout(hyst_row2)
    hyst_outer.addWidget(motion_label)
    tab_hyst_layout.addWidget(hyst_frame)
    tab_hyst_layout.addStretch()

    window.hysteresis_widgets = HysteresisWidgets(
        label_edit=label_edit,
        freq_spin=freq_spin,
        motion_mode_combo=motion_mode_combo,
        amp_spin=amp_spin,
        amp_unit_combo=amp_unit_combo,
        lead_spin=lead_spin,
        offset_spin=offset_spin,
        settle_cycles_spin=settle_cycles_spin,
        record_cycles_spin=record_cycles_spin,
        duration_label=duration_label,
        start_button=start_button,
        abort_button=abort_button,
        status_label=status_label,
        motion_label=motion_label,
    )

    for widget in [
        freq_spin,
        amp_spin,
        lead_spin,
        offset_spin,
        settle_cycles_spin,
        record_cycles_spin,
    ]:
        widget.valueChanged.connect(lambda _value: hysteresis_actions.update_duration_label(window))
    window.force_control_widgets.target_spin.valueChanged.connect(
        lambda _value: hysteresis_actions.update_duration_label(window)
    )
    amp_unit_combo.currentIndexChanged.connect(lambda _index: hysteresis_actions.on_amp_unit_changed(window))
    motion_mode_combo.currentIndexChanged.connect(lambda _index: hysteresis_actions.on_motion_mode_changed(window))
    hysteresis_actions.on_amp_unit_changed(window)
    hysteresis_actions.on_motion_mode_changed(window)
    amp_spin.setValue(DEFAULT_HYST_AMP_MM if DEFAULT_HYST_UNIT == "mm" else DEFAULT_HYST_AMP_RPM)
    hysteresis_actions.update_duration_label(window)

    return panel

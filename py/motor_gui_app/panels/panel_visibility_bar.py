# -*- coding: utf-8 -*-
"""제어 패널 표시/숨김 체크박스 영역 생성 함수."""
from PyQt5.QtWidgets import QCheckBox, QHBoxLayout, QLabel

from ..ui.widget_groups import PanelVisibilityWidgets


def build_panel_visibility_bar(window) -> QHBoxLayout:
    """필요한 패널을 동시에 펼쳐 볼 수 있는 표시 체크박스 행을 생성."""
    row = QHBoxLayout()
    row.addWidget(QLabel("패널 표시:"))

    motion_checkbox = QCheckBox("속도/위치/토크")
    motion_checkbox.setChecked(True)
    force_checkbox = QCheckBox("로드셀/힘제어")
    force_checkbox.setChecked(True)
    hysteresis_checkbox = QCheckBox("히스테리시스")
    hysteresis_checkbox.setChecked(True)
    utility_checkbox = QCheckBox("스크립트/로깅")
    utility_checkbox.setChecked(False)

    window.panel_visibility_widgets = PanelVisibilityWidgets(
        motion_checkbox=motion_checkbox,
        force_checkbox=force_checkbox,
        hysteresis_checkbox=hysteresis_checkbox,
        utility_checkbox=utility_checkbox,
    )

    for checkbox in [
        motion_checkbox,
        force_checkbox,
        hysteresis_checkbox,
        utility_checkbox,
    ]:
        checkbox.setStyleSheet("font-weight: bold;")
        row.addWidget(checkbox)
    row.addStretch()
    return row

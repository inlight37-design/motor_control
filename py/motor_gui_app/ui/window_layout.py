# -*- coding: utf-8 -*-
"""메인 윈도우의 패널과 그래프 UI 조립 헬퍼."""
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QFrame, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..panels.hysteresis_panel import build_hysteresis_panel
from ..panels.load_cell_panel import build_load_cell_panel
from ..panels.force_control_panel import build_force_control_panel
from ..panels.motion_control_panel import build_motion_control_panel
from ..panels.script_logging_panel import build_script_logging_panel
from ..panels.top_status_panel import build_top_status_area
from ..panels.log_viewer_panel import build_log_viewer_panel
from ..panels.emergency_stop_panel import build_emergency_stop_row
from ..panels.panel_visibility_bar import build_panel_visibility_bar
from ..panels.graph_panel import build_graph_panel
from .widget_groups import PanelContainers


def build_main_ui(window, ifaces: List[str], default_iface: str):
    """상단 상태 영역, 제어 패널, 그래프를 순서대로 조립."""
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    window.setCentralWidget(scroll)

    central = QWidget()
    scroll.setWidget(central)
    layout = QVBoxLayout(central)
    layout.setSpacing(4)

    build_top_status_area(window, layout, ifaces, default_iface)
    layout.addWidget(build_log_viewer_panel(window))
    layout.addLayout(build_emergency_stop_row(window))
    layout.addLayout(build_panel_visibility_bar(window))

    motion_panel = build_motion_control_panel(window)
    layout.addWidget(motion_panel)

    force_panel = QFrame()
    force_panel.setFrameShape(QFrame.StyledPanel)
    force_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    force_layout = QVBoxLayout(force_panel)
    force_layout.setSpacing(4)

    force_layout.addWidget(build_load_cell_panel(window))
    force_layout.addWidget(build_force_control_panel(window))
    force_layout.addStretch()
    layout.addWidget(force_panel)

    hysteresis_panel = build_hysteresis_panel(window)
    layout.addWidget(hysteresis_panel)

    utility_panel = build_script_logging_panel(window)
    layout.addWidget(utility_panel)

    window.panel_containers = PanelContainers(
        motion_panel=motion_panel,
        force_panel=force_panel,
        hysteresis_panel=hysteresis_panel,
        utility_panel=utility_panel,
    )

    layout.addWidget(build_graph_panel(window))

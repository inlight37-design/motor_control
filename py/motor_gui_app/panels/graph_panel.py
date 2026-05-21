# -*- coding: utf-8 -*-
"""실시간 속도/RT 주기 그래프 패널 생성 함수."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QSizePolicy, QSplitter
import pyqtgraph as pg

from ..ui.widget_groups import GraphWidgets


def build_graph_panel(window) -> QSplitter:
    """속도 그래프와 RT 루프 주기 그래프를 만들고 curve 핸들을 graph_widgets에 보관."""
    splitter = QSplitter(Qt.Vertical)
    splitter.setMinimumWidth(0)

    # 속도 그래프: 목표 RPM과 실측 RPM을 함께 표시한다.
    speed_plot = pg.PlotWidget(title="모터 속도 (RPM)")
    speed_plot.setMinimumWidth(0)
    speed_plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    speed_plot.setBackground("w")
    speed_plot.showGrid(x=True, y=True)
    speed_plot.setClipToView(True)
    speed_plot.setDownsampling(auto=True, mode="peak")
    speed_plot.setLabel("left", "속도", units="RPM")
    speed_plot.setLabel("bottom", "시간", units="sec")
    speed_plot.addLegend()
    target_curve = speed_plot.plot(
        pen=pg.mkPen("r", style=Qt.DashLine, width=2),
        name="목표",
    )
    actual_curve = speed_plot.plot(
        pen=pg.mkPen("b", width=3),
        name="실제",
    )
    splitter.addWidget(speed_plot)

    # RT 루프 주기 그래프: 1ms 기준선과 실측 주기를 표시한다.
    rt_plot = pg.PlotWidget(title="RT 제어루프 주기 (μs) — 목표 1000μs")
    rt_plot.setMinimumWidth(0)
    rt_plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    rt_plot.setBackground("#111")
    rt_plot.showGrid(x=True, y=True, alpha=0.5)
    rt_plot.setClipToView(True)
    rt_plot.setDownsampling(auto=True, mode="peak")
    rt_plot.setLabel("left", "주기", units="μs")
    rt_plot.setLabel("bottom", "시간", units="sec")
    rt_plot.setYRange(800, 1200)
    rt_plot.addItem(
        pg.InfiniteLine(pos=1000, angle=0, pen=pg.mkPen("g", width=1, style=Qt.DashLine))
    )
    rt_dt_curve = rt_plot.plot(pen=pg.mkPen("#00ccff", width=2))
    splitter.addWidget(rt_plot)

    window.graph_widgets = GraphWidgets(
        speed_plot=speed_plot,
        rt_plot=rt_plot,
        target_curve=target_curve,
        actual_curve=actual_curve,
        rt_dt_curve=rt_dt_curve,
    )

    return splitter

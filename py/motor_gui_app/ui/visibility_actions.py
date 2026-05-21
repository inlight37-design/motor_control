# -*- coding: utf-8 -*-
"""패널과 그래프 표시/숨김 동작."""


def toggle_panel_visibility(window):
    """선택한 제어 패널만 펼쳐서 필요한 화면 조합을 동시에 볼 수 있게 한다."""
    checkboxes = window.panel_visibility_widgets.checkboxes()
    panels = window.panel_containers.visibility_pairs()
    for checkbox, panel in zip(checkboxes, panels):
        panel.setVisible(checkbox.isChecked())


def toggle_graph_visibility(window):
    """속도/RT 그래프 표시 토글. 숨기면 렌더링 부하가 줄어든다."""
    top_status = window.top_status_widgets
    widgets = window.graph_widgets
    show_speed = top_status.show_speed_checkbox.isChecked()
    show_rt = top_status.show_rt_checkbox.isChecked()
    widgets.speed_plot.setVisible(show_speed)
    widgets.rt_plot.setVisible(show_rt)

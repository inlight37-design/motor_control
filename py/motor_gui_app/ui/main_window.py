# -*- coding: utf-8 -*-
"""패널을 조립하고 앱 전체 이벤트를 연결하는 PyQt 메인 윈도우."""
from typing import List

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QMainWindow

from . import graph_update
from ..actions import linear_encoder_actions
from ..actions import load_cell_actions
from . import status_update
from ..actions import system_actions
from . import log_view_actions
from .session_properties import SessionFlagProperties
from . import window_layout
from . import runtime_init


class MasterWindow(QMainWindow, SessionFlagProperties):
    lc_connect_result_signal = pyqtSignal(list)
    linear_encoder_connect_result_signal = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        runtime_init.configure_window(self)
        ifaces, default_iface = runtime_init.init_runtime_objects(self)
        runtime_init.init_state_flags(self)
        self.init_ui(ifaces, default_iface)
        self.lc_connect_result_signal.connect(lambda channels: load_cell_actions.on_lc_connect_result(self, channels))
        self.linear_encoder_connect_result_signal.connect(
            lambda ok, msg: linear_encoder_actions.on_linear_encoder_connect_result(self, ok, msg)
        )
        load_cell_actions.sync_force_abs_mode(self, log=False)
        runtime_init.connect_runtime_signals(self)
        runtime_init.start_runtime_loops(self)

    # ══════════════════════════════════════════════════════════════════
    # UI 초기화 — 모든 위젯을 구성하는 대형 메서드
    # ══════════════════════════════════════════════════════════════════
    def init_ui(self, ifaces: List[str], default_iface: str):
        window_layout.build_main_ui(self, ifaces, default_iface)

    # ═════════════════════════════════════════════════════════════════
    # 그래프 업데이트 — QTimer(33ms)에서 호출 (~30fps)
    # ═════════════════════════════════════════════════════════════════
    def update_graphs(self):
        """주기적 그래프 + 진단 라벨 갱신 (~30fps).

        deque에서 데이터를 꺼내 NumPy 배열에 쓰고, PyQtGraph에 전달한다.
        NumPy 고정 배열 + 슬라이스 전달로 메모리 할당 없이 효율적으로 렌더링.
        """
        is_speed_mode = (self.position_torque_widgets.mode_combo.currentIndex() == 0)
        graph_update.update_speed_graph(self, is_speed_mode=is_speed_mode)
        graph_update.update_rt_graph(self)
        status_update.update_status_labels(self)

    # ═════════════════════════════════════════════════════════════════
    # 로그 시스템 — 버퍼링 + 주기적 flush로 UI 블로킹 방지
    # ═════════════════════════════════════════════════════════════════
    def update_log(self, msg: str):
        log_view_actions.update_log(self, msg)

    def flush_log_buffer(self):
        log_view_actions.flush_log_buffer(self)

    # ═════════════════════════════════════════════════════════════════
    # 종료 처리 — 모든 리소스를 순서대로 정리
    # ═════════════════════════════════════════════════════════════════
    def closeEvent(self, event):
        system_actions.close_event(self, event)


# ══════════════════════════════════════════════════════════════════════
# 프로그램 진입점
# ══════════════════════════════════════════════════════════════════════

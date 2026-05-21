# -*- coding: utf-8 -*-
"""MasterWindow가 들고 있는 UI 실행 상태."""
from dataclasses import dataclass, field


@dataclass
class WindowState:
    """위젯 핸들이 아닌 GUI 실행 상태를 모아 둔다."""

    loaded_script_path: str | None = None
    pos_offset: int = 0
    syncing_pos_units: bool = False
    ext_tare_n: list[float] = field(default_factory=lambda: [0.0, 0.0])
    force_ctrl_mode: str = "pid"
    force_abs_mode: bool = False
    prev_lc_unit: str = "N"
    last_logged_err: int = 0

    def reset_runtime(self):
        """앱 시작 시 실험 실행에 따라 바뀌는 보조 상태를 초기화."""
        self.loaded_script_path = None
        self.pos_offset = 0
        self.syncing_pos_units = False
        self.ext_tare_n = [0.0, 0.0]
        self.force_ctrl_mode = "pid"
        self.last_logged_err = 0
        self.prev_lc_unit = "N"

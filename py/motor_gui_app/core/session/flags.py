# -*- coding: utf-8 -*-
"""현재 GUI/CLI 세션에서 실행 중인 작업 상태.

이 객체는 제어 명령을 보내거나 UI를 직접 갱신하지 않는다. 여러 액션이 공유하는
"지금 무엇이 실행 중인가" 상태만 보관해서, 나중에 GUI 없이 CLI에서 같은 흐름을
쓸 때도 동일한 상태 모델을 재사용할 수 있게 한다.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SessionFlags:
    """모터 세션 실행 상태 플래그."""

    motor_running: bool = False
    script_running: bool = False
    waveform_running: bool = False
    manual_csv_logging_active: bool = False
    force_control_running: bool = False
    hyst_test_running: bool = False
    hyst_log_path: Optional[Path] = None
    hyst_logging_active: bool = False
    hyst_test_token: int = 0

    def reset_runtime(self) -> None:
        """앱 시작/재초기화 시 런타임 상태를 초기값으로 되돌린다."""
        self.motor_running = False
        self.script_running = False
        self.waveform_running = False
        self.manual_csv_logging_active = False
        self.force_control_running = False
        self.hyst_test_running = False
        self.hyst_log_path = None
        self.hyst_logging_active = False
        self.hyst_test_token = 0

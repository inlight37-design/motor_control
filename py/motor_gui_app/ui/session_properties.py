# -*- coding: utf-8 -*-
"""MasterWindow가 노출하는 세션 실행 상태 property 묶음."""
from pathlib import Path
from typing import Optional


class SessionFlagProperties:
    """기존 window.xxx 상태 접근을 유지하면서 저장소는 session.flags로 모은다."""

    @property
    def motor_running(self) -> bool:
        return self.session.flags.motor_running

    @motor_running.setter
    def motor_running(self, value: bool):
        self.session.flags.motor_running = bool(value)

    @property
    def script_running(self) -> bool:
        return self.session.flags.script_running

    @script_running.setter
    def script_running(self, value: bool):
        self.session.flags.script_running = bool(value)

    @property
    def waveform_running(self) -> bool:
        return self.session.flags.waveform_running

    @waveform_running.setter
    def waveform_running(self, value: bool):
        self.session.flags.waveform_running = bool(value)

    @property
    def manual_csv_logging_active(self) -> bool:
        return self.session.flags.manual_csv_logging_active

    @manual_csv_logging_active.setter
    def manual_csv_logging_active(self, value: bool):
        self.session.flags.manual_csv_logging_active = bool(value)

    @property
    def force_control_running(self) -> bool:
        return self.session.flags.force_control_running

    @force_control_running.setter
    def force_control_running(self, value: bool):
        self.session.flags.force_control_running = bool(value)

    @property
    def hyst_test_running(self) -> bool:
        return self.session.flags.hyst_test_running

    @hyst_test_running.setter
    def hyst_test_running(self, value: bool):
        self.session.flags.hyst_test_running = bool(value)

    @property
    def hyst_log_path(self) -> Optional[Path]:
        return self.session.flags.hyst_log_path

    @hyst_log_path.setter
    def hyst_log_path(self, value: Optional[Path]):
        self.session.flags.hyst_log_path = value

    @property
    def hyst_logging_active(self) -> bool:
        return self.session.flags.hyst_logging_active

    @hyst_logging_active.setter
    def hyst_logging_active(self, value: bool):
        self.session.flags.hyst_logging_active = bool(value)

    @property
    def hyst_test_token(self) -> int:
        return self.session.flags.hyst_test_token

    @hyst_test_token.setter
    def hyst_test_token(self, value: int):
        self.session.flags.hyst_test_token = int(value)

# -*- coding: utf-8 -*-
"""Latest motor, realtime, and sensor feedback values."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


@dataclass
class MotorFeedback:
    """Latest EPOS motor feedback exposed by MonitorThread."""

    target_rpm: int = 0
    status_word: int = 0
    error_code: int = 0
    memorized_error_code: int = 0
    memorized_error_time: float = 0.0
    actual_position_ticks: int = 0
    actual_torque_permille: int = 0

    def is_fault(self) -> bool:
        return (int(self.status_word) & 0x0008) != 0

    def is_enabled(self) -> bool:
        return (int(self.status_word) & 0x006F) == 0x0027


@dataclass
class RealtimeDiagnostics:
    """Latest realtime loop diagnostics from the C++ control node."""

    jitter_us: int = 0
    overrun_count: int = 0
    wkc_error_count: int = 0
    dt_mean_us: int = 0
    jitter_mean_us: int = 0
    jitter_max_us: int = 0
    diag_overrun_count: int = 0
    diag_wkc_error_count: int = 0


@dataclass
class LoadCellFeedback:
    """Latest load-cell topic feedback."""

    forces_n: list[float] = field(default_factory=lambda: [math.nan, math.nan])
    safety_tripped: bool = False
    last_recv_t: float = 0.0

    def force_n(self, channel: int) -> float:
        return float(self.forces_n[_channel_index(channel)])

    def set_force_n(self, channel: int, value: float, recv_t: float | None = None) -> None:
        self.forces_n[_channel_index(channel)] = float(value)
        self.last_recv_t = time.time() if recv_t is None else float(recv_t)

    def fresh(self, max_age_s: float = 1.0, now: float | None = None) -> bool:
        current_time = time.time() if now is None else float(now)
        return (current_time - float(self.last_recv_t)) < float(max_age_s)


@dataclass
class LinearEncoderFeedback:
    """Latest linear encoder topic feedback."""

    count: int = 0
    mm: float = math.nan
    last_recv_t: float = 0.0

    def fresh(self, max_age_s: float = 1.0, now: float | None = None) -> bool:
        current_time = time.time() if now is None else float(now)
        return (current_time - float(self.last_recv_t)) < float(max_age_s)


def _channel_index(channel: int) -> int:
    return 0 if int(channel) == 0 else 1

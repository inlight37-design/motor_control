# -*- coding: utf-8 -*-
"""MonitorThread 값을 읽기 전용 API로 감싼 상태 조회 객체."""
import math
import time


class StateView:
    """C++ 노드와 센서 피드백의 최신값을 읽는 얇은 facade.

    ControlClient가 명령 전송만 담당한다면, StateView는 monitor의 public 값을
    읽기 좋은 이름으로 제공한다. 여기서는 monitor 값을 수정하지 않는다.
    """

    def __init__(self, monitor):
        self._monitor = monitor

    @property
    def _motor(self):
        return self._monitor.motor_feedback

    @property
    def _realtime(self):
        return self._monitor.realtime_diagnostics

    @property
    def _load_cell(self):
        return self._monitor.load_cell_feedback

    @property
    def _linear_encoder(self):
        return self._monitor.linear_encoder_feedback

    def status_word(self) -> int:
        return int(self._motor.status_word)

    def error_code(self) -> int:
        return int(self._motor.error_code)

    def memorized_error(self) -> tuple[int, float]:
        """Return the recently seen error code kept briefly after auto reset."""
        return int(self._motor.memorized_error_code), float(self._motor.memorized_error_time)

    def clear_memorized_error(self) -> None:
        """Clear the recently seen error code display state."""
        self._motor.memorized_error_code = 0
        self._motor.memorized_error_time = 0.0

    def motor_state_text(self) -> str:
        return self._monitor.get_motor_state_str()

    def is_fault(self) -> bool:
        return self._motor.is_fault()

    def is_enabled(self) -> bool:
        return self._motor.is_enabled()

    def actual_position_ticks(self) -> int:
        return int(self._motor.actual_position_ticks)

    def actual_torque_permille(self) -> int:
        return int(self._motor.actual_torque_permille)

    def target_rpm(self) -> int:
        return int(self._motor.target_rpm)

    def rt_jitter_us(self) -> int:
        return int(self._realtime.jitter_us)

    def rt_overrun_count(self) -> int:
        return int(self._realtime.overrun_count)

    def rt_wkc_error_count(self) -> int:
        return int(self._realtime.wkc_error_count)

    def force_n(self, channel: int, tare_offsets_n=None) -> float:
        """로드셀 채널 힘[N]을 반환. tare_offsets_n을 주면 표시용 tare를 적용한다."""
        value = self._load_cell.force_n(channel)
        if tare_offsets_n is not None and not math.isnan(value):
            value -= float(tare_offsets_n[int(channel)])
        return value

    def load_cell_fresh(self, max_age_s: float = 1.0) -> bool:
        return self._load_cell.fresh(max_age_s)

    def linear_count(self) -> int:
        return int(self._linear_encoder.count)

    def linear_mm(self) -> float:
        return float(self._linear_encoder.mm)

    def linear_fresh(self, max_age_s: float = 1.0) -> bool:
        return self._linear_encoder.fresh(max_age_s)

    def wait_until_enabled(self, timeout_s: float = 5.0, poll_s: float = 0.05) -> bool:
        """CLI용 간단한 폴링 헬퍼. GUI는 Qt signal을 사용한다."""
        deadline = time.time() + float(timeout_s)
        while time.time() < deadline:
            if self.is_enabled():
                return True
            time.sleep(float(poll_s))
        return self.is_enabled()

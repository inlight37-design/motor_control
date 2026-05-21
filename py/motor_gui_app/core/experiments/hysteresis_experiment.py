# -*- coding: utf-8 -*-
"""히스테리시스 테스트 실행 흐름.

이 모듈은 PyQt 위젯을 직접 알지 않는다. C++ 노드에 예약 명령을 보내고,
안정화/기록/종료 상태 전환을 scheduler와 callback으로 표현한다. GUI는
callback에서 라벨을 바꾸고, CLI는 같은 callback에서 print만 하면 된다.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..config import MAX_RPM
from ..control_client import HysteresisPositionSettings, HysteresisVelocitySettings


Scheduler = Callable[[int, Callable[[], None]], None]
StatusCallback = Callable[["HysteresisStatus"], None]


@dataclass(frozen=True)
class HysteresisExperimentSettings:
    """히스테리시스 테스트 한 번의 실행 조건."""

    motion_mode: str
    freq_hz: float
    amp_rpm: float
    offset_rpm: float
    settle_cycles: int
    record_cycles: int
    log_path: Path | str
    amp_ticks: float = 0.0
    max_tps: float = 0.0
    requested_amp: float = 0.0
    lead_mm_rev: float = 0.0
    amp_unit: str = "rpm"
    start_lead_ms: int = 300
    finish_lead_ms: int = 300

    @property
    def period_s(self) -> float:
        return 1.0 / max(float(self.freq_hz), 1.0e-9)

    @property
    def settle_ms(self) -> int:
        return int(max(0.0, int(self.settle_cycles) * self.period_s) * 1000)

    @property
    def record_ms(self) -> int:
        return int(max(0.001, int(self.record_cycles) * self.period_s) * 1000)

    @property
    def is_position(self) -> bool:
        return str(self.motion_mode).lower() == "position"


@dataclass(frozen=True)
class HysteresisStatus:
    """실험 상태 변경 이벤트."""

    phase: str
    token: int
    settings: HysteresisExperimentSettings
    log_path: Path | str | None = None
    reason: str = ""


class HysteresisPreconditionError(RuntimeError):
    """히스테리시스 실험을 시작할 수 없을 때 던지는 명시적 예외."""


@dataclass(frozen=True)
class HysteresisPreconditions:
    """GUI/CLI 실행 환경별 히스테리시스 시작 조건."""

    require_motor_running: bool = False
    require_idle_session: bool = True
    min_velocity_amp_rpm: float = 0.5
    min_position_amp_ticks: float = 1.0
    max_rpm: float = float(MAX_RPM)


class HysteresisExperiment:
    """히스테리시스 테스트 상태 전이를 담당하는 작은 실행기."""

    def __init__(
        self,
        control,
        flags,
        scheduler: Scheduler,
        preconditions: Optional[HysteresisPreconditions] = None,
    ):
        self._control = control
        self._flags = flags
        self._scheduler = scheduler
        self._preconditions = preconditions or HysteresisPreconditions()
        self._on_status: StatusCallback = lambda _status: None
        self._active_settings: Optional[HysteresisExperimentSettings] = None

    def start(self, settings: HysteresisExperimentSettings, on_status: Optional[StatusCallback] = None) -> int:
        """테스트를 시작하고 토큰을 반환."""
        self._validate_preconditions(settings)

        self._on_status = on_status or (lambda _status: None)
        self._active_settings = settings
        self._flags.hyst_log_path = Path(settings.log_path)
        self._flags.hyst_logging_active = True
        self._flags.hyst_test_running = True
        self._flags.waveform_running = True
        self._flags.hyst_test_token += 1
        token = self._flags.hyst_test_token

        try:
            if settings.is_position:
                self._control.start_hysteresis_position(
                    HysteresisPositionSettings(
                        freq_hz=settings.freq_hz,
                        amp_ticks=settings.amp_ticks,
                        offset_ticks=0.0,
                        max_tps=settings.max_tps,
                        settle_cycles=settings.settle_cycles,
                        record_cycles=settings.record_cycles,
                        log_path=settings.log_path,
                    )
                )
            else:
                self._control.start_hysteresis_velocity(
                    HysteresisVelocitySettings(
                        freq_hz=settings.freq_hz,
                        amp_rpm=settings.amp_rpm,
                        offset_rpm=settings.offset_rpm,
                        settle_cycles=settings.settle_cycles,
                        record_cycles=settings.record_cycles,
                        log_path=settings.log_path,
                    )
                )
        except Exception:
            self._active_settings = None
            self._flags.hyst_log_path = None
            self._flags.hyst_logging_active = False
            self._flags.hyst_test_running = False
            self._flags.waveform_running = False
            raise

        self._emit("armed", token, settings)
        self._scheduler(
            settings.start_lead_ms + settings.settle_ms,
            lambda token=token, settings=settings: self.begin_logging(token, settings.record_ms),
        )
        return token

    def _validate_preconditions(self, settings: HysteresisExperimentSettings) -> None:
        """GUI/CLI가 공유하는 시작 전 안전 조건을 확인."""
        preconditions = self._preconditions
        if self._flags.hyst_test_running:
            raise HysteresisPreconditionError("히스테리시스 테스트가 이미 실행 중입니다.")
        if preconditions.require_motor_running and not self._flags.motor_running:
            raise HysteresisPreconditionError("먼저 모터 노드를 시작해 주세요.")
        if preconditions.require_idle_session:
            if self._flags.script_running or self._flags.waveform_running:
                raise HysteresisPreconditionError("실행 중인 스크립트/파형을 먼저 정지해 주세요.")
            if self._flags.manual_csv_logging_active:
                raise HysteresisPreconditionError("CSV 로깅을 먼저 중지해 주세요.")
            if self._flags.force_control_running:
                raise HysteresisPreconditionError("힘 제어를 먼저 정지해 주세요.")

        if float(settings.freq_hz) <= 0.0:
            raise HysteresisPreconditionError("주파수는 0보다 커야 합니다.")
        if int(settings.settle_cycles) < 0:
            raise HysteresisPreconditionError("안정화 cycle은 0 이상이어야 합니다.")
        if int(settings.record_cycles) <= 0:
            raise HysteresisPreconditionError("기록 cycle은 1 이상이어야 합니다.")
        if not str(settings.log_path):
            raise HysteresisPreconditionError("로그 경로가 비어 있습니다.")

        amp_rpm = abs(float(settings.amp_rpm))
        if not settings.is_position and amp_rpm < float(preconditions.min_velocity_amp_rpm):
            raise HysteresisPreconditionError(
                "변환된 진폭이 너무 작아 모터 속도 명령으로 표현하기 어렵습니다. "
                "진폭, 주파수 또는 리드값을 조정해 주세요."
            )
        if amp_rpm > float(preconditions.max_rpm):
            raise HysteresisPreconditionError(
                f"입력한 조건은 약 {amp_rpm:.1f} rpm이 필요합니다. "
                f"현재 안전 한계는 {preconditions.max_rpm:.0f} rpm이므로 "
                "진폭/주파수를 줄이거나 리드값을 확인해 주세요."
            )
        if settings.is_position and abs(float(settings.amp_ticks)) < float(preconditions.min_position_amp_ticks):
            raise HysteresisPreconditionError(
                "변환된 위치 진폭이 1 tick보다 작습니다. 진폭 또는 리드값을 조정해 주세요."
            )

    def begin_logging(self, token: int, record_ms: Optional[int] = None) -> None:
        """안정화 구간 후 기록 구간 상태로 전환."""
        if not self._is_current(token):
            return
        settings = self._active_settings
        if settings is None:
            self.abort("설정 없음")
            return
        if not self._flags.hyst_log_path:
            self.abort("로그 경로 없음")
            return

        self._flags.hyst_logging_active = True
        self._emit("logging", token, settings)
        delay_ms = int(record_ms if record_ms is not None else settings.record_ms)
        self._scheduler(
            delay_ms + settings.finish_lead_ms,
            lambda token=token: self.finish(token),
        )

    def finish(self, token: Optional[int] = None) -> None:
        """테스트를 정상 종료."""
        if token is not None and not self._is_current(token):
            return
        if not self._flags.hyst_test_running:
            return

        settings = self._active_settings or self._empty_settings()
        if self._flags.hyst_logging_active:
            self._control.stop_csv_logging()
        self._control.stop_hysteresis()
        self._flags.waveform_running = False
        self._flags.hyst_test_running = False
        self._flags.hyst_logging_active = False
        self._emit("done", self._flags.hyst_test_token, settings)

    def abort(self, reason: str = "사용자 중지") -> None:
        """테스트를 즉시 중지하고 지연 콜백을 무효화."""
        if not self._flags.hyst_test_running:
            return

        self._flags.hyst_test_token += 1
        token = self._flags.hyst_test_token
        settings = self._active_settings or self._empty_settings()
        if self._flags.hyst_logging_active:
            self._control.stop_csv_logging()
        self._control.stop_hysteresis()
        self._flags.waveform_running = False
        self._flags.hyst_test_running = False
        self._flags.hyst_logging_active = False
        self._emit("aborted", token, settings, reason=reason)

    def _is_current(self, token: int) -> bool:
        return token == self._flags.hyst_test_token and self._flags.hyst_test_running

    def _emit(
        self,
        phase: str,
        token: int,
        settings: HysteresisExperimentSettings,
        reason: str = "",
    ) -> None:
        self._on_status(
            HysteresisStatus(
                phase=phase,
                token=token,
                settings=settings,
                log_path=self._flags.hyst_log_path,
                reason=reason,
            )
        )

    @staticmethod
    def _empty_settings() -> HysteresisExperimentSettings:
        return HysteresisExperimentSettings(
            motion_mode="velocity",
            freq_hz=1.0,
            amp_rpm=0.0,
            offset_rpm=0.0,
            settle_cycles=0,
            record_cycles=0,
            log_path="",
        )

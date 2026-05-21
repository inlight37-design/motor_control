# -*- coding: utf-8 -*-
"""GUI/CLI가 함께 사용할 수 있는 고수준 제어 API.

큰 흐름
-------
  UI 버튼 또는 CLI 명령
      -> ControlClient 메서드 호출
          -> command_builders가 ROS2 명령 객체/문자열 생성
              -> CommandThread 큐에 전달
                  -> C++ epos_motor_node가 토픽으로 수신

이 파일은 PyQt 위젯을 직접 알지 않는다. 숫자, 문자열, dataclass만 받아서
제어 명령 순서를 표현한다. 그래서 나중에 GUI가 아닌 터미널 CLI에서도 같은
흐름을 재사용할 수 있다.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .command_builders import (
    make_force_alpha_cmd,
    make_force_abs_cmd,
    make_force_direction_cmd,
    make_force_feedback_cmd,
    make_force_limit_cmd,
    make_force_max_rpm_cmd,
    make_force_pid_cmd,
    make_force_start_cmd,
    make_force_stop_cmd,
    make_force_tanh_cmd,
    make_force_tare_offset_cmd,
    make_force_tare_reset_cmd,
    make_force_target_cmd,
    make_hyst_position_cmd,
    make_hyst_velocity_cmd,
    make_waveform_start_cmd,
    make_waveform_stop_cmd,
)


@dataclass(frozen=True)
class ForcePidSettings:
    kp: float
    ki: float
    kd: float
    output_alpha: float


@dataclass(frozen=True)
class ForceTanhSettings:
    sensitivity_n: float
    deadband_n: float
    output_alpha: float


@dataclass(frozen=True)
class ForceControlSettings:
    target_n: float
    max_rpm: float
    direction: int
    feedback: str
    mode: str = "pid"
    pid: Optional[ForcePidSettings] = None
    tanh: Optional[ForceTanhSettings] = None


@dataclass(frozen=True)
class WaveformSettings:
    waveform_type: str
    freq_hz: float
    amp_rpm: float
    offset_rpm: float
    freq_end_hz: float = 0.0
    duration_s: float = 0.0

    def command_text(self) -> str:
        token = str(self.waveform_type).lower()
        if token == "chirp":
            return (
                f"chirp {self.freq_hz} {self.freq_end_hz} "
                f"{self.amp_rpm} {self.offset_rpm} {self.duration_s}"
            )
        return f"{token} {self.freq_hz} {self.amp_rpm} {self.offset_rpm}"


@dataclass(frozen=True)
class HysteresisVelocitySettings:
    freq_hz: float
    amp_rpm: float
    offset_rpm: float
    settle_cycles: int
    record_cycles: int
    log_path: Path | str


@dataclass(frozen=True)
class HysteresisPositionSettings:
    freq_hz: float
    amp_ticks: float
    offset_ticks: float
    max_tps: float
    settle_cycles: int
    record_cycles: int
    log_path: Path | str


class ControlClient:
    """C++ 제어 노드에 보낼 명령 순서를 한곳에 모은 얇은 컨트롤러."""

    def __init__(self, commander):
        self.commander = commander

    # ------------------------------------------------------------------
    # 수동 모터 제어
    # ------------------------------------------------------------------
    def set_operation_mode(self, mode: int) -> None:
        """EPOS 운전 모드 변경. 8=position, 9=velocity, 10=torque."""
        self.commander.set_op_mode(int(mode))

    def set_accel_limit(self, rpm_per_s: float) -> None:
        """속도 명령 slew-rate 제한을 설정."""
        self.commander.set_accel(float(rpm_per_s))

    def set_rpm_limit(self, rpm_limit: float) -> None:
        """수동/스크립트 속도 명령 절대 한계를 설정."""
        self.commander.set_rpm_limit(float(rpm_limit))

    def set_manual_rpm(self, rpm: float) -> None:
        """수동 속도 명령을 설정."""
        self.commander.set_manual_target_rpm(float(rpm))

    def set_position_speed_limit(self, ticks_per_s: int | float) -> None:
        """위치 제어 이동 속도 한계를 설정."""
        self.commander.set_pos_speed_limit(int(ticks_per_s))

    def move_to_position_ticks(self, target_ticks: int | float, speed_ticks_per_s: int | float | None = None) -> None:
        """지정한 motor tick 위치로 이동 명령을 보낸다."""
        if speed_ticks_per_s is not None:
            self.set_position_speed_limit(speed_ticks_per_s)
        self.commander.set_manual_target_pos(int(round(float(target_ticks))))

    def set_manual_torque(self, torque_permille: int | float) -> None:
        """수동 토크 명령을 설정. 단위는 rated torque의 per mille."""
        self.commander.set_manual_target_trq(int(torque_permille))

    def emergency_stop(self, hold_position_ticks: int | None = None) -> None:
        """모든 동작 명령을 안전 기본값으로 되돌린다."""
        self.commander.emergency_stop()
        self.set_manual_torque(0)
        if hold_position_ticks is not None:
            self.move_to_position_ticks(hold_position_ticks)

    # ------------------------------------------------------------------
    # Python 모션 스크립트
    # ------------------------------------------------------------------
    def start_motion_script(self, script) -> None:
        """Python 모션 스크립트를 CommandThread 평가 루프에서 실행."""
        self.commander.start_script(script)

    def stop_motion_script(self) -> None:
        """Python 모션 스크립트를 종료하고 수동 모드로 복귀."""
        self.commander.stop_script()

    def set_script_update_hz(self, update_hz: int | float) -> None:
        """Python 모션 스크립트 평가 주파수를 설정."""
        self.commander.set_script_update_hz(int(update_hz))

    # ------------------------------------------------------------------
    # 힘 제어
    # ------------------------------------------------------------------
    def start_force_control(self, settings: ForceControlSettings) -> None:
        """힘 제어 시작에 필요한 파라미터를 순서대로 보낸 뒤 start를 전송."""
        direction = 1 if int(settings.direction) >= 0 else -1
        feedback = str(settings.feedback).lower()
        mode = str(settings.mode).lower()

        self.commander.send_force_ctrl_cmd(make_force_feedback_cmd(feedback))
        self.commander.send_force_ctrl_cmd(make_force_direction_cmd(direction))
        self.commander.send_force_ctrl_cmd(make_force_max_rpm_cmd(settings.max_rpm))
        self.commander.send_force_ctrl_cmd(make_force_target_cmd(settings.target_n))

        if mode == "tanh":
            if settings.tanh is None:
                raise ValueError("Tanh 힘 제어 시작에는 ForceTanhSettings가 필요합니다.")
            self.apply_force_tanh(settings.tanh)
        else:
            if settings.pid is None:
                raise ValueError("PID 힘 제어 시작에는 ForcePidSettings가 필요합니다.")
            self.apply_force_pid(settings.pid)

        self.commander.send_force_ctrl_cmd(make_force_start_cmd())

    def stop_force_control(self) -> None:
        """힘 제어를 정지."""
        self.commander.send_force_ctrl_cmd(make_force_stop_cmd())

    def apply_force_pid(self, settings: ForcePidSettings) -> None:
        """PID 힘 제어 파라미터를 적용."""
        self.commander.send_force_ctrl_cmd(
            make_force_pid_cmd(settings.kp, settings.ki, settings.kd)
        )
        self.commander.send_force_ctrl_cmd(make_force_alpha_cmd(settings.output_alpha))

    def apply_force_tanh(self, settings: ForceTanhSettings) -> None:
        """Tanh 힘 제어 파라미터를 적용."""
        self.commander.send_force_ctrl_cmd(
            make_force_tanh_cmd(settings.sensitivity_n, settings.deadband_n)
        )
        self.commander.send_force_ctrl_cmd(make_force_alpha_cmd(settings.output_alpha))

    def reset_force_tare_offsets(self) -> None:
        """C++ 힘 제어 루프에 적용된 로드셀 Tare 오프셋을 모두 해제."""
        self.commander.send_force_ctrl_cmd(make_force_tare_reset_cmd())

    def set_force_tare_offset(self, channel: int, offset_n: float) -> None:
        """지정 채널의 Tare 오프셋을 C++ 힘 제어 루프에 전달."""
        self.commander.send_force_ctrl_cmd(make_force_tare_offset_cmd(channel, offset_n))

    def sync_force_tare_offsets(self, offsets_n) -> None:
        """현재 GUI/세션 Tare 오프셋 배열을 C++ 힘 제어 루프와 동기화."""
        for channel, offset_n in enumerate(offsets_n):
            self.set_force_tare_offset(channel, offset_n)

    def set_force_limit(self, enabled: bool, limit_n: float, soft_start_pct: float) -> None:
        """Python 소프트 리미트와 C++ hard force limit을 함께 설정.

        Python 쪽은 limit_n의 soft_start_pct 지점부터 속도 명령을 줄이고,
        C++ RT 루프는 같은 limit_n을 마지막 hard stop 조건으로 사용한다.
        """
        safe_limit_n = max(0.1, float(limit_n))
        self.commander.set_soft_limit(bool(enabled), safe_limit_n, float(soft_start_pct))
        self.commander.send_force_ctrl_cmd(
            make_force_limit_cmd(safe_limit_n if enabled else 0.0)
        )

    def set_force_absolute_mode(self, enabled: bool) -> None:
        """힘 제어 입력을 signed 힘으로 볼지 |F| 장력 크기로 볼지 설정."""
        self.commander.send_force_ctrl_cmd(make_force_abs_cmd(bool(enabled)))

    # ------------------------------------------------------------------
    # 파형 제어
    # ------------------------------------------------------------------
    def start_waveform(self, settings: WaveformSettings) -> str:
        """C++ RT 파형 생성기를 시작하고, 로그에 쓸 명령 문자열을 반환."""
        cmd = make_waveform_start_cmd(
            settings.waveform_type,
            settings.freq_hz,
            settings.amp_rpm,
            settings.offset_rpm,
            freq_end_hz=settings.freq_end_hz,
            duration_s=settings.duration_s,
        )
        self.commander.send_waveform_cmd(cmd)
        return settings.command_text()

    def stop_waveform(self) -> None:
        """C++ RT 파형 생성기를 정지."""
        self.commander.send_waveform_cmd(make_waveform_stop_cmd())

    # ------------------------------------------------------------------
    # 히스테리시스 테스트
    # ------------------------------------------------------------------
    def start_hysteresis_velocity(self, settings: HysteresisVelocitySettings) -> None:
        """속도 사인파 기반 히스테리시스 테스트를 C++ 노드에 예약."""
        self.commander.send_waveform_cmd(
            make_hyst_velocity_cmd(
                settings.freq_hz,
                settings.amp_rpm,
                settings.offset_rpm,
                settings.settle_cycles,
                settings.record_cycles,
                settings.log_path,
            )
        )

    def start_hysteresis_position(self, settings: HysteresisPositionSettings) -> None:
        """위치 사인파 기반 히스테리시스 테스트를 C++ 노드에 예약."""
        self.commander.send_waveform_cmd(
            make_hyst_position_cmd(
                settings.freq_hz,
                settings.amp_ticks,
                settings.offset_ticks,
                settings.max_tps,
                settings.settle_cycles,
                settings.record_cycles,
                settings.log_path,
            )
        )

    def stop_hysteresis(self) -> None:
        """히스테리시스 테스트에 사용 중인 C++ 파형을 정지."""
        self.stop_waveform()

    # ------------------------------------------------------------------
    # CSV 로깅
    # ------------------------------------------------------------------
    def start_csv_logging(self, log_path: Path | str) -> None:
        """C++ 비동기 CSV 로거를 시작."""
        self.commander.send_log_cmd(f"start {log_path}")

    def stop_csv_logging(self) -> None:
        """C++ 비동기 CSV 로거를 정지."""
        self.commander.send_log_cmd("stop")

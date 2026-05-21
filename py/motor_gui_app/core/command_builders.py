# -*- coding: utf-8 -*-
"""GUI 명령을 구조화 ROS2 메시지로 만들고, 기존 문자열 명령도 변환한다."""
from pathlib import Path
from typing import Optional

from .ros_messages import (
    ForceCtrlCmd,
    FORCE_CTRL_MSG_AVAILABLE,
    WaveformCmd,
    WAVEFORM_MSG_AVAILABLE,
)


def _waveform_type_value(wf_type: str) -> Optional[int]:
    if not WAVEFORM_MSG_AVAILABLE or WaveformCmd is None:
        return None
    return {
        "sine": WaveformCmd.TYPE_SINE,
        "square": WaveformCmd.TYPE_SQUARE,
        "triangle": WaveformCmd.TYPE_TRIANGLE,
        "chirp": WaveformCmd.TYPE_CHIRP,
    }.get(str(wf_type).lower())


def make_waveform_start_cmd(
    wf_type: str,
    freq_hz: float,
    amp_rpm: float,
    offset_rpm: float,
    freq_end_hz: float = 0.0,
    duration_s: float = 0.0,
):
    """일반 파형 시작 명령을 생성한다.

    메시지 패키지를 사용할 수 있으면 WaveformCmd 객체, 아니면 기존 문자열을 반환한다.
    """
    token = str(wf_type).lower()
    if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None:
        msg = WaveformCmd()
        msg.action = WaveformCmd.ACTION_START
        msg.waveform_type = _waveform_type_value(token) or WaveformCmd.TYPE_NONE
        msg.freq_hz = float(freq_hz)
        msg.amp_rpm = float(amp_rpm)
        msg.offset_rpm = float(offset_rpm)
        if token == "chirp":
            msg.freq_end_hz = float(freq_end_hz)
            msg.duration_s = float(duration_s)
        return msg

    if token == "chirp":
        return f"chirp {freq_hz} {freq_end_hz} {amp_rpm} {offset_rpm} {duration_s}"
    return f"{token} {freq_hz} {amp_rpm} {offset_rpm}"


def make_waveform_stop_cmd():
    """파형 정지 명령을 생성한다."""
    if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None:
        msg = WaveformCmd()
        msg.action = WaveformCmd.ACTION_STOP
        return msg
    return "none"


def make_hyst_velocity_cmd(
    freq_hz: float,
    amp_rpm: float,
    offset_rpm: float,
    settle_cycles: int,
    record_cycles: int,
    log_path: Path | str,
):
    """히스테리시스 속도 사인 예약 명령을 생성한다."""
    if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None:
        msg = WaveformCmd()
        msg.action = WaveformCmd.ACTION_START_HYST_VELOCITY
        msg.waveform_type = WaveformCmd.TYPE_SINE
        msg.freq_hz = float(freq_hz)
        msg.amp_rpm = float(amp_rpm)
        msg.offset_rpm = float(offset_rpm)
        msg.settle_cycles = int(settle_cycles)
        msg.record_cycles = int(record_cycles)
        msg.log_path = str(log_path)
        return msg
    return f"hyst_sine {freq_hz:.9g} {amp_rpm:.9g} {offset_rpm:.9g} {settle_cycles} {record_cycles} {log_path}"


def make_hyst_position_cmd(
    freq_hz: float,
    amp_ticks: float,
    offset_ticks: float,
    max_tps: float,
    settle_cycles: int,
    record_cycles: int,
    log_path: Path | str,
):
    """히스테리시스 위치 사인 예약 명령을 생성한다."""
    if WAVEFORM_MSG_AVAILABLE and WaveformCmd is not None:
        msg = WaveformCmd()
        msg.action = WaveformCmd.ACTION_START_HYST_POSITION
        msg.waveform_type = WaveformCmd.TYPE_POSITION_SINE
        msg.freq_hz = float(freq_hz)
        msg.amp_pos_ticks = float(amp_ticks)
        msg.offset_pos_ticks = float(offset_ticks)
        msg.max_pos_tps = float(max_tps)
        msg.settle_cycles = int(settle_cycles)
        msg.record_cycles = int(record_cycles)
        msg.log_path = str(log_path)
        return msg
    return (
        f"hyst_pos_sine {freq_hz:.9g} {amp_ticks:.9g} {offset_ticks:.9g} {max_tps:.9g} "
        f"{settle_cycles} {record_cycles} {log_path}"
    )


def make_force_start_cmd():
    return _force_action_cmd("start", ForceCtrlCmd.ACTION_START if ForceCtrlCmd is not None else None)


def make_force_stop_cmd():
    return _force_action_cmd("stop", ForceCtrlCmd.ACTION_STOP if ForceCtrlCmd is not None else None)


def make_force_target_cmd(target_n: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_TARGET)
        msg.target_n = float(target_n)
        return msg
    return f"target {target_n}"


def make_force_direction_cmd(direction: int):
    direction = -1 if int(direction) < 0 else 1
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_DIRECTION)
        msg.direction = direction
        return msg
    return f"direction {direction}"


def make_force_feedback_cmd(feedback: str):
    feedback_key = str(feedback).lower()
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_FEEDBACK)
        msg.feedback = _feedback_value(feedback_key)
        return msg
    return f"feedback {feedback_key}"


def make_force_abs_cmd(enabled: bool):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_FORCE_ABS)
        msg.force_abs = bool(enabled)
        return msg
    return f"force_abs {1 if enabled else 0}"


def make_force_pid_cmd(kp: float, ki: float, kd: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_PID)
        msg.kp = float(kp)
        msg.ki = float(ki)
        msg.kd = float(kd)
        return msg
    return f"pid {kp} {ki} {kd}"


def make_force_tanh_cmd(sensitivity_n: float, deadband_n: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_TANH)
        msg.tanh_sensitivity_n = float(sensitivity_n)
        msg.tanh_deadband_n = float(deadband_n)
        return msg
    return f"tanh {sensitivity_n} {deadband_n}"


def make_force_tare_offset_cmd(ch: int, offset_n: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_TARE_OFFSET)
        msg.tare_channel = int(ch)
        msg.tare_offset_n = float(offset_n)
        return msg
    return f"tare_offset {ch} {float(offset_n)}"


def make_force_tare_reset_cmd():
    return _force_action_cmd("tare_reset", ForceCtrlCmd.ACTION_TARE_RESET if ForceCtrlCmd is not None else None)


def make_force_max_rpm_cmd(max_rpm: int | float):
    rpm = int(float(max_rpm))
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_MAX_RPM)
        msg.max_rpm = rpm
        return msg
    return f"maxrpm {rpm}"


def make_force_limit_cmd(limit_n: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_LIMIT)
        msg.limit_n = float(limit_n)
        return msg
    return f"limit {limit_n}"


def make_force_alpha_cmd(alpha: float):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None:
        msg = _force_msg(ForceCtrlCmd.ACTION_SET_OUTPUT_ALPHA)
        msg.output_alpha = float(alpha)
        return msg
    return f"alpha {alpha}"


def _force_msg(action: int):
    msg = ForceCtrlCmd()
    msg.action = action
    return msg


def _force_action_cmd(legacy_text: str, action: Optional[int]):
    if FORCE_CTRL_MSG_AVAILABLE and ForceCtrlCmd is not None and action is not None:
        return _force_msg(action)
    return legacy_text


def _feedback_value(feedback: str) -> int:
    feedback = str(feedback).lower()
    if feedback in ("ch1", "1"):
        return ForceCtrlCmd.FEEDBACK_CH1
    if feedback in ("avg", "average"):
        return ForceCtrlCmd.FEEDBACK_AVG
    if feedback in ("max", "absmax"):
        return ForceCtrlCmd.FEEDBACK_MAX_ABS
    return ForceCtrlCmd.FEEDBACK_CH0


def build_waveform_msg(cmd: str):
    """문자열 호환 파형 명령을 WaveformCmd 객체로 변환.

    변환할 수 없거나 메시지 패키지를 사용할 수 없으면 None을 반환한다.
    호출 쪽은 None일 때 기존 문자열 토픽으로 fallback한다.
    """
    if not WAVEFORM_MSG_AVAILABLE or WaveformCmd is None:
        return None

    parts = str(cmd).strip().split()
    if not parts:
        return None

    token = parts[0].lower()
    msg = WaveformCmd()

    try:
        if token in ("none", "stop"):
            msg.action = WaveformCmd.ACTION_STOP
            return msg

        if token == "hyst_sine" and len(parts) >= 7:
            msg.action = WaveformCmd.ACTION_START_HYST_VELOCITY
            msg.waveform_type = WaveformCmd.TYPE_SINE
            msg.freq_hz = float(parts[1])
            msg.amp_rpm = float(parts[2])
            msg.offset_rpm = float(parts[3])
            msg.settle_cycles = int(parts[4])
            msg.record_cycles = int(parts[5])
            msg.log_path = " ".join(parts[6:])
            return msg

        if token == "hyst_pos_sine" and len(parts) >= 8:
            msg.action = WaveformCmd.ACTION_START_HYST_POSITION
            msg.waveform_type = WaveformCmd.TYPE_POSITION_SINE
            msg.freq_hz = float(parts[1])
            msg.amp_pos_ticks = float(parts[2])
            msg.offset_pos_ticks = float(parts[3])
            msg.max_pos_tps = float(parts[4])
            msg.settle_cycles = int(parts[5])
            msg.record_cycles = int(parts[6])
            msg.log_path = " ".join(parts[7:])
            return msg

        type_map = {
            "sine": WaveformCmd.TYPE_SINE,
            "square": WaveformCmd.TYPE_SQUARE,
            "triangle": WaveformCmd.TYPE_TRIANGLE,
            "chirp": WaveformCmd.TYPE_CHIRP,
        }
        if token not in type_map:
            return None

        msg.action = WaveformCmd.ACTION_START
        msg.waveform_type = type_map[token]
        if token == "chirp":
            if len(parts) < 6:
                return None
            msg.freq_hz = float(parts[1])
            msg.freq_end_hz = float(parts[2])
            msg.amp_rpm = float(parts[3])
            msg.offset_rpm = float(parts[4])
            msg.duration_s = float(parts[5])
        else:
            if len(parts) < 4:
                return None
            msg.freq_hz = float(parts[1])
            msg.amp_rpm = float(parts[2])
            msg.offset_rpm = float(parts[3])
            if len(parts) >= 5:
                msg.duration_s = float(parts[4])
        return msg
    except (TypeError, ValueError):
        return None


def build_force_ctrl_msg(cmd: str):
    """문자열 호환 힘 제어 명령을 ForceCtrlCmd 객체로 변환.

    변환할 수 없거나 메시지 패키지를 사용할 수 없으면 None을 반환한다.
    호출 쪽은 None일 때 기존 문자열 토픽으로 fallback한다.
    """
    if not FORCE_CTRL_MSG_AVAILABLE or ForceCtrlCmd is None:
        return None

    parts = str(cmd).strip().split()
    if not parts:
        return None

    token = parts[0].lower()
    msg = ForceCtrlCmd()

    try:
        if token == "start":
            msg.action = ForceCtrlCmd.ACTION_START
        elif token == "stop":
            msg.action = ForceCtrlCmd.ACTION_STOP
        elif token == "target" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_TARGET
            msg.target_n = float(parts[1])
        elif token == "direction" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_DIRECTION
            msg.direction = int(parts[1])
        elif token == "feedback" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_FEEDBACK
            feedback = parts[1].lower()
            if feedback in ("ch1", "1"):
                msg.feedback = ForceCtrlCmd.FEEDBACK_CH1
            elif feedback in ("avg", "average"):
                msg.feedback = ForceCtrlCmd.FEEDBACK_AVG
            elif feedback in ("max", "absmax"):
                msg.feedback = ForceCtrlCmd.FEEDBACK_MAX_ABS
            else:
                msg.feedback = ForceCtrlCmd.FEEDBACK_CH0
        elif token in ("force_abs", "abs_force", "tension_abs"):
            msg.action = ForceCtrlCmd.ACTION_SET_FORCE_ABS
            msg.force_abs = True if len(parts) < 2 else (int(parts[1]) != 0)
        elif token == "pid" and len(parts) >= 4:
            msg.action = ForceCtrlCmd.ACTION_SET_PID
            msg.kp = float(parts[1])
            msg.ki = float(parts[2])
            msg.kd = float(parts[3])
        elif token == "tanh" and len(parts) >= 3:
            msg.action = ForceCtrlCmd.ACTION_SET_TANH
            msg.tanh_sensitivity_n = float(parts[1])
            msg.tanh_deadband_n = float(parts[2])
        elif token == "tare_offset" and len(parts) >= 3:
            msg.action = ForceCtrlCmd.ACTION_SET_TARE_OFFSET
            msg.tare_channel = int(parts[1])
            msg.tare_offset_n = float(parts[2])
        elif token == "tare_reset":
            msg.action = ForceCtrlCmd.ACTION_TARE_RESET
        elif token == "maxrpm" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_MAX_RPM
            msg.max_rpm = int(float(parts[1]))
        elif token == "limit" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_LIMIT
            msg.limit_n = float(parts[1])
        elif token == "alpha" and len(parts) >= 2:
            msg.action = ForceCtrlCmd.ACTION_SET_OUTPUT_ALPHA
            msg.output_alpha = float(parts[1])
        else:
            return None
    except (TypeError, ValueError):
        return None

    return msg

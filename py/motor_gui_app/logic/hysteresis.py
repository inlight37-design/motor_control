# -*- coding: utf-8 -*-
"""히스테리시스 테스트 이름 생성, 진폭 변환, 동작 요약 계산 헬퍼."""
from dataclasses import dataclass
import math

from ..core import motor_units


EPS_FREQ = 1.0e-9
EPS_LEAD = 1.0e-9


@dataclass(frozen=True)
class VelocityAmplitude:
    amp_rpm: float
    requested_amp: float
    lead_mm_rev: float
    unit: str


@dataclass(frozen=True)
class PositionAmplitude:
    amp_ticks: float
    amp_mm: float
    requested_amp: float
    lead_mm_rev: float
    unit: str


def compact_number(value: float, decimals: int = 3) -> str:
    """파일명 토큰용 숫자 문자열. 1.000 -> 1, 0.125 -> 0.125."""
    if not math.isfinite(value):
        return "nan"
    if abs(value - round(value)) < 0.5 * (10 ** -decimals):
        return str(int(round(value)))
    return f"{value:.{decimals}f}".rstrip("0").rstrip(".")


def safe_label(raw: str, fallback: str = "hyst") -> str:
    """임의의 라벨 문자열을 파일명에 안전한 ASCII 토큰으로 변환."""
    chars = []
    last_under = False
    for ch in (raw or fallback):
        ok = ch.isascii() and (ch.isalnum() or ch in "._-")
        if ok:
            chars.append(ch)
            last_under = False
        elif not last_under:
            chars.append("_")
            last_under = True
    safe = "".join(chars).strip("._-")
    return safe or fallback


def auto_label(
    freq_hz: float,
    target_force_N: float,
    amplitude: float,
    amplitude_unit: str,
    record_cycles: int,
    motion_mode: str,
) -> str:
    """기본 히스테리시스 로그 라벨: 주파수_목표힘_진폭_사이클_모드."""
    freq = compact_number(abs(float(freq_hz)), 3)
    tension = compact_number(abs(float(target_force_N)), 1)
    amp = compact_number(abs(float(amplitude)), 3)
    amp_unit = amplitude_unit or "rpm"
    mode_token = "pos" if motion_mode == "position" else "vel"
    return f"{freq}hz_{tension}n_{amp}{amp_unit}_{int(record_cycles)}cyc_{mode_token}"


def amplitude_to_rpm(
    freq_hz: float,
    requested_amp: float,
    lead_mm_rev: float,
    unit: str,
) -> VelocityAmplitude:
    """GUI 진폭 입력값을 속도 사인파 RPM 진폭으로 변환."""
    freq = max(float(freq_hz), EPS_FREQ)
    requested = abs(float(requested_amp))
    lead = max(float(lead_mm_rev), EPS_LEAD)
    amp_unit = unit or "rpm"
    if amp_unit == "mm":
        amp_rpm = requested * 60.0 * 2.0 * math.pi * freq / lead
    else:
        amp_rpm = requested
    return VelocityAmplitude(amp_rpm=amp_rpm, requested_amp=requested, lead_mm_rev=lead, unit=amp_unit)


def amplitude_to_position_ticks(
    freq_hz: float,
    requested_amp: float,
    lead_mm_rev: float,
    unit: str,
    ticks_per_rev: int,
) -> PositionAmplitude:
    """GUI 진폭 입력값을 위치 사인파 tick 진폭으로 변환."""
    vel = amplitude_to_rpm(freq_hz, requested_amp, lead_mm_rev, unit)
    if vel.unit == "mm":
        amp_mm = vel.requested_amp
    else:
        freq = max(float(freq_hz), EPS_FREQ)
        amp_rev = (vel.amp_rpm / 60.0) / (2.0 * math.pi * freq)
        amp_mm = amp_rev * vel.lead_mm_rev
    amp_ticks = amp_mm * motor_units.ticks_per_mm(ticks_per_rev, vel.lead_mm_rev)
    return PositionAmplitude(
        amp_ticks=amp_ticks,
        amp_mm=amp_mm,
        requested_amp=vel.requested_amp,
        lead_mm_rev=vel.lead_mm_rev,
        unit=vel.unit,
    )


def cycle_timing(freq_hz: float, settle_cycles: int, record_cycles: int) -> tuple[float, float, float]:
    """안정화/기록 사이클 수를 초 단위 시간으로 변환."""
    period_s = 1.0 / max(float(freq_hz), EPS_FREQ)
    settle_s = int(settle_cycles) * period_s
    record_s = int(record_cycles) * period_s
    return settle_s, record_s, settle_s + record_s


def duration_text(freq_hz: float, settle_cycles: int, record_cycles: int) -> str:
    settle_s, record_s, total_s = cycle_timing(freq_hz, settle_cycles, record_cycles)
    return f"{total_s:.1f} s (stable {settle_s:.1f} + log {record_s:.1f})"


def position_required_tps(amp_ticks: float, freq_hz: float) -> float:
    return float(amp_ticks) * 2.0 * math.pi * max(float(freq_hz), EPS_FREQ)


def position_required_rpm(amp_ticks: float, freq_hz: float, ticks_per_rev: int) -> float:
    return position_required_tps(amp_ticks, freq_hz) * 60.0 / float(ticks_per_rev)


def position_max_tps(required_tps: float, max_rpm: float, ticks_per_rev: int) -> float:
    max_tps_by_rpm = float(max_rpm) * float(ticks_per_rev) / 60.0
    return min(max_tps_by_rpm, max(float(required_tps) * 1.25, float(required_tps) + 1000.0, 1000.0))


def motion_summary(
    freq_hz: float,
    requested_amp: float,
    lead_mm_rev: float,
    unit: str,
    offset_rpm: float,
    motion_mode: str,
    ticks_per_rev: int,
) -> str:
    """히스테리시스 테스트의 예상 움직임을 사람이 읽기 쉬운 문장으로 반환."""
    freq = max(float(freq_hz), EPS_FREQ)
    vel = amplitude_to_rpm(freq, requested_amp, lead_mm_rev, unit)
    is_position = motion_mode == "position"

    if is_position:
        pos = amplitude_to_position_ticks(freq, requested_amp, lead_mm_rev, unit, ticks_per_rev)
        required_tps = position_required_tps(pos.amp_ticks, freq)
        required_rpm = required_tps * 60.0 / float(ticks_per_rev)
        return (
            f"위치 사인: 시작점→한쪽 {2.0 * pos.amp_mm:.3f} mm→시작점 "
            f"(A={pos.amp_mm:.3f} mm, {pos.amp_ticks:.0f} tick), "
            f"peak vel≈{required_tps:.0f} tick/s ({required_rpm:.1f} rpm)"
        )

    amp_rev = (vel.amp_rpm / 60.0) / (2.0 * math.pi * freq)
    amp_mm = amp_rev * vel.lead_mm_rev
    pp_rev = 2.0 * amp_rev
    pp_mm = 2.0 * amp_mm
    drift_rev = float(offset_rpm) / (60.0 * freq)
    drift_mm = drift_rev * vel.lead_mm_rev

    if vel.unit == "mm":
        motion = (
            f"예상 이동량: 중앙 기준 ±{amp_mm:.3f} mm (p-p {pp_mm:.3f} mm), "
            f"속도 사인 실제 궤적은 시작점→한쪽 {pp_mm:.3f} mm→시작점, "
            f"lead {vel.lead_mm_rev:.3f} mm/rev → {vel.amp_rpm:.1f} rpm"
        )
        if abs(round(vel.amp_rpm) - vel.amp_rpm) > 0.05:
            motion += f" (nearest int {round(vel.amp_rpm)} rpm)"
    else:
        motion = (
            f"예상 이동량: 중앙 기준 ±{amp_rev:.3f} rev / ±{amp_mm:.3f} mm "
            f"(p-p {pp_rev:.3f} rev / {pp_mm:.3f} mm), "
            f"속도 사인 실제 궤적은 시작점→한쪽 {pp_mm:.3f} mm→시작점"
        )

    if abs(drift_rev) > 0.001:
        motion += f", offset drift {drift_rev:+.3f} rev/cycle ({drift_mm:+.3f} mm/cycle)"
    return motion

# -*- coding: utf-8 -*-
"""수동 속도/위치/토크 제어와 비상정지 동작 헬퍼."""
from ..core.config import DEFAULT_POSITION_LEAD_MM_REV, DEFAULT_POSITION_TICKS_PER_REV
from ..core.time_utils import now_str
from . import force_control_actions, hysteresis_actions, waveform_actions


def change_op_mode(window, index: int):
    """운전 모드 콤보박스 변경 시 C++ 노드에 모드 전환 명령을 보낸다."""
    modes = [9, 8, 10]  # 0: 속도(CSV), 1: 위치(CSP), 2: 토크(CST)
    mode = modes[index]
    window.control.set_operation_mode(mode)
    window.update_log(f"[{now_str()}] 제어 모드 변경 요청: {mode}")


def pos_lead_mm_rev(window) -> float:
    widgets = getattr(window, "position_torque_widgets", None)
    if widgets is not None:
        return max(float(widgets.pos_lead_spin.value()), 1e-9)
    return max(float(DEFAULT_POSITION_LEAD_MM_REV), 1e-9)


def pos_ticks_per_rev(_window) -> float:
    return max(float(DEFAULT_POSITION_TICKS_PER_REV), 1.0)


def pos_ticks_per_mm(window) -> float:
    return pos_ticks_per_rev(window) / pos_lead_mm_rev(window)


def pos_ticks_to_mm(window, ticks: int | float) -> float:
    return float(ticks) / pos_ticks_per_mm(window)


def pos_mm_to_ticks(window, mm: int | float) -> int:
    return int(round(float(mm) * pos_ticks_per_mm(window)))


def sync_pos_mm_from_ticks(window):
    """tick 입력칸 값을 mm 입력칸에 반영."""
    widgets = getattr(window, "position_torque_widgets", None)
    if window.ui_state.syncing_pos_units or widgets is None:
        return
    window.ui_state.syncing_pos_units = True
    try:
        widgets.pos_mm_spin.setValue(pos_ticks_to_mm(window, widgets.pos_spin.value()))
    finally:
        window.ui_state.syncing_pos_units = False


def sync_pos_ticks_from_mm(window):
    """mm 입력칸 값을 tick 입력칸에 반영."""
    widgets = getattr(window, "position_torque_widgets", None)
    if window.ui_state.syncing_pos_units or widgets is None:
        return
    window.ui_state.syncing_pos_units = True
    try:
        widgets.pos_spin.setValue(pos_mm_to_ticks(window, widgets.pos_mm_spin.value()))
    finally:
        window.ui_state.syncing_pos_units = False


def on_pos_lead_changed(window):
    """리드값 변경 시 같은 tick 위치의 mm 표시를 다시 계산."""
    sync_pos_mm_from_ticks(window)


def set_zero_position(window):
    """현재 실제 위치를 표시 기준 0으로 삼는다."""
    widgets = window.position_torque_widgets
    window.ui_state.pos_offset = window.session.state.actual_position_ticks()
    widgets.pos_spin.setValue(0)
    widgets.pos_mm_spin.setValue(0.0)
    window.update_log(f"[{now_str()}] 위치 영점 설정 (내부 오프셋: {window.ui_state.pos_offset} 틱)")


def send_manual_pos(window):
    """수동 위치 명령을 실제 encoder tick 기준으로 변환해 전송."""
    widgets = window.position_torque_widgets
    tps = widgets.pos_speed_spin.value()

    pos = widgets.pos_spin.value()
    pos_mm = pos_ticks_to_mm(window, pos)
    real_target = pos + window.ui_state.pos_offset
    window.control.move_to_position_ticks(real_target, speed_ticks_per_s=tps)
    speed_mm_s = float(tps) / pos_ticks_per_mm(window)
    window.update_log(
        f"[{now_str()}] 위치 명령: 표시={pos} tick ({pos_mm:.3f} mm) / "
        f"실제={real_target} tick (속도: {tps} tick/s, {speed_mm_s:.3f} mm/s)"
    )


def send_manual_trq(window):
    """수동 토크 명령을 전송."""
    trq = window.position_torque_widgets.trq_spin.value()
    window.control.set_manual_torque(trq)
    window.update_log(f"[{now_str()}] 수동 토크 명령: {trq * 0.101:.1f} mN·m ({trq} ‰)")


def send_manual_rpm(window):
    """수동 RPM 명령을 전송."""
    rpm = float(window.manual_motion_widgets.rpm_spin.value())
    window.control.set_manual_rpm(rpm)
    window.update_log(f"[{now_str()}] 수동 RPM: {rpm:.0f}")


def emergency_stop(window):
    """모든 제어 명령을 안전한 기본 상태로 되돌린다."""
    if window.hyst_test_running:
        hysteresis_actions.abort_test(window, reason="비상 정지")

    window.control.emergency_stop(hold_position_ticks=window.session.state.actual_position_ticks())
    window.manual_motion_widgets.rpm_spin.setValue(0)
    widgets = window.position_torque_widgets
    widgets.trq_spin.setValue(0)

    curr_pos = window.session.state.actual_position_ticks() - window.ui_state.pos_offset
    widgets.pos_spin.setValue(curr_pos)

    if window.waveform_running:
        waveform_actions.stop_waveform(window)

    if window.force_control_running:
        force_control_actions.stop_force_ctrl(window)

    window.update_log(f"[{now_str()}] 통합 비상 정지: 모든 제어 명령 리셋")

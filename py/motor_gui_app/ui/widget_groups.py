# -*- coding: utf-8 -*-
"""패널별 PyQt 위젯 핸들을 묶는 작은 컨테이너."""
from dataclasses import dataclass


@dataclass
class GraphWidgets:
    """속도/RT 그래프 위젯과 curve 핸들."""

    speed_plot: object
    rt_plot: object
    target_curve: object
    actual_curve: object
    rt_dt_curve: object


@dataclass
class ScriptLogWidgets:
    """CSV 로깅과 모션 스크립트 패널 위젯."""

    log_start_button: object
    log_stop_button: object
    log_path_label: object
    script_hz_spin: object
    script_label: object
    script_button: object


@dataclass
class TopStatusWidgets:
    """상단 시스템 제어와 진단 표시 위젯."""

    iface_combo: object
    status_label: object
    motor_button: object
    show_speed_checkbox: object
    show_rt_checkbox: object
    rt_cpu_spin: object
    motor_state_label: object
    error_code_label: object
    rt_jitter_label: object
    overrun_label: object
    wkc_error_label: object
    heartbeat_label: object
    fault_reset_button: object
    auto_reset_checkbox: object


@dataclass
class LoadCellWidgets:
    """로드셀 표시, tare, 소프트 리미트 위젯."""

    connect_button: object
    cal_button: object
    cal_ch0_button: object
    cal_ch1_button: object
    tare_ch0_button: object
    tare_ch1_button: object
    tare_all_button: object
    tare_reset_button: object
    unit_combo: object
    cal_label: object
    source_label: object
    tare_status_label: object
    ch0_label: object
    ch1_label: object
    delta_label: object
    max_label: object
    force_abs_checkbox: object
    soft_limit_checkbox: object
    force_limit_spin: object
    soft_start_spin: object
    soft_status_label: object


@dataclass
class ForceControlWidgets:
    """힘 제어 시작/정지와 PID/Tanh 설정 위젯."""

    start_button: object
    stop_button: object
    target_spin: object
    direction_combo: object
    feedback_combo: object
    max_rpm_spin: object
    status_label: object
    ctrl_mode_combo: object
    alpha_spin: object
    pid_panel: object
    kp_spin: object
    ki_spin: object
    kd_spin: object
    pid_apply_button: object
    tanh_panel: object
    tanh_sens_spin: object
    tanh_dead_spin: object
    tanh_apply_button: object


@dataclass
class WaveformWidgets:
    """C++ RT 파형 생성기 설정과 시작/정지 위젯."""

    type_combo: object
    freq_spin: object
    end_label: object
    freq_end_spin: object
    duration_label: object
    duration_spin: object
    amp_spin: object
    offset_spin: object
    start_button: object
    stop_button: object


@dataclass
class ManualMotionWidgets:
    """수동 RPM 입력과 공통 속도 제한 위젯."""

    rpm_spin: object
    send_button: object
    accel_spin: object
    limit_spin: object


@dataclass
class PositionTorqueWidgets:
    """위치/토크 제어 모드, 목표 입력, 현재값 표시 위젯."""

    mode_combo: object
    actual_pos_label: object
    actual_trq_label: object
    zero_pos_button: object
    pos_spin: object
    pos_mm_spin: object
    pos_lead_spin: object
    pos_speed_spin: object
    pos_move_button: object
    trq_spin: object
    trq_apply_button: object


@dataclass
class LinearEncoderWidgets:
    """GUI 내장/외부 리니어 엔코더 설정과 표시 위젯."""

    connect_button: object
    channel_spin: object
    counts_per_mm_spin: object
    invert_checkbox: object
    zero_button: object
    pos_label: object
    status_label: object


@dataclass
class HysteresisWidgets:
    """히스테리시스 자동 테스트 설정, 상태, 실행 제어 위젯."""

    label_edit: object
    freq_spin: object
    motion_mode_combo: object
    amp_spin: object
    amp_unit_combo: object
    lead_spin: object
    offset_spin: object
    settle_cycles_spin: object
    record_cycles_spin: object
    duration_label: object
    start_button: object
    abort_button: object
    status_label: object
    motion_label: object


@dataclass
class PanelVisibilityWidgets:
    """제어 패널 표시/숨김 체크박스."""

    motion_checkbox: object
    force_checkbox: object
    hysteresis_checkbox: object
    utility_checkbox: object

    def checkboxes(self):
        """패널 컨테이너와 같은 순서의 체크박스 목록."""
        return [
            self.motion_checkbox,
            self.force_checkbox,
            self.hysteresis_checkbox,
            self.utility_checkbox,
        ]


@dataclass
class PanelContainers:
    """메인 화면의 접힘/펼침 대상 패널 프레임."""

    motion_panel: object
    force_panel: object
    hysteresis_panel: object
    utility_panel: object

    def visibility_pairs(self):
        """PanelVisibilityWidgets와 함께 쓰는 순서의 패널 목록."""
        return [
            self.motion_panel,
            self.force_panel,
            self.hysteresis_panel,
            self.utility_panel,
        ]

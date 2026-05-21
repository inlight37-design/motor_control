# -*- coding: utf-8 -*-
"""GUI와 C++ EPOS 노드가 공유하는 ROS2 토픽 이름."""

# C++ 노드 실행 파일 이름. GUI의 노드 실행/서비스 경로와 CMake 실행 파일명이 맞아야 한다.
EPOS_NODE_EXECUTABLE = "epos_motor_node"

# ── EPOS 모터 제어 토픽 ─────────────────────────────────────────────
FEEDBACK_TOPIC = "/measured_speed"              # C++ → GUI: 실측 속도 (RPM)
TARGET_TOPIC = "/target_speed"                  # GUI → C++: 목표 속도 (RPM)
TOPIC_CYCLE_DT = "/epos/cycle_dt_us"            # C++ → GUI: RT 루프 주기 (μs)
TOPIC_STATUS_WORD = "/epos/status_word"         # C++ → GUI: EPOS4 상태 워드
TOPIC_ERROR_CODE = "/epos/error_code"           # C++ → GUI: EPOS4 에러 코드
TOPIC_WAVEFORM_CMD = "/epos/waveform_cmd"       # GUI → C++: 파형 명령 문자열(v1)
TOPIC_WAVEFORM_CMD_V2 = "/epos/waveform_cmd_v2" # GUI → C++: 파형 구조화 메시지(v2)
TOPIC_LOG_CMD = "/epos/log_cmd"                 # GUI → C++: CSV 로깅 시작/종료
TOPIC_HEARTBEAT = "/epos/heartbeat"             # GUI → C++: heartbeat
TOPIC_DIAG_SUMMARY = "/epos/diag_summary"       # C++ → GUI: 진단 요약 JSON
TOPIC_ACTUAL_POS = "/epos/actual_position"      # C++ → GUI: 현재 위치 (encoder tick)
TOPIC_ACTUAL_TRQ = "/epos/actual_torque"        # C++ → GUI: 현재 토크 (‰)
TOPIC_OP_MODE = "/op_mode_cmd"                  # GUI → C++: 운전 모드 (8, 9, 10)
TOPIC_TARGET_POS = "/target_position"           # GUI → C++: 목표 위치 (tick)
TOPIC_TARGET_TRQ = "/target_torque"             # GUI → C++: 목표 토크 (‰)
TOPIC_JITTER = "/epos/cycle_jitter_us"          # C++ → GUI: RT 루프 지터 (μs)
TOPIC_OVERRUN = "/epos/cycle_overrun_count"     # C++ → GUI: 주기 초과 횟수
TOPIC_WKC_ERR = "/epos/wkc_error_count"         # C++ → GUI: EtherCAT WKC 에러 횟수
TOPIC_FORCE_CTRL_CMD = "/epos/force_ctrl_cmd"   # GUI → C++: 힘 제어 명령 문자열(v1)
TOPIC_FORCE_CTRL_CMD_V2 = "/epos/force_ctrl_cmd_v2" # GUI → C++: 힘 제어 구조화 메시지(v2)
TOPIC_TARGET_FORCE = "/target_force_N"          # GUI → C++: 목표 힘 (N)

# ── 센서 토픽 ──────────────────────────────────────────────────────
TOPIC_LOAD_CELL_CH0_N = "/load_cell/ch0_N"       # 로드셀 채널 0 힘 값 (N)
TOPIC_LOAD_CELL_CH1_N = "/load_cell/ch1_N"       # 로드셀 채널 1 힘 값 (N)
TOPIC_LOAD_CELL_CH0_G = "/load_cell/ch0_g"       # 로드셀 채널 0 힘 값 (g)
TOPIC_LOAD_CELL_CH1_G = "/load_cell/ch1_g"       # 로드셀 채널 1 힘 값 (g)
TOPIC_LOAD_CELL_STATUS = "/load_cell/status"     # 로드셀 상태 JSON
TOPIC_LINEAR_ENCODER_COUNT = "/linear_encoder/position_count" # 리니어 엔코더 카운트
TOPIC_LINEAR_ENCODER_MM = "/linear_encoder/position_mm"       # 리니어 엔코더 위치 [mm]
TOPIC_LINEAR_ENCODER_STATUS = "/linear_encoder/status"        # 리니어 엔코더 상태 JSON
SERVICE_LINEAR_ENCODER_ZERO = "/linear_encoder/zero"          # 리니어 엔코더 영점 서비스

__all__ = [name for name in globals() if name.startswith("TOPIC_")]
__all__ += ["FEEDBACK_TOPIC", "TARGET_TOPIC", "EPOS_NODE_EXECUTABLE", "SERVICE_LINEAR_ENCODER_ZERO"]

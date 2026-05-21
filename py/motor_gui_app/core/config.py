# -*- coding: utf-8 -*-
"""Runtime paths and typed defaults loaded from config/defaults.json.

`config/defaults.json` is the editable data file. This module is the loader:
it chooses the active defaults file, applies environment variable overrides,
clamps values to safe ranges, and exposes the resulting constants used by the
GUI, CLI, and ROS2 launch helpers.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# ── 실행 위치 기반 경로 ─────────────────────────────────────────────
# config.py는 motor_gui_app/core 아래에 있으므로 패키지 루트는 parents[1]이다.
# Motor_gui_jh처럼 py/motor_gui_app + cpp/src 구조로 묶인 배포 폴더는 cpp를
# 기본 C++ 워크스페이스로 자동 선택한다. 환경변수 EPOS_WORKSPACE_DIR가 있으면
# 항상 그 값을 우선한다.
PACKAGE_DIR = Path(__file__).resolve().parents[1]
_DIST_ROOT = PACKAGE_DIR.parent.parent if PACKAGE_DIR.parent.name == "py" else None
_DIST_CPP_DIR = _DIST_ROOT / "cpp" if _DIST_ROOT is not None else None
_DIST_LOG_DIR = _DIST_ROOT / "logs" if _DIST_ROOT is not None else None
_DEFAULT_WORKSPACE_DIR = _DIST_CPP_DIR if (_DIST_CPP_DIR is not None and (_DIST_CPP_DIR / "src").exists()) else PACKAGE_DIR.parent
WORKSPACE_DIR = Path(os.environ.get("EPOS_WORKSPACE_DIR", str(_DEFAULT_WORKSPACE_DIR))).expanduser().resolve()

# ROS 설치 경로는 시스템 의존성이므로 기본값만 두고, 필요하면 환경변수로 덮어쓴다.
ROS_SETUP = os.environ.get("ROS_SETUP", "/opt/ros/jazzy/setup.bash")
WS_SETUP = os.environ.get("WS_SETUP", str(WORKSPACE_DIR / "install" / "setup.bash"))

# 워크스페이스별 DDS XML 파일을 써서 여러 복사본을 번갈아 실행해도 충돌을 줄인다.
DDS_CONFIG_PATH = os.environ.get(
    "FASTRTPS_DEFAULT_PROFILES_FILE",
    str(Path("/tmp") / f"fastdds_udp_only_{WORKSPACE_DIR.name}.xml")
)

# 런타임 산출물/사용자 파일 기본 위치. 환경변수로 실험별 폴더를 분리할 수 있다.
_DEFAULT_LOG_DIR = _DIST_LOG_DIR if (_DIST_LOG_DIR is not None and _DIST_LOG_DIR.exists()) else WORKSPACE_DIR / "logs"
LOG_DIR = Path(os.environ.get("EPOS_LOG_DIR", str(_DEFAULT_LOG_DIR))).expanduser()
SCRIPT_DIR = Path(os.environ.get("EPOS_SCRIPT_DIR", str(WORKSPACE_DIR))).expanduser()
LOAD_CELL_CAL_DIR = Path(os.environ.get("LOAD_CELL_CAL_DIR", str(Path.home() / "K-FLEX" / "Load_cell"))).expanduser()


def _read_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(min_value, min(max_value, value))


_workspace_defaults = WORKSPACE_DIR / "config" / "defaults.json"
_package_defaults = PACKAGE_DIR / "config" / "defaults.json"
DEFAULTS_PATH = Path(
    os.environ.get(
        "EPOS_DEFAULTS_FILE",
        str(_workspace_defaults if _workspace_defaults.exists() else _package_defaults),
    )
).expanduser()


def _load_defaults() -> Tuple[Dict[str, Any], Optional[str]]:
    try:
        with open(DEFAULTS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data, None
        return {}, "defaults root is not a JSON object"
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"


APP_DEFAULTS, DEFAULTS_LOAD_ERROR = _load_defaults()


def defaults_loaded() -> bool:
    """Return True when the active defaults.json file was loaded successfully."""
    return DEFAULTS_LOAD_ERROR is None


def config_summary() -> str:
    """Return a compact diagnostic string for logs, CLI, or troubleshooting."""
    if defaults_loaded():
        return f"defaults={DEFAULTS_PATH}"
    return f"defaults={DEFAULTS_PATH} load_error={DEFAULTS_LOAD_ERROR}"


def _cfg_value(path: str, default: Any) -> Any:
    value: Any = APP_DEFAULTS
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _cfg_float(path: str, default: float, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    try:
        value = float(_cfg_value(path, default))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _cfg_int(path: str, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    try:
        value = int(round(float(_cfg_value(path, default))))
    except (TypeError, ValueError):
        value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _cfg_bool(path: str, default: bool) -> bool:
    value = _cfg_value(path, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


DEFAULT_RT_CPU = _read_int_env("EPOS_RT_CPU", _cfg_int("motor.rt_cpu", 1, -1, 7), -1, 7)
MAX_RPM = _read_int_env("EPOS_MAX_RPM", _cfg_int("motor.max_rpm", 3000, 1, 100000), 1, 100000)
DEFAULT_MANUAL_RPM_LIMIT = _cfg_int("motor.manual_rpm_limit", MAX_RPM, 0, MAX_RPM)
DEFAULT_ACCEL_RPM_S = _cfg_int("motor.accel_rpm_s", 5000, 0, 50000)
DEFAULT_CMD_HZ = _cfg_int("motor.command_hz", 200, 1, 1000)
DEFAULT_CMD_TIMEOUT_MS = _read_int_env("EPOS_CMD_TIMEOUT_MS", _cfg_int("motor.cmd_timeout_ms", 0, 0, 60000), 0, 60000)
DEFAULT_HEARTBEAT_TIMEOUT_MS = _read_int_env(
    "EPOS_HEARTBEAT_TIMEOUT_MS",
    _cfg_int("motor.heartbeat_timeout_ms", 500, 0, 60000),
    0,
    60000,
)

DEFAULT_POSITION_LEAD_MM_REV = _cfg_float("position.lead_mm_rev", 5.0, 0.001, 1000.0)
DEFAULT_POSITION_TICKS_PER_REV = _cfg_int("position.ticks_per_rev", 2000, 1, 10000000)

DEFAULT_WF_FREQ_HZ = _cfg_float("waveform.freq_hz", 1.0, 0.01, 500.0)
DEFAULT_WF_FREQ_END_HZ = _cfg_float("waveform.freq_end_hz", 10.0, 0.01, 500.0)
DEFAULT_WF_DURATION_S = _cfg_float("waveform.duration_s", 30.0, 1.0, 3600.0)
DEFAULT_WF_AMP_RPM = _cfg_int("waveform.amp_rpm", 500, 0, MAX_RPM)
DEFAULT_WF_OFFSET_RPM = _cfg_int("waveform.offset_rpm", 0, -MAX_RPM, MAX_RPM)

DEFAULT_FORCE_TARGET_N = _cfg_float("force.target_N", 0.0, -9999.0, 9999.0)
DEFAULT_FORCE_MAX_RPM = _read_int_env("EPOS_FORCE_MAX_RPM", _cfg_int("force.max_rpm", 50, 10, MAX_RPM), 10, MAX_RPM)
DEFAULT_FORCE_ALPHA = _cfg_float("force.output_alpha", 0.3, 0.01, 1.0)
DEFAULT_FORCE_ABS_MODE = _cfg_bool("force.force_abs_mode", True)
DEFAULT_FORCE_SOFT_LIMIT_N = _cfg_float("force.soft_limit_N", 100.0, 0.1, 10000.0)
DEFAULT_FORCE_SOFT_START_PCT = _cfg_int("force.soft_start_pct", 70, 10, 99)
DEFAULT_FORCE_KP = _cfg_float("force.pid.kp", 0.5, 0.0, 100.0)
DEFAULT_FORCE_KI = _cfg_float("force.pid.ki", 0.05, 0.0, 100.0)
DEFAULT_FORCE_KD = _cfg_float("force.pid.kd", 0.01, 0.0, 100.0)
DEFAULT_FORCE_TANH_SENS_N = _cfg_float("force.tanh.sensitivity_N", 1.0, 0.01, 50.0)
DEFAULT_FORCE_TANH_DEADBAND_N = _cfg_float("force.tanh.deadband_N", 0.01, 0.0, 10.0)
DEFAULT_FORCE_WF_FREQ_HZ = _cfg_float("force.waveform.freq_hz", 1.0, 0.01, 500.0)
DEFAULT_FORCE_WF_AMP_N = _cfg_float("force.waveform.amp_N", 10.0, 0.0, 9999.0)
DEFAULT_FORCE_WF_OFFSET_N = _cfg_float("force.waveform.offset_N", 0.0, -9999.0, 9999.0)

DEFAULT_LOAD_CELL_DATA_RATE_HZ = _cfg_float("load_cell.data_rate_hz", 250.0, 1.0, 1200.0)
DEFAULT_LOAD_CELL_CHANGE_TRIGGER = _cfg_float("load_cell.change_trigger", 0.0, 0.0, 1.0)

DEFAULT_HYST_FREQ_HZ = _cfg_float("hysteresis.freq_hz", 1.0, 0.001, 50.0)
DEFAULT_HYST_MOTION_MODE = str(_cfg_value("hysteresis.motion_mode", "velocity")).lower()
DEFAULT_HYST_UNIT = str(_cfg_value("hysteresis.unit", "mm")).lower()
DEFAULT_HYST_AMP_MM = _cfg_float("hysteresis.amp_mm", 10.0, 0.001, 1000.0)
DEFAULT_HYST_AMP_RPM = _cfg_float("hysteresis.amp_rpm", 500.0, 1.0, float(MAX_RPM))
DEFAULT_HYST_LEAD_MM_REV = _cfg_float("hysteresis.lead_mm_rev", 5.0, 0.001, 1000.0)
DEFAULT_HYST_OFFSET_RPM = _cfg_int("hysteresis.offset_rpm", 0, -MAX_RPM, MAX_RPM)
DEFAULT_HYST_SETTLE_CYCLES = _cfg_int("hysteresis.settle_cycles", 1, 0, 20)
DEFAULT_HYST_RECORD_CYCLES = _cfg_int("hysteresis.record_cycles", 3, 1, 200)

DEFAULT_LINEAR_ENCODER_CHANNEL = _cfg_int("linear_encoder.channel", 0, 0, 3)
DEFAULT_LINEAR_COUNTS_PER_MM = _cfg_float("linear_encoder.counts_per_mm", 1000.0, 0.001, 1.0e9)
DEFAULT_LINEAR_INVERT = _cfg_bool("linear_encoder.invert", False)

# 그래프에 표시할 최대 데이터 포인트 수
MAX_GRAPH_POINTS = 12000

__all__ = [
    "APP_DEFAULTS", "DEFAULTS_LOAD_ERROR", "DEFAULTS_PATH", "PACKAGE_DIR", "WORKSPACE_DIR",
    "ROS_SETUP", "WS_SETUP", "DDS_CONFIG_PATH", "LOG_DIR", "SCRIPT_DIR",
    "LOAD_CELL_CAL_DIR", "MAX_GRAPH_POINTS", "MAX_RPM", "config_summary", "defaults_loaded",
]
__all__ += [name for name in globals() if name.startswith("DEFAULT_")]

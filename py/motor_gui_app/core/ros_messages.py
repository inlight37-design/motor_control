# -*- coding: utf-8 -*-
"""선택적으로 사용할 ROS2 커스텀 메시지 타입 감지."""

try:
    from epos_interfaces.msg import ForceCtrlCmd
    FORCE_CTRL_MSG_AVAILABLE = True
except Exception:
    ForceCtrlCmd = None
    FORCE_CTRL_MSG_AVAILABLE = False

try:
    from epos_interfaces.msg import WaveformCmd
    WAVEFORM_MSG_AVAILABLE = True
except Exception:
    WaveformCmd = None
    WAVEFORM_MSG_AVAILABLE = False


__all__ = [
    "ForceCtrlCmd",
    "FORCE_CTRL_MSG_AVAILABLE",
    "WaveformCmd",
    "WAVEFORM_MSG_AVAILABLE",
]

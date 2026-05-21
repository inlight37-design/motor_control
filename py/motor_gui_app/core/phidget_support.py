# -*- coding: utf-8 -*-
"""Phidget 장치 지원 여부와 공통 물리 상수."""

GRAVITY = 9.80665  # 중력 가속도 (m/s²), 그램↔뉴턴 변환에 사용

try:
    from Phidget22.Devices.Encoder import Encoder
    from Phidget22.Devices.VoltageRatioInput import VoltageRatioInput

    PHIDGET_AVAILABLE = True
except ImportError:
    Encoder = None
    VoltageRatioInput = None
    PHIDGET_AVAILABLE = False


__all__ = ["Encoder", "GRAVITY", "PHIDGET_AVAILABLE", "VoltageRatioInput"]

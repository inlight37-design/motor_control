# -*- coding: utf-8 -*-
"""Phidget 리니어 엔코더 리더."""
import threading
from typing import Optional

from ..core.linear_encoder_math import normalize_counts_per_mm, position_count, position_mm
from ..core.phidget_support import Encoder, PHIDGET_AVAILABLE

class LinearEncoderReader:
    """PhidgetEncoder 기반 리니어 엔코더 리더.

    GUI에서 직접 Phidget Encoder 채널을 읽고, CommandThread가 ROS2 토픽으로
    C++ 노드에 전달한다. 위치 제어에 바로 쓰기보다 우선 CSV 동기 기록용으로 둔다.
    """

    def __init__(self, channel: int = 0, counts_per_mm: float = 1000.0, invert: bool = False):
        self._lock = threading.Lock()
        self.channel = int(channel)
        self.counts_per_mm = normalize_counts_per_mm(counts_per_mm)
        self.invert = bool(invert)
        self.connected = False
        self._device = None
        self._raw_count = 0
        self._zero_raw = 0
        self._has_sample = False
        self.serial = None
        self.device_name = ""
        self.last_error = ""

    def _on_position_change(self, _dev, _position_change, _time_change, _index_triggered):
        with self._lock:
            try:
                self._raw_count = int(_dev.getPosition())
                self._has_sample = True
            except Exception as e:
                self.last_error = str(e)

    def configure(self, channel: Optional[int] = None, counts_per_mm: Optional[float] = None, invert: Optional[bool] = None):
        with self._lock:
            if channel is not None and not self.connected:
                self.channel = int(channel)
            if counts_per_mm is not None:
                self.counts_per_mm = normalize_counts_per_mm(counts_per_mm)
            if invert is not None:
                self.invert = bool(invert)

    def connect(self, channel: Optional[int] = None) -> tuple[bool, str]:
        if not PHIDGET_AVAILABLE:
            return False, "Phidget22 라이브러리 없음"
        self.disconnect()
        with self._lock:
            if channel is not None:
                self.channel = int(channel)
        try:
            dev = Encoder()
            dev.setChannel(self.channel)
            dev.setOnPositionChangeHandler(self._on_position_change)
            dev.openWaitForAttachment(3000)
            try:
                dev.setEnabled(True)
            except Exception:
                pass
            try:
                dev.setDataInterval(dev.getMinDataInterval())
            except Exception:
                pass
            try:
                dev.setPositionChangeTrigger(1)
            except Exception:
                pass
            raw = int(dev.getPosition())
            with self._lock:
                self._device = dev
                self.connected = True
                self._raw_count = raw
                self._zero_raw = raw
                self._has_sample = True
                self.serial = dev.getDeviceSerialNumber()
                self.device_name = dev.getDeviceName()
                self.last_error = ""
            return True, f"CH{self.channel} 연결됨"
        except Exception as e:
            with self._lock:
                self.connected = False
                self._device = None
                self.last_error = str(e)
            return False, str(e)

    def disconnect(self):
        with self._lock:
            dev = self._device
            self._device = None
            self.connected = False
        if dev:
            try:
                dev.close()
            except Exception:
                pass

    def zero(self):
        with self._lock:
            self._zero_raw = self._raw_count

    def get_position_count(self) -> int:
        with self._lock:
            return position_count(self._raw_count, self._zero_raw, self.invert)

    def get_position_mm(self) -> float:
        with self._lock:
            return position_mm(self._raw_count, self._zero_raw, self.counts_per_mm, self.invert)

    def get_raw_count(self) -> int:
        with self._lock:
            return int(self._raw_count)

    def has_sample(self) -> bool:
        with self._lock:
            return bool(self._has_sample)

# -*- coding: utf-8 -*-
"""Load-cell calibration JSON parsing shared by GUI readers and ROS nodes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .phidget_support import GRAVITY


def normalize_calibration_channels(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return calibration entries as a channels mapping keyed by string channel id."""
    if not isinstance(data, dict):
        return {}

    channels = data.get("channels")
    if isinstance(channels, dict):
        return {
            str(channel): cal
            for channel, cal in channels.items()
            if isinstance(cal, dict)
        }

    # Legacy single-channel format used by early calibration tools.
    if "scale" in data and "offset" in data:
        return {"0": {"scale_n": data["scale"], "offset_n": data["offset"]}}

    return {}


def load_calibration_channels(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read a calibration JSON file and return normalized channel entries."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    channels = normalize_calibration_channels(data)
    if not channels:
        raise ValueError("channels 항목이 없는 캘리브레이션 파일입니다.")
    return channels


def calibration_to_grams(calibration: dict[str, Any]) -> tuple[float, float]:
    """Convert a channel calibration entry to gram-based scale/offset."""
    if "scale_g" in calibration and "offset_g" in calibration:
        return float(calibration["scale_g"]), float(calibration["offset_g"])
    if "scale_n" in calibration and "offset_n" in calibration:
        return (
            float(calibration["scale_n"]) / GRAVITY * 1000.0,
            float(calibration["offset_n"]) / GRAVITY * 1000.0,
        )
    raise KeyError("scale_g/offset_g 또는 scale_n/offset_n 없음")


def select_channel_calibration(
    target_channel: int,
    channels: dict[str, dict[str, Any]],
) -> Optional[tuple[str, dict[str, Any], bool]]:
    """Select calibration for a target channel.

    Returns (source_key, calibration, copied_from_single_channel). If the file has
    exactly one channel, that entry is reused for other target channels to match
    the existing GUI/node behavior.
    """
    target_key = str(int(target_channel))
    if target_key in channels:
        return target_key, channels[target_key], False
    if len(channels) == 1:
        source_key = next(iter(channels.keys()))
        return source_key, channels[source_key], True
    return None


__all__ = [
    "calibration_to_grams",
    "load_calibration_channels",
    "normalize_calibration_channels",
    "select_channel_calibration",
]

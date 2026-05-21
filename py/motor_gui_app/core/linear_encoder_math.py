# -*- coding: utf-8 -*-
"""Linear encoder count/mm conversion helpers shared by GUI and ROS nodes."""
from __future__ import annotations


MIN_COUNTS_PER_MM = 0.001


def normalize_counts_per_mm(counts_per_mm: float) -> float:
    """Clamp count/mm calibration to a positive, nonzero value."""
    return max(MIN_COUNTS_PER_MM, float(counts_per_mm))


def position_count(raw_count: int, zero_raw: int, invert: bool = False) -> int:
    """Return zero-adjusted encoder count with optional sign inversion."""
    sign = -1 if bool(invert) else 1
    return int(sign * (int(raw_count) - int(zero_raw)))


def position_mm(
    raw_count: int,
    zero_raw: int,
    counts_per_mm: float,
    invert: bool = False,
) -> float:
    """Return zero-adjusted linear position in millimeters."""
    count = position_count(raw_count, zero_raw, invert)
    return float(count) / normalize_counts_per_mm(counts_per_mm)


__all__ = [
    "MIN_COUNTS_PER_MM",
    "normalize_counts_per_mm",
    "position_count",
    "position_mm",
]

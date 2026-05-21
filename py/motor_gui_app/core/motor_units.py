# -*- coding: utf-8 -*-
"""Motor position unit conversion helpers shared by GUI actions and logic."""
from __future__ import annotations


MIN_LEAD_MM_REV = 1.0e-9
MIN_TICKS_PER_REV = 1.0


def normalize_lead_mm_rev(lead_mm_rev: float) -> float:
    """Return a positive screw lead value in mm/rev."""
    return max(float(lead_mm_rev), MIN_LEAD_MM_REV)


def normalize_ticks_per_rev(ticks_per_rev: int | float) -> float:
    """Return a positive encoder resolution in ticks/rev."""
    return max(float(ticks_per_rev), MIN_TICKS_PER_REV)


def ticks_per_mm(ticks_per_rev: int | float, lead_mm_rev: float) -> float:
    """Return encoder ticks per linear millimeter."""
    return normalize_ticks_per_rev(ticks_per_rev) / normalize_lead_mm_rev(lead_mm_rev)


def ticks_to_mm(ticks: int | float, ticks_per_rev: int | float, lead_mm_rev: float) -> float:
    """Convert motor encoder ticks to linear millimeters."""
    return float(ticks) / ticks_per_mm(ticks_per_rev, lead_mm_rev)


def mm_to_ticks(mm: int | float, ticks_per_rev: int | float, lead_mm_rev: float) -> int:
    """Convert linear millimeters to rounded motor encoder ticks."""
    return int(round(float(mm) * ticks_per_mm(ticks_per_rev, lead_mm_rev)))


__all__ = [
    "MIN_LEAD_MM_REV",
    "MIN_TICKS_PER_REV",
    "mm_to_ticks",
    "normalize_lead_mm_rev",
    "normalize_ticks_per_rev",
    "ticks_per_mm",
    "ticks_to_mm",
]

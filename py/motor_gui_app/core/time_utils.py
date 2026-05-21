# -*- coding: utf-8 -*-
"""로그와 상태 표시에서 쓰는 작은 시간 유틸."""
import time


def now_str() -> str:
    """현재 시각을 HH:MM:SS 문자열로 반환."""
    return time.strftime("%H:%M:%S")


__all__ = ["now_str"]

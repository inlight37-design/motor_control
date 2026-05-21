# -*- coding: utf-8 -*-
"""한 실행 세션에서 공유하는 제어/상태/플래그 컨테이너."""
from dataclasses import dataclass
from typing import Optional

from .flags import SessionFlags
from .state_view import StateView


@dataclass
class MotorSession:
    """GUI와 CLI가 공통으로 붙잡을 최상위 세션 객체."""

    control: object
    state: Optional[StateView]
    flags: SessionFlags
    hysteresis: Optional[object] = None

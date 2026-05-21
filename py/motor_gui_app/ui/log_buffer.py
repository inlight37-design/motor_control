# -*- coding: utf-8 -*-
"""GUI 로그 버퍼와 flush 타이머 컨테이너."""
from collections import deque
from dataclasses import dataclass, field


@dataclass
class LogBuffer:
    """로그 메시지 큐와 주기적 flush 타이머를 함께 보관."""

    messages: deque = field(default_factory=lambda: deque(maxlen=5000))
    timer: object = None

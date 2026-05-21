# -*- coding: utf-8 -*-
"""Small first-order IIR/EMA filter shared by load-cell readers and nodes."""
from __future__ import annotations


class IIRFilter:
    """1차 IIR 저역통과 필터.

    y[n] = alpha * x[n] + (1 - alpha) * y[n-1]
    alpha가 작을수록 출력이 부드럽지만 반응이 느려진다.
    """

    def __init__(self, alpha: float = 0.1):
        self.alpha = float(alpha)
        self._prev = None

    def process(self, value: float) -> float:
        """새 샘플을 필터링하여 반환. 첫 샘플은 그대로 통과시킨다."""
        value = float(value)
        if self._prev is None:
            self._prev = value
            return value
        out = self.alpha * value + (1.0 - self.alpha) * self._prev
        self._prev = out
        return out

    def reset(self) -> None:
        """필터 상태를 초기화한다."""
        self._prev = None


__all__ = ["IIRFilter"]

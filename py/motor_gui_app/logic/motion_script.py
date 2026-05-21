# -*- coding: utf-8 -*-
"""사용자 모션 스크립트 로드와 유효성 검사."""
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

class MotionScriptError(RuntimeError):
    """모션 스크립트 로드/실행 중 발생하는 에러를 구분하기 위한 예외 클래스."""
    pass

@dataclass
class MotionScript:
    """로드된 모션 스크립트 인스턴스.

    속성:
        path: 스크립트 파일 경로
        func: target_rpm(t, state) → float 함수 (매 주기 호출됨)
        state: 스크립트가 자유롭게 사용하는 상태 딕셔너리 (init()에서 초기화)
    """
    path: str
    func: Callable[[float, Dict[str, Any]], float]
    state: Dict[str, Any]

    @staticmethod
    def load(path: str) -> "MotionScript":
        """파일에서 모션 스크립트를 로드하고 유효성을 검증.

        스크립트 파일은 반드시 target_rpm(t, state) 함수를 정의해야 하며,
        선택적으로 init(state) 함수를 정의하여 초기 상태를 설정할 수 있다.
        """
        if not os.path.exists(path):
            raise MotionScriptError("파일 없음")
        code = Path(path).read_text(encoding="utf-8")
        # exec()로 스크립트를 실행하여 함수를 추출 — math 모듈을 기본 제공
        g = {"__file__": path, "__name__": "__motion_script__", "math": math}
        l = {}
        try:
            exec(compile(code, path, "exec"), g, l)
        except Exception as e:
            raise MotionScriptError(f"문법 오류: {e}")
        # local namespace와 global namespace 양쪽에서 함수를 찾음
        init_fn = l.get("init", g.get("init"))
        target_fn = l.get("target_rpm", g.get("target_rpm"))
        if not callable(target_fn):
            raise MotionScriptError("target_rpm(t, state) 함수 없음")
        state = {}
        if callable(init_fn):
            try:
                init_fn(state)
            except Exception as e:
                raise MotionScriptError(f"init() 오류: {e}")
        return MotionScript(path=path, func=target_fn, state=state)


# ══════════════════════════════════════════════════════════════════════
# CommandThread — 제어 명령 발행 스레드 (200Hz 루프 + Heartbeat 10Hz)
# ══════════════════════════════════════════════════════════════════════
# [역할]
#   - 목표 속도(RPM), 위치(tick), 토크(‰)를 ROS2 토픽으로 주기적 발행
#   - 파형 생성 명령, CSV 로깅 명령, 힘 제어 명령을 C++ 노드에 전달
#   - Heartbeat를 10Hz로 발행하여 C++ 노드가 GUI 생존을 확인 가능
#   - 로드셀 힘 값을 200Hz로 발행하여 C++ 노드의 힘 제어에 활용
#
# [데이터 흐름]
#   MasterWindow(사용자 입력) → set_manual_target_rpm() 등 → _lock 보호 멤버 변수
#   → run() 루프에서 읽어서 → ROS2 publish → C++ 노드
#
# [동작 모드]
#   - "manual": GUI 스핀박스에서 설정한 목표값을 그대로 발행
#   - "script": 사용자 Python 스크립트가 계산한 RPM을 발행
#   - "waveform": C++ 노드 측에서 파형을 생성 (Python은 명령만 전달)
# ══════════════════════════════════════════════════════════════════════

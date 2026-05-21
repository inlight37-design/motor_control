# -*- coding: utf-8 -*-
"""C++ EPOS 모터 노드 서브프로세스 실행 관리."""
import os
import signal
import subprocess
import time
from typing import List, Optional

from PyQt5.QtCore import QThread, pyqtSignal

from .config import DEFAULT_RT_CPU
from .motor_process import build_motor_cmd
from .time_utils import now_str
from .topics import EPOS_NODE_EXECUTABLE

class NodeRunner(QThread):
    # Qt 시그널: 다른 스레드에서 GUI 스레드로 안전하게 메시지 전달
    log_signal = pyqtSignal(str)    # C++ 노드의 stdout 출력을 GUI 로그에 전달
    state_signal = pyqtSignal(bool) # 노드 실행 상태 변경 알림 (True=시작, False=종료)

    def __init__(self, iface: str):
        super().__init__()
        self.iface = iface              # EtherCAT 네트워크 인터페이스 이름
        self.rt_cpu = DEFAULT_RT_CPU    # RT 스레드 고정 CPU 코어 번호
        self.process: Optional[subprocess.Popen] = None  # C++ 노드 프로세스 핸들
        self.running = False            # 실행 중 플래그

    @staticmethod
    def _looks_like_node_process(cmdline: str) -> bool:
        """명령행이 EPOS 모터 노드 실행 프로세스인지 보수적으로 판별."""
        padded = f" {cmdline} "
        return (
            f" {EPOS_NODE_EXECUTABLE} " in padded
            or f"/{EPOS_NODE_EXECUTABLE} " in padded
            or padded.rstrip().endswith(f"/{EPOS_NODE_EXECUTABLE}")
        )

    @classmethod
    def _existing_node_pids(cls) -> List[int]:
        """현재 PC에 남아 있는 EPOS 모터 노드 후보 PID 목록."""
        result = subprocess.run(
            ["pgrep", "-af", EPOS_NODE_EXECUTABLE],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if result.returncode != 0:
            return []

        current_pid = os.getpid()
        pids: List[int] = []
        for line in result.stdout.splitlines():
            try:
                pid_text, cmdline = line.split(maxsplit=1)
                pid = int(pid_text)
            except ValueError:
                continue

            if pid == current_pid:
                continue
            if cls._looks_like_node_process(cmdline):
                pids.append(pid)
        return pids

    @classmethod
    def _has_existing_node_process(cls) -> bool:
        """현재 PC에 남아 있는 EPOS 모터 노드 후보가 있는지 확인."""
        return bool(cls._existing_node_pids())

    @classmethod
    def _signal_existing_nodes(cls, sig: int):
        """남아 있는 EPOS 모터 노드 후보 PID에만 종료 신호를 보냄."""
        pids = cls._existing_node_pids()
        if not pids:
            return
        subprocess.run(
            ["sudo", "kill", f"-{int(sig)}", *[str(pid) for pid in pids]],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _wait_until_existing_nodes_exit(cls, timeout_s: float) -> bool:
        """종료 신호 이후 기존 노드가 실제로 사라질 때까지 짧게 대기."""
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if not cls._has_existing_node_process():
                return True
            time.sleep(0.05)
        return not cls._has_existing_node_process()

    @classmethod
    def _cleanup_existing_nodes(cls):
        """이전 실행에서 남은 C++ 노드를 단계적으로 정리."""
        for sig, wait_s in [(signal.SIGINT, 0.8), (signal.SIGTERM, 0.6), (signal.SIGKILL, 0.3)]:
            if not cls._has_existing_node_process():
                return
            cls._signal_existing_nodes(sig)
            if cls._wait_until_existing_nodes_exit(wait_s):
                return

    def _stop_process_group(self):
        """현재 GUI가 시작한 프로세스 그룹을 poll 확인 후 단계적으로 종료."""
        proc = self.process
        if not proc or proc.poll() is not None:
            return

        try:
            pgid = os.getpgid(proc.pid)
        except Exception:
            pgid = None

        for sig, wait_s in [(signal.SIGINT, 0.8), (signal.SIGTERM, 0.6)]:
            if proc.poll() is not None:
                return
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                else:
                    proc.send_signal(sig)
                proc.wait(timeout=wait_s)
                return
            except subprocess.TimeoutExpired:
                continue
            except ProcessLookupError:
                return
            except Exception:
                break

        if proc.poll() is None:
            try:
                if pgid is not None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    proc.kill()
                proc.wait(timeout=0.5)
            except Exception:
                pass

    def set_iface(self, iface: str):
        """인터페이스 이름 변경 — 노드 실행 전에만 호출해야 함."""
        self.iface = iface

    def set_rt_cpu(self, rt_cpu: int):
        """RT CPU 코어 번호 변경 — 노드 실행 전에만 호출해야 함."""
        self.rt_cpu = rt_cpu

    def run(self):
        """QThread 진입점 — C++ 노드를 실행하고 stdout을 모니터링.

        시작 전에 기존 좀비 프로세스를 SIGINT → SIGTERM → SIGKILL 순으로 정리한다.
        이는 이전 실행이 비정상 종료된 경우 포트 충돌을 방지하기 위함.
        """
        self._cleanup_existing_nodes()

        self.running = True
        self.state_signal.emit(True)  # GUI에 "시작됨" 알림
        cmd = build_motor_cmd(self.iface, self.rt_cpu)
        self.log_signal.emit(f"[{now_str()}] {EPOS_NODE_EXECUTABLE} 실행: iface={self.iface}")

        # sudo 프로세스를 새 프로세스 그룹으로 생성 (os.setsid)
        # — 종료 시 SIGINT를 프로세스 그룹 전체에 보내기 위함
        self.process = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, preexec_fn=os.setsid, env=os.environ.copy())

        # C++ 노드의 stdout을 한 줄씩 읽어 GUI 로그에 전달
        while self.running:
            if self.process.poll() is not None:
                break  # 프로세스가 이미 종료됨
            line = self.process.stdout.readline() if self.process.stdout else ""
            if line:
                self.log_signal.emit(line.rstrip())

        self.running = False
        self.state_signal.emit(False)  # GUI에 "종료됨" 알림

    def stop(self):
        """C++ 노드를 안전하게 종료.

        SIGINT → SIGTERM → SIGKILL 순서로 시도하여,
        C++ 노드가 EtherCAT 연결을 정상적으로 해제할 시간을 준다.
        """
        self.running = False
        self._stop_process_group()
        self._cleanup_existing_nodes()
        self.quit()
        self.wait()  # QThread 완전 종료 대기


# ══════════════════════════════════════════════════════════════════════
# MotionScript — 사용자 정의 Python 모션 스크립트 로더
# ── 사용자가 작성한 .py 파일에서 target_rpm(t, state) 함수를 추출하여
#    CommandThread에서 주기적으로 호출, 복잡한 모션 프로파일을 실행
# ══════════════════════════════════════════════════════════════════════

# -*- coding: utf-8 -*-
"""GUI 없이 쓰는 최소 모터 제어 CLI.

코드 흐름
--------
  터미널 명령
      -> argparse subcommand
          -> ControlClient 또는 StateView
              -> CommandThread / MonitorThread
                  -> ROS2 토픽
                      -> C++ epos_motor_node

이 파일은 PyQt 위젯을 만들지 않는다. 그래서 GUI가 없어도 C++ 노드가 이미 떠
있다면 상태 확인, 정지, 짧은 수동 RPM/위치 명령을 터미널에서 보낼 수 있다.
"""
from __future__ import annotations

import argparse
import shlex
import sys
import time
import threading
from collections import deque
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from typing import Iterator

from ..core.config import (
    DEFAULT_CMD_HZ,
    DEFAULT_HEARTBEAT_TIMEOUT_MS,
    DEFAULTS_LOAD_ERROR,
    LOG_DIR,
    MAX_RPM,
    WORKSPACE_DIR,
    config_summary,
    defaults_loaded,
)
from ..core.control_client import ControlClient
from ..core.experiments import HysteresisExperiment, HysteresisExperimentSettings
from ..core.ros_bootstrap import prepare_ros_environment
from ..core.session import MotorSession, SessionFlags, StateView
from ..core.time_utils import now_str

_rclpy = None


def _load_rclpy():
    """ROS2 Python 모듈을 필요할 때 import한다.

    이렇게 해야 `--help`처럼 ROS2 통신을 실제로 쓰지 않는 CLI 경로가
    ROS 환경 source 여부와 무관하게 동작한다.
    """
    global _rclpy
    if _rclpy is not None:
        return _rclpy
    prepare_ros_environment()
    try:
        _rclpy = import_module("rclpy")
    except ImportError as exc:
        raise RuntimeError(
            "rclpy를 찾을 수 없습니다. 먼저 `source /opt/ros/jazzy/setup.bash`를 실행하거나 "
            "루트 `run_cli.py`처럼 ROS2 Python 경로가 잡힌 환경에서 실행해주세요."
        ) from exc
    return _rclpy


def _init_rclpy() -> bool:
    """rclpy를 필요할 때만 초기화하고, 우리가 초기화했는지 반환."""
    rclpy = _load_rclpy()
    if rclpy.ok():
        return False
    rclpy.init(args=None)
    return True


def _shutdown_rclpy(initialized_here: bool) -> None:
    rclpy = _load_rclpy()
    if initialized_here and rclpy.ok():
        rclpy.shutdown()


def _wait_until(condition, timeout_s: float, label: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise RuntimeError(f"{label} 준비 시간 초과")


@contextmanager
def command_session(cmd_hz: int = DEFAULT_CMD_HZ) -> Iterator[MotorSession]:
    """명령 발행용 세션. ControlClient만 필요할 때 사용."""
    initialized_here = _init_rclpy()
    from ..core.commander import CommandThread

    commander = CommandThread(cmd_hz=cmd_hz)
    control = ControlClient(commander)
    session = MotorSession(control=control, state=None, flags=SessionFlags())
    commander.start()
    try:
        _wait_until(lambda: commander.node is not None and commander.pub is not None, 2.0, "CommandThread")
        yield session
    finally:
        commander.stop()
        _shutdown_rclpy(initialized_here)


@contextmanager
def status_session() -> Iterator[StateView]:
    """상태 조회용 세션. 명령 퍼블리셔를 띄우지 않는다."""
    initialized_here = _init_rclpy()
    from ..core.monitor import MonitorThread

    speed_queue = deque()
    rt_queue = deque()
    monitor = MonitorThread(speed_queue, rt_queue)
    state = StateView(monitor)
    monitor.start()
    try:
        _wait_until(lambda: monitor.node is not None, 2.0, "MonitorThread")
        yield state
    finally:
        monitor.stop()
        _shutdown_rclpy(initialized_here)


class CliRuntime:
    """대화형 CLI에서 유지되는 공용 제어 세션.

    한 줄 명령은 실행 후 바로 종료해도 되지만, interactive shell은 사용자가
    여러 명령을 이어서 입력한다. 이때 CommandThread/MonitorThread를 매번
    새로 만들면 토픽 연결 지연도 생기고 흐름도 보기 어렵다. 그래서 shell
    안에서는 이 객체가 GUI와 비슷하게 제어/상태 스레드를 계속 잡고 있는다.
    """

    def __init__(self, cmd_hz: int = DEFAULT_CMD_HZ):
        self.cmd_hz = int(cmd_hz)
        self.initialized_here = False
        self.speed_queue = deque()
        self.rt_queue = deque()
        self.commander = None
        self.monitor = None
        self.control = None
        self.state = None
        self.session = None

    def __enter__(self) -> "CliRuntime":
        self.initialized_here = _init_rclpy()
        from ..core.commander import CommandThread
        from ..core.monitor import MonitorThread

        self.commander = CommandThread(cmd_hz=self.cmd_hz)
        self.monitor = MonitorThread(self.speed_queue, self.rt_queue)
        self.control = ControlClient(self.commander)
        self.state = StateView(self.monitor)
        flags = SessionFlags()
        self.session = MotorSession(control=self.control, state=self.state, flags=flags)
        self.session.hysteresis = HysteresisExperiment(
            self.control,
            flags,
            _threading_scheduler,
        )

        try:
            self.commander.start()
            self.monitor.start()
            _wait_until(
                lambda: self.commander.node is not None and self.commander.pub is not None,
                2.0,
                "CommandThread",
            )
            _wait_until(lambda: self.monitor.node is not None, 2.0, "MonitorThread")
        except Exception:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.session and self.session.hysteresis and self.session.flags.hyst_test_running:
            self.session.hysteresis.abort("CLI 종료")
            time.sleep(0.2)
        if self.control:
            try:
                self.control.emergency_stop()
                time.sleep(0.1)
            except Exception:
                pass
        if self.commander:
            self.commander.stop()
        if self.monitor:
            self.monitor.stop()
        _shutdown_rclpy(self.initialized_here)


def _runtime(args: argparse.Namespace) -> CliRuntime | None:
    return getattr(args, "_runtime", None)


@contextmanager
def _resolve_command_session(
    args: argparse.Namespace,
    cmd_hz: int = DEFAULT_CMD_HZ,
) -> Iterator[tuple[MotorSession, bool]]:
    """interactive runtime이 있으면 재사용하고, 없으면 one-shot 세션을 만든다."""
    runtime = _runtime(args)
    if runtime is not None:
        yield runtime.session, False
        return

    with command_session(cmd_hz=int(cmd_hz)) as session:
        yield session, True


def _print_state(state: StateView) -> None:
    print(
        "state={state} sw=0x{sw:04X} err=0x{err:04X} "
        "pos={pos}tick trq={trq}permille "
        "F0={f0:+.3f}N F1={f1:+.3f}N lin={lin:+.3f}mm".format(
            state=state.motor_state_text(),
            sw=state.status_word(),
            err=state.error_code(),
            pos=state.actual_position_ticks(),
            trq=state.actual_torque_permille(),
            f0=state.force_n(0),
            f1=state.force_n(1),
            lin=state.linear_mm(),
        ),
        flush=True,
    )


def cmd_status(args: argparse.Namespace) -> int:
    """모터/센서 최신 상태를 터미널에 출력."""
    period = 1.0 / max(float(args.hz), 0.1)
    duration = max(float(args.seconds), 0.0)
    deadline = time.time() + duration

    runtime = _runtime(args)
    if runtime is not None:
        state = runtime.session.state
        time.sleep(float(args.warmup))
        while True:
            _print_state(state)
            if duration == 0.0 or time.time() >= deadline:
                break
            time.sleep(period)
        return 0

    with status_session() as state:
        # 첫 토픽 수신 시간을 조금 준다.
        time.sleep(float(args.warmup))
        while True:
            _print_state(state)
            if duration == 0.0 or time.time() >= deadline:
                break
            time.sleep(period)
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """ROS2 세션 없이 현재 설정 경로와 핵심 기본값을 출력."""
    print(config_summary())
    print(f"workspace={WORKSPACE_DIR}")
    print(f"log_dir={LOG_DIR}")
    print(f"max_rpm={MAX_RPM}")
    print(f"cmd_hz={DEFAULT_CMD_HZ}")
    print(f"heartbeat_timeout_ms={DEFAULT_HEARTBEAT_TIMEOUT_MS}")
    if DEFAULTS_LOAD_ERROR:
        print("defaults.json을 읽지 못해 코드 내 fallback 기본값을 사용 중입니다.", file=sys.stderr)
    return 0 if defaults_loaded() or not bool(args.strict) else 1


def cmd_stop(args: argparse.Namespace) -> int:
    """파형/힘제어/RPM/토크를 안전 기본값으로 되돌리는 정지 명령."""
    with _resolve_command_session(args) as (session, owned_session):
        session.control.emergency_stop()
        if owned_session:
            time.sleep(0.35)
    print("stop command sent")
    return 0


def cmd_rpm(args: argparse.Namespace) -> int:
    """짧은 시간 동안 수동 RPM 명령을 발행한 뒤 정지."""
    seconds = max(float(args.seconds), 0.05)
    with _resolve_command_session(args, cmd_hz=int(args.cmd_hz)) as (session, owned_session):
        session.control.set_operation_mode(9)
        session.control.set_rpm_limit(abs(float(args.limit_rpm)))
        session.control.set_manual_rpm(float(args.rpm))
        print(f"rpm={args.rpm:g} for {seconds:g}s")
        try:
            time.sleep(seconds)
        finally:
            session.control.set_manual_rpm(0.0)
        if owned_session:
            time.sleep(0.2)
    return 0


def cmd_position(args: argparse.Namespace) -> int:
    """tick 단위 위치 명령을 보낸 뒤 잠깐 유지."""
    seconds = max(float(args.seconds), 0.1)
    with _resolve_command_session(args, cmd_hz=int(args.cmd_hz)) as (session, _owned_session):
        session.control.set_operation_mode(8)
        session.control.move_to_position_ticks(args.ticks, speed_ticks_per_s=args.speed)
        print(f"position={args.ticks}tick speed={args.speed}tick/s hold={seconds:g}s")
        time.sleep(seconds)
    return 0


def _threading_scheduler(delay_ms: int, callback) -> None:
    timer = threading.Timer(max(float(delay_ms), 0.0) / 1000.0, callback)
    timer.daemon = True
    timer.start()


def cmd_hyst_velocity(args: argparse.Namespace) -> int:
    """CLI에서 속도 사인 기반 히스테리시스 테스트를 실행."""
    log_path = Path(args.log_path) if args.log_path else (
        LOG_DIR / f"hyst_cli_{now_str().replace(':', '')}.csv"
    )
    settings = HysteresisExperimentSettings(
        motion_mode="velocity",
        freq_hz=float(args.freq),
        amp_rpm=float(args.amp_rpm),
        offset_rpm=float(args.offset_rpm),
        settle_cycles=int(args.settle_cycles),
        record_cycles=int(args.record_cycles),
        log_path=log_path,
        requested_amp=float(args.amp_rpm),
        amp_unit="rpm",
    )
    done = threading.Event()

    with _resolve_command_session(args, cmd_hz=int(args.cmd_hz)) as (session, _owned_session):
        if session.hysteresis is None:
            session.hysteresis = HysteresisExperiment(session.control, session.flags, _threading_scheduler)
        experiment = session.hysteresis

        def on_status(status):
            print(f"[{status.phase}] file={status.log_path} reason={status.reason}", flush=True)
            if status.phase in ("done", "aborted"):
                done.set()

        try:
            experiment.start(settings, on_status=on_status)
            timeout_s = (
                settings.start_lead_ms + settings.settle_ms + settings.record_ms + settings.finish_lead_ms
            ) / 1000.0 + 5.0
            if not done.wait(timeout=timeout_s):
                experiment.abort("CLI timeout")
                done.wait(timeout=1.0)
                return 1
        finally:
            if session.flags.hyst_test_running:
                experiment.abort("CLI 종료")
                done.wait(timeout=1.0)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="motor_gui_app.cli",
        description="Motor_gui_jh GUI 없이 쓰는 최소 모터 제어 CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="모터/로드셀/리니어 엔코더 최신 상태 출력")
    p.add_argument("--seconds", type=float, default=0.0, help="출력 시간. 0이면 한 번만 출력")
    p.add_argument("--hz", type=float, default=2.0, help="반복 출력 주파수")
    p.add_argument("--warmup", type=float, default=0.25, help="첫 출력 전 토픽 수신 대기 시간")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("config", help="현재 defaults.json 경로와 주요 기본값 출력")
    p.add_argument("--strict", action="store_true", help="defaults.json 로드 실패 시 종료 코드 1 반환")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("stop", help="파형/힘제어/RPM/토크 정지 명령 전송")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("rpm", help="수동 RPM을 지정 시간 동안 발행한 뒤 0으로 정지")
    p.add_argument("rpm", type=float, help="목표 RPM")
    p.add_argument("--seconds", type=float, default=1.0, help="명령 유지 시간")
    p.add_argument("--limit-rpm", type=float, default=3000.0, help="수동 RPM 절대 제한")
    p.add_argument("--cmd-hz", type=int, default=DEFAULT_CMD_HZ, help="명령 발행 주파수")
    p.set_defaults(func=cmd_rpm)

    p = sub.add_parser("position", help="tick 위치 명령 전송")
    p.add_argument("ticks", type=float, help="목표 위치 [motor tick]")
    p.add_argument("--speed", type=float, default=500.0, help="위치 이동 속도 [tick/s]")
    p.add_argument("--seconds", type=float, default=2.0, help="명령 후 CLI 유지 시간")
    p.add_argument("--cmd-hz", type=int, default=DEFAULT_CMD_HZ, help="명령 발행 주파수")
    p.set_defaults(func=cmd_position)

    p = sub.add_parser("hyst-velocity", help="속도 사인 기반 히스테리시스 테스트 예약")
    p.add_argument("--freq", type=float, required=True, help="사인파 주파수 [Hz]")
    p.add_argument("--amp-rpm", type=float, required=True, help="속도 사인 진폭 [rpm]")
    p.add_argument("--offset-rpm", type=float, default=0.0, help="속도 오프셋 [rpm]")
    p.add_argument("--settle-cycles", type=int, default=1, help="기록 전 안정화 cycle")
    p.add_argument("--record-cycles", type=int, default=3, help="CSV 기록 cycle")
    p.add_argument("--log-path", default="", help="CSV 경로. 비우면 logs/에 자동 생성")
    p.add_argument("--cmd-hz", type=int, default=DEFAULT_CMD_HZ, help="명령 발행 주파수")
    p.set_defaults(func=cmd_hyst_velocity)

    p = sub.add_parser("shell", help="명령을 계속 입력하는 대화형 CLI")
    p.set_defaults(shell=True)

    return parser


def _print_shell_intro(parser: argparse.ArgumentParser) -> None:
    print("Motor_gui_jh interactive CLI")
    print("명령 예시:")
    print("  config")
    print("  status")
    print("  status --seconds 2 --hz 5")
    print("  stop")
    print("  rpm 50 --seconds 1")
    print("  position 4000 --speed 500 --seconds 2")
    print("  hyst-velocity --freq 1 --amp-rpm 50 --settle-cycles 1 --record-cycles 3")
    print("  help")
    print("  exit")
    print()
    _ = parser


def run_shell(parser: argparse.ArgumentParser) -> int:
    """대화형 CLI. 한 번 실행한 터미널 안에서 여러 명령을 입력한다."""
    _print_shell_intro(parser)
    print("ROS2 command/monitor session 준비 중...")
    with CliRuntime() as runtime:
        print("ready")
        while True:
            try:
                line = input("motor> ").strip()
            except EOFError:
                print()
                return 0
            except KeyboardInterrupt:
                print("\nexit")
                return 130

            if not line:
                continue
            if line.lower() in ("exit", "quit", "q"):
                return 0
            if line.lower() in ("help", "?"):
                parser.print_help()
                continue

            try:
                argv = shlex.split(line)
            except ValueError as exc:
                print(f"parse error: {exc}", file=sys.stderr)
                continue

            try:
                args = parser.parse_args(argv)
                if getattr(args, "shell", False):
                    print("이미 interactive shell 안입니다. 종료는 exit를 입력하세요.")
                    continue
                args._runtime = runtime
                int(args.func(args))
            except SystemExit:
                continue
            except KeyboardInterrupt:
                print("\ninterrupted", file=sys.stderr)
                runtime.session.control.emergency_stop()
            except Exception as exc:
                print(f"error: {exc}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        if sys.stdin.isatty():
            return run_shell(parser)
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if getattr(args, "shell", False):
        return run_shell(parser)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""배포 폴더에서 GUI/CLI 런처가 공유하는 환경 설정."""
import os
import sys
from pathlib import Path


def find_distribution_root(start: Path) -> Path | None:
    """py/motor_gui_app와 cpp를 함께 가진 배포 루트를 위쪽으로 찾는다."""
    start = Path(start).resolve()
    for candidate in (start, *start.parents):
        if (candidate / "py" / "motor_gui_app").exists() and (candidate / "cpp").exists():
            return candidate
    return None


def configure_distribution_environment(root_dir: Path) -> None:
    """루트 run_gui.py/run_cli.py가 공통으로 쓰는 환경변수를 설정."""
    root_dir = Path(root_dir).resolve()
    py_dir = root_dir / "py"
    cpp_dir = root_dir / "cpp"
    log_dir = root_dir / "logs"
    defaults_file = py_dir / "motor_gui_app" / "config" / "defaults.json"

    if py_dir.exists() and str(py_dir) not in sys.path:
        sys.path.insert(0, str(py_dir))

    if cpp_dir.exists():
        os.environ.setdefault("EPOS_WORKSPACE_DIR", str(cpp_dir))
        os.environ.setdefault("WS_SETUP", str(cpp_dir / "install" / "setup.bash"))
    os.environ.setdefault("EPOS_LOG_DIR", str(log_dir))
    if defaults_file.exists():
        os.environ.setdefault("EPOS_DEFAULTS_FILE", str(defaults_file))
    log_dir.mkdir(parents=True, exist_ok=True)


__all__ = ["configure_distribution_environment", "find_distribution_root"]

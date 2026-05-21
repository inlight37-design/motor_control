#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Motor_gui_jh 배포 폴더용 GUI 실행 런처."""
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
PY_DIR = ROOT_DIR / "py"

if str(PY_DIR) not in sys.path:
    sys.path.insert(0, str(PY_DIR))

from motor_gui_app.app.launcher_env import configure_distribution_environment  # noqa: E402

configure_distribution_environment(ROOT_DIR)

from motor_gui_app.app.main import main  # noqa: E402


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""motor_gui_app 폴더 안에서 바로 실행하기 위한 런처.

예:
  python3 motor_gui_app/run_gui.py

루트 런처와 같은 배포 환경 설정을 최대한 찾아 적용한 뒤 GUI를 실행한다.
"""
import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PARENT_DIR = APP_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

from motor_gui_app.app.launcher_env import (  # noqa: E402
    configure_distribution_environment,
    find_distribution_root,
)

DIST_ROOT = find_distribution_root(APP_DIR)
if DIST_ROOT is not None:
    configure_distribution_environment(DIST_ROOT)

from motor_gui_app.app.main import main  # noqa: E402


if __name__ == "__main__":
    main()

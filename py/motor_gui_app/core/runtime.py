# -*- coding: utf-8 -*-
"""기존 `from runtime import *` 호출부를 위한 호환 런타임 레이어.

새 코드는 필요한 모듈을 직접 import하는 쪽을 우선한다. 이 파일은 예전 단일
파일 구조에서 쓰던 Qt/ROS/common import 묶음을 유지하기 위해 남겨 두며,
rclpy import 전에 DDS 환경변수도 함께 고정한다.
"""
# ══════════════════════════════════════════════════════════════════════
# 표준 라이브러리 임포트
# ══════════════════════════════════════════════════════════════════════
import sys
import os
import glob
import time
import math
import json
import signal
import shlex
import subprocess
import numpy as np
from collections import deque
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any, List
import threading

from .config import *
from .epos_errors import *
from .topics import *
from .ros_environment import (
    configure_ros_environment,
    detect_interfaces,
    ensure_fastdds_udp_only_profile,
)
from .motor_process import build_motor_cmd, ros_float
from .phidget_support import Encoder, GRAVITY, PHIDGET_AVAILABLE, VoltageRatioInput
from .ros_messages import (
    ForceCtrlCmd,
    FORCE_CTRL_MSG_AVAILABLE,
    WaveformCmd,
    WAVEFORM_MSG_AVAILABLE,
)
from .time_utils import now_str

# ══════════════════════════════════════════════════════════════════════
# ROS2 DDS 환경 설정 — 모듈 임포트 전에 환경 변수를 고정해야 함
# ══════════════════════════════════════════════════════════════════════
# 모듈 로딩 시점에 즉시 실행 — ROS2/rclpy import 전에 DDS 설정이 완료되어야 함
configure_ros_environment()
ensure_fastdds_udp_only_profile()

# ══════════════════════════════════════════════════════════════════════
# ROS2 및 PyQt5 임포트
# ── DDS 환경 설정 완료 후에 rclpy를 임포트해야 올바른 설정이 적용됨
# ══════════════════════════════════════════════════════════════════════
import rclpy
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import Float32, Int32, String
from std_srvs.srv import Trigger

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QDoubleSpinBox, QMessageBox, QFrame, QTextEdit,
    QFileDialog, QSplitter, QSpinBox, QComboBox, QCheckBox,
    QLineEdit, QScrollArea, QSizePolicy
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QTextCursor, QFont
import pyqtgraph as pg

# 안티앨리어싱 비활성화 — 대량의 데이터 포인트를 빠르게 렌더링하기 위함
pg.setConfigOptions(antialias=False)

# -*- coding: utf-8 -*-
"""모듈형 모터 GUI 실행 진입점."""
import sys

from ..core.ros_bootstrap import prepare_ros_environment

prepare_ros_environment()

import rclpy
from PyQt5.QtWidgets import QApplication

from ..ui.main_window import MasterWindow


def main():
    rclpy.init(args=None)
    app = QApplication(sys.argv)
    w = MasterWindow()
    w.show()
    sys.exit(app.exec_())

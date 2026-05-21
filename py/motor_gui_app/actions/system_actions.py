# -*- coding: utf-8 -*-
"""시스템 시작/종료, Fault 복구, 종료 정리 동작 헬퍼."""
from PyQt5.QtWidgets import QMessageBox

from ..core.ros_environment import detect_interfaces
from ..core.time_utils import now_str
from . import hysteresis_actions, motion_actions

try:
    import rclpy
except ImportError:
    rclpy = None


def refresh_ifaces(window):
    """EtherCAT 인터페이스 목록을 다시 감지하여 콤보박스를 갱신."""
    top_status = window.top_status_widgets
    current = top_status.iface_combo.currentText()
    top_status.iface_combo.clear()
    ifaces = detect_interfaces()
    for iface in ifaces:
        top_status.iface_combo.addItem(iface)
    if current in ifaces:
        top_status.iface_combo.setCurrentText(current)
    window.update_log(f"[{now_str()}] 인터페이스 감지: {ifaces}")


def on_fault_state(window, is_fault: bool):
    """Fault 상태에 따라 Fault Reset 버튼 표시를 갱신."""
    window.top_status_widgets.fault_reset_button.setVisible(is_fault)


def resend_after_fault(window):
    """Fault 복구 후 현재 GUI 목표값을 필요한 모드에 맞게 재전송."""
    mode_index = window.position_torque_widgets.mode_combo.currentIndex()
    if mode_index == 1:
        motion_actions.send_manual_pos(window)
        window.update_log(f"[{now_str()}] Fault 복구 -> 위치 재전송")
    elif mode_index == 2:
        motion_actions.send_manual_trq(window)
        window.update_log(f"[{now_str()}] Fault 복구 -> 토크 재전송")


def toggle_motor(window):
    """C++ EPOS 노드 프로세스를 시작하거나 종료."""
    if not window.runtime_threads.node_runner.isRunning():
        start_motor(window)
    else:
        stop_motor(window)


def start_motor(window):
    """C++ EPOS 노드 프로세스 시작."""
    top_status = window.top_status_widgets
    iface = top_status.iface_combo.currentText()
    if not iface:
        QMessageBox.warning(window, "오류", "인터페이스를 선택해주세요.")
        return

    window.runtime_threads.node_runner.set_iface(iface)
    window.runtime_threads.node_runner.set_rt_cpu(top_status.rt_cpu_spin.value())
    top_status.iface_combo.setEnabled(False)
    top_status.rt_cpu_spin.setEnabled(False)
    window.runtime_threads.node_runner.start()
    top_status.motor_button.setText("종료")
    top_status.motor_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
    top_status.status_label.setText("부팅...")
    top_status.status_label.setStyleSheet("color: orange;")


def stop_motor(window):
    """C++ EPOS 노드 프로세스 종료와 GUI 안전 기본값 복귀."""
    top_status = window.top_status_widgets
    if window.hyst_test_running:
        hysteresis_actions.abort_test(window, reason="시스템 종료")

    window.runtime_threads.node_runner.stop()
    top_status.iface_combo.setEnabled(True)
    top_status.rt_cpu_spin.setEnabled(True)
    top_status.motor_button.setText("시스템 시작")
    top_status.motor_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
    top_status.status_label.setText("OFF")
    top_status.status_label.setStyleSheet("color: red;")

    position_torque = window.position_torque_widgets
    position_torque.mode_combo.setCurrentIndex(0)
    window.manual_motion_widgets.rpm_spin.setValue(0)
    position_torque.pos_spin.setValue(0)
    position_torque.trq_spin.setValue(0)
    window.session.control.set_operation_mode(9)
    window.session.control.set_manual_rpm(0)


def on_motor_state(window, running: bool):
    """NodeRunner 실행 상태 변경을 GUI 상태 라벨에 반영."""
    top_status = window.top_status_widgets
    window.motor_running = running
    if running:
        top_status.status_label.setText("ON")
        top_status.status_label.setStyleSheet("color: green;")
        return

    if window.hyst_test_running:
        hysteresis_actions.abort_test(window, reason="모터 노드 종료")
    top_status.status_label.setText("OFF")
    top_status.status_label.setStyleSheet("color: red;")
    top_status.iface_combo.setEnabled(True)


def close_event(window, event):
    """윈도우 닫기 시 로드셀, 리니어 엔코더, 스레드, ROS2를 순서대로 정리."""
    try:
        window.device_readers.load_cell.disconnect()
    except Exception:
        pass
    try:
        window.device_readers.linear_encoder.disconnect()
    except Exception:
        pass
    try:
        window.session.control.emergency_stop()
    except Exception:
        pass
    try:
        if window.runtime_threads.node_runner.isRunning():
            window.runtime_threads.node_runner.stop()
    except Exception:
        pass
    try:
        window.runtime_threads.monitor.stop()
    except Exception:
        pass
    try:
        window.runtime_threads.commander.stop()
    except Exception:
        pass
    try:
        if rclpy is not None and rclpy.ok():
            rclpy.shutdown()
    except Exception:
        pass
    event.accept()

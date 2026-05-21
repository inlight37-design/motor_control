# -*- coding: utf-8 -*-
"""GUI 로그 버퍼와 QTextEdit flush 동작."""
from PyQt5.QtGui import QTextCursor


def update_log(window, msg: str):
    """로그 메시지를 버퍼에 추가한다."""
    window.log_buffer.messages.append(msg)


def flush_log_buffer(window, max_lines: int = 200):
    """로그 버퍼에서 일정 줄 수만 QTextEdit에 flush하여 UI 멈춤을 줄인다."""
    count = 0
    messages = window.log_buffer.messages
    while messages and count < max_lines:
        window.log_viewer.append(messages.popleft())
        count += 1
    if count > 0:
        window.log_viewer.moveCursor(QTextCursor.End)

# -*- coding: utf-8 -*-
"""GUI에서 공유하는 작은 스타일 상수."""

LC_BUTTON_STYLE = """
QPushButton {
    background-color: #37474f;
    color: white;
    padding: 3px 6px;
    border: 1px solid #607d8b;
    border-radius: 3px;
}
QPushButton:pressed {
    background-color: #ffd54f;
    color: #111111;
    border: 2px inset #ffb300;
}
QPushButton:disabled {
    background-color: #263238;
    color: #78909c;
    border: 1px solid #455a64;
}
"""

LC_BUTTON_OK_STYLE = (
    "background-color: #2e7d32; color: white; padding: 3px 6px; "
    "border: 1px solid #81c784; border-radius: 3px;"
)
LC_BUTTON_ERR_STYLE = (
    "background-color: #b71c1c; color: white; padding: 3px 6px; "
    "border: 1px solid #ef5350; border-radius: 3px;"
)


__all__ = ["LC_BUTTON_ERR_STYLE", "LC_BUTTON_OK_STYLE", "LC_BUTTON_STYLE"]

"""中文输入小窗（功能2 的主入口）。

为什么要有这个窗口：Deadlock 里用输入法直接打中文曾经把游戏搞崩
（SDL_windowskeyboard.c 相关的崩溃报告），所以中文输入放在我们自己的
Qt 窗口里（IME 天然支持），打完回车再翻译注入游戏。

焦点顺序很重要：我们的窗口先拿到焦点 -> 用户打完字 -> 窗口隐藏并把焦点
还给游戏 -> 才注入。否则游戏聊天框会被"失焦"关掉。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import Config


class ChatInputBox(QWidget):
    submitted = Signal(str, bool)  # (中文文本, 是否自动发送)

    def __init__(self, cfg: Config, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.cfg = cfg
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedWidth(620)
        self._build()
        self.hide()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        self.setStyleSheet(
            "QWidget { background: #14161f; border: 2px solid #2f3542; border-radius: 12px; }"
            "QLabel { color: #9aa4b2; border: none; }"
            "QLineEdit { background: #1d212c; color: #f5f6fa; border: 1px solid #2f3542;"
            " border-radius: 8px; padding: 8px 10px; }"
            "QPushButton { background: #2b6cb0; color: white; border: none;"
            " border-radius: 8px; padding: 7px 14px; font-weight: 600; }"
            "QPushButton:hover { background: #3182ce; }"
            "QCheckBox { color: #9aa4b2; border: none; }"
        )

        self._edit = QLineEdit()
        self._edit.setFont(QFont("Microsoft YaHei", 13))
        self._edit.setPlaceholderText("打中文，回车翻译成英文并注入游戏（Esc 取消）")
        self._edit.returnPressed.connect(self._on_submit)
        root.addWidget(self._edit)

        row = QHBoxLayout()
        self._auto_send = QCheckBox("翻译后自动发送")
        self._auto_send.setChecked(bool(self.cfg.input.auto_send))
        row.addWidget(self._auto_send)
        row.addStretch()
        self._hint = QLabel("")
        row.addWidget(self._hint)
        self._send_btn = QPushButton("翻译并注入")
        self._send_btn.clicked.connect(self._on_submit)
        row.addWidget(self._send_btn)
        root.addLayout(row)

    # ---- 对外 ----

    def summon(self) -> None:
        self._refresh_hint()
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.adjustSize()
            self.move((geo.width() - self.width()) // 2, int(geo.height() * 0.72))
        self.show()
        self.raise_()
        self.activateWindow()
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)
        self._edit.selectAll()

    def _refresh_hint(self) -> None:
        level = self.cfg.input.level
        if self.cfg.app.read_only:
            text = "只读模式：仅复制英文到剪贴板"
        else:
            text = {"L1": "L1 注入并自动发送", "L2": "L2 注入但不发送",
                    "L3": "L3 只复制到剪贴板"}.get(level, level)
        self._hint.setText(text)

    def _on_submit(self) -> None:
        text = self._edit.text().strip()
        if not text:
            return
        auto_send = self._auto_send.isChecked()
        self._edit.clear()
        self.hide()
        self.submitted.emit(text, auto_send)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            return
        super().keyPressEvent(event)

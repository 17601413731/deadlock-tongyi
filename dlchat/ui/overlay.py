"""游戏内悬浮窗：点击穿透、置顶、只显示译文。

复用 fanyi-v5 subtitle_overlay 的思路（无边框 + WindowTransparentForInput +
按内容自适应高度），这里多了：锚点选择、透明度、自动淡出、双语模式。
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QGuiApplication, QPainter, QColor, QPainterPath
from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..config import DisplaySection


class ChatOverlay(QWidget):
    def __init__(self, cfg: DisplaySection):
        super().__init__()
        self.cfg = cfg
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setWindowOpacity(max(0.2, min(1.0, cfg.opacity)))
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self._label = QLabel("")
        self._label.setFont(QFont(cfg.font_family, cfg.font_size, QFont.Weight.Bold))
        self._label.setStyleSheet("color: #ffffff; background: transparent;")
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._lines: deque[str] = deque(maxlen=max(1, cfg.max_lines))
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    # ---- 对外 ----

    def show_line(self, original: str, translated: str) -> None:
        if self.cfg.mode == "both":
            html = (f'<div style="color:#bdbdbd;font-size:{max(9, self.cfg.font_size - 3)}px">'
                    f'{_esc(original)}</div>'
                    f'<div>{_esc(translated)}</div>')
        else:
            html = _esc(translated)
        self._lines.append(html)
        self._label.setText("<hr style='border:0;border-top:1px solid rgba(255,255,255,0.15)'>"
                            .join(self._lines))
        self._refit()
        if not self.isVisible():
            self.show()
        if self.cfg.hide_after_s > 0:
            self._hide_timer.start(int(self.cfg.hide_after_s * 1000))

    def clear(self) -> None:
        self._lines.clear()
        self._label.clear()
        self.hide()

    def reposition(self) -> None:
        self._refit()

    # ---- 内部 ----

    def _refit(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._label.adjustSize()
        width = 760 if self.cfg.anchor != "custom" else 620
        height = max(28, self._label.sizeHint().height() + 22)
        if self.cfg.anchor == "custom":
            x, y = self.cfg.custom_pos
        elif self.cfg.anchor == "chat":
            # 贴左下聊天区（Deadlock 聊天在左下方）
            x = int(geo.width() * 0.012)
            y = int(geo.height() * 0.64)
            width = int(geo.width() * 0.42)
        else:
            x = (geo.width() - width) // 2
            y = geo.height() - height - 70
        self.setGeometry(x, y, width, height)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        painter.fillPath(path, QColor(12, 14, 22, 170))
        painter.end()


def _esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>"))

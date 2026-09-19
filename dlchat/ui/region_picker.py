"""屏幕区域框选：拖一个矩形，把聊天区圈出来。

坐标按主屏分辨率为基准归一化到 0~1 存进配置，换分辨率不用重设。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget


class RegionPicker(QWidget):
    picked = Signal(list)   # 归一化 [x1, y1, x2, y2]
    cancelled = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._screen_geo: QRect | None = None

    def start(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.cancelled.emit()
            return
        self._screen_geo = screen.geometry()
        self.setGeometry(self._screen_geo)
        self._origin = self._current = None
        self.show()
        self.raise_()
        self.activateWindow()

    # ---- 交互 ----

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        rect = QRect(self._origin, event.position().toPoint()).normalized()
        self.hide()
        if rect.width() < 20 or rect.height() < 12:
            self.cancelled.emit()
            return
        geo = self._screen_geo or self.geometry()
        norm = [
            round(rect.left() / geo.width(), 4),
            round(rect.top() / geo.height(), 4),
            round(rect.right() / geo.width(), 4),
            round(rect.bottom() / geo.height(), 4),
        ]
        self.picked.emit(norm)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            self.cancelled.emit()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        painter.setPen(QPen(QColor(255, 255, 255, 160), 1, Qt.PenStyle.DashLine))
        painter.drawText(24, 40, "拖动鼠标框选聊天区域（Esc 取消）")
        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            painter.setBrush(QColor(79, 195, 247, 60))
            painter.setPen(QPen(QColor(79, 195, 247), 2))
            painter.drawRect(rect)
        painter.end()

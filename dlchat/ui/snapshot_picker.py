"""截图框选：先在游戏里截图，再在静态图上框区域。

为什么不用全屏浮层框选（旧做法，实测不可用）：
  · 无边框全屏游戏会盖住浮层、或抢回焦点，鼠标根本画不出框
  · 我们的窗口一拿到焦点，游戏里的聊天框就关了、聊天气泡也会淡出，
    于是"要框的东西"在框选时根本看不见

正确流程：
  1) 在游戏里把聊天框打开、字打好，按热键（默认 Alt+P）
  2) 工具**立刻**截下整屏（此刻游戏在前台，内容正确）
  3) 你再切回工具，在一张冻结的截图上拖框 —— 想框多久框多久
  4) 现场就能验证：对话框会把你框的区域立刻 OCR 一遍，直接显示读到什么

这个模块还提供"自动找"：按游戏里的占位文字（To (ALL): / 对（所有人）：）
自动定位聊天输入行，用户只需微调。
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
)

from ..capture.ocr import OCREngine
from ..capture.screen import ScreenGrabber
from ..chat.filter import looks_like_chat

logger = logging.getLogger(__name__)

# 游戏里的聊天输入行占位符（用来"自动找输入行"）
PLACEHOLDER_HINTS = ("to (", "to(", "对（", "对(", "说：", "说:")


def capture_full_screen(grabber: ScreenGrabber | None = None) -> np.ndarray | None:
    """截整屏（游戏在前台时调用，越快越好）。"""
    own = grabber is None
    grab = grabber or ScreenGrabber()
    try:
        return grab.grab([0.0, 0.0, 1.0, 1.0])
    finally:
        if own:
            grab.close()


def find_placeholder_lines(ocr: OCREngine, frame: np.ndarray) -> list[tuple]:
    """在截图里找聊天输入行占位符，返回 [(x1,y1,x2,y2,text)]（像素坐标）。"""
    hits = []
    for line in ocr.recognize(frame):
        low = line.text.strip().lower()
        if any(h in low for h in PLACEHOLDER_HINTS) or any(
                h in line.text for h in ("对（", "说：")):
            hits.append((*line.box, line.text))
    return hits


class _ImageCanvas(QLabel):
    """显示截图并支持拖框；坐标换算集中在这里，便于测试。"""

    def __init__(self, frame: np.ndarray, parent=None):
        super().__init__(parent)
        self.frame_h, self.frame_w = frame.shape[:2]
        self._pixmap_full = _to_pixmap(frame)
        self._scale = 1.0
        self.sel: QRect | None = None
        self._origin: QPoint | None = None
        self.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setMouseTracking(True)

    def fit(self, max_w: int, max_h: int) -> None:
        self._scale = min(max_w / self.frame_w, max_h / self.frame_h, 1.0)
        w = max(1, int(self.frame_w * self._scale))
        h = max(1, int(self.frame_h * self._scale))
        self.setFixedSize(w, h)
        self.setPixmap(self._pixmap_full.scaled(
            w, h, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    # ---- 坐标换算（纯函数，测试覆盖）----

    def to_image(self, pos: QPoint) -> QPoint:
        if self._scale <= 0:
            return QPoint(0, 0)
        x = min(max(0, int(pos.x() / self._scale)), self.frame_w)
        y = min(max(0, int(pos.y() / self._scale)), self.frame_h)
        return QPoint(x, y)

    def selection_normalized(self) -> list[float] | None:
        if self.sel is None:
            return None
        r = self.sel.normalized()
        if r.width() < 8 or r.height() < 6:
            return None
        return [round(r.left() / self.frame_w, 4), round(r.top() / self.frame_h, 4),
                round(r.right() / self.frame_w, 4), round(r.bottom() / self.frame_h, 4)]

    def set_selection_pixels(self, x1: int, y1: int, x2: int, y2: int) -> None:
        self.sel = QRect(x1, y1, max(1, x2 - x1), max(1, y2 - y1))
        self.update()

    # ---- 交互 ----

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = self.to_image(event.position().toPoint())
            self.sel = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            cur = self.to_image(event.position().toPoint())
            self.sel = QRect(self._origin, cur)
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._origin = None
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.sel is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._scale
        r = QRect(int(self.sel.left() * s), int(self.sel.top() * s),
                  int(self.sel.width() * s), int(self.sel.height() * s))
        painter.setPen(QPen(QColor(79, 195, 247), 2))
        painter.fillRect(r, QColor(79, 195, 247, 50))
        painter.drawRect(r)
        painter.end()


class SnapshotPickerDialog(QDialog):
    """在截图上框选区域。target: 'input'（聊天输入行）或 'chat'（聊天区）。"""

    def __init__(self, frame: np.ndarray, target: str, ocr: OCREngine | None = None,
                 parent=None):
        super().__init__(parent)
        self.frame = frame
        self._target = target          # 初始模式；之后以 mode_box 为准
        self.ocr = ocr
        self.result_region: list[float] | None = None
        self.result_target: str = target
        self.setWindowTitle("框选聊天输入行" if target == "input" else "框选聊天区域")
        self.setMinimumSize(900, 620)
        self._build()
        if target == "input":
            self._auto_find()          # 输入行可以先自动找一次

    # ---- 构建 ----

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        tip = ("在下面的截图里拖框，圈住聊天输入行（To (ALL): 你打的字 那一行）。"
               if self.target == "input" else
               "在下面的截图里拖框，圈住聊天气泡出现的那一带（顶部头像下方）。")
        head = QHBoxLayout()
        head.addWidget(QLabel("我要框："))
        self.mode_box = QComboBox()
        self.mode_box.addItems(["聊天输入行（我说的话）", "聊天区域（别人说的话）"])
        self.mode_box.setCurrentIndex(0 if self.target == "input" else 1)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        head.addWidget(self.mode_box)
        head.addStretch()
        root.addLayout(head)

        label = QLabel(tip + "\n截图是你在游戏里按热键时抓的，所以聊天内容都在。")
        label.setWordWrap(True)
        root.addWidget(label)

        self.canvas = _ImageCanvas(self.frame)
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(scroll, 1)

        self.status = QLabel("拖框选择区域；框好后点「测试识别」看能不能读到内容")
        self.status.setWordWrap(True)
        self.status.setFont(QFont("Microsoft YaHei", 9))
        root.addWidget(self.status)

        row = QHBoxLayout()
        auto_btn = QPushButton("自动找输入行" if self.target == "input" else "自动找聊天区")
        auto_btn.clicked.connect(self._auto_find)
        row.addWidget(auto_btn)
        test_btn = QPushButton("测试识别")
        test_btn.clicked.connect(self._test_ocr)
        row.addWidget(test_btn)
        row.addStretch()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = QPushButton("就用这个区域")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        row.addWidget(ok)
        root.addLayout(row)

        self.resize(1000, 700)
        self.canvas.fit(940, 480)

    # ---- 动作 ----

    def _auto_find(self) -> None:
        if self.ocr is None:
            self._set_status("（没有 OCR 引擎，无法自动找；请手动框）")
            return
        try:
            self.ocr.load()
        except Exception as e:  # noqa: BLE001
            self._set_status(f"OCR 不可用: {e}")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if self.target == "input":
                hits = find_placeholder_lines(self.ocr, self.frame)
                if not hits:
                    self._set_status("没找到 'To (ALL):' 这样的输入行提示 —— "
                                     "请确认截图时聊天框是打开的，或手动框。")
                    return
                x1, y1, x2, y2, text = hits[0]
                pad = 8
                # 输入行可能比占位符长很多，向右扩一截
                self.canvas.set_selection_pixels(max(0, x1 - pad), max(0, y1 - pad),
                                                 min(self.frame.shape[1], x2 + 400),
                                                 min(self.frame.shape[0], y2 + pad))
                self._set_status(f"找到输入行提示 {text!r}，已自动框好，可微调")
            else:
                # 聊天区：找"像玩家说的话"的行（英文气泡），取它们的外接范围
                lines = [l for l in self.ocr.recognize(self.frame)
                         if looks_like_chat(l.text)]
                if not lines:
                    self._set_status("这张截图里没发现聊天内容 —— 请在有聊天气泡时重新截图，或手动框。")
                    return
                x1 = min(l.box[0] for l in lines) - 20
                y1 = min(l.box[1] for l in lines) - 10
                x2 = max(l.box[2] for l in lines) + 20
                y2 = max(l.box[3] for l in lines) + 20
                self.canvas.set_selection_pixels(max(0, x1), max(0, y1),
                                                 min(self.frame.shape[1], x2),
                                                 min(self.frame.shape[0], y2))
                self._set_status(f"发现 {len(lines)} 行疑似聊天内容，已自动框好，可微调")
        finally:
            QApplication.restoreOverrideCursor()

    def _test_ocr(self) -> None:
        region = self.canvas.selection_normalized()
        if region is None:
            self._set_status("先拖一个稍微大点的框")
            return
        if self.ocr is None:
            self._set_status("没有 OCR 引擎，跳过测试")
            return
        h, w = self.frame.shape[:2]
        x1, y1 = int(region[0] * w), int(region[1] * h)
        x2, y2 = int(region[2] * w), int(region[3] * h)
        crop = np.ascontiguousarray(self.frame[y1:y2, x1:x2])
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            lines = self.ocr.recognize(crop)
        except Exception as e:  # noqa: BLE001
            self._set_status(f"识别失败: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        if not lines:
            self._set_status(f"区域 {region} 里没识别到文字 —— 框得不准或位置不对，重新框")
            return
        if self.target == "input":
            from ..input.line_reader import clean_input_line

            raw = " ".join(l.text for l in lines if l.text)
            clean = clean_input_line(raw)
            if clean:
                self._set_status(f"✅ 这个区域能读到：{clean!r}（OCR 原文 {raw!r}）")
            else:
                self._set_status(f"⚠️ 只读到了提示文字/空白：{raw!r} —— "
                                 f"请把框贴紧你打的那行字")
            return
        accepted = [l.text for l in lines if looks_like_chat(l.text)]
        rejected = [l.text for l in lines if not looks_like_chat(l.text)]
        msg = f"识别 {len(lines)} 行；其中 {len(accepted)} 行会被当聊天翻译"
        if accepted:
            msg += "：" + "、".join(accepted[:3])
        if rejected:
            msg += f"（{len(rejected)} 行被过滤，如 {rejected[:2]}）"
        self._set_status(msg)

    def _accept(self) -> None:
        region = self.canvas.selection_normalized()
        if region is None:
            self._set_status("还没框出有效区域")
            return
        self.result_region = region
        self.result_target = self.target
        self.accept()

    @property
    def target(self) -> str:
        """当前框的是"输入行"还是"聊天区"（跟着下拉框走）。"""
        box = getattr(self, "mode_box", None)
        if box is None:
            return self._target
        return "input" if box.currentIndex() == 0 else "chat"

    def _on_mode_changed(self) -> None:
        self.setWindowTitle("框选聊天输入行" if self.target == "input" else "框选聊天区域")
        self.canvas.sel = None
        self.canvas.update()
        self._auto_find()

    def _set_status(self, text: str) -> None:
        self.status.setText(text)
        logger.info("框选: %s", text)


def pick_region_on_snapshot(frame: np.ndarray, target: str, ocr: OCREngine | None = None,
                            parent=None) -> list[float] | None:
    dlg = SnapshotPickerDialog(frame, target, ocr, parent)
    if dlg.exec():
        return dlg.result_region
    return None


def _to_pixmap(frame: np.ndarray) -> QPixmap:
    """numpy RGB -> QPixmap（不依赖 Pillow 的 Qt 绑定，自己拷内存）。"""
    h, w = frame.shape[:2]
    arr = np.ascontiguousarray(frame[:, :, ::-1])       # RGB -> BGR
    from PySide6.QtGui import QImage

    img = QImage(arr.data, w, h, 3 * w, QImage.Format.Format_BGR888)
    return QPixmap.fromImage(img.copy())

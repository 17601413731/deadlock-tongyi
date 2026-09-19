"""读取游戏聊天输入行里"我已经打好的中文"。

思路：聊天框打开时，输入行固定显示在屏幕某个位置，形如
    To (ALL): 我打的中文
（英文界面）或
    对（所有人）：我打的中文
所以我们只要 OCR 这一小条区域，再把占位前缀和尾部多余空格剥掉。

这块区域很小（约 600x40 像素），比全屏 OCR 快几十倍；而且只有连按空格
触发时才读一次，不常驻跑，CPU 占用可以忽略。
"""

from __future__ import annotations

import logging
import re

from ..capture.ocr import OCREngine, create_ocr
from ..capture.screen import ScreenGrabber
from ..config import Config

logger = logging.getLogger(__name__)

# 输入行占位前缀：To (ALL): / To (ALLIES): / 对（所有人）： / 说：
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:To\s*\(\s*[A-Za-z\u4e00-\u9fff]+\s*\)|对\s*[（(][^）)]*[）)]|"
    r"说|全体|所有人|友方|队伍)\s*[:：]?\s*",
    re.I,
)
# OCR 常见的边缘噪声
_EDGE_JUNK = "|_~`'\"“”‘’,;；:：-—=+*·。."
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")


class InputLineReader:
    """OCR 聊天输入行 -> 干净的中文文本。"""

    def __init__(self, cfg: Config, grabber: ScreenGrabber | None = None,
                 ocr: OCREngine | None = None):
        self.cfg = cfg
        self.grabber = grabber or ScreenGrabber()
        self.ocr = ocr or create_ocr(cfg.ocr.backend,
                                     min_confidence=max(0.3, cfg.ocr.min_confidence - 0.2),
                                     upscale=max(2, cfg.ocr.upscale),
                                     invert=cfg.ocr.invert)
        self._loaded = False
        self.last_raw = ""
        self.last_text = ""

    # ---------- 对外 ----------

    def read(self) -> str:
        """读一次输入行；读不到内容返回空串。"""
        if not self._ensure_loaded():
            return ""
        frame = self.grabber.grab(self.cfg.input.input_region)
        if frame is None:
            return ""
        raw = self._ocr_text(frame)
        self.last_raw = raw
        text = clean_input_line(raw)
        self.last_text = text
        if raw and not text:
            logger.debug("输入行内容被清洗掉（可能只是占位提示）: %r", raw)
        return text

    def preview(self, save_path: str | None = None) -> tuple[str, str]:
        """给校准用：返回 (原始 OCR 文本, 清洗后文本)，可选把裁剪图存下来。"""
        frame = self.grabber.grab(self.cfg.input.input_region)
        if frame is None:
            return "", ""
        if save_path:
            from PIL import Image

            Image.fromarray(frame.astype("uint8")).save(save_path)
        if not self._ensure_loaded():
            return "", ""
        raw = self._ocr_text(frame)
        self.last_raw, self.last_text = raw, clean_input_line(raw)
        return raw, self.last_text

    def _ocr_text(self, frame) -> str:
        """输入行用整块检测(det)：区域是手画的，留白难免，检测比硬切行稳。"""
        boxes = self.ocr.recognize(frame)
        return " ".join(b.text for b in boxes if b.text).strip()

    def close(self) -> None:
        try:
            self.grabber.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 内部 ----------

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        if self.grabber.backend == "none":
            logger.error("读输入行失败：抓帧后端不可用")
            return False
        try:
            self.ocr.load()
            self._loaded = True
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("读输入行失败：OCR 不可用(%s)", e)
            return False


def clean_input_line(raw: str) -> str:
    """清洗 OCR 结果：剥占位前缀、剥边缘噪声、去掉尾部空格。"""
    text = (raw or "").strip()
    if not text:
        return ""
    # 可能出现多个框，占位符可能被拆开识别 -> 反复剥
    for _ in range(3):
        new = _PLACEHOLDER_RE.sub("", text, count=1).strip()
        if new == text:
            break
        text = new
    text = text.strip(_EDGE_JUNK).strip()
    # 去掉连续空白（含三下空格留下的）
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text:
        return ""
    # 纯符号/纯数字不要（多半是 OCR 误读）
    if not CJK_RE.search(text) and not LATIN_RE.search(text):
        return ""
    # 太短且不是中文（可能只是把占位符认错）
    if len(text) <= 1 and not CJK_RE.search(text):
        return ""
    return text

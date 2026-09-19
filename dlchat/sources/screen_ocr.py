"""屏幕 OCR 来源：抓聊天区 -> 变化检测 -> OCR -> 过滤 -> 解析成聊天行。

两种模式：
- detect=False（默认）：位置固定的聊天条，按 rows 切条只跑识别(rec)，快。
- detect=True：整块做文本检测(det)+识别，适合"世界频道气泡出现在任意位置"，
  代价是慢很多（det 在大图上是主要开销）。

Deadlock 聊天显示的两条线索：convar `chat_top_bar_max_messages=6`（顶部聊天条，
最多 6 个面板）、`citadel_chat_fade_time=10`（10 秒淡出，另有 7 秒延长）；
另外实测截图里能看到英雄头顶世界空间的气泡文字。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ..capture.ocr import OCREngine, OCRLine
from ..capture.screen import ScreenGrabber, frame_diff
from ..chat.filter import is_hud_noise, looks_like_chat, looks_like_player_name
from ..chat.line import ChatLine
from ..chat.parser import parse_line
from ..config import OCRSection
from .base import ChatSource, SourceStatus

logger = logging.getLogger(__name__)


class ScreenOCRSource(ChatSource):
    name = "ocr"

    def __init__(self, cfg: OCRSection, ocr: OCREngine, grabber: ScreenGrabber | None = None,
                 known_phrases: set[str] | None = None,
                 ui_strings: set[str] | None = None,
                 owns_resources: bool = True,
                 focus_check: Callable[[], bool] | None = None):
        self.cfg = cfg
        self.ocr = ocr
        self.grabber = grabber or ScreenGrabber()
        self.known_phrases = known_phrases or set()
        self.ui_strings = ui_strings or set()
        # 与"读输入行"共用引擎/抓帧器时由 ChatService 统一释放，这里不能关
        self.owns_resources = owns_resources
        # 游戏窗口是否在前台；不在前台就完全不抓屏（否则会把桌面文字当聊天）
        self.focus_check = focus_check
        self._prev = None
        self._last_poll = 0.0
        self._status = SourceStatus()
        self.last_cost_ms = 0.0
        self._unfocused_logged = 0.0

    # ---- 生命周期 ----

    def start(self) -> bool:
        if self.grabber.backend == "none":
            self._status = SourceStatus(running=False, detail="拿不到屏幕画面（抓帧后端不可用）")
            return False
        try:
            self.ocr.load()
        except Exception as e:  # noqa: BLE001
            self._status = SourceStatus(running=False, detail=str(e))
            return False
        mode = "整块检测" if self.cfg.detect else f"切 {self.cfg.rows} 条识别"
        self._status = SourceStatus(
            running=True,
            detail=f"OCR 运行中（{self.ocr.name} / {self.grabber.backend} / {mode}）",
            extra=f"区域 {self.cfg.region}",
        )
        return True

    def stop(self) -> None:
        if self.owns_resources:
            self.grabber.close()
        self._status = SourceStatus(running=False, detail="已停止")

    def status(self) -> SourceStatus:
        return self._status

    # ---- 轮询 ----

    def poll(self) -> list[ChatLine]:
        now = time.monotonic()
        if (now - self._last_poll) * 1000 < self.cfg.interval_ms:
            return []
        self._last_poll = now

        # 游戏不在前台 -> 那块区域里是桌面/浏览器/本工具自己，抓了就是错的
        if self.focus_check is not None:
            try:
                focused = self.focus_check()
            except Exception:  # noqa: BLE001
                focused = True
            if not focused:
                if now - self._unfocused_logged > 60:
                    self._unfocused_logged = now
                    logger.info("游戏不在前台，暂停屏幕识别（避免把桌面文字当聊天）")
                self._prev = None      # 回前台时重新抓一帧做对比基准
                return []

        frame = self.grabber.grab(self.cfg.region)
        if frame is None:
            return []
        diff = frame_diff(self._prev, frame)
        self._prev = frame
        if diff < self.cfg.change_threshold:
            return []

        t0 = time.perf_counter()
        boxes = (self.ocr.recognize(frame) if self.cfg.detect
                 else self.ocr.recognize_strips(frame, self.cfg.rows))
        self.last_cost_ms = (time.perf_counter() - t0) * 1000
        if not boxes:
            return []
        return self._to_lines(boxes)

    # ---- 内部 ----

    def _to_lines(self, boxes: list[OCRLine]) -> list[ChatLine]:
        ordered = sorted(boxes, key=lambda b: (b.box[1], b.box[0]))
        merged = self._merge_wrapped(ordered)

        lines: list[ChatLine] = []
        pending_name = ""
        for box in merged[-self.cfg.max_lines:]:
            text = box.text.strip()
            if not text:
                continue

            # 先试标准聊天格式（[ALL] 名字: 内容 / 名字: 内容）
            parsed = parse_line(text, source="ocr", confidence=box.score, bbox=box.box)
            if parsed is not None and (parsed.speaker or self._has_tag(text)):
                parsed.speaker = parsed.speaker or pending_name
                lines.append(parsed)
                pending_name = ""
                continue

            # 再试"名字在上一行、内容在下一行"的世界气泡形态
            if looks_like_player_name(text) and not self._is_chat(text):
                pending_name = text
                continue

            if self.cfg.filter_hud and not self._is_chat(text):
                logger.debug("OCR 过滤掉非聊天文本: %r", text)
                continue
            if is_hud_noise(text):
                continue

            lines.append(ChatLine(text=text, speaker=pending_name, source="ocr",
                                  confidence=box.score, bbox=box.box, raw=text))
            pending_name = ""
        return lines

    @staticmethod
    def _has_tag(text: str) -> bool:
        return text.lstrip().startswith("[")

    def _is_chat(self, text: str) -> bool:
        return looks_like_chat(text, self.known_phrases, self.ui_strings)

    def _merge_wrapped(self, boxes: list[OCRLine]) -> list[OCRLine]:
        """合并被换行的续行（长消息）。"""
        merged: list[OCRLine] = []
        for box in boxes:
            if merged and self._is_continuation(merged[-1], box):
                prev = merged[-1]
                merged[-1] = OCRLine(
                    text=f"{prev.text} {box.text}".strip(),
                    score=min(prev.score, box.score),
                    box=(prev.box[0], prev.box[1],
                         max(prev.box[2], box.box[2]), max(prev.box[3], box.box[3])),
                )
            else:
                merged.append(box)
        return merged

    @staticmethod
    def _is_continuation(prev: OCRLine, cur: OCRLine) -> bool:
        ph = max(1, prev.box[3] - prev.box[1])
        ch = max(1, cur.box[3] - cur.box[1])
        gap = cur.box[1] - prev.box[3]
        if gap > 0.9 * max(ph, ch):
            return False
        if gap < -0.5 * ph:
            return False
        return cur.box[0] > prev.box[0] + 0.02 * max(1, prev.box[2] - prev.box[0])

"""聊天行去重与追踪。

OCR 每 400ms 抓一次同一个聊天区，同一行会被反复读到；聊天面板滚动/淡出时
还会出现"同一句话换了位置"。所以需要：
- 精确指纹集合：覆盖所有见过的行
- 模糊匹配：只和最近若干行比（OCR 抖动会导致一两个字符差异）
- TTL 淘汰：聊天面板滚走的旧行，超时后允许再次出现（比如队友复读同一句）
"""

from __future__ import annotations

import time
from collections import deque
from difflib import SequenceMatcher
from typing import Iterable

from .line import ChatLine


class LineTracker:
    def __init__(self, similarity: float = 0.9, ttl_s: float = 25.0,
                 fuzzy_window: int = 40, max_seen: int = 600,
                 ignore_speakers: Iterable[str] = ()):
        # ttl_s 参考游戏里的 citadel_chat_fade_time=10(+7 延长)：聊天条 10~17 秒后消失，
        # 超过这个时间同一句话再出现（队友复读）就应该重新上报，所以默认 25 秒。
        self.similarity = similarity
        self.ttl_s = ttl_s
        self.fuzzy_window = fuzzy_window
        self.max_seen = max_seen
        self.ignore_speakers = {s.strip().lower() for s in ignore_speakers if s and s.strip()}
        self._seen: deque[tuple[str, str, float]] = deque(maxlen=max_seen)  # (fp, norm, ts)
        self._fps: set[str] = set()

    # ---- 公共 API ----

    def update(self, lines: Iterable[ChatLine]) -> list[ChatLine]:
        """返回本次新增（未见过）的行，按出现顺序。"""
        self._prune()
        fresh: list[ChatLine] = []
        for line in lines:
            if self._is_ignored(line):
                continue
            if self._is_duplicate(line):
                continue
            self._remember(line)
            fresh.append(line)
        return fresh

    def reset(self) -> None:
        self._seen.clear()
        self._fps.clear()

    # ---- 内部 ----

    def _is_ignored(self, line: ChatLine) -> bool:
        if line.speaker and line.speaker.strip().lower() in self.ignore_speakers:
            return True
        return not line.norm_text

    def _is_duplicate(self, line: ChatLine) -> bool:
        if line.fingerprint in self._fps:
            return True
        norm = line.norm_text
        recent = list(self._seen)[-self.fuzzy_window:]
        for _fp, seen_norm, _ts in recent:
            if not seen_norm:
                continue
            # 长度差太多就不必算相似度（省 CPU）
            if abs(len(seen_norm) - len(norm)) > max(4, len(norm) * 0.35):
                continue
            if SequenceMatcher(None, seen_norm, norm).ratio() >= self.similarity:
                return True
        return False

    def _remember(self, line: ChatLine) -> None:
        self._seen.append((line.fingerprint, line.norm_text, line.ts))
        self._fps.add(line.fingerprint)

    def _prune(self) -> None:
        if not self._seen:
            return
        cutoff = time.time() - self.ttl_s
        while self._seen and self._seen[0][2] < cutoff:
            fp, _norm, _ts = self._seen.popleft()
            if all(other_fp != fp for other_fp, _n, _t in self._seen):
                self._fps.discard(fp)

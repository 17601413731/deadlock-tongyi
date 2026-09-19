"""聊天行数据结构。"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")

TARGET_ALL = "all"
TARGET_ALLIES = "allies"
TARGET_PARTY = "party"
TARGET_SYSTEM = "system"

_TARGET_MAP = {
    "all": TARGET_ALL, "all chat": TARGET_ALL, "所有人": TARGET_ALL, "[all]": TARGET_ALL,
    "allies": TARGET_ALLIES, "allies chat": TARGET_ALLIES, "team": TARGET_ALLIES,
    "team chat": TARGET_ALLIES, "友方": TARGET_ALLIES, "队伍": TARGET_ALLIES,
    "party": TARGET_PARTY, "party chat": TARGET_PARTY, "组队": TARGET_PARTY,
    "system": TARGET_SYSTEM, "系统": TARGET_SYSTEM,
}


def normalize_target(raw: str | None) -> str:
    if not raw:
        return TARGET_ALL
    return _TARGET_MAP.get(raw.strip().lower(), TARGET_ALL)


@dataclass
class ChatLine:
    """一条聊天消息（已剥掉频道前缀与说话人）。"""

    text: str
    speaker: str = ""
    target: str = TARGET_ALL
    ts: float = field(default_factory=time.time)
    source: str = "console"          # console | ocr
    confidence: float = 1.0
    bbox: tuple[int, int, int, int] | None = None
    raw: str = ""                    # 原始行，便于排查
    translated: str = ""             # 译文（回填）
    error: str = ""

    @property
    def lang(self) -> str:
        """粗略判断语言：有拉丁字母且几乎没汉字 -> en；否则 zh。"""
        has_cjk = bool(CJK_RE.search(self.text))
        has_latin = bool(LATIN_RE.search(self.text))
        if has_latin and not has_cjk:
            return "en"
        if has_cjk and not has_latin:
            return "zh"
        return "mixed"

    @property
    def fingerprint(self) -> str:
        """用于去重的指纹：忽略大小写、空白与标点。"""
        norm = _PUNCT_RE.sub("", _WS_RE.sub(" ", self.text).lower())
        return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]

    @property
    def norm_text(self) -> str:
        return _PUNCT_RE.sub("", _WS_RE.sub(" ", self.text).lower())

    def display_original(self) -> str:
        who = f"{self.speaker}: " if self.speaker else ""
        tag = {"all": "[全部] ", "allies": "[友方] ", "party": "[组队] "}.get(self.target, "")
        return f"{tag}{who}{self.text}"

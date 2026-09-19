"""把原始文本行解析成 ChatLine。

要处理三种来源：
1. 控制台日志（Source 2 服务端打印格式）：[All Chat][Name (3)]: message
2. CS 风格：[ALL] Name: message
3. OCR 出来的裸行：Name: message  或 直接就是 message

解析原则：宁可少剥一点，也不要把消息内容当说话人切掉。
"""

from __future__ import annotations

import re

from .line import ChatLine, normalize_target

# [All Chat][Name (3)]: msg   —— 服务端日志格式（server.dll 里的格式串）
_SRV_RE = re.compile(
    r"^\s*\[(?P<chan>[^\]]{1,24})\]\s*\[(?P<name>.{1,40}?)\s*\(\d+\)\]\s*[:：]\s*(?P<msg>.+)$"
)
# [ALL] Name: msg
_TAG_RE = re.compile(
    r"^\s*\[(?P<chan>[^\]]{1,24})\]\s*(?:(?P<name>[^:：]{1,32})\s*[:：]\s*)?(?P<msg>.*)$"
)
# Name: msg（无频道标签）
_NAME_RE = re.compile(r"^\s*(?P<name>[^:：]{1,32}?)\s*[:：]\s*(?P<msg>.+)$")

# 明显的非聊天行（连接信息、报错、状态输出）
_NOISE_RE = re.compile(
    r"^\s*(\[?Server\]?|Connecting to|Connection to|Downloading|Loading|"
    r"Unable to|Failed to|Error|Warning|Steam|Cbuf|NET_|SV_|CL_|host_)",
    re.I,
)


def _looks_like_message(msg: str) -> bool:
    msg = msg.strip()
    if len(msg) < 1:
        return False
    # 至少要有字母或汉字，纯符号/纯数字丢掉
    return bool(re.search(r"[A-Za-z\u4e00-\u9fff]", msg))


def parse_line(raw: str, *, source: str = "console", confidence: float = 1.0,
               bbox: tuple[int, int, int, int] | None = None) -> ChatLine | None:
    """解析一行；解析不出聊天内容时返回 None。"""
    if not raw:
        return None
    line = raw.strip()
    if not line or _NOISE_RE.search(line):
        return None

    m = _SRV_RE.match(line)
    if m:
        msg = m.group("msg").strip()
        if not _looks_like_message(msg):
            return None
        return ChatLine(text=msg, speaker=m.group("name").strip(),
                        target=normalize_target(m.group("chan")), source=source,
                        confidence=confidence, bbox=bbox, raw=raw)

    m = _TAG_RE.match(line)
    if m:
        msg = (m.group("msg") or "").strip()
        name = (m.group("name") or "").strip()
        if msg and _looks_like_message(msg):
            return ChatLine(text=msg, speaker=name,
                            target=normalize_target(m.group("chan")), source=source,
                            confidence=confidence, bbox=bbox, raw=raw)
        # 只有标签、没内容（OCR 半截行）——丢掉
        return None

    m = _NAME_RE.match(line)
    if m:
        msg = m.group("msg").strip()
        name = m.group("name").strip()
        # "Name: msg" 里 Name 不该像一整句话
        if _looks_like_message(msg) and len(name.split()) <= 3:
            return ChatLine(text=msg, speaker=name, source=source,
                            confidence=confidence, bbox=bbox, raw=raw)

    if _looks_like_message(line):
        return ChatLine(text=line, source=source, confidence=confidence,
                        bbox=bbox, raw=raw)
    return None


def parse_lines(raw_lines, **kw) -> list[ChatLine]:
    out: list[ChatLine] = []
    for raw in raw_lines:
        parsed = parse_line(raw, **kw)
        if parsed is not None:
            out.append(parsed)
    return out


def is_translatable(line: ChatLine) -> bool:
    """英文（或中英混排）才需要翻译；纯中文行只展示。"""
    return line.lang in ("en", "mixed")

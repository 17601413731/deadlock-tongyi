"""聊天相关：行模型、解析、去重、术语表。"""

from .glossary import Glossary
from .line import ChatLine, normalize_target
from .parser import is_translatable, parse_line, parse_lines
from .tracker import LineTracker

__all__ = [
    "ChatLine",
    "Glossary",
    "LineTracker",
    "is_translatable",
    "normalize_target",
    "parse_line",
    "parse_lines",
]

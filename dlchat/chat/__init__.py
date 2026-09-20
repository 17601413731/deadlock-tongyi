"""聊天相关：行模型与术语表。

这里曾经还导出 parser / tracker / filter（console.log 解析、去重、HUD 过滤）。
那三个是**外置桌面版**（截屏 OCR 那套）专用的：mod 方案直接读写游戏自己的聊天
界面，不存在"把 HUD 数字和聊天文字分开"的问题。于 2026-09-20 随桌面版一起删除，
需要时看 git 历史。
"""

from .glossary import Glossary
from .line import ChatLine, normalize_target

__all__ = [
    "ChatLine",
    "Glossary",
    "normalize_target",
]

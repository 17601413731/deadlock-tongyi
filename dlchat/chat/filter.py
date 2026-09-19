"""把 HUD 文字和聊天文字区分开。

全屏 OCR 会把 HUD 上的数字/计时/FPS/技能键全都识别出来。如果不筛掉，
翻译会在聊天窗里刷一堆 "45"、"FPS:221"、"2:17" 之类的垃圾。

筛选策略（按顺序）：
1. 明显的 HUD 形态：纯数字、分数、时间、FPS/ms、单个字母、血条数值
2. 已知界面词：命中游戏本地化里的 UI 词条且不像玩家说话
3. 保留：像"人话"的英文短句（≥2 个字母词或 ≥6 个字母），或命中我们的
   聊天词汇表（gg/wp/ez/mid…），或含 CJK（可能是中文玩家在打字）

注意：玩家名是 CJK 或短英文名，会被当成"可能是人名"返回，用于给消息配说话人，
不会被当聊天内容翻译。
"""

from __future__ import annotations

import re

# 纯 HUD 形态
_NUMERIC_RE = re.compile(
    r"^\s*[+\-x×]?\s*\d+(?:[.,:/]\d+)*\s*(?:%|ms|s|fps)?\s*$", re.I)
_TIME_RE = re.compile(r"^\s*\d{1,2}:\d{2}\s*$")
_FPS_RE = re.compile(r"^\s*(?:FPS|PING)\s*[:：]?\s*\d+\s*$", re.I)
_VS_RE = re.compile(r"^\s*\d+\s*(?:vs|VS|v)\s*\d+\s*$")
_SINGLE_RE = re.compile(r"^\s*[A-Za-z]\s*$")
# 游戏固定 UI 词（出现即判为界面文字）
_UI_WORDS = {
    "fps", "ping", "ms", "kda", "kills", "deaths", "assists", "souls", "level",
    "buy", "sell", "shop", "scoreboard", "pause", "unpause", "match", "victory",
    "defeat", "respawn", "cooldown", "ready", "locked", "unlocked", "damage",
    "healing", "objective", "guardian", "walker", "shrine", "jungle", "lane",
}
# 聊天里真实出现的高频词（有这些词就更可能是聊天）。
# 注意：匹配时按词首前缀算（"feeding" 命中 "feed"、"smurfing" 命中 "smurf"），
# 所以这里放词根即可；长度 < 4 的词不做前缀匹配（避免误伤）。
_CHATTY_WORDS = {
    "gg", "wp", "ez", "gl", "glhf", "hf", "ty", "thx", "np", "gj", "ns", "mb",
    "omw", "brb", "afk", "oom", "ks", "b", "def", "push", "back", "help", "mid",
    "no", "yes", "why", "lol", "wtf", "omg", "pls", "plz", "sry", "sorry", "nice",
    "good", "bad", "go", "wait", "stop", "come", "run", "low", "care", "careful",
    "missing", "miss", "gank", "ult", "cd", "lag", "report", "troll", "feed",
    "noob", "diff", "cope", "team", "guys", "bro", "how", "what",
    "who", "where", "time", "need", "want", "can", "cant", "dont", "you", "your",
    "him", "her", "they", "we", "us", "me", "my", "our", "the", "and", "but",
    # 游戏里常见但上面没覆盖的
    "smurf", "toxic", "throw", "tilt", "inting", "dive", "rotate", "flank",
    "shrine", "walker", "guardian", "urn", "rejuv", "souls", "lane", "jungle",
    "deny", "farm", "recall", "group", "retreat", "escape", "heal", "mana",
    "haze", "lash", "seven", "yamato", "warden", "infernus", "abrams",
}
# 明显是开发/文件目录词：单靠"够长"挡不住，单独列黑名单
_NON_CHAT_WORDS = {
    "scripts", "script", "tests", "test", "docs", "doc", "packaging", "config",
    "build", "dist", "source", "assets", "models", "readme", "license", "venv",
    "tools", "setup", "temp", "output", "outputs", "cache", "spike_out",
    "desktop", "downloads", "documents", "pictures", "videos", "music",
    "folder", "files", "main", "utils", "init", "setup", "install", "requirements",
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{0,20}")
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _is_chatty(word: str) -> bool:
    """词本身或它的词根在聊天词表里（feeding -> feed，smurfing -> smurf）。"""
    if word in _CHATTY_WORDS:
        return True
    return any(len(c) >= 4 and word.startswith(c) for c in _CHATTY_WORDS)

# 代码 / 路径 / 命令行 / 文件名 —— 这些一律不是聊天。
# 实测踩过的坑：游戏不在前台时把桌面上的文件名和批处理内容当聊天翻译了。
_CODEISH_RE = re.compile(
    r"[\\/]"                                    # 路径分隔符
    r"|\.(py|md|json|ya?ml|toml|bat|cmd|ps1|txt|exe|dll|onnx|log|ini|cfg|vpk)\b"
    r"|--[a-z]"                                 # 命令行参数
    r"|^\s*(rem|set|chcp|echo|cd|dir|copy|python|pip|git|npm|ollama|import|from|def|class)\b"
    r"|=\S|>\S|<\S|\|\S"                        # 赋值 / 重定向 / 管道
    r"|[A-Za-z]:\\",                            # 盘符
    re.I,
)


def is_hud_noise(text: str) -> bool:
    """像 HUD 数值/固定 UI 文本 -> True（不是聊天）。"""
    t = text.strip()
    if not t:
        return True
    if (_NUMERIC_RE.match(t) or _TIME_RE.match(t) or _FPS_RE.match(t)
            or _VS_RE.match(t) or _SINGLE_RE.match(t)):
        return True
    words = [w.lower() for w in _WORD_RE.findall(t)]
    if not words:
        return not CJK_RE.search(t)
    if all(w in _UI_WORDS for w in words):
        return True
    return False


def looks_like_chat(text: str, known_phrases: set[str] | None = None,
                    ui_strings: set[str] | None = None) -> bool:
    """像"玩家说的话" -> True。宁可漏掉，也不要把 HUD 数字翻出来刷屏。

    ui_strings 是游戏官方本地化里的中文串（"对局技巧"这种界面文字），
    完全命中就判为界面文本——只做全等匹配，所以"中路没人"这类句子不受影响。
    """
    t = text.strip()
    if not t or is_hud_noise(t):
        return False

    if ui_strings and t.strip("。！？.!? ") in ui_strings:
        return False

    if known_phrases:
        key = t.rstrip(".!。！").lower()
        if key in known_phrases:
            return True

    # 代码/路径/命令/文件名一律不是聊天。
    # 实测踩过的坑：切到桌面时把 "docs"、"packaging scripts"、"chcp 65001 >nul"、
    # "run.bat --selftest" 这些当成聊天翻译了。
    if _CODEISH_RE.search(t):
        return False

    words = [w.lower() for w in _WORD_RE.findall(t)]
    if not words:
        # 没有拉丁词：有汉字就算（中文玩家打的短句，"撤"、"上"这种也算）
        return bool(CJK_RE.search(t))

    if any(_is_chatty(w) for w in words):
        return True
    # 同一 token 重复（"b b b" / "push push"）：token 本身得是聊天词
    if len(set(words)) == 1 and _is_chatty(words[0]):
        return True
    if all(w in _NON_CHAT_WORDS for w in words):
        return False
    if len(words) == 1:
        # 单个词：够长、不是界面词、也不是文件名常用词才算（"pushing" ✅ "scripts" ❌）
        return len(words[0]) >= 5 and words[0] not in _UI_WORDS
    # 多个词：至少 3 个词且总字母数够。
    # "packaging scripts"、"docs tests" 这类文件名堆叠过不了；
    # "stop feeding noob"、"7 is smurfing" 这种正常聊天能过。
    return len(words) >= 3 and sum(len(w) for w in words) >= 10


def looks_like_player_name(text: str) -> bool:
    """像玩家名（用于给世界频道的气泡消息配说话人）。"""
    t = text.strip()
    if not t or len(t) > 24:
        return False
    if CJK_RE.search(t):
        return 2 <= len(t) <= 12 and not is_hud_noise(t)
    words = _WORD_RE.findall(t)
    return 1 <= len(words) <= 3 and any(w[0].isupper() for w in words)

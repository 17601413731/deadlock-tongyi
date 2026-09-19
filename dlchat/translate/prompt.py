"""提示词构造。

要点（都有调研依据）：
- 温度 0：短句最容易出现"幻觉补充说明"，温度越高越严重。
- 硬性"只输出译文"约束：WMT24 审计把"输入太短缺上下文"列为模型乱加解释的首要原因。
- **静态前缀**：system + 少样本必须逐字节不变，这样 Ollama/llama.cpp 能命中 KV 前缀缓存，
  云端（DeepSeek）也有前缀折扣。因此每句变化的术语对照放进**用户消息**，不放 system。
- 术语只注入本句命中的几条（大词表整包塞进去只会拖慢首字延迟）。
- 保留英文清单静态写死（gg/ez 这类词硬翻反而错）。
- 少样本：3 个游戏内真实说法，引导口语化而不是书面语。
"""

from __future__ import annotations

from ..chat.line import ChatLine

SYSTEM_EN_ZH = """你是《Deadlock》(中文名"异锁") 游戏内的实时聊天翻译。玩家会发英文聊天，你把它翻成简体中文。

硬性规则：
1. 只输出译文本身。不要解释、不要加引号、不要写"翻译："、不要重复原文。
2. 这是游戏内快捷交流，用玩家真实的口语说法，短、直接。不要书面化，不要加敬语。
3. 下面这些词保留英文原样不翻译：{keep}
4. 用户消息可能以 "TERMS:" 开头，那是本次必须遵守的术语对照（格式 英文=中文），
   只按它翻译，不要把 TERMS 这一段本身翻译出来。没有 TERMS 行时按你自己的理解翻。
5. 原文是脏话或嘲讽时，用中文玩家同等强度的说法，不要净化也不要加码。
6. 只有一两个词时，直接给对应的中文喊话，不要补全成完整句子。"""

SYSTEM_ZH_EN = """You are translating Chinese in-game chat for the game Deadlock into short, natural English.

Hard rules:
1. Output ONLY the translation. No explanation, no quotes, no "Translation:" prefix.
2. Use real North-American in-game chat style: short, casual, abbreviations are fine.
3. The user message may start with a "TERMS:" line giving required terminology
   (format chinese=english). Use it exactly and do NOT translate the TERMS line itself.
4. Never add politeness or extra content. One line only.
5. **Never invent words that are not in the source** — no "lol", no "bro", no "please",
   no extra jokes. Keep the same intensity: if the source is blunt, stay blunt;
   if it is polite, stay polite.
6. If the input is one or two words, translate it as a short callout, not a sentence.
7. Deadlock slang (this is a MOBA shooter, NOT a messaging app):
   送 = feed (giving the enemy free kills), 越塔 = dive, 抱团 = group up,
   开团 = initiate, 绕后 = flank, 蹲 = camp, 抓人 = gank, 残血 = low,
   大招 = ult, 魂瓮 = urn, 复生石 = rejuvenator, 大怪 = mid boss.
   "送" NEVER means "send" in this context."""

FEWSHOT_EN_ZH: list[tuple[str, str]] = [
    ("mid no", "中路没人"),
    ("he's low, dive him", "他残血，上"),
    ("b b b", "撤撤撤"),
    ("need help with urn", "来个人帮忙送魂瓮"),
]

FEWSHOT_ZH_EN: list[tuple[str, str]] = [
    # 少样本必须**术语正确**：早期版本里有
    #   ("来个人帮忙送魂瓮", "need help with urn")
    # —— 原文的「送」在译文里没有对应词，实测把模型教成了"送≈可忽略"，
    # 于是「别送了」被翻成 "stop sending"（用户实测截图）。换成术语一致的例子。
    ("别送了", "stop feeding"),
    ("你一直送", "you keep feeding"),
    ("中路没人", "mid is open"),
    ("他残血", "he's low"),
    ("撤", "b"),
    ("越塔杀他", "dive him"),
    ("抱团推", "group up and push"),
    ("魂瓮要没了", "urn is about to expire"),
]

MAX_HINT_TERMS = 12


def build_system(direction: str, keep_all: list[str], extra: str = "") -> str:
    """构造**静态** system 提示（同一方向下逐字节不变，便于前缀缓存）。"""
    if direction == "en->zh":
        text = SYSTEM_EN_ZH.format(keep=", ".join(keep_all) if keep_all else "无")
    else:
        text = SYSTEM_ZH_EN
    if extra:
        text += "\n\n补充要求：\n" + extra.strip()
    return text


def build_user_message(text: str, terms: list[tuple[str, str]],
                       direction: str = "en->zh", limit: int = MAX_HINT_TERMS) -> str:
    """把命中的术语贴在用户消息里；没有命中就原样返回。"""
    if not terms:
        return text
    sep = "=" if direction == "en->zh" else "="
    pairs = "; ".join(f"{src}{sep}{dst}" for src, dst in terms[:limit])
    return f"TERMS: {pairs}\n{text}"


def fewshot(direction: str) -> list[tuple[str, str]]:
    return FEWSHOT_EN_ZH if direction == "en->zh" else FEWSHOT_ZH_EN


def build_messages(text: str, direction: str, terms: list[tuple[str, str]],
                   keep_all: list[str], history: list[tuple[str, str]] | None = None,
                   extra: str = "", with_fewshot: bool = True) -> list[dict]:
    """组装 OpenAI 兼容 messages。

    顺序：静态 system -> 静态少样本 -> 历史（变） -> 当前句（变）。
    前缀越稳定，后端的前缀缓存越省时间。
    """
    messages: list[dict] = [
        {"role": "system", "content": build_system(direction, keep_all, extra)}
    ]
    if with_fewshot:
        for src, dst in fewshot(direction):
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": dst})
    for src, dst in (history or []):
        messages.append({"role": "user", "content": src})
        messages.append({"role": "assistant", "content": dst})
    messages.append({"role": "user",
                     "content": build_user_message(text, terms, direction)})
    return messages


def direction_of(line: ChatLine) -> str:
    return "en->zh" if line.lang in ("en", "mixed") else "zh->en"

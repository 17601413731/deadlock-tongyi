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
6. 只有一两个词时，直接给对应的中文喊话，不要补全成完整句子。
7. 用户消息可能以 "LOCKED:" 开头，那表示正文里那些词**已经被预先译成中文**了
   （所以正文是中英混杂的）。照 LOCKED 给的中文词义去理解整句，不要另行翻译它们，
   也不要把 LOCKED 那几行抄进译文。"""

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
   "送" NEVER means "send" in this context.
8. If the user message starts with a "LOCKED:" line, those words were already translated
   before it reached you — read the sentence with the meaning LOCKED gives, and never
   copy the LOCKED line itself into your output."""

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

# 俄语源语言的少样本。为什么必须有：few-shot 是"输出长什么样"的唯一示范，
# 拿英译中的示例去教俄译中，模型会以为源语言是英文（实测这类错配会让它
# 把西里尔字母当人名原样带进译文）。这几条选的是亚服/欧服聊天里最常见的类型。
FEWSHOT_RU_ZH: list[tuple[str, str]] = [
    ("мид пусто", "中路没人"),
    ("он лоу, дави его", "他残血，上"),
    ("назад назад", "撤撤撤"),
    ("помогите с урной", "来个人帮忙送魂瓮"),
]

# 非英语源语言的提示词（目前只有俄语，亚服/欧服最常见）。
# 为什么需要单独一条：以前这些消息要么在游戏侧被当成"非英文"丢掉，
# 要么被当成英文送进上面的提示词 —— 模型会把西里尔字母硬当英文处理，
# 输出的中文里常常夹着没翻的原文，然后被译后校验（无汉字即判失败）丢掉。
SYSTEM_RU_ZH = """你是《Deadlock》(中文名"异锁") 游戏内的实时聊天翻译。玩家会发**俄语**聊天，你把它翻成简体中文。

硬性规则：
1. 只输出译文本身。不要解释、不要加引号、不要写"翻译："、不要重复原文。
2. 必须输出中文（汉字）。原文里的西里尔字母不要留在译文里。
3. 这是游戏内快捷交流，用玩家真实的口语说法，短、直接。不要书面化，不要加敬语。
4. 玩家 ID、英雄名、物品名保持原样不翻译（例如 GG、mid、urn 这类英文缩写直接留着）。
5. 只有一两个词时，直接给对应的中文喊话，不要补全成完整句子。
6. 用户消息可能以 "TERMS:" 开头，那是本次必须遵守的术语对照（格式 原文=中文），
   只按它翻译，不要把 TERMS 这一段本身翻译出来。
7. 原文是脏话或嘲讽时，用中文玩家同等强度的说法，不要净化也不要加码。"""

# 源语言 -> system 提示词。键是语言的短码，和 bridge/server.py 的 _detect_language 对齐。
SYSTEM_BY_SOURCE = {"en": SYSTEM_EN_ZH, "ru": SYSTEM_RU_ZH, "el": SYSTEM_RU_ZH}


def system_for(direction: str, source_lang: str = "en") -> str:
    """按"方向 + 源语言"挑 system 提示词。

    注意：返回的模板里可能还有 {keep} 占位符，由 build_system 填。
    未知源语言一律退回英文版（模型自己会处理多语言输入）。
    """
    if direction == "zh->en":
        return SYSTEM_ZH_EN
    return SYSTEM_BY_SOURCE.get((source_lang or "en").lower()[:2], SYSTEM_EN_ZH)


def build_system(direction: str, keep_all: list[str], extra: str = "",
                 source_lang: str = "en") -> str:
    """构造**静态** system 提示（同一方向+源语言下逐字节不变，便于前缀缓存）。"""
    template = system_for(direction, source_lang)
    text = template.format(keep=", ".join(keep_all) if keep_all else "无") \
        if "{keep}" in template else template
    if extra:
        text += "\n\n补充要求：\n" + extra.strip()
    return text


def build_user_message(text: str, terms: list[tuple[str, str]],
                       direction: str = "en->zh", limit: int = MAX_HINT_TERMS,
                       locked: list[tuple[str, str]] | None = None) -> str:
    """把命中的术语贴在用户消息里；没有命中就原样返回。

    ``terms`` 是**术语约束**（英文=中文），``locked`` 是**已预先译好**的词
    （见 glossary.apply_slang 的第三个返回值）：这些英文词在正文里已经被替换成中文，
    所以只能告诉模型"照这个词义理解"，不能再要求它"翻译"。
    两者语义不同，用不同的行名，避免模型混为一谈。
    """
    lines: list[str] = []
    if locked:
        # 去重：同一个来源词只留一条（调用方已经去过一次，这里再兜一道，
        # 因为 build_user_message 也可能被别的调用方直接用）
        seen: set[str] = set()
        uniq: list[tuple[str, str]] = []
        for src, dst in locked:
            if src.lower() in seen:
                continue
            seen.add(src.lower())
            uniq.append((src, dst))
        pairs = "; ".join(f"{src}={dst}" for src, dst in uniq[:MAX_HINT_TERMS])
        lines.append(f"LOCKED: {pairs}")
        lines.append("（LOCKED 里的词在正文里已经预先译成中文了，照这个词义理解，不要另译）")
    if terms:
        taken = {src.lower() for src, _ in locked or []}
        rest = [(src, dst) for src, dst in terms if src.lower() not in taken]
        if rest:
            pairs = "; ".join(f"{src}={dst}" for src, dst in rest[:limit])
            lines.append(f"TERMS: {pairs}")
    if not lines:
        return text
    return "\n".join(lines) + "\n" + text


def fewshot(direction: str, source_lang: str = "en") -> list[tuple[str, str]]:
    if direction != "en->zh":
        return FEWSHOT_ZH_EN
    return FEWSHOT_RU_ZH if (source_lang or "en").lower().startswith(
        ("ru", "el")) else FEWSHOT_EN_ZH


def build_messages(text: str, direction: str, terms: list[tuple[str, str]],
                   keep_all: list[str], history: list[tuple[str, str]] | None = None,
                   extra: str = "", with_fewshot: bool = True,
                   locked: list[tuple[str, str]] | None = None,
                   source_lang: str = "en") -> list[dict]:
    """组装 OpenAI 兼容 messages。

    顺序：静态 system -> 静态少样本 -> 历史（变） -> 当前句（变）。
    前缀越稳定，后端的前缀缓存越省时间。
    """
    messages: list[dict] = [
        {"role": "system",
         "content": build_system(direction, keep_all, extra, source_lang)}
    ]
    if with_fewshot:
        for src, dst in fewshot(direction, source_lang):
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": dst})
    for src, dst in (history or []):
        messages.append({"role": "user", "content": src})
        messages.append({"role": "assistant", "content": dst})
    messages.append({"role": "user",
                     "content": build_user_message(text, terms, direction,
                                                   locked=locked)})
    return messages


def direction_of(line: ChatLine) -> str:
    return "en->zh" if line.lang in ("en", "mixed") else "zh->en"

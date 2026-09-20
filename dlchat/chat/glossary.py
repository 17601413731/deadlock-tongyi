"""术语表：官方本地化（自动生成）+ 社区俚语（手工）+ 保留英文清单。

三层优先级（从高到低）：
1. phrases.json    整句命中 -> 直接返回译文，不调用模型（零延迟、零成本）
2. keep_as_is.json 这些词保留英文原样
3. slang.json / glossary.json  术语约束，注入 prompt 或做替换
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .. import paths

logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = paths.data_dir()


# 本地化文件里的碎片（单字母、缩写、代词）当术语只会污染提示词：
# 实测出现过 "s=秒"（因为 he's）、"You=我"、"They're=他们" 这种噪声。
_TERM_STOPLIST = {
    "s", "m", "n", "t", "d", "re", "ve", "ll", "e", "g", "kg", "cm", "mm", "km",
    "you", "your", "yours", "they", "them", "their", "we", "us", "our", "he", "him",
    "his", "she", "her", "it", "its", "i", "me", "my", "the", "a", "an", "of", "to",
    "and", "or", "is", "are", "was", "were", "be", "been", "do", "does", "did",
    "this", "that", "these", "those", "there", "here", "all", "any", "some",
    "on", "in", "at", "by", "for", "with", "from", "as", "so", "if", "but", "not",
}


def _contains_word(text: str, term: str) -> bool:
    """按词边界匹配（避免 miss 命中 missing 之类的误伤）。"""
    if not term:
        return False
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    pattern = r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])"
    return re.search(pattern, text, re.I) is not None


class Glossary:
    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.terms: dict[str, dict] = {}
        self.phrases: dict[str, str] = {}
        self.slang: dict[str, str] = {}
        self.keep: list[str] = []
        self.meta: dict = {}
        self._load()
        # 中->英方向的黑名单（见 data/zh_term_blocklist.json 的说明）：
        # 中文没有词边界，单字/常用词条目会大面积误命中，把提示词带偏。
        # 必须在任何 terms_for 调用之前就绪，所以放在 _load() 紧后面。
        raw_block = self._read_json("zh_term_blocklist.json", {})
        self._zh_block: set[str] = {
            # lstrip("\ufeff")：防止用记事本编辑后 BOM 混进第一个词条（那会让它漏网）
            k.lstrip("\ufeff").strip()
            for k in (raw_block.get("block") or [])
            if isinstance(k, str) and k.strip()
        }

        # 反向索引：中文 -> 英文（中译英方向用），先到先得
        self._zh_index: dict[str, str] = {}
        for en, item in self.terms.items():
            self._zh_index.setdefault(item["zh"], en)
        for en, zh in self.slang.items():
            self._zh_index.setdefault(zh, en)

        # 人工审校的 中文->英文 词条（data/deadlock_zh2en.json，结构是
        # {"送": {"en": "feed", "kind": "slang"}}）。
        # 这一层**允许单字**（送=feed 这种），因为它是我们逐条整理过的；
        # 而下面 _zh_index 的兜底匹配仍然只认 ≥2 字，避免"上=Up"这类噪音。
        #
        # 这里曾经读 data/glossary_zh.json —— 那是同一份数据的扁平副本
        # （104 条逐条相同、零冲突），两份并存等于"改一份不会同步另一份"。
        # 已于 2026-09-20 合并到这一份（它多了 kind 字段，信息更全）。
        raw_zh = self._read_json("deadlock_zh2en.json", {})
        self.zh_terms: dict[str, str] = {}
        for k, v in raw_zh.items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            en = v.get("en")
            if isinstance(en, str) and en:
                self.zh_terms[k] = en
        self._zh_terms_sorted = sorted(self.zh_terms.items(), key=lambda kv: -len(kv[0]))

        # 术语按长度倒序，替换时优先长词（"mid boss" 先于 "mid"）
        self._slang_sorted = sorted(self.slang.items(), key=lambda kv: -len(kv[0]))
        self._terms_sorted = sorted(self.terms.items(), key=lambda kv: -len(kv[0]))
        self._keep_re = self._compile_keep()
        # 中->英整句直译：手写的中文常用语命中就直接返回，不叫模型（否则模型会瞎翻，
        # 例如 "别送了" 被翻成 "skip urn"）。这条优先于反向术语表。
        self.phrases_zh: dict[str, str] = {
            k: v for k, v in self._read_json("phrases_zh.json", {}).items()
            if not k.startswith("_")
        }
        self._phrases_rev = {v: k for k, v in self.phrases.items()}
        self._phrases_rev.update(self.phrases_zh)

    # ---- 加载 ----

    def _read_json(self, name: str, default):
        path = self.data_dir / name
        if not path.exists():
            logger.warning("术语文件缺失: %s", path)
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.error("术语文件解析失败 %s: %s", path, e)
            return default

    def _load(self) -> None:
        data = self._read_json("glossary.json", {})
        self.terms = data.get("terms", {})
        self.meta = data.get("meta", {})
        self.phrases = self._read_json("phrases.json", {})
        # ⚠️ templates.json（带 {hero_name} 这类占位符的整句）**故意不读**：
        # 它是生成器的产物、目前没有任何消费者 —— 聊天轮盘里带占位符的句子
        # 在 mod 方案下根本不会以英文形态出现在聊天行里（游戏早就把它本地化了）。
        # 需要"把 {s:param_1} 填进去再整句直译"时，从这里 read_json 回来即可，
        # 数据一直由 build_glossary.py 维护着。
        self.slang = {k: v for k, v in self._read_json("slang.json", {}).items()
                      if not k.startswith("_")}
        keep = self._read_json("keep_as_is.json", {})
        self.keep = [w for w in keep.get("keep", []) if w]
        # 保留英文清单与俚语表的**矛盾**要在这里判定：同一个词两边都有时，stash 先跑，
        # 词被换成占位符 → 模型根本看不到它 → 俚语那条规则永远不会生效
        # （实测 afk/ult/b/ks/wp 等 15 个词全是这个下场：既不翻也不解释）。
        #
        # 规矩：**keep_as_is 优先**。它是逐词人工写下来的，比通用俚语表更贴近中文玩家的
        # 实际说法（中文玩家就是打 afk/ult/b/ks/wp，不会打「大招」「挂机」）。
        # 文件层面已经清过一遍（slang.json 不再重复这些词），这里再兜一道：
        # 真遇到重叠就丢掉俚语那条并打日志 —— 沉默地让两条规则同时失效是最坏的结果。
        overrides = {str(w).lower() for w in (keep.get("_slang_overrides") or [])}
        clash = sorted({w.lower() for w in self.keep} & {k.lower() for k in self.slang})
        if clash:
            keep_set = {w.lower() for w in self.keep}
            unnamed = sorted(set(clash) - overrides)
            if unnamed:
                logger.warning("slang.json 与 keep_as_is 重叠（按保留英文处理，建议清理数据）: %s",
                               ", ".join(unnamed))
            self.slang = {k: v for k, v in self.slang.items()
                          if k.lower() not in keep_set}
        # 英->中方向的黑名单（见 data/en_term_blocklist.json 的说明）
        raw_en_block = self._read_json("en_term_blocklist.json", {})
        self._en_block: set[str] = {
            k.lstrip("\ufeff").strip().lower()
            for k in (raw_en_block.get("block") or [])
            if isinstance(k, str) and k.strip()
        }
        logger.info("术语表: %d 术语 / %d 整句 / %d 俚语 / %d 保留词",
                    len(self.terms), len(self.phrases), len(self.slang), len(self.keep))

    def _compile_keep(self) -> re.Pattern | None:
        if not self.keep:
            return None
        parts = sorted((re.escape(w) for w in self.keep), key=len, reverse=True)
        return re.compile(r"(?<![A-Za-z])(" + "|".join(parts) + r")(?![A-Za-z])", re.I)

    # ---- 查询 ----

    def exact_phrase(self, text: str, direction: str = "en->zh") -> str | None:
        """整句命中聊天轮盘等固定短语。"""
        key = text.strip().rstrip(".!。！").lower()
        table = self.phrases if direction.startswith("en") else self._phrases_rev
        for src, dst in table.items():
            if src.strip().rstrip(".!。！").lower() == key:
                return dst
        return None

    def keep_tokens(self, text: str) -> list[str]:
        if self._keep_re is None:
            return []
        return sorted({m.group(0) for m in self._keep_re.finditer(text)})

    @property
    def phrase_keys(self) -> set[str]:
        """已知的聊天短语/词（给小写比较用），供 HUD 过滤判断"像不像人话"。"""
        keys = {p.strip().lower() for p in self.phrases}
        keys |= {s.strip().lower() for s in self.slang}
        keys |= {k.strip().lower() for k in self.keep}
        return {k for k in keys if k}

    @property
    def zh_ui_strings(self) -> set[str]:
        """游戏官方本地化里的中文串：OCR 出来的这些多半是界面文字而不是聊天。"""
        return {item["zh"] for item in self.terms.values() if item.get("zh")}

    def terms_for(self, text: str, direction: str = "en->zh",
                  limit: int = 12) -> list[tuple[str, str]]:
        """找出文本里命中的术语，返回 [(原文词, 译名)]。"""
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        if direction.startswith("en"):
            for en, zh in self._slang_sorted:
                if en.lower() in seen:
                    continue
                if _contains_word(text, en):
                    found.append((en, zh))
                    seen.add(en.lower())
                if len(found) >= limit:
                    return found
            for en, item in self._terms_sorted:
                if en.lower() in seen or len(found) >= limit:
                    continue
                if self._is_noise_term(en):
                    continue
                if _contains_word(text, en):
                    found.append((en, item["zh"]))
                    seen.add(en.lower())
        else:
            # 中->英：先用**人工审校词条**（长短优先，允许单字：送=feed），
            # 再用兜底反向索引。
            # ⚠️ 兜底那一层只认长度 ≥2 的中文词条：单字的（上=Up、秒=seconds、我=me）
            # 会污染提示词（实测 "他残血，上" 被注入 "上=Up"，译文变成 "he's low, Up"）。
            # 审校层为什么可以放开：这些词是我们按 Deadlock 语境逐条确认过的，
            # 「送」在这种语境里就是 feed，不是 send。
            seen_en: set[str] = set()
            matched_zh: list[str] = []
            for zh, en in self._zh_terms_sorted:
                if len(found) >= limit:
                    return found
                if (not self._zh_allowed(zh, curated=True)
                        or zh not in text or en.lower() in seen_en):
                    continue
                # 长词已命中就跳过它的子串：「越塔=dive」命中后不该再塞「塔=guardian」
                if any(zh in longer for longer in matched_zh):
                    continue
                found.append((zh, en))
                matched_zh.append(zh)
                seen_en.add(en.lower())
            # ⚠️ 这里绝对不能把循环变量叫 en：外层 `en` 已经被上面的循环用掉了，
            # 覆盖它会让 en.lower() 读到**别的东西**（实测：去重比对失效，
            # 「魂瓮要没了」和「魂瓮」一起进提示词）。
            for zh2, en2 in sorted(self._zh_index.items(), key=lambda kv: -len(kv[0])):
                if len(found) >= limit:
                    break
                if (len(zh2) >= 2 and self._zh_allowed(zh2) and zh2 in text
                        and en2.lower() not in seen_en):
                    found.append((zh2, en2))
                    seen_en.add(en2.lower())
        return found

    def _zh_allowed(self, zh: str, curated: bool = False) -> bool:
        """中->英方向：这个中文术语允不允许被注入提示词。

        两道闸（都是实测踩坑后加的，别删）：
          1. 黑名单（data/zh_term_blocklist.json）——「上」命中「马上到/早上好/上路」，
             「他们」是菜单文本里的代词（英文写成 "They're"），这类一律不注入。
          2. 单字只认**人工审校层**（deadlock_zh2en.json，逐条确认过「送=feed」）：
             兜底反向索引里的单字一律不注入 —— 中文没有词边界，做不到"只有独立成句
             才算黑话"，实测「上=go」会把「马上到」带偏。
        """
        if not zh or zh in self._zh_block:
            return False
        return len(zh) >= 2 or curated

    def apply_slang(self, text: str) -> tuple[str, dict[str, str], list[tuple[str, str]]]:
        """把命中的俚语替换成中文（英->中方向译前锁定术语）。

        返回 ``(替换后的文本, {占位符: 原词}, [(英文原词, 中文)])``。

        第三个返回值是**替换账本**：这些词在正文里已经被换成中文了，模型看到的
        是"他残血 dive him"这种中英混杂的句子。以前不把账本交出去，导致
        `terms_for()` 在改写后的文本上再也找不到原来的英文词 —— 结果是
        **最该锁术语的短句（push mid and get urn）一条 TERMS 都没拿到**，
        模型只能自由发挥。现在由调用方把它作为"已预先译好"的提示交给模型。
        """
        stash: dict[str, str] = {}
        hints: list[tuple[str, str]] = []
        out = text
        if self._keep_re is not None:
            def _stash(m: re.Match) -> str:
                token = m.group(0)
                key = f"\u2981{len(stash)}\u2981"
                stash[key] = token
                return key

            out = self._keep_re.sub(_stash, out)
        for en, zh in self._slang_sorted:
            pattern = re.compile(r"(?<![A-Za-z])" + re.escape(en) + r"(?![A-Za-z])", re.I)
            new, count = pattern.subn(zh, out)
            if count and en.lower() != zh.lower():
                # 按长度倒序（_slang_sorted 已经排好）→ "mid boss" 记成一条，
                # 不会再补一条 "mid=中路" 把长词的意思顶掉
                hints.append((en, zh))
            out = new
        return out, stash, hints

    @staticmethod
    def restore(text: str, stash: dict[str, str]) -> str:
        for key, token in stash.items():
            text = text.replace(key, token)
        return text

    def reverse_slang(self, text: str) -> str:
        """中->英方向：把中文术语替换回英文，保证对面看得懂。"""
        out = text
        for zh, en in sorted(self._zh_index.items(), key=lambda kv: -len(kv[0])):
            if zh and zh in out:
                out = out.replace(zh, f" {en} ")
        return re.sub(r"\s{2,}", " ", out).strip()

    def _is_noise_term(self, term: str) -> bool:
        """判断某个"术语"是不是本地化碎片/日常词，不值得注入提示词。

        四道闸（每一道都有实测依据）：
          1. 停用词表：本地化文件里有 "You=我"、"They're=他们" 这种代词条目；
          2. 黑名单（data/en_term_blocklist.json）：键本身就是日常英语词 ——
             "their shrine is down" 注入 Down=下、"nice fight" 注入 Fight=进攻；
          3. 含撇号的键一律丢：本地化里的缩写形式基本都是语法词，不是术语
             （实测 "They're"、"Don't" 都在表里）；
          4. 长度/符号碎片：实测出现过 "s=秒"（因为 he's）、"+ DPS and +m radius"。
        """
        t = term.strip().lower().rstrip("'’")
        if not t:
            return True
        if t in self._en_block:
            return True
        if "'" in term or "’" in term:
            return True
        if t in _TERM_STOPLIST:
            return True
        # 单个拉丁字母 / 纯符号
        if len(t) == 1 and t.isalpha():
            return True
        # 只有 2 个字符且不是常见游戏词（hp/ap/cd 这类由 slang 负责）
        if len(t) == 2 and t.isalpha() and t not in {"hp", "mp", "ap", "ad", "cd", "tp"}:
            return True
        # 数字/符号开头的碎片（"+ DPS and +m radius"、"-Bullet Resist"）
        if not t[0].isalpha():
            return True
        return False

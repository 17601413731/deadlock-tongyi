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


class Glossary:
    def __init__(self, data_dir: str | Path = DEFAULT_DATA_DIR):
        self.data_dir = Path(data_dir)
        self.terms: dict[str, dict] = {}
        self.phrases: dict[str, str] = {}
        self.templates: dict[str, str] = {}
        self.slang: dict[str, str] = {}
        self.keep: list[str] = []
        self.meta: dict = {}
        self._load()

        # 反向索引：中文 -> 英文（中译英方向用），先到先得
        self._zh_index: dict[str, str] = {}
        for en, item in self.terms.items():
            self._zh_index.setdefault(item["zh"], en)
        for en, zh in self.slang.items():
            self._zh_index.setdefault(zh, en)

        # 人工审校的 中文->英文 词条（data/glossary_zh.json）。
        # 这一层**允许单字**（送=feed 这种），因为它是我们逐条整理过的；
        # 而下面 _zh_index 的兜底匹配仍然只认 ≥2 字，避免"上=Up"这类噪音。
        self.zh_terms: dict[str, str] = {
            k: v for k, v in self._read_json("glossary_zh.json", {}).items()
            if not k.startswith("_") and isinstance(v, str) and v
        }
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
        self.templates = self._read_json("templates.json", {})
        self.slang = {k: v for k, v in self._read_json("slang.json", {}).items()
                      if not k.startswith("_")}
        keep = self._read_json("keep_as_is.json", {})
        self.keep = [w for w in keep.get("keep", []) if w]
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
                if _is_noise_term(en):
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
                if zh not in text or en.lower() in seen_en:
                    continue
                # 长词已命中就跳过它的子串：「越塔=dive」命中后不该再塞「塔=guardian」
                if any(zh in longer for longer in matched_zh):
                    continue
                found.append((zh, en))
                matched_zh.append(zh)
                seen_en.add(en.lower())
            for zh, en in sorted(self._zh_index.items(), key=lambda kv: -len(kv[0])):
                if len(found) >= limit:
                    break
                if len(zh) >= 2 and zh in text and en.lower() not in seen_en:
                    found.append((zh, en))
                    seen_en.add(en.lower())
        return found

    def apply_slang(self, text: str) -> tuple[str, dict[str, str]]:
        """把命中的俚语替换成中文（英->中方向译前锁定术语）。

        返回 (替换后的文本, {占位符: 原词})，占位符用于译后恢复原有写法。
        保留英文清单里的词先换成占位符，避免被替换/翻译。
        """
        stash: dict[str, str] = {}
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
            out = pattern.sub(zh, out)
        return out, stash

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


def _contains_word(text: str, term: str) -> bool:
    """按词边界匹配（避免 miss 命中 missing 之类的误伤）。"""
    if not term:
        return False
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    pattern = r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])"
    return re.search(pattern, text, re.I) is not None


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


def _is_noise_term(term: str) -> bool:
    """判断某个"术语"是不是本地化碎片，不值得注入提示词。"""
    t = term.strip().lower().rstrip("'’")
    if not t:
        return True
    if t in _TERM_STOPLIST:
        return True
    # 单个拉丁字母 / 纯符号
    if len(t) == 1 and t.isalpha():
        return True
    # 只有 2 个字符且不是常见游戏词（hp/ap/cd 这类由 slang 负责）
    if len(t) == 2 and t.isalpha() and t not in {"hp", "mp", "ap", "ad", "cd", "tp"}:
        return True
    return False

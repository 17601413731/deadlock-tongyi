#!/usr/bin/env python
"""从 Deadlock 自带的多语言本地化文件生成术语表。

思路：游戏自己就有官方 EN/ZH 对照（英雄、装备、技能、状态、聊天轮盘），
直接抽出来做术语约束，比让模型自由发挥准确得多；而且可以随游戏补丁重新生成。

产出（全部落在 data/ 下）：
  glossary.json    EN -> {zh, aliases, cat}   约 4000 条，自动生成，请勿手改
  phrases.json     整句 EN -> ZH             聊天轮盘等，可直接命中、零延迟
  templates.json   带占位符的整句（如 Attack {hero_name}），运行时做替换

手工维护的两份不在这里生成：slang.json（社区俚语）、keep_as_is.json（保留英文）。

用法：
    python scripts/build_glossary.py
    python scripts/build_glossary.py --game "D:\\software\\steam\\steamapps\\common\\Deadlock\\game"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

DEFAULT_GAME_DIR = Path(
    r"D:\software\steam\steamapps\common\Deadlock\game"
)

# 要抽取的本地化模块：目录名 -> 分类
MODULES: dict[str, str] = {
    "citadel_gc_hero_names": "hero",
    "citadel_gc_mod_names": "item",
    "citadel_heroes": "ability",
    "citadel_attributes": "status",
    "citadel_mods": "item",
    "citadel_main": "ui",
    "citadel_gc": "ui",
    "citadel_vdata": "ui",
}

KV_RE = re.compile(r'"((?:[^"\\]|\\.)*)"\s+"((?:[^"\\]|\\.)*)"')
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")
# 中文值里出现连续的拉丁小写字母 → 多半是没删干净的拼音
# （实测 "信号轮盘 xinhao lunpan"；英雄译名里的字母通常是大写缩写，不受影响）
PINYIN_RE = re.compile(r"\b[a-z]{4,}\b")
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}|%[sdif]|<[^>]+>")
# 生成物里混进来的**模板/格式串**：整条都不是给人看的文本，进了术语表只会污染提示词。
#   实测混进来过："+s DurationApplies % Spirit Resist"、"other} Won"、
#   "&nbsp;killed themself"、"Party  other}"、"Mystery Item  %s"、"On Explode:"。
# 判据（三条都是"这条不可能是术语"，宁可漏也不要放进去）：
#   1. 带 HTML 实体（&nbsp; / &amp;）
#   2. 括号不配对（多出 } 或 %number% 这种残留）
#   3. 英文以 : 结尾（"On Wall Hit:" 这种是句首标签，不是可替换的词）
BAD_TERM_TEXT_RE = re.compile(r"&[a-z]+;|[{}]|[%$]\w|:\s*$", re.I)
# 剥掉占位符之后留下的"孤儿单位/连接词"：占位符没了，句子变成
#   "Recast within s."、"Can't Pause for more seconds"、"Summon a Deadhead every stacks"
# —— 这种条目注入提示词比不注入更糟（模型会照抄一句残句）。
# 判据：以 s/m/sec 结尾、或独立出现 s/m/x 这样的孤立单位。
ORPHAN_UNIT_RE = re.compile(r"(?:^|\s)(?:s|m|x|sec|secs|stacks)\.?$", re.I)
# 上面那条只挡**结尾**的孤立单位，挡不住 "+s Duration and Cooldown" 这种
# 单位出现在中间的（"s" 前面是 "+" 不是空格）。这条管"紧跟在符号后面的孤立单位"——
# 也就是数值占位符被剥掉后的残句。刻意**不**匹配普通的 "Stacks"/"S America"，
# 那种是假阳性（第一版写成任意位置的孤立 s/m，结果这两条正常词条被误报）。
LONE_UNIT_RE = re.compile(r"[+\-–]\s*(?:s|m|x|sec|secs|stacks)\b", re.I)
# "S America" 这种区域名要单独排掉（它是地图/服务器列表里的词，不是术语）
REGION_NOISE_RE = re.compile(r"^(?:[NSEW]\s+)?(?:America|Europe|Asia|Africa|Oceania)$", re.I)
# 剥掉数字后剩下的"more/at/for"这类悬空词（"Expires: at"、"Can't Pause for more"）。
# 只在这些词出现在**结尾**时判定，避免误伤正常术语。
DANGLING_TAIL_RE = re.compile(r"(?:\bmore|\bat|\bfor|\bof|\bwithin|\bevery|\band)$", re.I)
# 原始英文里带数字但清洗后数字没了 → 说明这里原本是 %s/%.1f 之类的数值占位符，
# 剩下的文本是残句（"Can't Pause for more seconds" 就是这么来的）。
NUMERIC_PLACEHOLDER_RE = re.compile(r"%\d|\d")
# 中文值里如果出现"单个拉丁字母 = 单位"（"m=米"、"s=秒"），保留；其余含拉丁字母的
# 中文值基本是未翻译残留，丢掉。
UNIT_ZH = {"米": "m", "秒": "s", "点": "pt", "倍": "x"}
# 中文字之间被插了空格（"肉  盾"、"高  压  电"、"区 域 封 锁"）——这是本地化文件里的
# 排版残留。作为术语/少样本示例喂给模型，模型会照抄这种怪空格。
CJK_SPACE_RE = re.compile(r"(?<=[\u4e00-\u9fff])[ \t]+(?=[\u4e00-\u9fff])")
# AI 生成或从别的游戏搬来的脏别名：会在别名/搜索关键字里混进完全无关的词
# （实测："不朽尸王"→幸免于难、"刷新球"→刷新环、"大电锤"→积雷电容）。
# 这些词会被 build_gamenames.py 带进名称保护表，让"不朽尸王"被当成"幸免于难"的别名，
# 翻译时直接说错名字。判据是"这个词不属于 Deadlock"。
ALIAS_BLOCKLIST = {
    "不朽尸王", "刷新球", "大电锤", "回音战刃", "天堂之戟", "塞拉斯", "弗兰克",
    "骷髅王", "一枪超人", "哈基米", "帕吉", "屠夫", "沙王", "斧王", "拉比克",
    "悠米", "提夫林", "米垃圾", "血魔", "狼人", "骷髅", "剑圣", "敌法",
}
# 别名里出现这些词根说明它来自别的游戏（Dota/LoL 的装备与英雄名）
ALIAS_FOREIGN_RE = re.compile(
    r"(跳刀|漩涡|战鼓|风暴宝器|刷新|电锤|尸王|戟|刃甲|羊刀|大炮|蝴蝶|狂战)", re.I)
# 这些后缀是同一术语的变体，不作为独立词条
VARIANT_SUFFIXES = (
    "_search", "_label", "_postvalue_label", "_prevalue_label",
    "_postfix", "_prefix", "_desc", "_description", "_tooltip",
    "_short", "_long", "_plural",
)
# 纯 UI 噪音：不作为术语（保留会干扰短句翻译）
NOISE_KEYS = re.compile(
    r"^(Language|english|schinese)$"
    r"|_search|_postfix|_postvalue|_label$"
    r"|Button|Tooltip|Dialog|Toast|Error|Failed|Loading|Steam|Setting",
    re.I,
)


def parse_kv(path: Path) -> dict[str, str]:
    """解析 Valve KeyValues 本地化文件，返回 key -> value（首个出现优先）。"""
    out: dict[str, str] = {}
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("["):
                continue
            for key, value in KV_RE.findall(line):
                out.setdefault(key, value)
    return out


def strip_variant(key: str) -> str:
    """去掉 :n 语境后缀与变体后缀，得到术语主键。"""
    base = key.split(":")[0]
    for suffix in VARIANT_SUFFIXES:
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def is_search_key(key: str) -> bool:
    return key.split(":")[0].endswith("_search")


def clean(text: str) -> str:
    """去掉占位符/标签/多余空白，并**压掉中文字之间的排版空格**。

    例：`"区 域 封 锁"` -> `"区域封锁"`，`"<br>往基地走了"` -> `"往基地走了"`。
    不压的话术语表里会留下 99 条带空格的怪值（实测），作为 in-context 示例
    喂给模型，模型会照着学。
    """
    out = PLACEHOLDER_RE.sub("", text).replace("<br>", " ")
    out = CJK_SPACE_RE.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def clean_zh(text: str) -> str:
    """中文侧的额外清洗：丢掉"根本不是给人看的"那些值。

    ⚠️ 这里**不能**"中文里混了拉丁字母就丢" —— 官方的英雄译名本身就带字母
    （McGinnis=麦金妮、Vyper=蝰邪、Akimbo=阿金驳），一刀切会把 37 个英雄名
    连同它们的别名一起删掉。真正要拦的是模板残句（&nbsp;、other}、%name%），
    由 BAD_TERM_TEXT_RE 负责。
    """
    out = clean(text)
    if not out or BAD_TERM_TEXT_RE.search(out):
        return ""
    return out


def is_usable_zh(out: str) -> bool:
    """清洗后还值不值得进表（防止 clean_zh 把内容削成空）。"""
    return bool(out) and bool(CJK_RE.search(out))


def clean_alias(alias: str, canonical: str) -> bool:
    """别名/搜索关键字清洗：只留"像名字"的中文别名。

    游戏自己的 `_search` 字段是一锅粥（中文别名 + 拼音 + 从别的游戏搬来的词），
    没法可靠切分，所以判据刻意保守：
      · 已经等于正式译名的不算别名；
      · 太长的不像别名（正式译名都 ≤16 字）；
      · 拉丁字母/数字混在里面的一律丢（拼音就是这种）；
      · 上了黑名单的丢（"不朽尸王"这种跨游戏词）。
    """
    if not alias or alias == canonical:
        return False
    if CJK_RE.search(canonical) and CJK_RE.search(alias):
        # 同一个名字的另一种叫法通常共享至少一个字（"岚梦"/"岚梦"、"老七"/"柒" 这类例外由黑名单兜）
        shared = set(alias) & set(canonical)
        if not shared and alias not in ALIAS_BLOCKLIST:
            return False
    if LATIN_RE.search(alias) or any(ch.isdigit() for ch in alias):
        return False
    if len(alias) > 8 or alias in ALIAS_BLOCKLIST:
        return False
    if ALIAS_FOREIGN_RE.search(alias):
        return False
    return True


def cjk_tokens(text: str) -> list[str]:
    """从 "保安 警长 baoan jingzhang 守望者" 这类搜索关键字里挑出中文别名。"""
    return [t for t in re.split(r"[\s,;/]+", text) if t and CJK_RE.search(t)]


def find_pair(loc_root: Path, module: str) -> tuple[Path, Path] | None:
    for base in (loc_root / module, loc_root):
        en = base / f"{module}_english.txt"
        zh = base / f"{module}_schinese.txt"
        if en.exists() and zh.exists():
            return en, zh
    return None


def build(game_dir: Path) -> tuple[dict, dict, dict, dict, list[str]]:
    loc_root = game_dir / "citadel" / "resource" / "localization"
    if not loc_root.exists():
        raise SystemExit(f"找不到本地化目录: {loc_root}")

    terms: dict[str, dict] = {}
    phrases: dict[str, str] = {}
    templates: dict[str, str] = {}
    stats: dict[str, int] = {}
    by_lower: dict[str, str] = {}      # 小写英文 -> 表里的键（大小写去重用）
    notes: list[str] = []              # 清洗过程的说明，最后打印出来供人工复核

    for module, category in MODULES.items():
        pair = find_pair(loc_root, module)
        if pair is None:
            print(f"  跳过 {module}（缺文件）")
            continue
        en, zh = parse_kv(pair[0]), parse_kv(pair[1])

        # 先把 _search 里的中文别名挂到主键上（只留"像名字"的那些）
        aliases: dict[str, list[str]] = {}
        for key, value in en.items():
            if not is_search_key(key) or key not in zh:
                continue
            stem = strip_variant(key)
            canonical = clean_zh(zh.get(stem, ""))
            alias = [t for t in cjk_tokens(zh[key]) if clean_alias(t, canonical)]
            if alias:
                aliases.setdefault(stem, []).extend(alias)

        added = 0
        for key, en_text in en.items():
            if is_search_key(key) or key not in zh:
                continue
            stem = strip_variant(key)
            if NOISE_KEYS.search(stem):
                continue
            en_clean = clean(en_text)
            zh_clean = clean_zh(zh[key])
            if not en_clean or not is_usable_zh(zh_clean):
                continue
            if en_clean.lower() == zh_clean.lower():
                continue  # 未翻译（本地化文件里两边一样的条目）
            # 英文键里必须真的有拉丁字母，中文值里必须真的有汉字
            if not LATIN_RE.search(en_clean) or not CJK_RE.search(zh_clean):
                continue
            if BAD_TERM_TEXT_RE.search(en_clean):
                continue
            if ORPHAN_UNIT_RE.search(en_clean) or DANGLING_TAIL_RE.search(en_clean):
                continue
            if REGION_NOISE_RE.match(en_clean):
                continue
            # 清洗后仍留着孤立的单位 token（"+s Duration" / "+m Move Speed"）：
            # 那个 s/m 原本是 %s 之类的数值占位符，剥掉之后就成了残句
            if LONE_UNIT_RE.search(en_clean):
                continue
            # 原文带数字、清洗后没了 → 这是被剥掉的数值占位符留下的残句
            if NUMERIC_PLACEHOLDER_RE.search(en_text) and not NUMERIC_PLACEHOLDER_RE.search(en_clean):
                continue
            # 长度上限：术语是"可以替换的词"，不是句子。
            # ⚠️ 别删这两行 —— 曾经为了重构顺手删掉，结果 "Increased Trooper Health
            # Increased Respawn Times" 这种拼接串、"+s DurationApplies % Spirit Resist"
            # 这种残留全部涌进术语表（实测新增 10 条垃圾）。
            if len(en_clean) > 40 or len(zh_clean) > 40:
                notes.append(f"[长度] {en_clean[:44]!r}")
                continue
            if len(en_clean.split()) > 5:
                continue  # 长句交给 phrases/模型，不进术语表
            if any(ch in en_clean for ch in "/"):
                # "Level /"、"/ Souls"、"Question /" 这种是界面上的拼接片段
                notes.append(f"[斜杠片段] {en_clean!r}")
                continue

            # 大小写不敏感地去重：本地化文件里同时存在 "Silencer"/"silencer"、
            # "Max Health"/"max health" 这类重复键（实测 62 组），两个都留
            # 就是给提示词塞重复项。zh 不同的那几组（On hit/On Hit）保留差异写法。
            dedup_key = en_clean.lower()
            existing_key = by_lower.get(dedup_key)
            existing = terms.get(existing_key) if existing_key else None
            if existing is not None:
                # 同一英文词条多个译名：保留第一个，其余记进别名
                if zh_clean not in existing["aliases"] and zh_clean != existing["zh"]:
                    existing["aliases"].append(zh_clean)
                continue

            terms[en_clean] = {
                "zh": zh_clean,
                "aliases": sorted(set(aliases.get(stem, [])))[:4],
                "cat": category,
            }
            by_lower[dedup_key] = en_clean
            added += 1
            # 顺带把中文译名反查英文，便于 ZH->EN 方向
        stats[module] = added

        # 聊天轮盘 / 快捷语：整句直译，运行时可零延迟命中
        for key, en_text in en.items():
            if key not in zh or not re.search(r"chatwheel|ping_wheel|ping_phrase", key, re.I):
                continue
            en_clean = clean(en_text)
            zh_clean = clean_zh(zh[key])
            if not en_clean or not zh_clean or en_clean == zh_clean:
                continue
            if PINYIN_RE.search(zh_clean):
                # 本地化文件里有"中文 + 拼音"的查询关键字串（实测：
                # "信号轮盘 xinhao lunpan"）。带进 phrases.json 后，
                # 玩家会看到拼音当译文，也会教模型输出拼音。
                notes.append(f"[拼音残留] {en_clean!r} -> {zh_clean!r}")
                continue
            if "{" in en_text or "%" in en_text:
                templates[en_clean] = zh_clean
            else:
                phrases[en_clean] = zh_clean

    return terms, phrases, templates, stats, notes


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Deadlock EN->ZH 术语表")
    ap.add_argument("--game", type=Path, default=DEFAULT_GAME_DIR,
                    help="Deadlock 的 game 目录")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = ap.parse_args()

    print(f"游戏目录: {args.game}")
    terms, phrases, templates, stats, notes = build(args.game)
    args.out.mkdir(parents=True, exist_ok=True)

    meta = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "game_dir": str(args.game),
        "modules": stats,
        "term_count": len(terms),
        "phrase_count": len(phrases),
    }
    (args.out / "glossary.json").write_text(
        json.dumps({"meta": meta, "terms": terms}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    (args.out / "phrases.json").write_text(
        json.dumps(phrases, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (args.out / "templates.json").write_text(
        json.dumps(templates, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    print(f"\n术语 {len(terms)} 条 / 整句 {len(phrases)} 条 / 含占位符整句 {len(templates)} 条")
    for module, n in stats.items():
        print(f"  {module:26} +{n}")
    if notes:
        # 清洗日志：重新生成时"哪些条目被挡掉了、为什么"，方便人工复核
        # （沉默地丢数据是这类生成脚本最容易踩的坑）
        print(f"\n被清洗规则挡掉 {len(notes)} 条（前 12 条）：")
        for line in notes[:12]:
            print("  " + line)
    print("\n样例：")
    for i, (en, item) in enumerate(terms.items()):
        if i >= 8:
            break
        alias = f"  (别名: {'/'.join(item['aliases'])})" if item["aliases"] else ""
        print(f"  {en:<30} -> {item['zh']:<16} [{item['cat']}]{alias}")
    print(f"\n已写入 {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

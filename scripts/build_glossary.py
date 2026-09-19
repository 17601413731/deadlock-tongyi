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
PLACEHOLDER_RE = re.compile(r"\{[^}]*\}|%[sdif]|<[^>]+>")
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
    return PLACEHOLDER_RE.sub("", text).replace("<br>", " ").strip()


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


def build(game_dir: Path) -> tuple[dict, dict, dict, dict]:
    loc_root = game_dir / "citadel" / "resource" / "localization"
    if not loc_root.exists():
        raise SystemExit(f"找不到本地化目录: {loc_root}")

    terms: dict[str, dict] = {}
    phrases: dict[str, str] = {}
    templates: dict[str, str] = {}
    stats: dict[str, int] = {}

    for module, category in MODULES.items():
        pair = find_pair(loc_root, module)
        if pair is None:
            print(f"  跳过 {module}（缺文件）")
            continue
        en, zh = parse_kv(pair[0]), parse_kv(pair[1])

        # 先把 _search 里的中文别名挂到主键上
        aliases: dict[str, list[str]] = {}
        for key, value in en.items():
            if not is_search_key(key) or key not in zh:
                continue
            stem = strip_variant(key)
            canonical = zh.get(stem, "")
            alias = [t for t in cjk_tokens(zh[key]) if t != canonical]
            if alias:
                aliases.setdefault(stem, []).extend(alias)

        added = 0
        for key, en_text in en.items():
            if is_search_key(key) or key not in zh:
                continue
            stem = strip_variant(key)
            if NOISE_KEYS.search(stem):
                continue
            en_clean, zh_clean = clean(en_text), clean(zh[key])
            if not en_clean or not zh_clean:
                continue
            if en_clean.lower() == zh_clean.lower():
                continue  # 未翻译
            if not LATIN_RE.search(en_clean) or not CJK_RE.search(zh_clean):
                continue
            if len(en_clean) > 40 or len(zh_clean) > 40:
                continue
            if len(en_clean.split()) > 5:
                continue  # 长句交给 phrases/模型，不进术语表

            existing = terms.get(en_clean)
            if existing is not None:
                # 同一英文词条多个译名：保留第一个，其余记进别名
                if zh_clean not in existing["aliases"] and zh_clean != existing["zh"]:
                    existing["aliases"].append(zh_clean)
                continue

            terms[en_clean] = {
                "zh": zh_clean,
                "aliases": sorted(set(aliases.get(stem, [])))[:6],
                "cat": category,
            }
            added += 1
            # 顺带把中文译名反查英文，便于 ZH->EN 方向
        stats[module] = added

        # 聊天轮盘 / 快捷语：整句直译，运行时可零延迟命中
        for key, en_text in en.items():
            if key not in zh or not re.search(r"chatwheel|ping_wheel|ping_phrase", key, re.I):
                continue
            en_clean = clean(en_text)
            zh_clean = clean(zh[key])
            if not en_clean or not zh_clean or en_clean == zh_clean:
                continue
            if "{" in en_text or "%" in en_text:
                templates[en_clean] = zh_clean
            else:
                phrases[en_clean] = zh_clean

    return terms, phrases, templates, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Deadlock EN->ZH 术语表")
    ap.add_argument("--game", type=Path, default=DEFAULT_GAME_DIR,
                    help="Deadlock 的 game 目录")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parent.parent / "data")
    args = ap.parse_args()

    print(f"游戏目录: {args.game}")
    terms, phrases, templates, stats = build(args.game)
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

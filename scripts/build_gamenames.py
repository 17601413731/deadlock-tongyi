#!/usr/bin/env python
"""生成 data/gamenames.json —— 英雄/物品名对照表（给游戏内 mod 做"名称保护"）。

mod 启动时会从桥的 /api/v1/gamenames 拉这份表，把玩家名/英雄名/物品名保护起来不翻译。
我们从游戏本地化自动生成（比手写全、能随补丁重跑）。

用法：
    python scripts/build_gamenames.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat import paths                                  # noqa: E402

CATEGORIES = ("hero", "item")   # 只保护英雄名和装备名；技能/状态里多是数值文本


def _is_clean_name(en: str, zh: str) -> bool:
    """名称保护表只放"真名字"：过滤掉 %子弹抗性、%/s、{s:xxx} 这类数值/格式串。"""
    if not zh or len(en) > 24 or len(zh) > 16:
        return False
    if any(ch in en for ch in "%{}<>") or any(ch in zh for ch in "%{}<>"):
        return False
    if en.strip().endswith(("s", "/s")) and len(en) <= 5:
        return False
    # 至少要有 3 个连续字母（排除 "+2.4"、"T1"、纯数字）
    return sum(1 for ch in en if ch.isalpha()) >= 3


def main() -> int:
    glossary_path = paths.data_dir() / "glossary.json"
    if not glossary_path.exists():
        print(f"找不到 {glossary_path}，先跑 scripts/build_glossary.py")
        return 1
    data = json.loads(glossary_path.read_text(encoding="utf-8"))
    terms = data.get("terms", {})

    names: dict[str, str] = {}
    for en, item in terms.items():
        if item.get("cat") not in CATEGORIES:
            continue
        zh = (item.get("zh") or "").strip()
        if not _is_clean_name(en, zh):
            continue
        names[en] = zh
        for alias in item.get("aliases", [])[:3]:       # 社区叫法也保护起来
            if _is_clean_name(alias, zh):
                names.setdefault(alias, zh)

    out = paths.data_dir() / "gamenames.json"
    out.write_text(json.dumps(names, ensure_ascii=False, indent=1, sort_keys=True),
                   encoding="utf-8")
    print(f"已写入 {out}：{len(names)} 条（按分类 {CATEGORIES}）")
    for i, (en, zh) in enumerate(list(names.items())[:8]):
        print(f"  {en:<24} -> {zh}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

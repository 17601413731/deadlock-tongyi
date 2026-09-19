"""在 Deadlock 官方本地化里查术语的官方译名（英↔简中双向）。

用途：我们要建"中文→英文"术语表，最怕自己编的译名和游戏内不一致
（比如 Urn 到底叫魂瓮还是骨灰瓮、Rejuvenator 叫复生石还是复活石）。
这里直接查官方文件，拿到的就是玩家在游戏里看到的词。

用法：
    python scripts/lookup_terms.py --en Urn "Mid-Boss" Rejuvenator
    python scripts/lookup_terms.py --zh 魂瓮 越塔 送
    python scripts/lookup_terms.py --core          # 打印核心术语表
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LOC = Path(r"D:\software\steam\steamapps\common\Deadlock\game\citadel"
           r"\resource\localization")
LINE_RE = re.compile(r'^\s*"([^"]+)"\s+"(.*)"\s*$')

# 核心术语（来自 SteamDB 的 Deadlock 术语表，2026 版）
CORE_EN = [
    "Souls", "Last Hit", "Soul Orb", "Deny", "Net Worth", "Ability Points",
    "Boon", "Imbue", "Flex Slot", "Guardian", "Walker", "Base Guardian",
    "Shrine", "Patron", "Urn", "Mid-Boss", "Rejuvenator", "Neutral", "Camp",
    "Rune", "Powerup", "Trooper", "Active", "Passive", "Component",
    "Buff", "Nerf", "Rework", "Meta", "Lane", "Yellow Lane", "Blue Lane",
    "Green Lane", "Purple Lane", "Stun", "Slow", "Root", "Silence",
    "Zipline", "Shop", "Stamina", "Dash", "Parry", "Melee", "Headshot",
]
CORE_ZH = [
    "魂瓮", "送", "别送", "越塔", "抱团", "打野", "偷家", "开团", "蹲人",
    "绕后", "撤退", "推进", "集合", "抱团推进", "残血", "大招", "技能",
    "经济", "补刀", "反补", "视野", "辅助", "上单", "中路", "下路",
]


def parse(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def load() -> tuple[dict, dict, dict, dict]:
    main = LOC / "citadel_main" / "citadel_main_%s.txt"
    vo = LOC / "citadel_generated_vo" / "citadel_generated_vo_%s.txt"
    return (parse(Path(str(main) % "english")), parse(Path(str(main) % "schinese")),
            parse(Path(str(vo) % "english")), parse(Path(str(vo) % "schinese")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--en", nargs="*", default=[])
    ap.add_argument("--zh", nargs="*", default=[])
    ap.add_argument("--core", action="store_true")
    args = ap.parse_args()

    en_main, zh_main, en_vo, zh_vo = load()
    # 反向索引：英文文本 -> token
    en_index: dict[str, str] = {}
    for token, text in en_main.items():
        en_index.setdefault(text.strip().lower(), token)

    if args.core or (not args.en and not args.zh):
        print("=== 核心术语的官方中文（查英文原文精确匹配）")
        for term in CORE_EN:
            token = en_index.get(term.lower())
            zh = zh_main.get(token, "") if token else ""
            print(f"  {term:16} -> {zh or '（未精确匹配到，可能词形不同）':24} [{token or '-'}]")
        return 0

    for term in args.en:
        token = en_index.get(term.strip().lower())
        zh = zh_main.get(token, "") if token else ""
        print(f"EN {term!r:20} -> {zh!r}   token={token}")
        if not token:
            hits = [(t, v) for t, v in en_main.items()
                    if term.lower() in v.lower() and len(v) < 60][:6]
            for t, v in hits:
                print(f"     近似: {v!r} -> {zh_main.get(t,'')!r}   [{t}]")

    for term in args.zh:
        hits = [(t, v) for t, v in zh_main.items() if term in v and len(v) < 60][:6]
        print(f"ZH {term!r}")
        for t, v in hits:
            print(f"     {v!r:34} <- EN {en_main.get(t, '')!r}   [{t}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

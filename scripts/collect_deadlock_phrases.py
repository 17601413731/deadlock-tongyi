"""采集 Deadlock 官方"玩家沟通用语"（英↔简中对照）。

来源：游戏自带的本地化文件（松散文本，无需解包）
    game/citadel/resource/localization/citadel_main/citadel_main_{english,schinese}.txt
    game/citadel/resource/localization/citadel_generated_vo/citadel_generated_vo_{english,schinese}.txt

采集三类：
  1. 聊天轮盘（chat wheel）呼号 —— 玩家实际上最常用的沟通句，Valve 自带官方翻译
  2. 聊天/沟通相关 UI 文案
  3. 短语音呼号（VO 里长度短的，玩家听到并会模仿的说法）

为什么不用社区整理的：这份是官方数据，术语（魂瓮/守卫/步行者等）与游戏内完全一致，
直接拿来做术语表和少样本示例不会引入偏差。

用法：
    python scripts/collect_deadlock_phrases.py            # 采集并写文件
    python scripts/collect_deadlock_phrases.py --sample   # 只看样例
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LOC = Path(r"D:\software\steam\steamapps\common\Deadlock\game\citadel"
           r"\resource\localization")
# 本脚本只负责"解析 + 采样"（宽匹配会捞到 2 万条英雄语音，属噪声）。
# 正式语料由 scripts/build_phrase_corpus.py 产出到 data/deadlock_*.json。
OUT_JSON = ROOT / "data" / ".deadlock_raw_ignore.json"
OUT_TSV = ROOT / "data" / ".deadlock_raw_ignore.tsv"

LINE_RE = re.compile(r'^\s*"([^"]+)"\s+"(.*)"\s*$')

GROUPS = {
    "main": ("citadel_main", "citadel_main"),
    "vo": ("citadel_generated_vo", "citadel_generated_vo"),
}

# 轮盘呼号：citadel_chatwheel_label_X / citadel_chatwheel_message_X
CHATWHEEL_RE = re.compile(r"^citadel_chatwheel_(label|message)_(.+)$")
# 聊天/沟通 UI 文案
CHATUI_RE = re.compile(r"chat|communi|ping", re.I)
# 短呼号（VO）：长度短、像喊话
SHORT_CALL_RE = re.compile(r"^citadel_vo_.*(ping|chat|warn|alert|call)", re.I)


def parse_locale(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.lstrip().startswith("//"):
            continue
        m = LINE_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


def load_pair(group: str) -> tuple[dict[str, str], dict[str, str]]:
    name = GROUPS[group][1]
    base = LOC / name
    return (parse_locale(base / f"{name}_english.txt"),
            parse_locale(base / f"{name}_schinese.txt"))


def collect() -> dict[str, dict[str, str]]:
    en_main, zh_main = load_pair("main")
    en_vo, zh_vo = load_pair("vo")
    print(f"localization: main {len(en_main)} token / vo {len(en_vo)} token")

    wheel: dict[str, dict[str, str]] = {}
    for token, text in en_main.items():
        m = CHATWHEEL_RE.match(token)
        if not m:
            continue
        kind, key = m.group(1), m.group(2)
        zh_text = zh_main.get(token, "")
        entry = wheel.setdefault(key, {})
        entry["en" if kind == "message" else "label"] = text.strip()
        if zh_text:
            entry["zh" if kind == "message" else "labelZh"] = zh_text.strip()

    ui: dict[str, dict[str, str]] = {}
    for token, text in en_main.items():
        if CHATWHEEL_RE.match(token) or not CHATUI_RE.search(token):
            continue
        zh_text = zh_main.get(token, "")
        if not zh_text or len(text) > 120:
            continue
        ui[token] = {"en": text.strip(), "zh": zh_text.strip()}

    short: dict[str, dict[str, str]] = {}
    for token, text in en_vo.items():
        if not SHORT_CALL_RE.search(token) or not (1 < len(text) <= 48):
            continue
        zh_text = zh_vo.get(token, "")
        if not zh_text:
            continue
        short[token] = {"en": text.strip(), "zh": zh_text.strip()}

    return {"chatwheel": wheel, "chatUi": ui, "shortCalls": short}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    data = collect()
    wheel, ui, short = data["chatwheel"], data["chatUi"], data["shortCalls"]
    print(f"聊天轮盘 {len(wheel)} 条 | 聊天 UI {len(ui)} 条 | 短呼号 {len(short)} 条")

    if args.sample:
        print("\n=== 聊天轮盘（官方，英↔简中）")
        for key, item in list(wheel.items())[:40]:
            print(f"  {key:14} {item.get('en','')!r:34} {item.get('zh','')!r}")
        return 0

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    with OUT_TSV.open("w", encoding="utf-8") as fh:
        fh.write("kind\tkey\ten\tzh\n")
        for key, item in sorted(wheel.items()):
            fh.write(f"chatwheel\t{key}\t{item.get('en','')}\t{item.get('zh','')}\n")
        for token, item in sorted(short.items()):
            fh.write(f"call\t{token}\t{item['en']}\t{item['zh']}\n")
        for token, item in sorted(ui.items()):
            fh.write(f"ui\t{token}\t{item['en']}\t{item['zh']}\n")
    print(f"已写 {OUT_JSON}")
    print(f"已写 {OUT_TSV}")

    print("\n=== 聊天轮盘采样")
    for key, item in list(wheel.items())[:30]:
        print(f"  {item.get('en','')!r:36} {item.get('zh','')!r}")
    print("\n=== 短呼号采样")
    for token, item in list(short.items())[:12]:
        print(f"  {item['en']!r:36} {item['zh']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

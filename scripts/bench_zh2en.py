"""量化对比：改提示词/术语表前后，中文→英文的术语命中率。

为什么要这个：术语质量问题很容易变成"凭感觉争论"。这里用 data/deadlock_testset.jsonl
（30 条真实中文聊天 + 期望英文术语）跑两条提示词，统计命中率并逐句打印证据。

  --variant legacy : 复刻改动前的少样本（含那句误导性的"送魂瓮→need help with urn"）
  --variant new    : 当前项目里的提示词（新少样本 + Deadlock 黑话规则 + 审校术语表）

用法：
    python scripts/bench_zh2en.py --variant legacy
    python scripts/bench_zh2en.py --variant new
    python scripts/bench_zh2en.py --compare        # 两个都跑并给对比表
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TESTSET = ROOT / "data" / "deadlock_testset.jsonl"

# 改动前的少样本（历史事实，用于对照）
LEGACY_FEWSHOT = [
    ("中路没人", "mid is open"),
    ("他残血", "he's low"),
    ("撤", "b"),
    ("来个人帮忙送魂瓮", "need help with urn"),
]
LEGACY_SYSTEM = """You are translating Chinese in-game chat for the game Deadlock into short, natural English.

Hard rules:
1. Output ONLY the translation. No explanation, no quotes, no "Translation:" prefix.
2. Use real North-American in-game chat style: short, casual, abbreviations are fine.
3. The user message may start with a "TERMS:" line giving required terminology
   (format chinese=english). Use it exactly and do NOT translate the TERMS line itself.
4. Never add politeness or extra content. One line only.
5. If the input is one or two words, translate it as a short callout, not a sentence."""


def call_ollama(messages: list[dict], model: str, timeout: int = 120) -> str:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.0,
                       "max_tokens": 128, "keep_alive": "10m"}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]["content"].strip()


def build_legacy(text: str, model: str) -> str:
    msgs = [{"role": "system", "content": LEGACY_SYSTEM}]
    for src, dst in LEGACY_FEWSHOT:
        msgs.append({"role": "user", "content": src})
        msgs.append({"role": "assistant", "content": dst})
    msgs.append({"role": "user", "content": text})
    return call_ollama(msgs, model)


def build_new(text: str, model: str) -> str:
    from dlchat.chat.glossary import Glossary
    from dlchat.translate.prompt import build_messages
    g = Glossary()
    terms = g.terms_for(text, "zh->en", limit=8)
    msgs = build_messages(text, "zh->en", terms, keep_all=[])
    return call_ollama(msgs, model)


def score(variant: str) -> list[dict]:
    from dlchat.config import load_config
    model = load_config().translate.model
    rows = []
    for line in TESTSET.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        text, expect = item["zh"], item["expect"]
        out = build_legacy(text, model) if variant == "legacy" else build_new(text, model)
        low = out.lower()
        hit = [e for e in expect if e.lower() in low]
        rows.append({"zh": text, "out": out, "expect": expect,
                     "hit": hit, "ok": len(hit) == len(expect)})
    return rows


def report(variant: str, rows: list[dict], verbose: bool) -> float:
    ok = sum(1 for r in rows if r["ok"])
    rate = ok / len(rows) * 100 if rows else 0.0
    print(f"[{variant}] 术语命中 {ok}/{len(rows)} = {rate:.0f}%")
    if verbose:
        for r in rows:
            mark = "✓" if r["ok"] else "✗"
            print(f"  {mark} {r['zh']!r:28} -> {r['out']!r}")
            if not r["ok"]:
                print(f"      期望包含 {r['expect']}，实际命中 {r['hit']}")
    return rate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=["legacy", "new"], default="new")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.compare:
        legacy = report("legacy（改动前）", score("legacy"), args.verbose)
        new = report("new（改动后）", score("new"), args.verbose)
        print(f"\n结论：术语命中率 {legacy:.0f}% -> {new:.0f}%"
              f"（{'+' if new >= legacy else ''}{new - legacy:.0f} 个百分点）")
        return 0

    rows = score(args.variant)
    report(args.variant, rows, True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

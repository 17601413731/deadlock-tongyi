#!/usr/bin/env python
"""实测六：翻译链路（提示词 + 术语约束 + 模型）在真实聊天句上的表现。

需要翻译后端可用：
  · 本地 Ollama：先 `ollama serve`（本机模型已存在：hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K）
  · 或云端：改 config.yaml 的 base_url / api_key / model

用法：
    python scripts/spike_translate.py                 # 跑内置的 12 条真实聊天句
    python scripts/spike_translate.py --text "mid no"
    python scripts/spike_translate.py --zh "中路没人，撤"   # 反向：中->英
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.chat.glossary import Glossary              # noqa: E402
from dlchat.config import load_config                  # noqa: E402
from dlchat.translate.client import ChatTranslator     # noqa: E402

# 真实会出现在 Deadlock 聊天里的句子（短、口语、带术语和俚语）
SAMPLES_EN = [
    "mid no",
    "he's low, dive him",
    "push B and get urn",
    "gg wp",
    "careful, they're rotating to blue lane",
    "mid boss in 30 seconds, group up",
    "why did you dive their walker alone",
    "need help with urn pls",
    "7 is smurfing",
    "stop feeding noob",
    "b b b",
    "ty",
]
SAMPLES_ZH = [
    "中路没人",
    "他残血，上",
    "推中路，然后去拿魂瓮",
    "别送了",
    "等我一下，马上到",
]


async def run(args) -> int:
    cfg = load_config(args.config)
    if args.model:
        cfg.translate.model = args.model
    glossary = Glossary()
    tr = ChatTranslator(cfg.translate, glossary)

    ok, detail = await tr.ping()
    print(f"后端: {cfg.translate.base_url}  模型: {cfg.translate.model}")
    print(f"连通性: {'✅' if ok else '❌'} {detail}")
    if not ok:
        print("\n后端不可用。本地的话先 `ollama serve`；或者改 config.yaml 用云端。")
        return 1

    print("\n预热中（首次会加载模型到显存）...")
    t0 = time.perf_counter()
    await tr.prewarm()
    print(f"预热耗时 {(time.perf_counter()-t0):.1f}s\n")

    if args.text:
        out = await tr.translate_full(args.text, "en->zh")
        print(f"EN: {args.text}\nZH: {out}")
        await tr.close()
        return 0
    if args.zh:
        out = await tr.translate_full(args.zh, "zh->en")
        print(f"ZH: {args.zh}\nEN: {out}")
        await tr.close()
        return 0

    print("=" * 72)
    print("英文 -> 中文")
    print("=" * 72)
    times = []
    for text in SAMPLES_EN:
        t0 = time.perf_counter()
        out = await tr.translate_full(text, "en->zh")
        dt = (time.perf_counter() - t0) * 1000
        times.append(dt)
        terms = glossary.terms_for(text, "en->zh", limit=4)
        hint = ("  术语: " + ", ".join(f"{a}={b}" for a, b in terms)) if terms else ""
        print(f"  {text:<44} -> {out}   [{dt:.0f}ms]{hint}")

    print("\n" + "=" * 72)
    print("中文 -> 英文")
    print("=" * 72)
    for text in SAMPLES_ZH:
        t0 = time.perf_counter()
        out = await tr.translate_full(text, "zh->en")
        dt = (time.perf_counter() - t0) * 1000
        times.append(dt)
        print(f"  {text:<24} -> {out}   [{dt:.0f}ms]")

    hits, misses = 0, 0
    print(f"\n平均延迟 {sum(times)/len(times):.0f} ms（{len(times)} 句）")
    print("检查要点：")
    print("  1. 短句不能变成完整句子（'mid no' 应该是'中路没人'，不是'中路没有敌人了'）")
    print("  2. 不能出现解释、引号、'翻译：' 之类的前缀")
    print("  3. 术语要对：urn=魂瓮、walker=机甲、mid boss=中路BOSS")
    print("  4. gg/ez/ks 这类保留英文不翻")
    print("  5. 中->英要像北美玩家说话（'b'、'omw' 这种缩写），不要书面语")
    await tr.close()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="翻译链路实测")
    ap.add_argument("--text", default="", help="只翻这一句（英->中）")
    ap.add_argument("--zh", default="", help="只翻这一句（中->英）")
    ap.add_argument("--model", default="", help="临时换模型，例如 kaelri/hy-mt2:1.8b-q8_0")
    ap.add_argument("--config", default="config.yaml")
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

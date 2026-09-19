"""横向对比本机所有 Hy-MT2 模型：质量（术语命中率）+ 显存占用 + 延迟。

背景：游戏开起来会闪退，转储指向渲染层（D3D11 抛 C++ 异常），最可能是显存不够 ——
当前 7B Q6_K 常驻 6.8 GB，加上桌面与游戏就超了 16 GB。要换模型就必须知道
"换小的会损失多少质量"，否则只是拍脑袋。

本脚本**不碰桥的设置**：直接按项目里真实的提示词 + 术语表问 Ollama，
每个模型跑完把 keep_alive 设成 30s 让它自己释放。

用法：
    python scripts/compare_models.py            # 全部候选
    python scripts/compare_models.py --quick    # 每个模型只跑 10 条
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
OLLAMA = "http://127.0.0.1:11434"

CANDIDATES = [
    "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K",     # 当前在用
    "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "kaelri/hy-mt2:1.8b-q8_0",
    "kaelri/hy-mt2:1.8b-q4_K_M",
]

# 英->中 小测集：(英文, 可接受的中文关键词)
EN2ZH = [
    ("care, they're flanking", ["小心", "绕后", "包抄"]),
    ("he's low, dive him", ["残血", "上", "低"]),
    ("need help on yellow", ["黄路", "帮助"]),
    ("urn is dropping", ["灵瓮", "魂瓮", "瓮"]),
    ("missing mid", ["消失", "中路", "不见"]),
    ("push the walker", ["机甲", "推进", "推"]),
    ("deny him", ["反补", "回收", "补"]),
    ("stop feeding", ["别送", "送", "别喂"]),
]


def opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def chat(model: str, messages: list[dict], keep_alive: str = "30s",
         timeout: int = 180) -> tuple[str, float]:
    body = json.dumps({"model": model, "messages": messages, "temperature": 0.0,
                       "max_tokens": 128, "keep_alive": keep_alive}).encode()
    req = urllib.request.Request(OLLAMA + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with opener().open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip(), (time.perf_counter() - t0) * 1000


def vram_of(model: str) -> float:
    """问 Ollama 这个模型现在占多少显存（GB）。"""
    try:
        with opener().open(OLLAMA + "/api/ps", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return 0.0
    for m in data.get("models", []):
        if m.get("name") == model:
            return (m.get("size_vram") or 0) / 2**30
    return 0.0


def run_model(model: str, quick: bool) -> dict:
    from dlchat.chat.glossary import Glossary
    from dlchat.translate.prompt import build_messages
    g = Glossary()

    zh_lines = [json.loads(ln) for ln in
                (ROOT / "data" / "deadlock_testset.jsonl").read_text(
                    encoding="utf-8").splitlines() if ln.strip()]
    if quick:
        zh_lines = zh_lines[:10]

    # 先热一下（把模型载入显存）
    chat(model, [{"role": "user", "content": "ok"}], keep_alive="60s")
    vram = vram_of(model)

    z2e_hits = 0
    z2e_lat: list[float] = []
    z2e_bad: list[str] = []
    for item in zh_lines:
        terms = g.terms_for(item["zh"], "zh->en", limit=8)
        msgs = build_messages(item["zh"], "zh->en", terms, keep_all=[])
        out, ms = chat(model, msgs, keep_alive="60s")
        z2e_lat.append(ms)
        low = out.lower()
        if all(e.lower() in low for e in item["expect"]):
            z2e_hits += 1
        else:
            z2e_bad.append(f"{item['zh']} -> {out}")

    e2z_hits = 0
    e2z_lat: list[float] = []
    e2z_bad: list[str] = []
    for text, accepts in EN2ZH:
        terms = g.terms_for(text, "en->zh", limit=8)
        msgs = build_messages(text, "en->zh", terms, keep_all=g.keep)
        out, ms = chat(model, msgs, keep_alive="30s")
        e2z_lat.append(ms)
        if any(a in out for a in accepts):
            e2z_hits += 1
        else:
            e2z_bad.append(f"{text} -> {out}")

    return {
        "model": model,
        "vram": vram,
        "z2e": z2e_hits / len(zh_lines) * 100 if zh_lines else 0,
        "z2e_n": len(zh_lines),
        "z2e_ms": statistics.median(z2e_lat) if z2e_lat else 0,
        "e2z": e2z_hits / len(EN2ZH) * 100,
        "e2z_ms": statistics.median(e2z_lat) if e2z_lat else 0,
        "z2e_bad": z2e_bad[:4],
        "e2z_bad": e2z_bad[:3],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--models", nargs="*", default=CANDIDATES)
    args = ap.parse_args()

    rows = []
    for m in args.models:
        print(f"--- 测 {m} ...", flush=True)
        try:
            rows.append(run_model(m, args.quick))
        except Exception as e:  # noqa: BLE001
            print(f"    失败: {e}")

    print("\n=== 对比结果")
    print(f"{'模型':46} {'显存':>7} {'中→英术语':>9} {'中→英延迟':>9} "
          f"{'英→中术语':>9} {'英→中延迟':>9}")
    for r in rows:
        print(f"{r['model']:46} {r['vram']:6.1f}G {r['z2e']:8.0f}% "
              f"{r['z2e_ms']:7.0f}ms {r['e2z']:8.0f}% {r['e2z_ms']:7.0f}ms")

    for r in rows:
        if r["z2e_bad"] or r["e2z_bad"]:
            print(f"\n{r['model']} 的失败样例:")
            for b in r["z2e_bad"]:
                print(f"  中→英 {b}")
            for b in r["e2z_bad"]:
                print(f"  英→中 {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

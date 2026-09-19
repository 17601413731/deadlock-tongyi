"""对比本机两个模型的翻译延迟（两个方向各跑几条），跑完恢复原模型。

用法：python scripts/model_bench.py [port]
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
BASE = f"http://127.0.0.1:{PORT}"

MODELS = [
    "hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K",
    "kaelri/hy-mt2:1.8b-q8_0",
]

EN = ["mid no", "he is low, dive him", "careful, they are flanking through the tunnels",
      "push the urn and back off", "nice ult"]
ZH = ["中路没人", "他残血，上", "小心他们从隧道绕后", "推完魂瓮就撤", "大打得好"]


def call(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def measure(texts: list[str], src: str, tgt: str) -> list[float]:
    out = []
    for t in texts:
        t0 = time.perf_counter()
        r = call("/api/v1/translate",
                 {"text": t, "sourceLanguage": src, "targetLanguage": tgt})
        if r.get("ok") and not r.get("viaCache"):
            out.append((time.perf_counter() - t0) * 1000)
    return out


def main() -> int:
    original = call("/api/v1/settings", {"view": "compact"}).get("model")
    print(f"原模型: {original}\n")
    try:
        for model in MODELS:
            r = call("/api/v1/settings", {"model": model})
            if not r.get("ok"):
                print(f"{model}: 切换失败 {r.get('error')}")
                continue
            # 切换后先热一下（第一次含载入显存的时间）
            call("/api/v1/translate", {"text": "warm up", "sourceLanguage": "en",
                                       "targetLanguage": "zh-Hans"})
            en2zh = measure(EN, "en", "zh-Hans")
            zh2en = measure(ZH, "zh", "en")
            fmt = lambda v: (f"中位 {statistics.median(v):.0f} ms "
                             f"(min {min(v):.0f} / max {max(v):.0f}, n={len(v)})"
                             ) if v else "无数据"
            print(f"{model}")
            print(f"   英->中 : {fmt(en2zh)}")
            print(f"   中->英 : {fmt(zh2en)}")
    finally:
        if original:
            call("/api/v1/settings", {"model": original})
            print(f"\n已恢复模型: {original}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

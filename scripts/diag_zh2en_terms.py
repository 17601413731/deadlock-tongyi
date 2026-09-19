"""诊断 zh->en 术语注入：为什么"送"会被翻成 sending。

只读：查词典 + 走桥翻译几句对照，不改任何配置。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import urllib.request  # noqa: E402

BASE = "http://127.0.0.1:8791"

LINES = [
    "别送了",
    "别送了，行吗？",
    "你别送了呗，一直送 都 0-10 了",
    "别送了，行吗？你一直送，都已经0-10了。",
]


def ask(text: str) -> dict:
    body = json.dumps({"text": text, "sourceLanguage": "zh",
                       "targetLanguage": "en"}).encode()
    req = urllib.request.Request(BASE + "/api/v1/translate", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=90).read().decode())


def main() -> int:
    from dlchat.chat.glossary import Glossary
    g = Glossary()

    print("=== 词典里和「送」有关的条目")
    for name, table, direction in (("terms(zh->en)", g.terms, "zh->en"),
                                   ("phrases_zh", getattr(g, "phrases_zh", {}), "zh->en"),
                                   ("slang", getattr(g, "slang", {}), "?")):
        hits = {k: v for k, v in table.items() if isinstance(k, str) and "送" in k}
        print(f"  {name:16} 命中 {len(hits)} 条: {hits}")
    print("  terms 表大小:", len(g.terms), "| 其中含中文键的:",
          sum(1 for k in g.terms if any("\u4e00" <= c <= "\u9fff" for c in k)))
    print("  terms_for('你一直送','zh->en') ->",
          g.terms_for("你一直送", "zh->en")[:5])
    print("  terms_for('别送了','zh->en') ->", g.terms_for("别送了", "zh->en")[:5])

    print("\n=== 逐句实测（走桥，和游戏同一条路）")
    for line in LINES:
        r = ask(line)
        extra = []
        if r.get("viaCache"):
            extra.append("词典/缓存命中")
        if r.get("skipped"):
            extra.append("跳过:" + r["skipped"])
        print(f"  {line!r}\n     -> {r.get('translation')!r} {' '.join(extra)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

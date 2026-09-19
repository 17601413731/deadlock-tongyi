"""证明"模型本来会翻，只是不知道这游戏的黑话"。

对比同一句话在两种条件下的输出：
  A. 不注入术语（现状：模型按字面义翻）
  B. 注入一条术语提示（送=feed）—— 模型立刻改用游戏内说法

只读实验：直接问 Ollama，用桥同一套提示词构造，不改任何设置。
用法：python scripts/diag_term_hint_effect.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LINE = "别送了，行吗？你一直送，都已经0-10了。"
HINTS = [("送", "feed"), ("别送了", "stop feeding"), ("一直送", "keep feeding")]


def call(messages: list[dict], model: str) -> str:
    body = json.dumps({
        "model": model, "messages": messages, "temperature": 0.0,
        "max_tokens": 128, "keep_alive": "10m",
    }).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def main() -> int:
    from dlchat.config import load_config
    from dlchat.translate.prompt import (FEWSHOT_ZH_EN, build_messages, build_system,
                                        build_user_message)

    cfg = load_config()
    model = cfg.translate.model
    print(f"模型: {model}")
    print(f"原句: {LINE}\n")

    system = build_system("zh->en", [])
    cases = [
        ("A. 只给 system（无少样本、无术语）", []),
        ("B. 注入术语提示：送=feed", [("送", "feed")]),
    ]
    for title, terms in cases:
        user = build_user_message(LINE, terms, "zh->en")
        out = call([{"role": "system", "content": system},
                    {"role": "user", "content": user}], model)
        print(f"{title}\n   译文: {out!r}\n")

    print("=== 关键对比：加上我们现在的少样本示例（桥的真实提示词）")
    print(f"  当前 zh->en 少样本 {len(FEWSHOT_ZH_EN)} 组：{FEWSHOT_ZH_EN}")
    msgs = build_messages(LINE, "zh->en", [], keep_all=[])
    out = call(msgs, model)
    print(f"  D. 桥的真实提示词（含少样本）\n     译文: {out!r}\n")

    out = call(build_messages(LINE, "zh->en", [], keep_all=[], with_fewshot=False), model)
    print(f"  E. 同一提示词但去掉少样本\n     译文: {out!r}\n")

    # 少样本里那句带"送"的例子，单独看它的影响
    bad = [p for p in FEWSHOT_ZH_EN if "送" in p[0]]
    if bad:
        print(f"=== 少样本里含「送」的例子会把「送」教成什么")
        for zh, en in bad:
            print(f"  {zh!r} -> {en!r}   （原文有「送」，译文里没有对应词）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

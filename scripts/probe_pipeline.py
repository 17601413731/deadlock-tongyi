"""逐层排查 zh->en 为什么输出 "wtf"：BridgeApp -> ChatTranslator -> 词典 -> 裸模型。

用法：python scripts/probe_pipeline.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SAMPLES = ["小心对面绕后", "我来了", "别送了"]


def main() -> int:
    from dlchat.bridge.server import BridgeApp
    from dlchat.chat.glossary import Glossary
    from dlchat.config import load_config
    from dlchat.translate.client import ChatTranslator

    cfg = load_config()
    g = Glossary()
    print(f"config: model={cfg.translate.model} ctx={cfg.translate.context_window} "
          f"max_tokens={cfg.translate.max_tokens} temp={cfg.translate.temperature}")
    print(f"glossary: terms={len(g.terms)} phrases={len(g.phrases)} "
          f"phrases_zh={len(g.phrases_zh)} slang={len(g.slang)}")

    for text in SAMPLES:
        print(f"\n=== {text}")
        print("  _direction(auto,zh) ->",
              BridgeApp._direction(text, "auto", "zh-Hans"),
              "| (zh,en) ->", BridgeApp._direction(text, "zh", "en"))
        print("  glossary.terms_for(zh->en):", g.terms_for(text, "zh->en")[:6])
        try:
            print("  glossary.apply_slang:", g.apply_slang(text, "zh->en"))
        except Exception as e:  # noqa: BLE001
            print("  apply_slang 异常:", e)

    app = BridgeApp(cfg, g)
    app.start_loop()
    for text in SAMPLES:
        r = app.translate(text, "zh", "en")
        print(f"\nBridgeApp.translate({text!r}) -> {r}")

    # 绕过桥，直接用 translator
    fast = cfg.translate.model_copy(update={"context_window": 0, "max_tokens": 128})
    tr = ChatTranslator(fast, g)
    for text in SAMPLES:
        try:
            out = asyncio.run(tr.translate_full(text, "zh->en"))
        except Exception as e:  # noqa: BLE001
            out = f"<异常 {e}>"
        print(f"ChatTranslator.translate_full({text!r}) -> {out!r}")
    try:
        asyncio.run(tr.close())
    except Exception:  # noqa: BLE001
        pass
    app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

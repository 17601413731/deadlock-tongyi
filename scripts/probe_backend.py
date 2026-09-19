"""排查翻译后端：同一个句子用四种请求形态问 Ollama，看模型到底怎么答。

背景：桥突然对任何中文都回 "wtf"，而裸调 /v1/chat/completions 会得到一段
"你的消息似乎不完整" 的通用助手回复 —— 像是模型没按翻译任务作答。
本脚本把可能的差异（OpenAI 兼容层 vs 原生 API、chat 模板 vs 裸 prompt、
temperature/keep_alive）逐个排掉。

用法：python scripts/probe_backend.py ["要翻的中文"]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OLLAMA = "http://localhost:11434"
TEXT = sys.argv[1] if len(sys.argv) > 1 else "小心对面绕后"


def post(path: str, payload: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        OLLAMA + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def show(title: str, out: str) -> None:
    print(f"--- {title}\n    {out!r}\n")


def main() -> int:
    from dlchat.config import load_config
    cfg = load_config()
    model = cfg.translate.model
    print(f"模型: {model}\n待翻: {TEXT}\n")

    # 0. 模型自带的 chat 模板是什么样
    try:
        info = post("/api/show", {"model": model})
        tmpl = (info.get("template") or "")[:400]
        print("=== /api/show template ===")
        print(tmpl or "(空)")
        print("parameters:", (info.get("parameters") or "").strip()[:200])
        print()
    except Exception as e:  # noqa: BLE001
        print("show 失败:", e)

    # 1. 桥用的提示词（system + fewshot + user），走 OpenAI 兼容层
    try:
        from dlchat.translate.prompt import build_messages
        msgs = build_messages(TEXT, "zh->en", [], [])
        r = post("/v1/chat/completions", {
            "model": model, "messages": msgs, "temperature": 0.0,
            "max_tokens": 64, "keep_alive": "10m"})
        show("1) OpenAI 兼容 + 桥的完整提示词", r["choices"][0]["message"]["content"])
    except Exception as e:  # noqa: BLE001
        print("1) 失败:", e)

    # 2. 极简单轮，OpenAI 兼容
    try:
        r = post("/v1/chat/completions", {
            "model": model, "temperature": 0.0, "max_tokens": 64,
            "messages": [{"role": "user", "content": f"Translate to English: {TEXT}"}]})
        show("2) OpenAI 兼容 + 极简指令", r["choices"][0]["message"]["content"])
    except Exception as e:  # noqa: BLE001
        print("2) 失败:", e)

    # 3. 原生 /api/chat
    try:
        r = post("/api/chat", {
            "model": model, "stream": False, "keep_alive": "10m",
            "options": {"temperature": 0.0, "num_predict": 64},
            "messages": [{"role": "user", "content": f"Translate to English: {TEXT}"}]})
        show("3) 原生 /api/chat", r["message"]["content"])
    except Exception as e:  # noqa: BLE001
        print("3) 失败:", e)

    # 4. 原生 /api/generate（裸 prompt，不经 chat 模板）
    try:
        r = post("/api/generate", {
            "model": model, "stream": False, "keep_alive": "10m", "raw": True,
            "options": {"temperature": 0.0, "num_predict": 64},
            "prompt": f"把下面这句中文翻译成英文，只输出译文：\n{TEXT}\n"})
        show("4) 原生 /api/generate (raw)", r["response"])
    except Exception as e:  # noqa: BLE001
        print("4) 失败:", e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

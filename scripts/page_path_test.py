"""复现游戏侧那条路：用无头 Edge 加载 /bridge 页面，看它最终写进标题的内容与耗时。

游戏里的通信是：隐藏 HTML 面板加载 /bridge?... -> 页面 fetch 桥 API -> 写 document.title
-> 面板事件把标题带回游戏。这个脚本用真实 Chromium 内核走同一条路，所以能提前发现
"页面超时/响应被截断/op 被降级"这类只有游戏里才会暴露的问题。

用法：python scripts/page_path_test.py [port]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
EDGE_CANDIDATES = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

CASES = [
    ("health", None),
    ("models", None),
    ("settings", {"view": "compact"}),
    ("settings/test", {"text": "he is low, dive him"}),
    ("translate", {"text": "mid no", "sourceLanguage": "en", "targetLanguage": "zh-Hans"}),
]


def edge() -> Path:
    for p in EDGE_CANDIDATES:
        if p.exists():
            return p
    raise SystemExit("找不到 Edge")


def run_page(page_url: str, budget_ms: int) -> tuple[str, float]:
    tmp = Path(tempfile.mkdtemp(prefix="dlchat_page_"))
    t0 = time.perf_counter()
    proc = subprocess.run(
        [str(edge()), "--headless=new", "--disable-gpu", "--no-first-run",
         f"--user-data-dir={tmp}", f"--virtual-time-budget={budget_ms}",
         "--dump-dom", page_url],
        capture_output=True, text=True, errors="replace", timeout=120)
    dt = (time.perf_counter() - t0) * 1000
    m = re.search(r"<title>(.*?)</title>", proc.stdout or "", re.S)
    return (m.group(1).strip() if m else ""), dt


def main() -> int:
    fails = 0
    for op, payload in CASES:
        query = {"id": "t1", "op": op}
        if payload is not None:
            query["d"] = json.dumps(payload)
        url = f"http://localhost:{PORT}/bridge?" + urllib.parse.urlencode(query)
        title, dt = run_page(url, 9000)
        body = title
        m = re.match(r"^LCTt1(.*)$", title, re.S)
        if m:
            body = m.group(1)
        ok = False
        note = ""
        try:
            data = json.loads(body)
            ok = bool(data.get("ok"))
            note = json.dumps(data, ensure_ascii=False)[:110]
        except Exception:  # noqa: BLE001
            note = f"标题不合法: {title[:110]!r}"
        if not ok:
            fails += 1
        print(f"  {'✓' if ok else '✗'} {op:16} {dt:7.0f} ms  {note}")
    print(f"\n[结果] {'页面通道全部可用' if not fails else f'{fails} 项失败'}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())

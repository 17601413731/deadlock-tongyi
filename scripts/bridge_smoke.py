"""通过 HTTP 冒烟测试本地翻译桥（UTF-8 正确编码，别用 PowerShell 内联 JSON）。

用法：python scripts/bridge_smoke.py [port]
"""

from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CASES = [
    ("mid no", "en", "zh-Hans"),
    ("he's low, dive him", "en", "zh-Hans"),
    ("小心对面绕后", "zh", "en"),
    ("我来了", "zh", "en"),
    ("别送了", "zh", "en"),
]


def call(port: int, path: str, payload: dict | None = None) -> dict:
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
    health = call(port, "/api/v1/health")
    print(f"bridge: {health.get('name')} v{health.get('version')}")
    print(f"model : {health.get('provider')}")
    print(f"stats : {health.get('stats')}")
    ok = 0
    for text, src, tgt in CASES:
        try:
            r = call(port, "/api/v1/translate",
                     {"text": text, "sourceLanguage": src, "targetLanguage": tgt})
            flag = "✓" if r.get("ok") else "✗"
            cache = " (cache)" if r.get("viaCache") else ""
            print(f"  {flag} {text!r:24} -> {r.get('translation')!r}{cache}"
                  + ("" if r.get("ok") else f"  error={r.get('error')}"))
            ok += bool(r.get("ok"))
        except Exception as e:  # noqa: BLE001
            print(f"  ✗ {text!r:24} 异常: {e}")
    print(f"[smoke] {ok}/{len(CASES)} 通过")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())

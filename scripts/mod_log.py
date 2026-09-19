"""读游戏侧（Panorama mod）推到桥上的诊断日志。

mod 没法看 console，于是把 boot/翻译/失败信息 POST 到 /api/v1/log，
桥留环形缓冲并落盘到 <日志目录>/mod.log。联调时看这个最快：
能直接区分"游戏里那次翻译到底是不是我们的 mod 干的"。

用法：
    python scripts/mod_log.py              # 读最近 50 条
    python scripts/mod_log.py -n 200       # 读最近 200 条
    python scripts/mod_log.py --clear      # 清空缓冲
    python scripts/mod_log.py --file       # 直接 tail 落盘文件
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def call(port: int, payload: dict | None = None) -> dict:
    url = f"http://127.0.0.1:{port}/api/v1/log"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    from dlchat import paths

    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--limit", type=int, default=50)
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--clear", action="store_true")
    ap.add_argument("--file", action="store_true", help="直接 tail 落盘文件")
    ap.add_argument("--http", action="store_true",
                    help="看桥收到的 HTTP 访问日志（判断游戏有没有来访问过）")
    args = ap.parse_args()

    log_file = paths.log_dir() / "mod.log"
    if args.http:
        http_log = paths.log_dir() / "http.log"
        if not http_log.exists():
            print(f"还没有访问日志: {http_log}")
            print("（桥重启后才会开始记录；游戏里访问过就会写进来）")
            return 1
        lines = http_log.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"# {len(lines)} 条请求，最新在后  {http_log}")
        for line in lines[-args.limit:]:
            print("  " + line)
        return 0
    if args.file:
        if not log_file.exists():
            print(f"没有日志文件: {log_file}")
            return 1
        lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-args.limit:]:
            print(line)
        return 0

    try:
        if args.clear:
            print(call(args.port, {"op": "clear"}))
            return 0
        data = call(args.port, {"op": "read", "limit": args.limit})
    except Exception as e:  # noqa: BLE001
        print(f"读桥失败（桥没在跑？）: {e}")
        print(f"落盘日志: {log_file}")
        return 1

    entries = data.get("entries") or []
    print(f"# {len(entries)} 条（最新在后）  model.log={log_file}")
    for e in entries:
        t = e.get("t", 0)
        stamp = f"{t:.3f}" if t else "-"
        mod = e.get("mod") or e.get("op") or "-"
        msg = e.get("msg") or ""
        extra = e.get("extra")
        tail = f"  {json.dumps(extra, ensure_ascii=False)}" if extra else ""
        print(f"{stamp}  [{mod}]  {msg}{tail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""找并读 Deadlock 的控制台日志（`-condebug` / `-con_logfile` 写出来的）。

为什么需要它：mod 跑在 Panorama 里，报错默认只在游戏控制台里，我们在外面看不到。
带上 `-condebug` 启动后引擎会把控制台写进文件，里面就有 Panorama 的脚本错误和
HTML 面板加载失败的原因 —— 这类问题（比如"页面根本没加载"）只有这里能看到。

用法：
    python scripts/read_console_log.py              # 自动找日志并打印关键行
    python scripts/read_console_log.py --all        # 打印全部（尾部 200 行）
    python scripts/read_console_log.py --grep dlchat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SEARCH_ROOTS = [
    Path(r"D:\software\steam\steamapps\common\Deadlock\game"),
    Path(r"D:\software\steam\steamapps\common\Deadlock"),
]
NAMES = ("dlchat_console.log", "console.log")

# 和本次排查相关的关键词
KEYS = ("dlchat", "panorama", "html", "web", "script", "error", "failed",
        "AsyncWebRequest", "localhost:8791", "layout")


def find_logs() -> list[Path]:
    found: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for name in NAMES:
            for p in root.rglob(name):
                if p.is_file():
                    found.append(p)
    # 去重 + 新的排前面
    uniq = {str(p): p for p in found}
    return sorted(uniq.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--grep", default="")
    ap.add_argument("--tail", type=int, default=200)
    args = ap.parse_args()

    logs = find_logs()
    if not logs:
        print("没找到控制台日志。请先用 launch_debug.bat 启动一次游戏")
        print("（它会给 Deadlock 传 -condebug -con_logfile dlchat_console.log）")
        return 1

    for path in logs[:3]:
        print(f"=== {path}  ({path.stat().st_size} B, {path.stat().st_mtime:.0f})")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as e:  # noqa: BLE001
            print("  读失败:", e)
            continue
        if args.grep:
            hits = [ln for ln in lines if args.grep.lower() in ln.lower()]
            for ln in hits[-args.tail:]:
                print("  " + ln[:200])
            print(f"  -- 命中 {len(hits)} 行")
            continue
        if args.all:
            for ln in lines[-args.tail:]:
                print("  " + ln[:200])
            continue
        hits = [ln for ln in lines
                if any(k.lower() in ln.lower() for k in KEYS)]
        for ln in hits[-args.tail:]:
            print("  " + ln[:200])
        print(f"  -- 关键行 {len(hits)} / 总行 {len(lines)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

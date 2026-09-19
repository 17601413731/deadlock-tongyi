#!/usr/bin/env python
"""实测一：Deadlock 的控制台日志里到底有没有聊天？

背景：Deadlock 的 client.dll 里注册了 say / say_team / messagemode，
server.dll 打印聊天用 "[All Chat][名字 (3)]: 内容"。引擎（engine2.dll）里有
-con_logfile / -consolelog 这两个启动参数，也有 con_logfile 这个 cvar。
只要聊天会被写进日志，功能1 就能做到 100% 准确（不用 OCR）。

怎么试（游戏内，约 5 分钟）：
  1. Steam -> Deadlock -> 右键 属性 -> 启动选项，依次试这几个组合：
        a) -con_logfile console.log
        b) -consolelog
        c) -console -con_logfile console.log
        d) （进游戏后按 F7 开控制台）输入：con_logfile console.log
  2. 进 Hideout，让队友/小号在聊天里发一条英文（或你自己发一条）。
  3. 保持游戏运行，另开一个窗口跑：python scripts/spike_console_log.py --watch 90
  4. 看输出：如果出现 "疑似聊天行"，这条路就通了，把 source.kind 改成 console。

用法：
    python scripts/spike_console_log.py              # 只报告找到哪些日志文件
    python scripts/spike_console_log.py --watch 90   # 实时盯 90 秒
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.chat.parser import parse_line          # noqa: E402
from dlchat.config import load_config              # noqa: E402
from dlchat.sources.console_log import ConsoleLogSource  # noqa: E402

GAME_DIRS = [
    Path(r"D:\software\steam\steamapps\common\Deadlock\game"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game"),
    Path(r"D:\Steam\steamapps\common\Deadlock\game"),
    Path(r"D:\SteamLibrary\steamapps\common\Deadlock\game"),
]
PATTERNS = ["console*.log", "console*.txt", "*.log"]


def find_logs() -> list[Path]:
    out: list[Path] = []
    for game in GAME_DIRS:
        for sub in ("bin/win64", "citadel", "citadel/bin/win64"):
            base = game / sub
            if not base.exists():
                continue
            for pattern in PATTERNS:
                out += [p for p in base.glob(pattern) if p.is_file()]
    return sorted(set(out), key=lambda p: p.stat().st_mtime, reverse=True)


def report(args) -> int:
    cfg = load_config(args.config)
    print("=" * 68)
    print("Deadlock 控制台日志探测")
    print("=" * 68)

    logs = find_logs()
    if not logs:
        print("❌ 一个日志文件都没找到。")
        print("   说明还没用日志启动参数启动过游戏。请按下面任意一条启动游戏后再跑本脚本：")
        print("     -con_logfile console.log")
        print("     -consolelog")
        print("     -console -con_logfile console.log")
        print("   （进游戏后按 F7 开控制台，敲 con_logfile console.log 也行）")
        return 1

    print(f"找到 {len(logs)} 个候选日志：")
    for path in logs[:8]:
        age = time.time() - path.stat().st_mtime
        print(f"  · {path}  ({path.stat().st_size/1024:.1f} KB, {age/60:.1f} 分钟前修改)")
    newest = logs[0]
    print(f"\n最新日志：{newest}")
    tail = newest.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
    print("--- 末尾 40 行 ---")
    for line in tail:
        mark = "  <== 疑似聊天" if parse_line(line) is not None else ""
        print(f"  {line[:160]}{mark}")

    if args.watch <= 0:
        print("\n想实时盯：python scripts/spike_console_log.py --watch 90")
        return 0

    print(f"\n实时监听 {args.watch} 秒，请在游戏里发/收几条聊天...")
    cfg.console.tail_from_end = False
    source = ConsoleLogSource(cfg.console)
    source._path = newest  # noqa: SLF001 - 脚本就是要指定文件
    source._offset = max(0, newest.stat().st_size - 4096)  # noqa: SLF001
    source._partial = ""  # noqa: SLF001
    source._status.running = True  # noqa: SLF001

    hits = 0
    deadline = time.monotonic() + args.watch
    while time.monotonic() < deadline:
        lines = source.poll()
        for line in lines:
            hits += 1
            print(f"  [{line.source}] {line.display_original()}")
        time.sleep(0.2)

    print(f"\n本次共捕获 {hits} 条聊天行")
    if hits:
        print("✅ 控制台日志里有聊天 -> 把 config.yaml 的 source.kind 改成 console，最准最省 CPU")
    else:
        print("⚠️ 没捕获到聊天行。可能原因：")
        print("   1) 启动参数没生效（换上面另一个组合再试）")
        print("   2) 聊天确实不写日志 -> 那就用 OCR 方案（source.kind: ocr）")
        print("   3) 这段时间真的没人发聊天（找个朋友配合发一条）")
    return 0 if hits else 2


def main() -> int:
    ap = argparse.ArgumentParser(description="Deadlock 控制台日志实测")
    ap.add_argument("--watch", type=int, default=0, help="实时监听秒数，0=只看现有文件")
    ap.add_argument("--config", default="config.yaml")
    return report(ap.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

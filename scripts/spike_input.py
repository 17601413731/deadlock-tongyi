#!/usr/bin/env python
"""实测二：能不能往 Deadlock 聊天框里注入文字（功能2 的可行性）。

会依次测四件事，把结果报告出来：
  1. 剪贴板读写
  2. 能不能找到 Deadlock 窗口、能不能切到前台
  3. 打开聊天框（Enter）后注入文字（SendInput + 逐字延时）
  4. Ctrl+V 粘贴剪贴板

默认只做 1、2（安全，不动游戏）。真正注入需要显式加 --go。
建议顺序：先 --go --inject 看文字有没有出现在聊天框，再试 --go --paste。

用法：
    python scripts/spike_input.py                 # 只探测（不碰游戏）
    python scripts/spike_input.py --go --inject   # 打开聊天框并注入 hello test
    python scripts/spike_input.py --go --paste    # 打开聊天框并粘贴
    python scripts/spike_input.py --go --send     # 注入后回车发送（会真的发出去！）
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.config import load_config            # noqa: E402
from dlchat.input.injector import TextInjector   # noqa: E402

TEST_TEXT = "hello test"


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def main() -> int:
    ap = argparse.ArgumentParser(description="注入/粘贴可行性实测")
    ap.add_argument("--go", action="store_true", help="真的往游戏里注入（默认只探测）")
    ap.add_argument("--inject", action="store_true", help="测试注入文字")
    ap.add_argument("--paste", action="store_true", help="测试 Ctrl+V 粘贴")
    ap.add_argument("--send", action="store_true", help="注入后按回车发送（真的会发出去）")
    ap.add_argument("--text", default=TEST_TEXT, help="要注入的测试文本")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    inj = TextInjector(cfg.input)

    print("=" * 68)
    print("Deadlock 注入能力实测")
    print("=" * 68)

    step(1, "剪贴板")
    ok = inj.clipboard_available()
    print(f"  读写可用: {ok}")
    if ok:
        saved = inj.get_clipboard()
        inj.set_clipboard("clipboard-test-123")
        print(f"  回读验证: {'通过' if inj.get_clipboard() == 'clipboard-test-123' else '失败'}")
        inj.set_clipboard(saved)
    if not ok:
        print("  → pip install pyperclip")

    step(2, "游戏窗口")
    hwnd = inj.find_game_window()
    print(f"  找到窗口: {hwnd}")
    if hwnd is None:
        print("  → 先把 Deadlock 启动起来再测（只读模式/OCR 不受影响）")
    else:
        print(f"  当前是否在前台: {inj.game_window_focused()}")
        print(f"  尝试切前台: {inj.focus_game_window()}")

    if not args.go:
        print("\n(只做了探测。要真正注入请加 --go --inject / --go --paste)")
        return 0
    if hwnd is None:
        print("\n❌ 没有游戏窗口，无法注入")
        return 1

    print("\n⚠️  3 秒后开始操作游戏，请先把鼠标点回游戏窗口，让画面在前台...")
    for i in (3, 2, 1):
        print(f"    {i}...")
        time.sleep(1)

    inj.focus_game_window()
    time.sleep(0.3)

    step(3, "打开聊天框")
    print(f"  发送 {cfg.input.open_chat_key!r}")
    inj.press(cfg.input.open_chat_key, delay=0.35)

    if args.inject or not args.paste:
        step(4, f"注入 {args.text!r}")
        inj.type_text(args.text)
        time.sleep(0.3)
        if args.send:
            print("  按回车发送（真的发出去了）")
            inj.press(cfg.input.open_chat_key, delay=0.2)

    if args.paste:
        step(5, "Ctrl+V 粘贴")
        inj.set_clipboard(args.text)
        time.sleep(0.2)
        inj.press("ctrl+v", delay=0.3)

    print("\n" + "=" * 68)
    print("请回到游戏看聊天框，然后告诉我是哪种情况：")
    print("  A. 文字/粘贴内容正常出现        -> 可以做到全自动（L1/L2）")
    print("  B. 聊天框打开了但一个字都没进去  -> 游戏屏蔽了合成按键，只能用剪贴板+你手动 Ctrl+V（L3）")
    print("  C. 聊天框都没打开               -> Enter 不是开聊天键，查一下你绑的键位")
    print("  D. 游戏卡住/崩溃               -> 别再注入，告诉我，改走只读方案")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

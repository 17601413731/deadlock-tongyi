#!/usr/bin/env python
"""实测五：零注入链路（读聊天输入行 -> 翻译 -> 进剪贴板）。

不需要注入任何按键。使用场景：你在游戏聊天框里打完中文，连按 3 次空格，
工具读出这行字、翻成英文、放进剪贴板，你自己 Ctrl+A / Ctrl+V / 回车。

四种模式：
    python scripts/spike_input_line.py --preview   # 抓输入行 + OCR，校准区域（先跑这个）
    python scripts/spike_input_line.py --watch     # 连续 20 秒看它能不能跟上你打字
    python scripts/spike_input_line.py --once      # 读一次并翻译+复制到剪贴板
    python scripts/spike_input_line.py --taps      # 真实监听：连按 3 次空格触发一次转换

聊天框要打开（按回车/Shift+回车），里面要有你打的字。区域不对就改
config.yaml 的 input.input_region，或先用 --preview 看裁剪图。
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.config import load_config                    # noqa: E402
from dlchat.input.line_reader import InputLineReader     # noqa: E402
from dlchat.input.space_trigger import MultiTapTrigger   # noqa: E402

OUT = Path("spike_out")


def main() -> int:
    ap = argparse.ArgumentParser(description="零注入链路实测")
    ap.add_argument("--preview", action="store_true", help="抓输入行并打印 OCR 结果")
    ap.add_argument("--watch", type=int, default=0, help="连续观察多少秒")
    ap.add_argument("--once", action="store_true", help="读一次 + 翻译 + 复制剪贴板")
    ap.add_argument("--taps", action="store_true", help="真实监听连按空格")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    OUT.mkdir(exist_ok=True)
    print("=" * 68)
    print(f"输入行区域(归一化): {cfg.input.input_region}")
    print(f"触发方式: {cfg.input.taps} 次 {cfg.input.tap_key}（窗口 {cfg.input.tap_window_s}s）")
    print(f"交付方式: {cfg.input.handoff}")

    reader = InputLineReader(cfg)
    if reader.grabber.backend == "none":
        print("❌ 抓不到屏幕：pip install dxcam mss")
        return 1

    if not (args.watch or args.once or args.taps):
        args.preview = True

    if args.preview:
        raw, clean = reader.preview(str(OUT / "input_line.png"))
        print(f"\n裁剪图: {OUT / 'input_line.png'}")
        print(f"OCR 原文: {raw!r}")
        print(f"清洗后  : {clean!r}")
        if not clean:
            print("\n⚠️ 没读到文字。检查：① 聊天框是不是开着 ② 里面有没有字")
            print("   ③ 改 input.input_region（左/上/右/下，0~1 比例）再试")
        else:
            print("\n✅ 读到内容了。接着跑 --once 看翻译效果，或 --taps 试真实触发。")

    if args.watch:
        print(f"\n连续观察 {args.watch} 秒（去游戏里打字看看）...")
        end = time.time() + args.watch
        last = None
        while time.time() < end:
            text = reader.read()
            if text and text != last:
                last = text
                print(f"  {time.strftime('%H:%M:%S')}  {text!r}")
            time.sleep(0.6)

    def convert_once() -> None:
        import asyncio
        from dlchat.translate.client import ChatTranslator
        from dlchat.chat.glossary import Glossary

        chinese = reader.read()
        print(f"\n读到: {chinese!r}")
        if not chinese:
            print("⚠️ 没读到内容，跳过")
            return
        tr = ChatTranslator(cfg.translate, Glossary())

        async def _do():
            try:
                return await tr.translate_full(chinese, "zh->en")
            finally:
                await tr.close()

        english = asyncio.run(_do())
        print(f"英文: {english!r}")
        if english:
            import pyperclip

            pyperclip.copy(english)
            print("✅ 已复制到剪贴板 -> 游戏聊天框里按 Ctrl+A 再 Ctrl+V，回车发送")
        else:
            print("❌ 没翻出英文（翻译后端没起来？先 ollama serve 或改云端配置）")

    if args.once:
        convert_once()

    if args.taps:
        print(f"\n开始监听：请切回游戏、打开聊天框、打完中文后连按 "
              f"{cfg.input.taps} 次 {cfg.input.tap_key.upper()}")
        print("（Ctrl+C 退出）")
        trigger = MultiTapTrigger(
            key=cfg.input.tap_key, taps=cfg.input.taps, window_s=cfg.input.tap_window_s,
            on_fire=lambda: convert_once(),
            require_focus=None,   # 脚本模式下不做前台校验，方便你切窗口看输出
        )
        if not trigger.start():
            print("❌ 键盘监听注册失败")
            return 1
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            trigger.stop()
            print("\n已退出")

    reader.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""实测四：OCR 在这台机器上到底多快（决定能不能实时跑）。

对比两种模式：
  A) detect=True   整块文本检测 + 识别（区域未知时用，慢）
  B) detect=False  按 rows 切条只做识别（位置固定的聊天条，快）
并且会在"游戏开着"和"游戏关着"两种情况下分别测——游戏占满 CPU 时 OCR 会明显变慢。

用法：
    python scripts/bench_ocr.py                     # 用 config.yaml 的区域
    python scripts/bench_ocr.py --region 0,0,0.62,0.26 --rows 6
    python scripts/bench_ocr.py --image spike_out/region_raw.png
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.capture.ocr import create_ocr          # noqa: E402
from dlchat.capture.screen import ScreenGrabber    # noqa: E402
from dlchat.config import load_config              # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="OCR 速度实测")
    ap.add_argument("--region", default="")
    ap.add_argument("--rows", type=int, default=0)
    ap.add_argument("--image", default="")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    region = [float(v) for v in args.region.split(",")] if args.region else cfg.ocr.region
    rows = args.rows or cfg.ocr.rows

    grabber = None
    if args.image:
        from PIL import Image

        frame = np.asarray(Image.open(args.image).convert("RGB"))
        print(f"图片: {args.image} {frame.shape[1]}x{frame.shape[0]}")
    else:
        grabber = ScreenGrabber()
        if grabber.backend == "none":
            print("❌ 抓不到屏幕")
            return 1
        frame = grabber.grab(region)
        if frame is None:
            print("❌ 抓帧为空")
            return 1

    print(f"区域: {region} -> {frame.shape[1]}x{frame.shape[0]} 像素；切条数 rows={rows}")
    game = _game_running()
    print(f"游戏是否在运行: {game}  （游戏占 CPU 时 OCR 会明显变慢）")

    ocr = create_ocr(cfg.ocr.backend, min_confidence=cfg.ocr.min_confidence,
                     upscale=cfg.ocr.upscale, invert=cfg.ocr.invert)
    ocr.load()

    def run(tag, fn):
        fn()  # warmup
        t0 = time.perf_counter()
        out = None
        for _ in range(args.runs):
            out = fn()
        dt = (time.perf_counter() - t0) / args.runs * 1000
        texts = [l.text for l in (out or []) if l.text]
        print(f"  {tag}: {dt:7.0f} ms/帧   识别 {len(texts)} 行   {texts[:4]}")
        return dt

    full = None
    if not args.image:
        full = lambda: grabber.grab(region) or np.zeros((1, 1, 3), dtype=np.uint8)
        t0 = time.perf_counter()
        for _ in range(args.runs):
            full()
        print(f"  抓帧: {(time.perf_counter()-t0)/args.runs*1000:7.0f} ms/帧")

    print("\nA) detect=True（整块检测）")
    run("full-det", lambda: ocr.recognize(frame))

    print("\nB) detect=False（切条只识别）")
    run(f"strips-{rows}", lambda: ocr.recognize_strips(frame, rows))

    if grabber is not None:
        grabber.close()

    print("\n结论参考（本机实测，20 核 CPU / PP-OCRv6 small，游戏关闭时）：")
    print("  · 校准好的小区域(420x60) det+rec ≈ 100ms   -> 3~5 fps，推荐")
    print("  · 单行紧裁剪 rec-only          ≈  90ms/行  -> 快，但行高必须完全对得上")
    print("  · 全屏 1920x1080 det+rec       ≈ 1~4 秒    -> 太慢，别整屏跑")
    print("  · 游戏同时运行时会明显变慢，所以两种状态都测一下")
    print("  · 两个 OCR 引擎实例同时跑会互相抢线程（会把 100ms 拖到 8 秒），保持单实例")
    return 0


def _game_running() -> bool:
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if "deadlock" in name or "citadel" in name:
                return True
    except Exception:  # noqa: BLE001
        import subprocess

        try:
            out = subprocess.run(["tasklist"], capture_output=True, text=True,
                                 timeout=10).stdout.lower()
            return "deadlock" in out
        except Exception:  # noqa: BLE001
            return False
    return False


if __name__ == "__main__":
    raise SystemExit(main())

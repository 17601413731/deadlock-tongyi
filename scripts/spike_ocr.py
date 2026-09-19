#!/usr/bin/env python
"""实测三：OCR 能不能认出 Deadlock 的聊天文字。

会做三件事：
  1. 按配置的区域抓一张图，存到 spike_out/
  2. 跑 OCR，打印每行文字与置信度
  3. 画框存一张标注图，方便你肉眼确认框得准不准

用法：
    python scripts/spike_ocr.py                     # 用 config.yaml 里的区域
    python scripts/spike_ocr.py --region 0.01,0.55,0.40,0.95
    python scripts/spike_ocr.py --full              # 抓整屏（想让我帮你看就把这张图发我）
    python scripts/spike_ocr.py --watch 10          # 连续抓 10 秒，看聊天滚动时的效果
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
from dlchat.chat.parser import parse_line          # noqa: E402
from dlchat.config import load_config              # noqa: E402

OUT_DIR = Path("spike_out")


def save_image(arr: np.ndarray, name: str, boxes=None) -> Path:
    from PIL import Image, ImageDraw

    OUT_DIR.mkdir(exist_ok=True)
    img = Image.fromarray(arr.astype("uint8"))
    if boxes:
        draw = ImageDraw.Draw(img)
        for line in boxes:
            draw.rectangle(line.box, outline=(255, 64, 64), width=2)
            draw.text((line.box[0], max(0, line.box[1] - 12)),
                      f"{line.text[:28]} {line.score:.2f}", fill=(255, 220, 0))
    path = OUT_DIR / name
    img.save(path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Deadlock 聊天 OCR 实测")
    ap.add_argument("--region", default="", help="归一化 左,上,右,下")
    ap.add_argument("--full", action="store_true", help="抓整屏")
    ap.add_argument("--image", default="", help="对已保存的图片跑 OCR（不抓屏）")
    ap.add_argument("--watch", type=int, default=0, help="连续抓多少秒")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    region = [float(v) for v in args.region.split(",")] if args.region else cfg.ocr.region
    if args.full:
        region = [0.0, 0.0, 1.0, 1.0]

    grabber = ScreenGrabber() if not args.image else None
    print("=" * 68)
    if args.image:
        from PIL import Image

        frame = np.asarray(Image.open(args.image).convert("RGB"))
        print(f"输入图片: {args.image}  ({frame.shape[1]}x{frame.shape[0]})")
        grabber = None
    else:
        print(f"抓帧后端: {grabber.backend}   屏幕: {grabber.size[0]}x{grabber.size[1]}")
        print(f"区域(归一化): {region}")
        if grabber.backend == "none":
            print("❌ 抓不到屏幕画面：pip install dxcam mss")
            return 1

        frame = grabber.grab(region)
        if frame is None:
            print("❌ 抓帧返回空（可能是不支持的显示模式）")
            return 1
        raw_path = save_image(frame, "region_raw.png")
        print(f"原图已存: {raw_path}  ({frame.shape[1]}x{frame.shape[0]})")

    try:
        ocr = create_ocr(cfg.ocr.backend, min_confidence=cfg.ocr.min_confidence,
                         upscale=cfg.ocr.upscale, invert=cfg.ocr.invert)
        ocr.load()
    except Exception as e:  # noqa: BLE001
        print(f"❌ OCR 不可用: {e}")
        print("   → pip install rapidocr")
        print(f"   （原图已经存好了，可以先发给我看：{raw_path}）")
        grabber.close()
        return 1

    def run_once(tag: str, preloaded=None) -> int:
        img = preloaded if preloaded is not None else grabber.grab(region)
        if img is None:
            return 0
        t0 = time.perf_counter()
        boxes = ocr.recognize(img)
        cost = (time.perf_counter() - t0) * 1000
        print(f"\n--- {tag}: 识别到 {len(boxes)} 行，耗时 {cost:.0f}ms ---")
        hits = 0
        for line in boxes:
            parsed = parse_line(line.text, source="ocr", confidence=line.score)
            tag2 = ""
            if parsed is not None:
                hits += 1
                tag2 = f"   -> 说话人={parsed.speaker or '?'} 内容={parsed.text!r}"
            print(f"  [{line.score:.2f}] {line.text!r}{tag2}")
        if boxes:
            print(f"标注图: {save_image(img, f'ocr_{tag}.png', boxes)}")
        return hits

    started = time.time()
    if args.watch > 0 and grabber is not None:
        print(f"\n连续抓 {args.watch} 秒（去游戏里发几条聊天效果最好）...")
        last = ""
        while time.time() - started < args.watch:
            img = grabber.grab(region)
            if img is None:
                time.sleep(0.2)
                continue
            boxes = ocr.recognize(img)
            text = " | ".join(b.text for b in boxes)
            if text and text != last:
                last = text
                print(f"  {time.strftime('%H:%M:%S')}  {text[:150]}")
            time.sleep(max(0.2, cfg.ocr.interval_ms / 1000))
    else:
        hits = run_once("single", preloaded=frame)
        print(f"\n其中能解析成聊天行的: {hits}")

    print("\n" + "=" * 68)
    print("判断标准：")
    print("  · 认出来并且说话人/内容分对了 -> 直接可用（把 config.yaml 的 source.kind 保持 ocr）")
    print("  · 认出来但缺字/串行 -> 先把原图发我，我调预处理（放大倍数/反色/裁剪）")
    print("  · 一行都没认出来 -> 换个区域再试，或截图发我（--full 抓整屏）")
    grabber.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

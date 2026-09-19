#!/usr/bin/env python
"""生成程序图标 packaging/icon.ico（多尺寸）。

不用外部素材：画一个深色圆角方块 + 对话气泡 + "译"字，16~256 全尺寸打包进 ico。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "icon.ico"
FONTS = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def _font(size: int):
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    radius = max(2, size // 5)
    # 深色圆角底
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius,
                        fill=(23, 27, 38, 255), outline=(79, 195, 247, 255),
                        width=max(1, size // 32))
    # 对话气泡
    b = size * 0.16
    d.rounded_rectangle([b, b * 1.15, size - b, size - b * 1.9],
                        radius=max(2, size // 8), fill=(79, 195, 247, 255))
    d.polygon([(size * 0.32, size - b * 1.95),
               (size * 0.30, size - b * 0.95),
               (size * 0.48, size - b * 1.95)], fill=(79, 195, 247, 255))
    # 气泡里的"译"
    if size >= 32:
        font = _font(int(size * 0.42))
        text = "译"
        box = d.textbbox((0, 0), text, font=font)
        d.text(((size - (box[2] - box[0])) / 2 - box[0],
                (size - (box[3] - box[1])) / 2 - box[1] - size * 0.04),
               text, font=font, fill=(23, 27, 38, 255))
    return img


def main() -> int:
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = draw(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print(f"已生成 {OUT} ({OUT.stat().st_size/1024:.1f} KB, 尺寸 {sizes})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

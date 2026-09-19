"""分析 Panorama 编译产物（*_c）的二进制格式。

目的：判断我们能否**自己生成** _c 文件，从而彻底绕开 resourcecompiler。
用法：python scripts/compiled_format.py <文件> [<文件> ...]
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ascii_ratio(data: bytes) -> float:
    if not data:
        return 0.0
    return sum(1 for b in data if 9 <= b <= 13 or 32 <= b < 127) / len(data)


def show(path: Path) -> None:
    data = path.read_bytes()
    print("=" * 78)
    print(f"{path.name}   {len(data)} bytes   printable={ascii_ratio(data):.1%}")
    print(f"  head[0:32]  : {data[:32].hex(' ')}")
    print(f"  head[0:8] u32: {struct.unpack_from('<II', data, 0)}")

    # 找可打印串（>=6 字节）
    runs: list[tuple[int, str]] = []
    cur = bytearray()
    start = 0
    for i, b in enumerate(data):
        if 9 <= b <= 13 or 32 <= b < 127:
            if not cur:
                start = i
            cur.append(b)
        else:
            if len(cur) >= 6:
                runs.append((start, cur.decode("ascii", "replace")))
            cur.clear()
    if len(cur) >= 6:
        runs.append((start, cur.decode("ascii", "replace")))
    print(f"  可打印串 {len(runs)} 段，前 25 段：")
    for off, s in runs[:25]:
        print(f"    0x{off:05x}  {s[:110]}")

    # 尾部
    print(f"  tail[{-32}:] : {data[-32:].hex(' ')}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    show(f)
        else:
            show(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

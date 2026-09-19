"""解析/生成 Source 2 编译资源容器（*_c 文件）。

格式（依据 VRF 的 Resource.cs，已用 Deadlock 真实文件核对）：

    u32  fileSize
    u16  headerVersion   (= 12)
    u16  version         (资源类型版本；Panorama 布局=3，脚本=4)
    u32  blockOffset     (= 8，即跳过紧随其后的两个 u32)
    u32  blockCount
    [blockCount] × { u32 type(4字节 ASCII), u32 offset(相对本字段自身位置), u32 size }

块名示例：RED2（资源编译元信息）、DATA（实际负载）、LaCo（Panorama 布局 AST，KV3）、
RERL（外部引用）等。

用法：
    python scripts/red2.py <文件>              # 列出块
    python scripts/red2.py <文件> --dump DATA -o out.bin
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HEADER_VERSION = 12


def parse(data: bytes) -> tuple[int, int, list[tuple[str, int, int]]]:
    file_size, header_version, version = struct.unpack_from("<IHH", data, 0)
    if header_version != HEADER_VERSION:
        raise ValueError(f"不是资源文件（headerVersion={header_version}）")
    block_offset, block_count = struct.unpack_from("<II", data, 8)
    pos = 16 + (block_offset - 8)
    blocks: list[tuple[str, int, int]] = []
    for _ in range(block_count):
        btype = data[pos:pos + 4].decode("ascii", "replace")
        off_field = pos + 4
        rel_off, size = struct.unpack_from("<II", data, off_field)
        blocks.append((btype, off_field + rel_off, size))
        pos += 12
    return file_size, version, blocks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--dump")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()

    p = Path(args.path)
    data = p.read_bytes()
    file_size, version, blocks = parse(data)
    print(f"{p.name}: fileSize={file_size} (实际 {len(data)}) version={version} blocks={len(blocks)}")
    for btype, off, size in blocks:
        head = data[off:off + 16].hex(" ")
        ascii_head = "".join(chr(b) if 32 <= b < 127 else "." for b in data[off:off + 16])
        print(f"  {btype}  off=0x{off:06x} size={size:7}  head={head}  |{ascii_head}|")

    if args.dump:
        for btype, off, size in blocks:
            if btype == args.dump:
                payload = data[off:off + size]
                if args.out:
                    Path(args.out).write_bytes(payload)
                    print(f"  -> {args.out} ({len(payload)} B)")
                else:
                    print(f"  {btype} 负载 hex: {payload[:64].hex(' ')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

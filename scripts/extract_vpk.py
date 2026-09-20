"""从 Deadlock 的 VPK 里按路径模式提取文件（只读，不改游戏）。

用法：
    python scripts/extract_vpk.py --list panorama/layout/chat
    python scripts/extract_vpk.py --grep "chat" --limit 40
    python scripts/extract_vpk.py --extract panorama/styles/chat.vcss_c -o build/.work/vanilla
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
DL_GAME = Path(r"D:\software\steam\steamapps\common\Deadlock\game")
VPK_SIGNATURE = 0x55AA1234


def read_index(vpk: Path) -> list[tuple[str, int, int, int]]:
    """返回 [(vpk内路径, archive_index, offset, length)]。

    archive_index == 0x7FFF 表示数据就在 dir vpk 自身的数据区；
    否则数据在 <stem>_<index:03d>.vpk 里，offset 相对那个文件开头。
    """
    data = vpk.read_bytes()
    sig, ver, tree_size = struct.unpack_from("<III", data, 0)
    if sig != VPK_SIGNATURE:
        raise ValueError(f"不是 VPK: {vpk}")
    pos = 28 if ver == 2 else 12
    end = pos + tree_size

    def cstr(p: int) -> tuple[str, int]:
        e = data.index(b"\x00", p)
        return data[p:e].decode("utf-8", "replace"), e + 1

    out: list[tuple[str, int, int, int]] = []
    while pos < end:
        ext, pos = cstr(pos)
        if ext == "":
            break
        while True:
            directory, pos = cstr(pos)
            if directory == "":
                break
            while True:
                name, pos = cstr(pos)
                if name == "":
                    break
                _crc, preload, arch, off, length, _term = struct.unpack_from(
                    "<IHHIIH", data, pos)
                pos += 18 + preload
                full = f"{directory}/{name}.{ext}" if directory else f"{name}.{ext}"
                out.append((full, arch, off, length))
    return out


def read_entry(vpk: Path, arch: int, off: int, length: int) -> bytes:
    if arch == 0x7FFF:
        src = vpk
        base = 28 if struct.unpack_from("<I", vpk.read_bytes(), 4)[0] == 2 else 12
        base += struct.unpack_from("<I", vpk.read_bytes(), 8)[0]
        with src.open("rb") as f:
            f.seek(base + off)
            return f.read(length)
    part = vpk.with_name(f"{vpk.stem[:-4]}_{arch:03d}.vpk")
    with part.open("rb") as f:
        f.seek(off)
        return f.read(length)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vpk", default=str(DL_GAME / "citadel" / "pak01_dir.vpk"))
    ap.add_argument("--list", help="精确路径（不含扩展名前缀匹配）")
    ap.add_argument("--grep", help="正则匹配路径")
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--extract", nargs="*", help="要提取的完整 vpk 内路径")
    ap.add_argument("-o", "--out", default=str(ROOT / "build" / ".work" / "vanilla"))
    args = ap.parse_args()

    vpk = Path(args.vpk)
    index = read_index(vpk)
    print(f"[vpk] {vpk.name}: {len(index)} 个文件", file=sys.stderr)

    if args.grep:
        rx = re.compile(args.grep)
        hits = [e for e in index if rx.search(e[0])]
        print(f"[vpk] 匹配 {len(hits)} 个：")
        for path, arch, off, length in hits[:args.limit]:
            print(f"  {length:9} B  {path}")
        return 0

    if args.list:
        hits = [e for e in index if args.list in e[0]]
        for path, arch, off, length in hits[:args.limit]:
            print(f"  {length:9} B  {path}")
        return 0

    outdir = Path(args.out)
    for want in args.extract or []:
        match = [e for e in index if e[0] == want]
        if not match:
            print(f"[vpk] 未找到: {want}")
            continue
        path, arch, off, length = match[0]
        data = read_entry(vpk, arch, off, length)
        dest = outdir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        print(f"[vpk] {path} -> {dest} ({len(data)} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""构建我们自己的 Deadlock mod VPK（纯 Python，不依赖 VPKEdit）。

## 为什么能自己写 VPK

VPK 格式很简单，我已经从实际 mod 文件里逐字节确认过：

    Header (28 字节, version=2)
      signature 0x55AA1234 | version 2 | tree_size
      file_data_section_size | archive_md5_size | other_md5_size | signature_size
    Tree
      按 扩展名 → 目录 → 文件名 三层的 null 结尾字符串,
      每个文件跟一条 18 字节记录 + preload 数据:
        crc32(u32) preload_bytes(u16) archive_index(u16, 0x7FFF=数据在本文件内)
        entry_offset(u32, 相对文件数据区) entry_length(u32) terminator(u16=0xFFFF)
    文件数据区（各文件内容拼接）
    other_md5 段（48 字节）

Deadlock 的 mod 就是"单文件 VPK + 数据内联"（实测 BabelTower 的 pak01_dir.vpk：
180853 字节 = 28 + 185 + 180592 + 48，完全对得上）。

## 编译

Panorama 源码（.xml/.js/.css）必须编译成 _c 格式。本机没有 Source 2 CSDK，
但 **CS2 自带 resourcecompiler.exe**，用 -game 指向 Deadlock 的 gameinfo.gi 即可。

用法：
    python scripts/build_mod.py                 # 编译 + 打包
    python scripts/build_mod.py --no-compile    # 只打包（已经编译过）
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
MOD_SRC = ROOT / "mod"
MOD_OUT = ROOT / "build_mod"           # 编译产物（_c 文件）
DIST = ROOT / "dist_mod"

GAMEINFO = Path(r"D:\software\steam\steamapps\common\Deadlock\game\citadel\gameinfo.gi")
RESOURCE_COMPILER = Path(
    r"D:\software\steam\steamapps\common\Counter-Strike Global Offensive"
    r"\game\bin\win64\resourcecompiler.exe")

# 编译产物在 VPK 里的路径（panorama 下的相对路径）
COMPILE_TARGETS = {
    "scripts/dlchat.js": "panorama/scripts/dlchat.vjs_c",
    "styles/dlchat.css": "panorama/styles/dlchat.vcss_c",
    "layout/chat.xml": "panorama/layout/chat.vxml_c",
}

VPK_SIGNATURE = 0x55AA1234
ARCHIVE_INLINE = 0x7FFF


# ---------------------------------------------------------------------------
# VPK 写入
# ---------------------------------------------------------------------------

def write_vpk(files: dict[str, bytes], out_path: Path) -> Path:
    """把 {vpk内路径: 内容} 打成单文件 VPK（数据内联）。"""
    # 按 扩展名 -> 目录 -> 文件名 归组
    tree: dict[str, dict[str, dict[str, bytes]]] = {}
    for full, data in files.items():
        path = full.replace("\\", "/")
        if "." not in path.rsplit("/", 1)[-1]:
            raise ValueError(f"没有扩展名，VPK 无法索引: {full}")
        head, ext = path.rsplit(".", 1)
        directory, _, name = head.rpartition("/")
        tree.setdefault(ext, {}).setdefault(directory, {})[name] = data

    def cstr(s: str) -> bytes:
        return s.encode("utf-8") + b"\x00"

    tree_bytes = bytearray()
    data_bytes = bytearray()
    for ext in sorted(tree):
        tree_bytes += cstr(ext)
        for directory in sorted(tree[ext]):
            tree_bytes += cstr(directory)
            for name in sorted(tree[ext][directory]):
                payload = tree[ext][directory][name]
                tree_bytes += cstr(name)
                tree_bytes += struct.pack(
                    "<IHHIIH",
                    zlib.crc32(payload) & 0xFFFFFFFF,
                    0,                       # preload_bytes
                    ARCHIVE_INLINE,          # 数据就在本文件里
                    len(data_bytes),         # entry_offset（相对文件数据区）
                    len(payload),
                    0xFFFF,                  # terminator
                )
                data_bytes += payload
            tree_bytes += b"\x00"                    # 该目录的文件名列表结束
        tree_bytes += b"\x00"                        # 该扩展名的目录列表结束
    tree_bytes += b"\x00"                            # 整棵树结束

    header = struct.pack(
        "<IIIIIII",
        VPK_SIGNATURE, 2, len(tree_bytes),
        len(data_bytes),
        0,          # archive_md5_section_size
        48,         # other_md5_section_size（实测 mod VPK 是 48）
        0,          # signature_section_size
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(bytes(header) + bytes(tree_bytes) + bytes(data_bytes)
                         + b"\x00" * 48)
    return out_path


def read_vpk_index(path: Path) -> list[tuple[str, int, int]]:
    """读回 VPK 索引，用于自检：[(路径, offset, length)]。"""
    data = path.read_bytes()
    sig, ver, tree_size = struct.unpack_from("<III", data, 0)
    if sig != VPK_SIGNATURE:
        raise ValueError("不是 VPK")
    pos = 28 if ver == 2 else 12
    end = pos + tree_size
    out: list[tuple[str, int, int]] = []

    def rs(p: int) -> tuple[str, int]:
        e = data.index(b"\x00", p)
        return data[p:e].decode("utf-8", "replace"), e + 1

    while pos < end:
        ext, pos = rs(pos)
        if ext == "":
            break
        while True:
            directory, pos = rs(pos)
            if directory == "":
                break
            while True:
                name, pos = rs(pos)
                if name == "":
                    break
                _crc, preload, _arch, off, length, _term = struct.unpack_from(
                    "<IHHIIH", data, pos)
                pos += 18 + preload
                full = f"{directory}/{name}.{ext}" if directory else f"{name}.{ext}"
                out.append((full, off, length))
    return out


# ---------------------------------------------------------------------------
# 编译
# ---------------------------------------------------------------------------

def compile_sources() -> list[Path]:
    """用 CS2 的 resourcecompiler 编译 Panorama 源码 -> _c 文件。"""
    if not RESOURCE_COMPILER.exists():
        raise SystemExit(f"找不到编译器: {RESOURCE_COMPILER}")
    if not GAMEINFO.exists():
        raise SystemExit(f"找不到 gameinfo.gi: {GAMEINFO}")

    sources = [MOD_SRC / rel for rel in COMPILE_TARGETS]
    missing = [str(p) for p in sources if not p.exists()]
    if missing:
        raise SystemExit(f"源码缺失: {missing}")

    cmd = [
        str(RESOURCE_COMPILER),
        "-game", str(GAMEINFO),
        "-nop4",                      # 不碰 Perforce
        "-v",
        *[str(p) for p in sources],
    ]
    print("编译中：")
    print("  " + " ".join(f'"{c}"' if " " in c else c for c in cmd[1:]))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                          cwd=str(MOD_SRC))
    if proc.stdout:
        for line in proc.stdout.splitlines()[-25:]:
            print("   ", line)
    if proc.returncode != 0:
        print(proc.stderr[-2000:] if proc.stderr else "(无 stderr)")
        raise SystemExit(f"编译失败，退出码 {proc.returncode}")

    out: list[Path] = []
    for rel, vpk_path in COMPILE_TARGETS.items():
        compiled = (MOD_SRC / rel).with_name(
            (MOD_SRC / rel).stem + {"js": ".vjs_c", "css": ".vcss_c",
                                    "xml": ".vxml_c"}[(MOD_SRC / rel).suffix[1:]])
        if not compiled.exists():
            raise SystemExit(f"编译器没产出期望的文件: {compiled}")
        out.append(compiled)
        print(f"  ✅ {compiled.name}  ({compiled.stat().st_size} 字节)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="构建 Deadlock 翻译 mod VPK")
    ap.add_argument("--no-compile", action="store_true", help="跳过编译，直接用已有 _c 文件")
    ap.add_argument("--out", default="", help="输出 VPK 路径")
    args = ap.parse_args()

    if not args.no_compile:
        compile_sources()

    files: dict[str, bytes] = {}
    for rel, vpk_path in COMPILE_TARGETS.items():
        src = MOD_SRC / rel
        suffix = {"js": ".vjs_c", "css": ".vcss_c", "xml": ".vxml_c"}[src.suffix[1:]]
        compiled = src.with_name(src.stem + suffix)
        if not compiled.exists():
            raise SystemExit(f"缺少编译产物 {compiled}（先不加 --no-compile 跑一次）")
        files[vpk_path] = compiled.read_bytes()

    out_path = Path(args.out) if args.out else DIST / "pak01_dir.vpk"
    write_vpk(files, out_path)
    print(f"\n已生成 {out_path}  ({out_path.stat().st_size} 字节)")

    print("\n自检（读回索引）：")
    for full, off, length in read_vpk_index(out_path):
        print(f"  {full:<44} offset={off:<8} len={length}")
    expected = 28 + len(files)
    print(f"\n文件数={len(files)}  大小校验: 头部28 + 树 + 数据 + md5段48")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""读 Deadlock 的崩溃转储，输出"异常类型 + 出错模块"。

为什么自己解析：Windows 事件日志里没有记录，而 minidump 格式是公开的 —— 头部 +
流目录里就有 ExceptionStream（异常码/异常地址）和 ModuleListStream（模块基址）。
拿异常地址去模块表里查，就能知道崩在哪个 DLL，从而判断跟我们的 mod 有没有关系。

用法：
    python scripts/analyze_crash.py                       # 自动找最新的几个
    python scripts/analyze_crash.py <某个.mdmp>
    python scripts/analyze_crash.py --all                 # 分析全部
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DUMP_DIR = Path(r"D:\software\steam\steamapps\common\Deadlock\game\bin\win64")

STREAM_EXCEPTION = 6
STREAM_MODULE_LIST = 4
STREAM_MISC_INFO = 15
STREAM_SYSTEM_INFO = 7
STREAM_THREAD_LIST = 3

# 常见异常码
EXC = {
    0xC0000005: "ACCESS_VIOLATION 访问违例（读写野指针）",
    0xC0000094: "INT_DIVIDE_BY_ZERO",
    0xC00000FD: "STACK_OVERFLOW 栈溢出",
    0xC0000409: "STACK_BUFFER_OVERRUN / __fastfail（通常是检测到内存破坏）",
    0xC0000374: "HEAP_CORRUPTION 堆损坏",
    0x80000003: "BREAKPOINT",
    0xE06D7363: "C++ EXCEPTION（未捕获的 C++ 异常）",
    0xC000001D: "ILLEGAL_INSTRUCTION",
    0xC0000017: "NO_MEMORY",
    0x80000002: "DATATYPE_MISALIGNMENT",
}


def u32(b: bytes, off: int) -> int:
    return struct.unpack_from("<I", b, off)[0]


def u64(b: bytes, off: int) -> int:
    return struct.unpack_from("<Q", b, off)[0]


def read_mdstring(data: bytes, rva: int) -> str:
    if not rva or rva + 4 > len(data):
        return "?"
    length = u32(data, rva)
    raw = data[rva + 4: rva + 4 + length]
    return raw.decode("utf-16-le", "replace")


def analyze(path: Path) -> None:
    data = path.read_bytes()
    if data[:4] != b"MDMP":
        print(f"{path.name}: 不是 minidump（前 4 字节 {data[:4]!r}）")
        return
    n_streams = u32(data, 8)
    dir_rva = u32(data, 12)
    stamp = u32(data, 20)

    streams: dict[int, tuple[int, int]] = {}
    for i in range(n_streams):
        off = dir_rva + i * 12
        stype, size, rva = struct.unpack_from("<III", data, off)
        streams[stype] = (size, rva)

    print(f"=== {path.name}")
    print(f"    文件时间: {path.stat().st_mtime:.0f}  流数: {n_streams}")

    # 模块表
    modules: list[tuple[int, int, str]] = []
    if STREAM_MODULE_LIST in streams:
        _, rva = streams[STREAM_MODULE_LIST]
        count = u32(data, rva)
        pos = rva + 4
        for _ in range(count):
            base = u64(data, pos)
            size = u32(data, pos + 8)
            name_rva = u32(data, pos + 20)
            modules.append((base, size, read_mdstring(data, name_rva)))
            pos += 108                      # sizeof(MINIDUMP_MODULE)
    print(f"    已加载模块: {len(modules)}")

    def which(addr: int) -> str:
        for base, size, name in modules:
            if base <= addr < base + size:
                return f"{Path(name).name}+0x{addr - base:x}"
        return f"<不在任何模块内> 0x{addr:x}"

    # 异常流
    if STREAM_EXCEPTION in streams:
        _, rva = streams[STREAM_EXCEPTION]
        thread_id = u32(data, rva)
        code = u32(data, rva + 8)
        flags = u32(data, rva + 12)
        addr = u64(data, rva + 24)
        n_params = u32(data, rva + 32)
        params = [u64(data, rva + 40 + i * 8) for i in range(min(n_params, 4))]
        desc = EXC.get(code, "未知异常码")
        print(f"    异常: 0x{code:08X}  {desc}")
        print(f"    异常地址: 0x{addr:x}  ->  {which(addr)}")
        print(f"    异常线程: {thread_id}   参数: {[hex(p) for p in params]}")
        if code == 0xC0000005 and params:
            kind = {0: "读", 1: "写", 8: "执行"}.get(params[0], str(params[0]))
            print(f"    访问违例类型: {kind}  目标地址: 0x{params[1]:x}"
                  + (f"  ->  {which(params[1])}" if params[1] else ""))
        # C++ 异常：第 4 个参数是抛出异常那个模块的基址
        if code == 0xE06D7363 and len(params) >= 4:
            print(f"    抛出异常的模块: {which(params[3])}")

    # 崩溃线程的栈扫描：按模块统计栈上的返回地址 —— 不用符号表也能看出"崩在谁里面"
    if STREAM_THREAD_LIST in streams:
        _, rva = streams[STREAM_THREAD_LIST]
        count = u32(data, rva)
        pos = rva + 4
        target = None
        for _ in range(count):
            tid = u32(data, pos)
            stack_start = u64(data, pos + 16)
            stack_size = u32(data, pos + 24)
            stack_rva = u32(data, pos + 28)
            if STREAM_EXCEPTION in streams and tid == u32(data, streams[STREAM_EXCEPTION][1]):
                target = (tid, stack_start, stack_size, stack_rva)
            pos += 48
        if target:
            tid, start, size, srva = target
            blob = data[srva: srva + size]
            hits: dict[str, int] = {}
            for off in range(0, len(blob) - 8, 8):
                val = struct.unpack_from("<Q", blob, off)[0]
                if val < 0x10000:
                    continue
                for base, msize, name in modules:
                    if base <= val < base + msize:
                        key = Path(name).name
                        hits[key] = hits.get(key, 0) + 1
                        break
            print(f"    崩溃线程栈命中（共 {len(blob)//8} 个槽，按模块）:")
            for name, n in sorted(hits.items(), key=lambda kv: -kv[1])[:10]:
                print(f"      {name:28} {n}")
    else:
        print("    没有异常流（可能是主动崩溃/断言）")

    # 崩溃附近的模块（按名字里关键字提示方向）
    key = [m for m in modules if any(k in m[2].lower() for k in
           ("panorama", "v8", "engine2", "citadel", "client", "materialsystem",
            "rendersystem", "nvwgf", "nvidia", "tier0", "filesystem"))]
    print("    相关模块:")
    for base, size, name in sorted(key, key=lambda m: m[2]):
        print(f"      {Path(name).name:28} base=0x{base:012x} size=0x{size:x}")
    print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    if args.path:
        analyze(Path(args.path))
        return 0
    dumps = sorted(DUMP_DIR.glob("deadlock_*.mdmp"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if not dumps:
        print("没找到转储文件")
        return 1
    for p in (dumps if args.all else dumps[:3]):
        analyze(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

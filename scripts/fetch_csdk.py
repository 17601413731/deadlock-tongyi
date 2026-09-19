"""下载 Reduced CSDK 12（社区版 Deadlock 工具链）。

为什么需要它：编译 Panorama 资源（`chat.xml`/`*.js`/`*.css` -> `*_c`）必须有
resourcecompiler。实测 CS2 零售版自带的 resourcecompiler 无法用于 Deadlock：

  * 它的 FileSystem 拒绝挂载自身安装目录之外的 pak（file sandbox）；
  * 即使把工程嵌进 CS2 目录，还缺 Workshop Tools 才有的 modtools.dll。

Deadlock 自己只带了 resourcecompiler.dll（无 exe），缺 modeldoc_utils/modtools。
社区把 CS2 Workshop Tools 与 Deadlock 的修正合并成 CSDK 12，正是为这件事准备的。

用法：
    python scripts/fetch_csdk.py --probe                 # 只看文件名与大小
    python scripts/fetch_csdk.py --download              # 下载到 D:\\csdk12\\
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

FILE_ID = "1-Z-4CszWQNudzwzs6e6abPsp5RGFOURS"
BASE = "https://drive.usercontent.google.com/download"
DEST_DIR = Path(r"D:\csdk12")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def http_get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve() -> tuple[str, str, int]:
    """返回 (最终下载 URL, 文件名, 字节大小)。大文件会先给一个确认页。"""
    url = f"{BASE}?id={FILE_ID}&export=download"
    with http_get(url) as resp:
        ctype = resp.headers.get("Content-Type", "")
        size = int(resp.headers.get("Content-Length") or 0)
        disp = resp.headers.get("Content-Disposition", "")
        if "text/html" not in ctype:
            name = _filename_from_disp(disp) or "csdk12.bin"
            return url, name, size
        page = resp.read().decode("utf-8", "replace")

    # 确认页：抓 form action 与隐藏字段
    action = re.search(r'<form[^>]+action="([^"]+)"', page)
    action = html.unescape(action.group(1)) if action else BASE
    fields = dict(re.findall(r'<input[^>]+name="([^"]+)"[^>]*value="([^"]*)"', page))
    if not fields:
        fields = dict(re.findall(r'<input[^>]+value="([^"]*)"[^>]*name="([^"]+)"', page))
        fields = {v: k for k, v in fields.items()}
    print(f"[csdk] 确认页字段: { {k: v[:24] for k, v in fields.items()} }")
    qs = urllib.parse.urlencode(fields)
    return f"{action}?{qs}", _filename_from_disp(disp) or "Reduced_CSDK_12.zip", 0


def _filename_from_disp(disp: str) -> str:
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disp or "")
    return urllib.parse.unquote(m.group(1)) if m else ""


def _stream(url: str, part: Path, offset: int, total_hint: int) -> tuple[int, int]:
    """下载到 part（从 offset 续传）。返回 (本次字节数, 服务端报的总大小)。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    if offset:
        req.add_header("Range", f"bytes={offset}-")
    t0 = time.time()
    done = 0
    with urllib.request.urlopen(req, timeout=120) as resp:
        status = getattr(resp, "status", 200)
        clen = int(resp.headers.get("Content-Length") or 0)
        if offset and status != 206:
            # 服务端不支持续传，只能从头来
            print("[csdk] 服务端忽略 Range，重新开始", flush=True)
            offset, done = 0, 0
        total = (offset + clen) if clen else total_hint
        mode = "ab" if offset else "wb"
        last = 0.0
        with part.open(mode) as fh:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                now = time.time()
                if now - last > 10:
                    last = now
                    speed = done / max(now - t0, 0.001) / 2**20
                    pct = f"{(offset+done)/total*100:5.1f}%" if total else "  ?  "
                    print(f"[csdk]   {pct}  {(offset+done)/2**20:8.1f} MiB  "
                          f"{speed:5.1f} MiB/s", flush=True)
    return done, total


def download(dest_dir: Path, retries: int = 12) -> Path:
    name = "Reduced_CSDK_12.zip"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name
    part = dest.with_suffix(dest.suffix + ".part")

    total = 0
    for attempt in range(1, retries + 1):
        offset = part.stat().st_size if part.exists() else 0
        url, _n, hint = resolve()
        if hint:
            total = hint
        print(f"[csdk] 第 {attempt} 次尝试，从 {offset/2**20:.1f} MiB 继续"
              f"（目标 {total/2**30:.2f} GiB）", flush=True)
        try:
            got, total = _stream(url, part, offset, total)
        except Exception as exc:  # noqa: BLE001  —— 断流/超时都当普通中断，续传即可
            print(f"[csdk] 中断: {type(exc).__name__}: {exc}", flush=True)
        size = part.stat().st_size
        if total and size >= total:
            break
        print(f"[csdk] 当前 {size/2**20:.1f} MiB", flush=True)
    else:
        raise SystemExit(f"[csdk] 重试 {retries} 次仍未完成: {part.stat().st_size} B")

    part.replace(dest)
    print(f"[csdk] 完成: {dest} ({dest.stat().st_size/2**30:.2f} GiB)")
    return dest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--dest", default=str(DEST_DIR))
    args = ap.parse_args()

    if args.probe:
        url, name, size = resolve()
        print(f"[csdk] 文件名: {name}")
        print(f"[csdk] 大小  : {size/2**30:.2f} GiB ({size} B)" if size else "[csdk] 大小: 未知（确认页）")
        print(f"[csdk] URL   : {url[:160]}...")
        return 0
    if args.download:
        download(Path(args.dest))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""等 Deadlock 退出后自动编译并安装 mod。

游戏运行时引擎会锁住 `addons\\pak01_dir.vpk`，装不进去（WinError 32）。与其让玩家
手动"关游戏 -> 跑脚本 -> 开游戏"，不如挂个后台任务盯着进程：一旦退出就装上，玩家下次
启动游戏自然就是新版。日志写到 build_mod/install.log。

用法（一般后台跑）：
    python scripts/wait_and_install.py                 # 最多等 90 分钟
    python scripts/wait_and_install.py --timeout 30
    python scripts/wait_and_install.py --now           # 不等，立刻试一次
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "build_mod" / "install.log"
ADDONS_VPK = Path(
    r"D:\software\steam\steamapps\common\Deadlock\game\citadel\addons\pak01_dir.vpk")
# DMM 自己的库：它导入 mod 时会在这里留一份 `files\pakNN_dir.vpk`，部署时从这里复制。
# 更新 mod 必须连这份一起换掉，否则 DMM 下次部署又把它那份旧的盖回去。
DMM_LIB = Path(r"C:\Users\Hlliang\AppData\Local\dev.stormix.deadlock-mod-manager\mods")

# DMM 接管后我们的包会被它按加载顺序改名，这些名字都要一起更新
DMM_TARGETS = ["pak02_dir.vpk", "pak03_dir.vpk"]


def log(msg: str) -> None:
    line = f"{datetime.now():%H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def game_running() -> bool:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq deadlock.exe", "/NH"],
                         capture_output=True, text=True, errors="replace")
    return "deadlock.exe" in (out.stdout or "")


def refresh_dmm_library(vpk: Path) -> None:
    """把 DMM 库里**我们那份** VPK 换成新编的（内容变了，但 DMM 只记文件名）。

    安全前提：只替换"包内路径里带 dlchat"的 VPK。DMM 库里可能还有别的本地 mod，
    绝不能因为名字像 pakNN_dir.vpk 就把人家的文件盖掉。
    """
    if not DMM_LIB.exists() or not vpk.exists():
        return
    new_data = vpk.read_bytes()
    for mod_dir in sorted(DMM_LIB.glob("local-*")):
        files_dir = mod_dir / "files"
        if not files_dir.is_dir():
            continue
        for old in sorted(files_dir.glob("*.vpk")):
            try:
                names = _vpk_names(old)
            except Exception as exc:  # noqa: BLE001
                log(f"  跳过（读不出索引）: {old.name}: {exc}")
                continue
            if not any("dlchat" in n for n in names):
                log(f"  跳过（不是我们的包）: {mod_dir.name}\\{old.name}")
                continue
            if old.read_bytes() == new_data:
                log(f"  已是最新: {mod_dir.name}\\files\\{old.name}")
                continue
            shutil.copy2(vpk, old)
            log(f"  刷新 DMM 库: {mod_dir.name}\\files\\{old.name}")


def _vpk_names(path: Path) -> list[str]:
    """读 VPK 索引里的路径列表（用来认清是不是我们的包）。"""
    data = path.read_bytes()
    sig, _, tree_size = struct.unpack_from("<III", data, 0)
    if sig != 0x55AA1234:
        raise ValueError("不是 VPK")
    pos, end = 28, 28 + tree_size
    out: list[str] = []

    def cstr(p: int) -> tuple[str, int]:
        e = data.index(b"\x00", p)
        return data[p:e].decode("utf-8", "replace"), e + 1

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
                _crc, preload, _arch, _off, _len, _term = struct.unpack_from(
                    "<IHHIIH", data, pos)
                pos += 18 + preload
                out.append(f"{directory}/{name}.{ext}" if directory else f"{name}.{ext}")
    return out


def install_once() -> bool:
    log("开始编译 + 安装 ...")
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "stage_compile.py"),
                           "--install", "--targets", *DMM_TARGETS],
                          cwd=str(ROOT), capture_output=True, text=True,
                          errors="replace")
    for line in (proc.stdout + proc.stderr).splitlines():
        if line.strip():
            log("  " + line.strip())
    ok = proc.returncode == 0
    if ok:
        refresh_dmm_library(ROOT / "dist_mod" / "pak01_dir.vpk")
        # DMM 库里换过了，让它按自己的部署逻辑再铺一次（重新启用等效）
        log("提示：DMM 库里也换成了新版；若游戏里仍无变化，在 DMM 里对该 mod 点一次再部署")
    log("安装" + ("成功" if ok else f"失败（exit={proc.returncode}）"))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=90, help="最多等多少分钟")
    ap.add_argument("--now", action="store_true", help="不等，立刻试一次")
    ap.add_argument("--interval", type=float, default=5, help="轮询间隔（秒）")
    args = ap.parse_args()

    if args.now:
        return 0 if install_once() else 1

    log(f"等待 Deadlock 退出（最多 {args.timeout:.0f} 分钟）...")
    deadline = time.time() + args.timeout * 60
    while time.time() < deadline:
        if not game_running():
            log("检测到 deadlock.exe 已退出")
            time.sleep(3)                     # 给引擎一点时间释放文件句柄
            while game_running():
                time.sleep(2)
            if install_once():
                return 0
            log("安装失败，30 秒后重试（可能被别的程序占用）")
            time.sleep(30)
        time.sleep(args.interval)
    log("等待超时，未安装。手动跑 install_mod.bat 即可。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

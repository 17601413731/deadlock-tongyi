"""通译（Tongyi）启动器：给 Steam 启动选项用的"包装器"。

它解决的是"打了 mod 还得手动开桥"这件事，做法是把游戏本身的启动命令包一层：

    Steam → Deadlock → 属性 → 启动选项：
        "C:\\...\\tongyi-launch.exe" %command%

于是点"开始游戏"时：

    1. 先把翻译桥**在本进程内**起起来（不是另开一个进程，所以只有一个进程、
       没有窗口，`tongyi-launch.exe` 一退桥就跟着没了，不会留孤儿）
    2. 再原样启动游戏本体（Steam 给的 %command% 参数直接透传）
    3. 等游戏退出后，把桥关掉、自己退出

为什么是"内嵌"而不是"拉一个桥的子进程"：
  · 少一个进程、少一份 Python 运行时（打包体积和内存都省）
  · 生命周期天然绑定：游戏退了 = 启动器退了 = 桥没了，不存在"桥还在但你没在玩"
  · `%command%` 里的路径带空格也不会出岔子（我们不做字符串拼接，直接透传参数列表）

不用管理员权限、不写注册表、不常驻 —— 只在游戏运行期间存在。
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from . import paths, single_instance

logger = logging.getLogger("dlchat.launcher")

LAUNCHER_MUTEX = "Global\\deadlock-tongyi-launcher"
GAME_EXE = "deadlock.exe"
# 桥被别人（手动 run_bridge 或前一次启动器）占着时要等多久
BRIDGE_WAIT_S = 25.0


def setup_logging(level: int = logging.INFO) -> Path:
    """把日志写到文件。

    ⚠ 打包成**无窗口** exe 之后没有 stdout，日志是唯一的排查手段 ——
    `run_bridge.py` 里的 `basicConfig` 那种"打到控制台"的做法在这里等于没日志。
    """
    log_file = paths.log_dir() / "launcher.log"
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        handler = RotatingFileHandler(log_file, maxBytes=512_000,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%m-%d %H:%M:%S"))
        root.addHandler(handler)
    root.setLevel(level)
    # 这些太吵，只在排查时开
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    return log_file


def bridge_port(cfg: Any) -> int:
    try:
        return int(cfg.bridge.port)
    except Exception:  # noqa: BLE001
        return 8791


def health_ok(port: int, timeout: float = 1.5) -> bool:
    """端口上有没有一个活着的桥（用它的 /api/v1/health）。"""
    url = f"http://127.0.0.1:{port}/api/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_for_bridge(port: int, timeout: float) -> bool:
    """等桥开始监听。游戏已经在启动流程里了，别让玩家等太久 —— 超时就照常开游戏。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if health_ok(port):
            return True
        time.sleep(0.25)
    return False


def game_running() -> list[int]:
    """已经在跑的 deadlock.exe 进程号（防止重复启动 + 判断游戏有没有退）。

    用 tasklist 而不是 psutil：桥这条链路刻意只依赖核心几个包
    （openai/pydantic/yaml），装包越小、发给别人时越不容易出错。
    """
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GAME_EXE}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:  # noqa: BLE001
        logger.warning("查询游戏进程失败: %s", e)
        return []
    pids: list[int] = []
    for line in out.splitlines():
        parts = [p.strip().strip('"') for p in line.split('","')]
        if len(parts) >= 2 and parts[0].lower() == GAME_EXE:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                continue
    return pids


def start_bridge_embedded(cfg: Any, port: int) -> bool:
    """在本进程内把桥起起来（后台线程）。返回 False = 端口上已经有一个桥了。"""
    from .bridge import BridgeApp, BridgeServer

    if health_ok(port):
        logger.info("端口 %d 上已经有一个桥在跑，直接用它", port)
        return False

    app = BridgeApp(cfg)
    app.start_loop()
    server = BridgeServer(app, port)
    server.start()                       # 内部起线程，不会阻塞这里
    logger.info("桥已在本进程内启动: http://127.0.0.1:%d", port)

    # 预热放到后台：本地 Ollama 首次载模型要 30~40 秒，不能挡着游戏启动。
    def _warm() -> None:
        try:
            t0 = time.perf_counter()
            ok = app.warmup()
            logger.info("预热%s，耗时 %.1fs", "完成" if ok else "跳过/失败",
                        time.perf_counter() - t0)
        except Exception as e:  # noqa: BLE001
            logger.warning("预热异常: %s", e)

    threading.Thread(target=_warm, daemon=True, name="launcher-warmup").start()
    return True


def spawn_game(command: list[str]) -> subprocess.Popen | None:
    """原样透传 Steam 给的 %command%。"""
    if not command:
        return None
    try:
        # 不捕获输出：让游戏自己开窗口；cwd 用可执行文件所在目录，和 Steam 直接启动时一致
        return subprocess.Popen(command, cwd=str(Path(command[0]).parent))
    except (OSError, ValueError) as e:  # noqa: BLE001
        logger.error("启动游戏失败: %s（命令: %s）", e, command)
        return None


def wait_for_game(proc: subprocess.Popen, port: int = 0) -> int:
    """等游戏退出；顺便每 15 秒确认一次桥还活着。返回游戏的退出码。

    为什么要顺手看桥：启动器是无窗口的，万一桥中途挂了（端口被占、依赖缺失），
    玩家只会看到"游戏里一直未连接"，没有任何提示。日志里留下时间点，排查时能对上。
    """
    last_state: bool | None = None
    ticks = 0
    while True:
        try:
            proc.wait(timeout=1.0)
            logger.info("游戏已退出（退出码 %s）", proc.returncode)
            return int(proc.returncode or 0)
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            logger.info("收到中断，准备退出")
            return 0
        ticks += 1
        if port and ticks % 15 == 0:
            alive = health_ok(port, timeout=1.0)
            if alive != last_state:
                logger.info("桥%s", "正常" if alive else "无响应（游戏内会显示未连接）")
                last_state = alive


def split_command(parsed: argparse.Namespace, extra: list[str]) -> list[str]:
    """把"位置参数 + 未知参数"合并成要启动的命令（保持顺序）。

    单独拎出来是为了能离线测：这里是 Steam 那条链路上最容易出错的一环 ——
    Steam 会把游戏路径和它自己的开关（-console、-novid…）一起塞进 %command%，
    合并错了就是"点了开始游戏没反应"或"启动的是别的东西"。
    """
    return list(parsed.command or []) + list(extra or [])


def use_bundled_ca() -> str:
    """让 HTTPS 用打包进来的 CA 证书。

    为什么需要：PyInstaller 打包后 `ssl.create_default_context()` 拿不到系统证书库，
    表现是 httpx 建客户端时直接抛 `FileNotFoundError: [Errno 2]`（栈顶在 ssl.py），
    于是**云端翻译一条都发不出去** —— 而源码运行完全正常，只有在打包版里才复现。
    把 SSL_CERT_FILE 指到 certifi 自带的 cacert.pem（spec 里已经收集进来了）即可。
    开发环境不动它：那里系统证书库是好的，改了指错路反而更糟。
    """
    if not getattr(sys, "frozen", False):
        return ""
    try:
        import certifi
        cafile = certifi.where()
    except Exception as e:  # noqa: BLE001
        logger.warning("拿不到 certifi 证书路径: %s", e)
        return ""
    if cafile and os.path.exists(cafile):
        os.environ.setdefault("SSL_CERT_FILE", cafile)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", cafile)
        logger.info("HTTPS 证书: %s", cafile)
        return cafile
    logger.warning("证书文件不存在: %s", cafile)
    return ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="tongyi-launch",
        description="通译启动器：先起翻译桥，再启动游戏（给 Steam 启动选项用）")
    ap.add_argument("command", nargs="*",
                    help="要启动的游戏命令；Steam 里写 %%command%%")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--port", type=int, default=0, help="默认取 config.yaml 的 bridge.port")
    ap.add_argument("--no-bridge", action="store_true",
                    help="只启动游戏，不起桥（排查用）")
    ap.add_argument("--stay", action="store_true",
                    help="没有给游戏命令时也保持运行（只起桥，Ctrl+C 退出）")
    # parse_known_args：Steam 会把它自己的一些开关（-console、-novid…）也塞进 %command%，
    # 用严格的 parse_args 会因为"未知参数"直接报错退出 —— 那就变成"点了开始游戏没反应"。
    args, extra = ap.parse_known_args(argv)
    if extra:
        logger.info("透传未知参数（Steam/游戏自己的开关）: %s", extra)
    # 位置参数与未知参数按原样拼回去（保持顺序），再交给游戏
    command = split_command(args, extra)

    log_file = setup_logging()
    logger.info("=" * 60)
    logger.info("dlchat 启动器启动。command=%s", command or "(空)")
    # 必须在任何 httpx 客户端建立之前设置（桥和预热都会建）
    use_bundled_ca()

    from .config import load_config

    cfg = load_config(args.config)
    port = args.port or bridge_port(cfg)

    # 已经有启动器在跑（例如玩家点了两次"开始游戏"）：这次只透传游戏，不碰桥。
    if not single_instance.acquire(LAUNCHER_MUTEX):
        logger.warning("已有启动器在运行，本次只启动游戏（桥交给前一个实例）")
        proc = spawn_game(command)
        if proc is not None:
            return wait_for_game(proc, port)
        return 1

    started_by_us = False
    if not args.no_bridge:
        try:
            started_by_us = start_bridge_embedded(cfg, port)
        except Exception as e:  # noqa: BLE001
            # 桥起不来也要让游戏能开：玩家至少还能正常玩，日志里有原因
            logger.exception("桥启动失败，继续启动游戏: %s", e)

        if started_by_us:
            if wait_for_bridge(port, BRIDGE_WAIT_S):
                logger.info("桥已就绪，开始启动游戏")
            else:
                logger.error("等了 %.0fs 桥还没就绪，照常启动游戏（游戏内会显示未连接）",
                             BRIDGE_WAIT_S)
    else:
        logger.info("--no-bridge：只启动游戏")

    if not command:
        if not args.stay:
            logger.info("没有给游戏命令，退出（只想开桥请加 --stay）")
            logger.info("日志: %s", log_file)
            return 0
        logger.info("只起桥模式（Ctrl+C 退出）。日志: %s", log_file)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return 0

    proc = spawn_game(command)
    if proc is None:
        return 1
    code = wait_for_game(proc, port)
    logger.info("退出（桥随本进程一起结束）")
    # 把游戏的退出码原样传回去：Steam 会把它记进游戏时长/崩溃统计，
    # 排查"游戏莫名退出"时也用得上。
    return code


if __name__ == "__main__":
    raise SystemExit(main())

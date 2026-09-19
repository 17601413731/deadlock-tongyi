#!/usr/bin/env python
"""启动本地翻译桥（给 Deadlock 游戏内 mod 用）。

用法：
    python scripts/run_bridge.py                 # 默认端口 8791
    python scripts/run_bridge.py --port 8791 --no-warmup

启动后：
    · 游戏内的 BabelTower mod 面板 应显示"桥已连接"
    · 自检：curl http://127.0.0.1:8791/api/v1/health
    · 试翻：curl -X POST http://127.0.0.1:8791/api/v1/translate -H "Content-Type: application/json" ^
            -d "{\"text\":\"mid no\",\"targetLanguage\":\"zh-Hans\"}"
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat.bridge import BridgeApp, BridgeServer       # noqa: E402
from dlchat.config import load_config                   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Deadlock 本地翻译桥")
    ap.add_argument("--port", type=int, default=0, help="默认取 config.yaml 的 bridge.port")
    ap.add_argument("--no-warmup", action="store_true", help="跳过模型预热")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    cfg = load_config(args.config)
    port = args.port or cfg.bridge.port
    app = BridgeApp(cfg)
    app.start_loop()

    # 把"到底在读哪两份文件"印出来。设置不生效最常见的原因就是改错了文件
    # （项目目录的 config.yaml 和 %APPDATA% 那份都有，优先级还不一样），
    # 而这件事光看界面是看不出来的。
    from dlchat import paths
    from dlchat.settings import settings_path
    print(f"配置: {paths.default_config_path()}")
    print(f"设置覆盖层: {settings_path()}"
          f"{'' if settings_path().exists() else '（还没有，保存过一次才会出现）'}")

    if not args.no_warmup:
        print("预热翻译后端（首次会把模型载入显存，约 30-40 秒）...")
        t0 = time.perf_counter()
        ok = app.warmup()
        print(f"预热{'完成' if ok else '失败'}，耗时 {time.perf_counter()-t0:.1f}s")

    # 定时把模型钉在显存里：Ollama 空闲就会卸载，重载那一下在游戏占着 GPU 时
    # 很可能超过客户端超时，玩家体感就是"翻译时好时坏"。
    app.start_keepalive()
    print("已启用 keep-alive（每 3 分钟保活一次，避免模型被卸载）")

    server = BridgeServer(app, port)
    try:
        server.start()
    except RuntimeError as e:
        print(f"启动失败: {e}")
        return 1

    h = app.health()
    print(f"\n翻译桥已启动: http://127.0.0.1:{port} 和 http://[::1]:{port}")
    print(f"  引擎: {h['provider']}")
    print(f"  术语: {h['glossary']}")
    print(f"  健康检查: http://127.0.0.1:{port}/api/v1/health")
    print("\n现在启动游戏即可（游戏内 mod 面板会显示已连接）。Ctrl+C 退出。")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n退出中...")
    finally:
        server.stop()
        app.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

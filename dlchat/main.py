"""入口：加载配置 -> 起界面与服务 -> 注册全局热键。

用法：
    python -m dlchat                     # 启动 (源码运行)
    deadlock-tongyi.exe                  # 启动 (打包后)
    python -m dlchat --no-autostart      # 只开界面，不自动开始接收
    python -m dlchat --selftest          # 命令行自检后退出
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QMenu

from . import paths, single_instance
from .app.hotkeys import HotkeyManager
from .app.service import ChatService
from .config import load_config, save_config
from .input.selftest import run_selftest
from .input.space_trigger import MultiTapTrigger
from .ui.input_box import ChatInputBox
from .ui.overlay import ChatOverlay
from .ui.panel import STYLE, MainPanel

logger = logging.getLogger(__name__)


def _setup_logging(level: str) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(logging.FileHandler(
            paths.log_dir() / "dlchat.log", encoding="utf-8"))
    except OSError:
        pass
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )


def _make_output_utf8() -> None:
    """Windows 控制台默认 GBK，重定向时打印 ✅/中文会直接抛 UnicodeEncodeError。

    这里把标准输出/错误改成 UTF-8 + errors=replace：既不会崩，也不会因为
    一个符号打不出来而中断整个自检输出。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def build_app(argv: list[str]) -> tuple[QApplication, MainPanel, ChatService,
                                        HotkeyManager, "MultiTapTrigger | None"]:
    _make_output_utf8()
    parser = argparse.ArgumentParser(description="Deadlock 文字聊天双向翻译")
    parser.add_argument("--no-autostart", action="store_true", help="不自动开始接收")
    parser.add_argument("--selftest", action="store_true", help="只做自检并退出")
    parser.add_argument("--config", default=None,
                        help="指定配置文件；默认用用户目录/程序目录下的 config.yaml")
    parser.add_argument("--allow-multi", action="store_true", help="允许多开（默认单实例）")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    _setup_logging(cfg.ui.log_level)

    if args.selftest:
        report = run_selftest(cfg, check_translator=True)
        # 控制台里用纯 ASCII 标记，避免不同终端编码差异
        print(f"路径: {paths.describe()}\n")
        print(report.to_text(ascii_only=not sys.stdout.isatty()))
        raise SystemExit(0 if report.all_ok else 1)

    # 单实例：两份会抢热键、抢抓屏、抢注入
    if not args.allow_multi and not single_instance.acquire():
        print("已经有一个 通译/Tongyi 在运行了（想多开加 --allow-multi）")
        raise SystemExit(0)

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)          # 全局深色主题：主面板、设置页、对话框统一
    service = ChatService(cfg)
    overlay = ChatOverlay(cfg.display)
    input_box = ChatInputBox(cfg)
    panel = MainPanel(cfg, service, overlay, input_box)

    hotkeys = HotkeyManager()
    ok, failed = hotkeys.register({
        cfg.hotkey.send_box: input_box.summon,
        cfg.hotkey.send_clipboard: service.submit_clipboard,
        cfg.hotkey.toggle_receive: lambda: service.set_paused(not service.paused),
        cfg.hotkey.retranslate_last: service.retranslate_last,
    })
    if failed:
        panel._append_system(f"⚠️ 热键注册失败: {', '.join(failed)}")
    if ok:
        panel._append_system(f"热键: {', '.join(ok)}")

    # 零注入主路径：在游戏聊天框里打完中文，连按 N 次空格触发转换
    trigger: MultiTapTrigger | None = None
    if cfg.input.trigger == "space_taps":
        trigger = MultiTapTrigger(
            key=cfg.input.tap_key,
            taps=cfg.input.taps,
            window_s=cfg.input.tap_window_s,
            on_fire=service.convert_input_line,
            require_focus=(service.game_focused if cfg.input.require_game_focus else None),
            is_busy=lambda: service.converting,
        )
        if trigger.start():
            panel._append_system(
                f"✅ 零注入模式：聊天框里打完中文后，连按 {cfg.input.taps} 次 "
                f"{cfg.input.tap_key.upper()} → 英文进剪贴板（自己 Ctrl+A 再 Ctrl+V）")
        else:
            panel._append_system("⚠️ 连击触发注册失败，可改用 Alt+Y 从剪贴板转换")

    if not args.no_autostart and cfg.app.enable_receive:
        service.start()
    return app, panel, service, hotkeys, trigger


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app, panel, service, hotkeys, trigger = build_app(argv)

    if not panel.cfg.ui.start_minimized:
        panel.show()

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = QSystemTrayIcon(panel)
        menu = QMenu()
        menu.addAction("显示主面板", panel.showNormal)
        menu.addAction("中文输入框", panel.input_box.summon)
        menu.addAction("转换聊天输入行", service.convert_input_line)
        menu.addAction("暂停/恢复", lambda: service.set_paused(not service.paused))
        menu.addAction("退出", app.quit)
        tray.setContextMenu(menu)
        tray.setToolTip("Deadlock 聊天翻译")
        tray.show()

    try:
        return app.exec()
    finally:
        if trigger is not None:
            trigger.stop()
        hotkeys.unregister_all()
        service.stop()
        save_config(panel.cfg)


if __name__ == "__main__":
    raise SystemExit(main())

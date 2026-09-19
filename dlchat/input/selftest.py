"""能力自检：一次跑完，告诉你这台机器上哪条路可用。

先自检再开功能，能省掉大量"为什么没反应"的排查。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    hint: str = ""


@dataclass
class SelfTestReport:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "", hint: str = "") -> None:
        self.checks.append(Check(name, ok, detail, hint))

    @property
    def all_ok(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_text(self, ascii_only: bool = False) -> str:
        """ascii_only=True 时用 [OK]/[X]，避免在 GBK 控制台/重定向时报编码错。"""
        lines = []
        for c in self.checks:
            if ascii_only:
                mark = "[OK]  " if c.ok else "[FAIL]"
            else:
                mark = "✅" if c.ok else "❌"
            line = f"{mark} {c.name}: {c.detail}"
            if not c.ok and c.hint:
                line += f"\n     → {c.hint}"
            lines.append(line)
        ok_count = sum(1 for c in self.checks if c.ok)
        summary = f"通过 {ok_count}/{len(self.checks)} 项"
        if not self.all_ok:
            summary += "（有失败项，见上面的 → 提示）"
        lines.append(summary)
        return "\n".join(lines)


def run_selftest(cfg, *, check_translator: bool = False) -> SelfTestReport:
    """本地能力自检。check_translator=True 时会联网/连本地后端探测一次。"""
    report = SelfTestReport()
    report.add("Python", sys.version_info >= (3, 10),
               f"{sys.version.split()[0]}", "需要 Python 3.10+")

    # 1. 依赖
    for module, hint in (("numpy", "pip install numpy"),
                         ("yaml", "pip install pyyaml"),
                         ("openai", "pip install openai"),
                         ("PySide6", "pip install PySide6")):
        try:
            __import__(module)
            report.add(f"依赖 {module}", True, "已安装")
        except Exception as e:  # noqa: BLE001
            report.add(f"依赖 {module}", False, str(e), hint)

    # 2. 剪贴板
    try:
        import pyperclip

        _ = pyperclip.paste()
        report.add("剪贴板读写", True, "可用")
    except Exception as e:  # noqa: BLE001
        report.add("剪贴板读写", False, str(e), "pip install pyperclip")

    # 3. 全局键盘 / 注入
    try:
        import keyboard  # noqa: F401

        report.add("全局键盘钩子(keyboard)", True, "可用（注入功能依赖它）")
    except Exception as e:  # noqa: BLE001
        report.add("全局键盘钩子(keyboard)", False, str(e), "pip install keyboard")

    # 4. 游戏窗口
    from .injector import TextInjector

    injector = TextInjector(cfg.input)
    hwnd = injector.find_game_window()
    report.add("Deadlock 窗口", hwnd is not None,
               f"已找到 hwnd={hwnd}" if hwnd else "没找到（游戏没开或窗口标题不同）",
               "先启动 Deadlock 再自检；窗口没开时注入会自动降级为复制剪贴板")
    if hwnd:
        report.add("游戏窗口在前台", injector.game_window_focused(),
                   "在前台" if injector.game_window_focused() else "不在前台（切前台可能被系统拦）")

    # 5. 抓帧
    try:
        from ..capture.screen import ScreenGrabber

        grabber = ScreenGrabber()
        ok = grabber.backend != "none"
        report.add("屏幕抓帧", ok, f"后端={grabber.backend}, 屏幕={grabber.size[0]}x{grabber.size[1]}",
                   "dxcam/mss 都不可用；试试 pip install dxcam")
        grabber.close()
    except Exception as e:  # noqa: BLE001
        report.add("屏幕抓帧", False, str(e), "pip install dxcam mss")

    # 6. OCR
    try:
        from ..capture.ocr import create_ocr

        engine = create_ocr(cfg.ocr.backend)
        engine.load()
        report.add("OCR 引擎", True, f"{engine.name} 已加载")
    except Exception as e:  # noqa: BLE001
        report.add("OCR 引擎", False, str(e), "pip install rapidocr")

    # 7. 控制台日志
    from ..sources.console_log import ConsoleLogSource

    log_source = ConsoleLogSource(cfg.console)
    path = log_source._resolve_path()  # noqa: SLF001 - 自检就是来探内部状态的
    report.add("控制台日志", path is not None,
               str(path) if path else "没找到 console.log",
               "用启动项 -con_logfile console.log 启动一次游戏（详见 spike_console_log.py）")

    # 8. 术语表
    from ..chat.glossary import Glossary

    try:
        g = Glossary()
        report.add("术语表", bool(g.terms), f"{len(g.terms)} 术语 / {len(g.phrases)} 整句")
    except Exception as e:  # noqa: BLE001
        report.add("术语表", False, str(e), "python scripts/build_glossary.py")

    # 9. 本地后端 vs 系统代理（这是个很容易踩的坑）
    from ..translate.client import is_local_url

    base_url = cfg.translate.base_url
    if is_local_url(base_url):
        import httpx

        proxies = httpx._utils.get_environment_proxies()  # noqa: SLF001
        proxy_note = f"检测到系统代理 {list(proxies.values())[0]}" if proxies else "无系统代理"
        report.add("本地后端代理绕行", True,
                   f"{base_url} 已强制直连（{proxy_note}）",
                   "开着 v2ray/Clash 时，httpx 会把 localhost 也塞进代理 -> 假的 HTTP 503")
    else:
        report.add("翻译后端地址", True, f"{base_url}（云端，走系统代理）")

    if check_translator:
        from ..chat.glossary import Glossary as _G
        from ..translate.client import ChatTranslator
        import asyncio

        async def _ping():
            tr = ChatTranslator(cfg.translate, _G())
            try:
                return await tr.ping()
            finally:
                await tr.close()

        try:
            ok, detail = asyncio.run(_ping())
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)
        report.add("翻译后端", ok, detail,
                   "确认 Ollama 已启动(ollama serve)或云端 base_url/api_key 填对")

    return report

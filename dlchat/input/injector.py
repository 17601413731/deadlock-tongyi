"""把英文译文送进游戏聊天框。

三级降级（config.input.level）：
- L3：只写剪贴板，你自己按 Ctrl+V（零风险，永远可用）
- L2：自动注入文字到已打开的聊天框，但不发送（推荐默认）
- L1：注入并自动回车发送（最省事，也最容易"以你的名义说话"，默认关）

关键实现细节：
- 逐字注入，每个字符之间留 key_delay_ms（实测很多游戏会吞掉过快合成的按键）
- Enter 前后要留更长间隔，否则"开聊天框"那一下会被忽略
- 注入前保存剪贴板、注入后恢复，避免污染你正在复制的东西
- 找不到游戏窗口就拒绝注入（防止把英文打到别的窗口里）
"""

from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import InputSection

logger = logging.getLogger(__name__)

# 认游戏窗口的正确方式：**进程名 + 窗口类名**，绝不用标题。
# 踩过的坑：用标题包含 "deadlock" 匹配，结果浏览器标签页（"Deadlock 聊天翻译…"）、
# 资源管理器（"deadlock-tongyi"）、PyCharm（"deadlock-tongyi – run.bat"）全都被认成游戏，
# 于是"游戏是否在前台"永远判错：切到桌面时乱 OCR，真在游戏里时三空格又不触发。
GAME_WINDOW_CLASSES = ("sdl_app",)          # Source 2 / SDL3 的游戏窗口类名
GAME_PROCESS_HINTS = ("deadlock", "citadel")  # 进程可执行文件名（小写）


@dataclass
class WindowInfo:
    hwnd: int
    cls: str = ""
    title: str = ""
    pid: int = 0
    process: str = ""


def is_game_window(info: WindowInfo) -> bool:
    """纯判定函数（方便测试）：类名必须像 Source 2 游戏窗口，进程名再确认一次。"""
    if info.cls.strip().lower() not in GAME_WINDOW_CLASSES:
        return False
    proc = (info.process or "").strip().lower()
    if proc:
        return any(h in proc for h in GAME_PROCESS_HINTS)
    # 读不到进程名时退回标题（仅在这种情况下才看标题）
    return any(h in (info.title or "").lower() for h in GAME_PROCESS_HINTS)


@dataclass
class InjectResult:
    ok: bool
    level: str
    detail: str


class TextInjector:
    def __init__(self, cfg: InputSection):
        self.cfg = cfg
        self._keyboard = None
        self._game_hwnd: int | None = None

    # ---------- 基础能力 ----------

    @property
    def keyboard(self):
        if self._keyboard is None:
            import keyboard

            self._keyboard = keyboard
        return self._keyboard

    def clipboard_available(self) -> bool:
        try:
            import pyperclip

            pyperclip.copy("")
            return True
        except Exception:  # noqa: BLE001
            return False

    def get_clipboard(self) -> str:
        try:
            import pyperclip

            return pyperclip.paste() or ""
        except Exception:  # noqa: BLE001
            return ""

    def set_clipboard(self, text: str) -> bool:
        try:
            import pyperclip

            pyperclip.copy(text)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("写剪贴板失败: %s", e)
            return False

    # ---------- 窗口 ----------

    @staticmethod
    def _process_name(pid: int) -> str:
        """拿进程可执行文件名（小写）；拿不到返回空串。"""
        if not pid:
            return ""
        try:
            import win32api
            import win32process

            handle = win32api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            try:
                path = win32process.GetModuleFileNameEx(handle, 0)
            finally:
                win32api.CloseHandle(handle)
            return Path(path).name.lower()
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _window_info(hwnd: int) -> WindowInfo:
        import win32gui
        import win32process

        cls = win32gui.GetClassName(hwnd) or ""
        title = win32gui.GetWindowText(hwnd) or ""
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:  # noqa: BLE001
            pid = 0
        return WindowInfo(hwnd=hwnd, cls=cls, title=title, pid=pid,
                          process=TextInjector._process_name(pid))

    def find_game_window(self, refresh: bool = False) -> int | None:
        """找 Deadlock 主窗口。

        只在第一次（或窗口失效时）枚举，之后走缓存——枚举 + 查进程名每次几十毫秒，
        而"是否在前台"每秒要被问好几次。
        """
        try:
            import win32gui
        except Exception:  # noqa: BLE001
            return None

        if not refresh and self._game_hwnd:
            try:
                if win32gui.IsWindow(self._game_hwnd) and is_game_window(
                        self._window_info(self._game_hwnd)):
                    return self._game_hwnd
            except Exception:  # noqa: BLE001
                pass
            self._game_hwnd = None

        found: list[WindowInfo] = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                info = self._window_info(hwnd)
            except Exception:  # noqa: BLE001
                return True
            if is_game_window(info):
                found.append(info)
            return True

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as e:  # noqa: BLE001
            logger.warning("枚举窗口失败: %s", e)
            return None
        if not found:
            return None
        # 多个候选时优先"标题里就有 Deadlock"的那个（比如同时开着别的 SDL 游戏）
        found.sort(key=lambda i: 0 if "deadlock" in (i.title or "").lower() else 1)
        self._game_hwnd = found[0].hwnd
        logger.info("游戏窗口: hwnd=%s 类名=%r 进程=%s 标题=%r",
                    found[0].hwnd, found[0].cls, found[0].process, found[0].title)
        return self._game_hwnd

    def game_window_focused(self) -> bool:
        try:
            import win32gui

            hwnd = self.find_game_window()
            return bool(hwnd) and win32gui.GetForegroundWindow() == hwnd
        except Exception:  # noqa: BLE001
            return False

    def focus_game_window(self) -> bool:
        try:
            import win32gui

            hwnd = self.find_game_window()
            if not hwnd:
                return False
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.12)
            return win32gui.GetForegroundWindow() == hwnd
        except Exception as e:  # noqa: BLE001
            logger.warning("切前台失败: %s", e)
            return False

    # ---------- 按键 ----------

    def press(self, key: str, delay: float = 0.06) -> None:
        kb = self.keyboard
        kb.press_and_release(key)
        time.sleep(delay)

    def type_text(self, text: str) -> None:
        """逐字写入。用 keyboard.write，非 ASCII 会走 KEYEVENTF_UNICODE。"""
        kb = self.keyboard
        delay = max(0.005, self.cfg.key_delay_ms / 1000.0)
        kb.write(text, delay=delay)

    def clear_chat_input(self) -> None:
        kb = self.keyboard
        kb.press_and_release("ctrl+a")
        time.sleep(0.05)
        kb.press_and_release("delete")
        time.sleep(0.05)

    # ---------- 高层动作 ----------

    def send(self, english: str, level: str | None = None,
             auto_send: bool | None = None) -> InjectResult:
        """把英文送进游戏。level/auto_send 为空时取配置。"""
        level = level or self.cfg.level
        if auto_send is None:
            auto_send = self.cfg.auto_send

        text = (self.cfg.send_prefix or "") + english.strip()
        if not text:
            return InjectResult(False, level, "译文为空，什么都没做")
        if len(text) > self.cfg.max_chars:
            text = text[: self.cfg.max_chars].rstrip()

        if level == "L3":
            ok = self.set_clipboard(text)
            return InjectResult(ok, level,
                                "已复制到剪贴板，请在聊天框按 Ctrl+V" if ok else "写剪贴板失败")

        hwnd = self.find_game_window()
        if hwnd is None:
            self.set_clipboard(text)
            return InjectResult(False, level, "没找到 Deadlock 窗口，已改为复制到剪贴板")

        saved = self.get_clipboard() if self.cfg.keep_clipboard else ""
        try:
            if not self.focus_game_window():
                self.set_clipboard(text)
                return InjectResult(False, level, "游戏窗口切不到前台，已改为复制到剪贴板")

            if level == "L1":
                # L1：我们把聊天框一并打开（游戏在后台时聊天框通常是关的）
                self.press(self.cfg.open_chat_key, delay=0.25)
            if self.cfg.clear_first:
                self.clear_chat_input()
            self.type_text(text)
            if auto_send:
                time.sleep(0.15)
                self.press(self.cfg.open_chat_key, delay=0.1)
            return InjectResult(True, level,
                                "已注入并发送" if auto_send else "已注入到聊天框（未发送）")
        except Exception as e:  # noqa: BLE001
            logger.exception("注入失败")
            self.set_clipboard(text)
            return InjectResult(False, level, f"注入失败({e})，已改为复制到剪贴板")
        finally:
            if self.cfg.keep_clipboard and saved:
                time.sleep(0.1)
                self.set_clipboard(saved)


def show_console_hint() -> None:
    """把当前进程设为 DPI 感知，避免多屏/缩放下坐标错位。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

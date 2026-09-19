"""全局热键注册（keyboard 库）。

回调在 keyboard 自己的线程上触发，所以回调里只做"入队/发信号"这类非阻塞动作，
真正的翻译与注入都在 ChatService 的工作线程里做。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self) -> None:
        self._keyboard = None
        self._registered: list[str] = []

    def register(self, mapping: dict[str, Callable[[], None]]) -> tuple[list[str], list[str]]:
        """注册 {热键: 回调}。返回 (成功列表, 失败列表)。"""
        try:
            import keyboard
        except Exception as e:  # noqa: BLE001
            logger.error("无法导入 keyboard，热键不可用: %s", e)
            return [], list(mapping.keys())

        self._keyboard = keyboard
        ok: list[str] = []
        failed: list[str] = []
        for combo, callback in mapping.items():
            if not combo:
                continue
            try:
                keyboard.add_hotkey(combo, _wrap(callback), suppress=False)
                ok.append(combo)
            except Exception as e:  # noqa: BLE001
                logger.error("热键 %s 注册失败: %s", combo, e)
                failed.append(combo)
        if ok:
            logger.info("热键已注册: %s", ", ".join(ok))
        self._registered = ok
        return ok, failed

    def unregister_all(self) -> None:
        if self._keyboard is not None:
            try:
                self._keyboard.unhook_all_hotkeys()
            except Exception as e:  # noqa: BLE001
                logger.warning("注销热键失败: %s", e)
        self._registered = []

    @property
    def registered(self) -> list[str]:
        return list(self._registered)


def _wrap(callback: Callable[[], None]) -> Callable[[], None]:
    def _inner() -> None:
        try:
            callback()
        except Exception:  # noqa: BLE001
            logger.exception("热键回调异常")

    return _inner

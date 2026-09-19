"""连击触发：在游戏聊天框里连按 N 次同一个键（默认空格）来触发"转换"。

为什么用这个而不是热键：你打完中文后手就在空格上，不用离开打字姿势；
而且工具**只监听键盘**，绝不注入任何按键——这是"零注入"方案的关键。

两个必须处理的细节：
1. 空格在游戏里是跳跃键。只有聊天框打开时空格才是"打字"，所以触发时要求
   游戏窗口在前台（config: require_game_focus）。聊天框没开时连按空格 = 跳三下，
   不会误触发，因为我们同时会检查 OCR 到的输入行里确实有文字。
2. 三次空格之间有时间窗（默认 1.5 秒），超时重新计数；中途敲了别的键也清零。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class MultiTapTrigger:
    def __init__(self, key: str = "space", taps: int = 3, window_s: float = 1.5,
                 on_fire: Callable[[], None] | None = None,
                 require_focus: Callable[[], bool] | None = None,
                 is_busy: Callable[[], bool] | None = None,
                 on_ignore: Callable[[str], None] | None = None):
        self.key = (key or "space").strip().lower()
        self.taps = max(2, int(taps))
        self.window_s = max(0.3, float(window_s))
        self.on_fire = on_fire
        self.require_focus = require_focus
        self.is_busy = is_busy
        # 检测到连击但被前台/忙碌条件否掉时回调，用来给用户反馈。
        # 没有它的话表现就是"按了没反应"，用户根本不知道为什么（踩过这个坑）。
        self.on_ignore = on_ignore
        self._times: list[float] = []
        self._lock = threading.Lock()
        self._keyboard = None
        self._hooked_key = None
        self._hooked_any = None
        self.armed = False
        self.fires = 0

    # ---------- 生命周期 ----------

    def start(self) -> bool:
        try:
            import keyboard
        except Exception as e:  # noqa: BLE001
            logger.error("无法导入 keyboard，连击触发不可用: %s", e)
            return False

        self._keyboard = keyboard
        try:
            # 任何键按下都重置计数：避免"打了一半的字 + 空格空格空格"这种误判
            self._hooked_any = keyboard.on_press(self._on_any_press, suppress=False)
            self._hooked_key = keyboard.on_release_key(
                self.key, self._on_target_release, suppress=False)
        except Exception as e:  # noqa: BLE001
            logger.error("连击触发注册失败: %s", e)
            return False

        self.armed = True
        logger.info("连击触发已就绪：连按 %d 次 %s（%.1fs 内）",
                    self.taps, self.key, self.window_s)
        return True

    def stop(self) -> None:
        self.armed = False
        if self._keyboard is not None:
            try:
                self._keyboard.unhook_all()
            except Exception:  # noqa: BLE001
                pass
        self._hooked_key = self._hooked_any = None
        with self._lock:
            self._times.clear()

    # ---------- 内部 ----------

    def _on_any_press(self, event) -> None:
        """任何键：若是目标键则计数，否则清零。"""
        name = (getattr(event, "name", "") or "").lower()
        if name != self.key:
            self._reset()
            return
        self._register_tap()

    def _on_target_release(self, _event) -> None:
        pass  # 计数在按下时做，这里只是占位（便于将来做"按住"手势）

    def _reset(self) -> None:
        with self._lock:
            self._times.clear()

    def _register_tap(self) -> None:
        if not self.armed:
            return
        now = time.monotonic()
        with self._lock:
            self._times = [t for t in self._times if now - t <= self.window_s]
            self._times.append(now)
            count = len(self._times)
            if count < self.taps:
                return
            self._times.clear()

        if self.require_focus is not None:
            try:
                if not self.require_focus():
                    logger.info("检测到连按 %d 次 %s，但游戏不在前台 -> 忽略", self.taps, self.key)
                    self._notify_ignore("游戏不在前台")
                    return
            except Exception:  # noqa: BLE001
                return
        if self.is_busy is not None:
            try:
                if self.is_busy():
                    logger.debug("连击触发忽略：上一次转换还在进行")
                    self._notify_ignore("上一次转换还在进行")
                    return
            except Exception:  # noqa: BLE001
                return

        self.fires += 1
        logger.info("检测到连按 %d 次 %s -> 触发转换", self.taps, self.key)
        if self.on_fire is not None:
            try:
                self.on_fire()
            except Exception:  # noqa: BLE001
                logger.exception("连击触发回调异常")

    def _notify_ignore(self, reason: str) -> None:
        if self.on_ignore is None:
            return
        try:
            self.on_ignore(reason)
        except Exception:  # noqa: BLE001
            pass

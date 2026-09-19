"""单实例保护：桌面端常驻程序最怕开两份。

两份会抢同一个全局热键、同时往游戏里注入、同时抓屏 OCR。用 Windows 命名互斥体
（CreateMutexW）挡掉第二个实例，并且把已运行窗口拉到前台。

不用 Qt 实现是为了能在创建 QApplication 之前就判断（早退出，不闪窗口）。
"""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\deadlock-tongyi-single-instance"
_mutex_handle = None


def acquire(name: str = MUTEX_NAME) -> bool:
    """拿到单实例锁返回 True；已有实例在跑返回 False。"""
    global _mutex_handle
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, name)
        last_error = kernel32.GetLastError()
        if not handle:
            logger.warning("创建互斥体失败，跳过多开检查")
            return True
        if last_error == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle          # 故意不释放：进程退出时系统自动回收
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("单实例检查异常（按允许多开处理）: %s", e)
        return True


def release() -> None:
    global _mutex_handle
    if _mutex_handle:
        try:
            ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:  # noqa: BLE001
            pass
        _mutex_handle = None

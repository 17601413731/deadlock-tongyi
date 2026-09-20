"""单实例保护：常驻进程最怕开两份。

现在的用途是**启动器**（`dlchat/launcher.py`）：Steam 启动项会在点"开始游戏"时被调起来，
连点两下或多开一个 Steam 窗口就会起两份启动器 —— 两份会抢同一个桥端口（8791），
后起的那份只会拿到"端口被占用"，玩家看到的是"桥起不来"。

用 Windows 命名互斥体（CreateMutexW）挡掉第二个实例。不用 Qt 实现（也不需要任何
第三方库）是为了在加载重依赖之前就能判断，早退出。

历史上它还负责"把已运行的桌面窗口拉到前台"，那段随桌面版一起在 2026-09-20 删除。
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

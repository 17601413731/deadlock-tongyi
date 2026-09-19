"""启动器入口（打包用）：无控制台窗口，给 Steam 启动选项用。

`%command%` 会被 Steam 原样附加在这后面，所以这里**不要**解析/改写参数列表，
直接交给 dlchat.launcher.main（它自己用 argparse 兼容未知参数之外的部分）。
"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()      # 打包后防止子进程重复启动
    from dlchat.launcher import main

    sys.exit(main())

"""主程序入口（打包用）：无控制台窗口。"""

from __future__ import annotations

import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()      # 打包后防止子进程重复启动
    from dlchat.main import main

    sys.exit(main())

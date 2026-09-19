#!/usr/bin/env python
"""离屏冒烟测试：把界面和服务都构造一遍，验证信号接线没问题，但不弹窗口。

用法：
    python scripts/smoke_gui.py
（内部会设置 QT_QPA_PLATFORM=offscreen，所以不会打扰你正在玩的游戏）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer                       # noqa: E402
from PySide6.QtWidgets import QApplication              # noqa: E402

from dlchat.app.hotkeys import HotkeyManager            # noqa: E402
from dlchat.app.service import ChatService              # noqa: E402
from dlchat.config import load_config                   # noqa: E402
from dlchat.ui.input_box import ChatInputBox            # noqa: E402
from dlchat.ui.overlay import ChatOverlay               # noqa: E402
from dlchat.ui.panel import MainPanel                   # noqa: E402
from dlchat.ui.region_picker import RegionPicker        # noqa: E402


def main() -> int:
    cfg = load_config("config.yaml")
    app = QApplication(sys.argv)

    service = ChatService(cfg)
    overlay = ChatOverlay(cfg.display)
    box = ChatInputBox(cfg)
    panel = MainPanel(cfg, service, overlay, box)
    picker = RegionPicker()
    hotkeys = HotkeyManager()   # 不真注册，只构造

    print("构造完成：ChatService / ChatOverlay / ChatInputBox / MainPanel / RegionPicker")

    # 用假数据跑一遍界面更新路径（不联网、不抓屏）
    from dlchat.chat.line import ChatLine

    overlay.show_line("he's low, dive him", "他残血，上")
    panel._on_line_received(ChatLine(text="he's low, dive him", speaker="Bob",
                                     source="ocr", confidence=0.93))
    panel._on_line_translated(ChatLine(text="he's low, dive him", speaker="Bob",
                                       translated="他残血，上"))
    panel._on_status("离屏冒烟测试")
    panel._on_error("这是测试错误，可忽略")
    box.summon()
    box.hide()
    picker.start()
    picker.hide()
    print("界面更新路径 OK（含悬浮窗、聊天记录、输入小窗、区域框选）")

    QTimer.singleShot(150, app.quit)
    app.exec()
    print("离屏冒烟测试通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

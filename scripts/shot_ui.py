#!/usr/bin/env python
r"""把界面离屏渲染成 PNG，用来检查/展示当前 UI（不弹窗口、不打扰游戏）。

用法：
    python scripts/shot_ui.py            # 输出到 %APPDATA%\deadlock-tongyi\ui_shots\
    python scripts/shot_ui.py --out DIR
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 默认离屏（不打扰游戏），但离屏平台没有字体（中文会变方框）。
# 加 --real-font 用真实 Windows 平台渲染：窗口不 show()，只 grab()，不会弹出来。
if "--real-font" not in sys.argv:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt, QTimer                        # noqa: E402
from PySide6.QtWidgets import QApplication                   # noqa: E402

from dlchat import paths                                     # noqa: E402
from dlchat.app.service import ChatService                   # noqa: E402
from dlchat.chat.line import ChatLine                        # noqa: E402
from dlchat.config import load_config                        # noqa: E402
from dlchat.ui.input_box import ChatInputBox                 # noqa: E402
from dlchat.ui.overlay import ChatOverlay                    # noqa: E402
from dlchat.ui.panel import STYLE, MainPanel                  # noqa: E402

FAKE_IN = [
    ChatLine(text="mid no", speaker="小懒虫睡觉觉", source="ocr", confidence=0.94,
             translated="中路没人"),
    ChatLine(text="he's low, dive him", speaker="比狗勾还狗勾", source="ocr",
             confidence=0.91, translated="他残血，上"),
    ChatLine(text="need help with urn pls", speaker="Kevin", source="ocr",
             confidence=0.97, translated="来个人帮忙送魂瓮"),
    ChatLine(text="gg wp", speaker="Bob", source="console", translated="打得不错"),
    ChatLine(text="7 is smurfing", speaker="Dave", source="ocr", confidence=0.88,
             translated="柒在开小号虐菜"),
]
FAKE_OUT = ChatLine(text="中路没人，我去送魂瓮", translated="mid is open, i'll take urn",
                    target="self", source="input")


def main() -> int:
    ap = argparse.ArgumentParser(description="离屏渲染 UI 截图")
    ap.add_argument("--out", default="")
    ap.add_argument("--real-font", action="store_true",
                    help="用真实 Windows 平台渲染（有中文字体，窗口不会显示出来）")
    args = ap.parse_args()
    out_dir = Path(args.out) if args.out else paths.output_dir() / "ui_shots"
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)      # 和 main.py 一致：全局深色主题
    service = ChatService(cfg)
    overlay = ChatOverlay(cfg.display)
    box = ChatInputBox(cfg)
    panel = MainPanel(cfg, service, overlay, box)
    panel.resize(900, 560)

    # 灌入假数据，让界面处于"运行中"的样子
    panel._on_status("运行中 · 来源: ocr · OCR 运行中（rapidocr / dxcam / 整块检测）")
    panel._append_system("✅ 零注入模式：聊天框里打完中文后，连按 3 次 SPACE → 英文进剪贴板")
    panel._append_system("热键: alt+t, alt+y, alt+g, alt+r")
    for line in FAKE_IN:
        panel._on_line_received(line)
        panel._on_line_translated(line)
    panel._on_outbound(FAKE_OUT)

    def shoot():
        if not args.real_font:
            panel.show()          # 离屏平台需要 show 才有尺寸
        app.processEvents()
        p1 = out_dir / "01_main_panel.png"
        panel.grab().save(str(p1))
        print(f"主面板     -> {p1}  ({panel.width()}x{panel.height()})")

        overlay.show_line("he's low, dive him", "他残血，上")
        overlay.show_line("need help with urn pls", "来个人帮忙送完瓮")
        overlay.show_line("gg wp", "打得不错")
        app.processEvents()
        p2 = out_dir / "02_overlay.png"
        overlay.grab().save(str(p2))
        print(f"游戏内悬浮窗 -> {p2}  ({overlay.width()}x{overlay.height()})")

        box.summon()
        box._edit.setText("他残血，我去追")
        app.processEvents()
        p3 = out_dir / "03_input_box.png"
        box.grab().save(str(p3))
        print(f"中文输入小窗 -> {p3}  ({box.width()}x{box.height()})")

        # 设置对话框
        from dlchat.ui.settings import SettingsDialog

        dlg = SettingsDialog(cfg, None)
        if not args.real_font:
            dlg.show()
        app.processEvents()
        p4 = out_dir / "04_settings.png"
        dlg.grab().save(str(p4))
        print(f"设置对话框 -> {p4}  ({dlg.width()}x{dlg.height()})")
        dlg.close()

        panel.hide()
        overlay.hide()
        box.hide()
        app.quit()

    QTimer.singleShot(300, shoot)
    app.exec()
    print(f"\n都在 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

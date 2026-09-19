"""主面板：状态、双语聊天记录、发送区、自检/框选入口。"""

from __future__ import annotations

import html

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..chat.line import ChatLine
from ..config import Config, save_config
from .. import paths
from ..input.selftest import run_selftest
from ..app.service import ChatService
from .input_box import ChatInputBox
from .overlay import ChatOverlay
from .region_picker import RegionPicker

STYLE = """
QMainWindow, QDialog, QWidget { background: #101218; color: #e6e9ef; }
QLabel { color: #e6e9ef; background: transparent; }
QLabel#title { font-size: 16px; font-weight: 700; color: #f5f7fa; }
QLabel#status { color: #9aa4b2; }
QTextEdit { background: #161a24; border: 1px solid #262c3a; border-radius: 8px; padding: 6px; }
QLineEdit { background: #1b2030; border: 1px solid #2b3244; border-radius: 8px; padding: 7px 10px; }
QPushButton { background: #23304a; border: 1px solid #33405e; border-radius: 8px; padding: 7px 13px; }
QPushButton:hover { background: #2c3d5e; }
QPushButton:disabled { background: #1a1f2b; color: #5c6577; border-color: #252b38; }
QPushButton#primary { background: #2f6fd0; border-color: #3b82f6; font-weight: 600; }
QPushButton#primary:hover { background: #3b82f6; }
QComboBox { background: #1b2030; border: 1px solid #2b3244; border-radius: 8px; padding: 5px 8px; }
QComboBox:disabled { color: #5c6577; }
QComboBox QAbstractItemView { background: #1b2030; color: #e6e9ef; selection-background-color: #2f6fd0; }
QCheckBox { color: #cfd6e2; }
QSpinBox, QDoubleSpinBox { background: #1b2030; border: 1px solid #2b3244; border-radius: 8px; padding: 5px 8px; }
QTabWidget::pane { border: 1px solid #262c3a; border-radius: 8px; background: #141822; }
QTabBar::tab { background: #1b2030; color: #9aa4b2; padding: 7px 16px; border: 1px solid #262c3a;
               border-bottom: none; border-top-left-radius: 8px; border-top-right-radius: 8px; }
QTabBar::tab:selected { background: #2f6fd0; color: #ffffff; }
QScrollBar:vertical { background: #141822; width: 10px; }
QScrollBar::handle:vertical { background: #33405e; border-radius: 5px; }
"""


class MainPanel(QMainWindow):
    send_requested = Signal(str, bool)   # 中文, 是否自动发送

    def __init__(self, cfg: Config, service: ChatService, overlay: ChatOverlay,
                 input_box: ChatInputBox):
        super().__init__()
        self.cfg = cfg
        self.service = service
        self.overlay = overlay
        self.input_box = input_box
        self.setWindowTitle("通译 · Deadlock 聊天翻译")
        self.setStyleSheet(STYLE)
        self.resize(880, 560)
        self._build()
        self._wire()
        self._update_buttons()
        self.first_run_checks()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("💬 通译 · Deadlock 聊天翻译")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch()
        self.status = QLabel("未启动")
        self.status.setObjectName("status")
        head.addWidget(self.status)
        layout.addLayout(head)

        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setFont(QFont("Microsoft YaHei", 10))
        layout.addWidget(self.history, 1)
        # 发送区（功能2）
        send_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText(
            "也可以直接在这里打中文回车；或在游戏聊天框打完后连按 3 次空格")
        self.out_edit.returnPressed.connect(self._on_send)
        send_row.addWidget(self.out_edit, 1)
        self.level_box = QComboBox()
        self.level_box.addItems(["L3 只复制", "L2 注入不发送", "L1 注入并发送"])
        self.level_box.setCurrentIndex({"L3": 0, "L2": 1, "L1": 2}.get(self.cfg.input.level, 1))
        self.level_box.setToolTip("仅当取消勾选「零注入」时生效")
        send_row.addWidget(self.level_box)
        self.zero_inject_box = QCheckBox("零注入")
        self.zero_inject_box.setChecked(self.cfg.input.handoff == "clipboard")
        self.zero_inject_box.setToolTip(
            "勾选=工具只截屏+监听键盘：英文进剪贴板，你自己 Ctrl+A 再 Ctrl+V\n"
            "取消=允许工具模拟按键自动注入（有反作弊风险面）")
        self.zero_inject_box.stateChanged.connect(self._sync_inject_controls)
        send_row.addWidget(self.zero_inject_box)
        self.readonly_box = QCheckBox("只读")
        self.readonly_box.setChecked(self.cfg.app.read_only)
        self.readonly_box.setToolTip("只读：连接收方向的自动操作也一起停掉，绝不碰游戏输入")
        send_row.addWidget(self.readonly_box)
        self.send_btn = QPushButton("翻译并交付")
        self.send_btn.setObjectName("primary")
        self.send_btn.clicked.connect(self._on_send)
        send_row.addWidget(self.send_btn)
        layout.addLayout(send_row)

        # 控制按钮
        ctrl = QHBoxLayout()
        self.toggle_btn = QPushButton("开始接收")
        self.toggle_btn.setObjectName("primary")
        self.toggle_btn.clicked.connect(self._on_toggle)
        ctrl.addWidget(self.toggle_btn)
        self.pause_btn = QPushButton("暂停")
        self.pause_btn.clicked.connect(self._on_pause)
        ctrl.addWidget(self.pause_btn)
        pick_btn = QPushButton("框选聊天区域")
        pick_btn.clicked.connect(self._on_pick_region)
        ctrl.addWidget(pick_btn)
        pick_input_btn = QPushButton("校准输入行")
        pick_input_btn.setToolTip("聊天框打开、里面有你打的中文时点这个：看看 OCR 读得对不对")
        pick_input_btn.clicked.connect(self._on_calibrate_input)
        ctrl.addWidget(pick_input_btn)
        pick_input_region_btn = QPushButton("框选输入行")
        pick_input_region_btn.setToolTip("聊天框打开时，把「To (ALL): 你打的字」这一条框出来")
        pick_input_region_btn.clicked.connect(self._on_pick_input_region)
        ctrl.addWidget(pick_input_region_btn)
        test_btn = QPushButton("自检")
        test_btn.clicked.connect(self._on_selftest)
        ctrl.addWidget(test_btn)
        settings_btn = QPushButton("设置")
        settings_btn.setObjectName("primary")
        settings_btn.setToolTip("所有可调项都在这里，保存后写回 config.yaml")
        settings_btn.clicked.connect(self._open_settings)
        ctrl.addWidget(settings_btn)
        clear_btn = QPushButton("清屏")
        clear_btn.clicked.connect(self.history.clear)
        ctrl.addWidget(clear_btn)
        ctrl.addStretch()
        layout.addLayout(ctrl)
        self._sync_inject_controls()

    def _wire(self) -> None:
        self.service.status_changed.connect(self._on_status)
        self.service.line_received.connect(self._on_line_received)
        self.service.line_translated.connect(self._on_line_translated)
        self.service.outbound_translated.connect(self._on_outbound)
        self.service.injection_done.connect(self._on_injected)
        self.service.error_occurred.connect(self._on_error)
        self.service.backend_status.connect(self._on_backend)
        self.input_box.submitted.connect(self._on_box_submitted)

    # ---------- 槽 ----------

    def _on_toggle(self) -> None:
        if self.service.running:
            self.service.stop()
        else:
            self.service.start()
        QTimer.singleShot(120, self._update_buttons)

    def _on_pause(self) -> None:
        self.service.set_paused(not self.service.paused)
        self.pause_btn.setText("恢复" if self.service.paused else "暂停")

    def _on_pick_region(self) -> None:
        self._pick_target = "ocr"
        self.picker = RegionPicker()
        self.picker.picked.connect(self._on_region_picked)
        self.picker.start()

    def _on_pick_input_region(self) -> None:
        """框选聊天输入行（"To (ALL): 你打的字"那一条）。"""
        self._pick_target = "input"
        self.picker = RegionPicker()
        self.picker.picked.connect(self._on_region_picked)
        self.picker.start()

    def _on_region_picked(self, region: list) -> None:
        if getattr(self, "_pick_target", "ocr") == "input":
            self.cfg.input.input_region = region
            self.cfg.input.input_region_calibrated = True
            save_config(self.cfg)
            self._append_system(f"聊天输入行区域已更新为 {region}（已写入 config.yaml）")
            self._on_calibrate_input()
            return
        self.cfg.ocr.region = region
        self.cfg.ocr.region_calibrated = True
        save_config(self.cfg)
        self._append_system(f"聊天区域已更新为 {region}（已写入 config.yaml）")

    def _on_selftest(self) -> None:
        self._append_system("正在自检（含翻译后端连通性），稍等...")
        report = run_selftest(self.cfg, check_translator=False)
        self._append_system(report.to_text().replace("\n", "<br>"))
        self.service.ping_backend()

    def _on_calibrate_input(self) -> None:
        """校准输入行：抓一次输入行区域并显示 OCR 结果。"""
        self._append_system("正在读取聊天输入行（聊天框要打开、里面有字）...")
        detail = self.service.calibrate_input_line()
        self._append_system(html.escape(detail).replace("\n", "<br>"))

    def _open_settings(self) -> None:
        """设置对话框：保存后写回 config.yaml，并按需重启接收服务。"""
        from .settings import SettingsDialog

        was_running = self.service.running
        dialog = SettingsDialog(self.cfg, self)
        if not dialog.exec():
            return

        # 界面控件同步成新配置
        self.zero_inject_box.setChecked(self.cfg.input.handoff == "clipboard")
        self.readonly_box.setChecked(self.cfg.app.read_only)
        self.level_box.setCurrentIndex(
            {"L3": 0, "L2": 1, "L1": 2}.get(self.cfg.input.level, 1))
        self._sync_inject_controls()
        self._append_system(f"✅ 设置已保存到 {paths.default_config_path()}")

        if was_running:
            self.service.stop()
            QTimer.singleShot(400, self._restart_service)
            self._append_system("正在按新配置重启接收服务...")

    def _restart_service(self) -> None:
        self.service.start()
        self._update_buttons()

    def _sync_inject_controls(self) -> None:
        """零注入勾选时，禁用注入等级下拉（那个只对注入路径有意义）。"""
        zero = self.zero_inject_box.isChecked()
        self.level_box.setEnabled(not zero and not self.readonly_box.isChecked())

    def _on_readonly_toggled(self) -> None:
        self._sync_inject_controls()

    def _on_backend(self, ok: bool, detail: str) -> None:
        mark = "✅" if ok else "❌"
        self._append_system(f"{mark} 翻译后端: {html.escape(detail)}")

    def _on_status(self, text: str) -> None:
        # 状态栏空间有限，太长会顶到窗口边缘
        self.status.setText(text if len(text) <= 46 else text[:45] + "…")
        self.status.setToolTip(text)
        self._update_buttons()

    def _on_line_received(self, line: ChatLine) -> None:
        src = {"console": "控制台", "ocr": "OCR"}.get(line.source, line.source)
        self._append_system(f"📥 [{src}] {html.escape(line.display_original())}")

    def _on_line_translated(self, line: ChatLine) -> None:
        if not line.translated:
            return
        who = html.escape(line.speaker or "?")
        self.history.append(
            f'<div style="margin:6px 0">'
            f'<span style="color:#7f8a9a">{who}: </span>'
            f'<span style="color:#8d99ae">{html.escape(line.text)}</span><br>'
            f'<span style="color:#63b3ed;font-weight:600">{html.escape(line.translated)}</span>'
            f'</div>'
        )
        self.history.verticalScrollBar().setValue(
            self.history.verticalScrollBar().maximum())
        if self.cfg.display.overlay and line.lang != "zh":
            self.overlay.show_line(line.text, line.translated)

    def _on_outbound(self, line: ChatLine) -> None:
        self.history.append(
            f'<div style="margin:6px 0">'
            f'<span style="color:#f6ad55">我说: </span>'
            f'<span style="color:#8d99ae">{html.escape(line.text)}</span><br>'
            f'<span style="color:#68d391;font-weight:600">{html.escape(line.translated)}</span>'
            f'</div>'
        )

    def _on_injected(self, result) -> None:
        mark = "✅" if result.ok else "⚠️"
        self._append_system(f"{mark} {html.escape(result.detail)}")

    def _on_error(self, text: str) -> None:
        self._append_system(f'<span style="color:#fc8181">❌ {html.escape(text)}</span>')

    def _on_box_submitted(self, text: str, auto_send: bool) -> None:
        self.service.submit_text(text, auto_send)

    def _on_send(self) -> None:
        text = self.out_edit.text().strip()
        if not text:
            return
        self.out_edit.clear()
        self.service.submit_text(text, self._auto_send())

    # ---------- 辅助 ----------

    def _auto_send(self) -> bool:
        idx = self.level_box.currentIndex()
        self.cfg.input.level = ["L3", "L2", "L1"][idx]
        self.cfg.input.handoff = "clipboard" if self.zero_inject_box.isChecked() else "inject"
        self.cfg.app.read_only = self.readonly_box.isChecked()
        self._sync_inject_controls()
        return idx == 2

    def _append_system(self, text: str) -> None:
        self.history.append(f'<div style="color:#6b7480;font-size:11px">{text}</div>')
        self.history.verticalScrollBar().setValue(
            self.history.verticalScrollBar().maximum())

    def _update_buttons(self) -> None:
        running = self.service.running
        self.toggle_btn.setText("停止接收" if running else "开始接收")

    def first_run_checks(self) -> None:
        """启动时检查"还没校准"这类会让功能看起来失灵的状态，直接说清楚。"""
        if self.cfg.source.kind == "ocr" and not self.cfg.ocr.region_calibrated:
            self._append_system(
                '⚠️ <b>聊天区域还没校准</b>：现在的默认区域可能框到桌面内容，'
                '会把文件名/命令行当成聊天翻译。'
                '请切到游戏、等有人打字时点「框选聊天区域」。')
        if self.cfg.app.enable_send and not self.cfg.input.input_region_calibrated:
            self._append_system(
                '⚠️ <b>聊天输入行还没校准</b>：进游戏按回车打开聊天框、打几个中文字，'
                '然后点「框选输入行」圈住 <code>To (ALL): 你打的字</code> 那一行。')
        if self.cfg.source.require_game_focus:
            self._append_system(
                'ℹ️ 已开启"只在游戏前台时识别"：切到桌面/其他窗口时不会翻译任何东西。')

    def closeEvent(self, event) -> None:  # noqa: N802
        self.service.stop()
        self.overlay.close()
        save_config(self.cfg)
        event.accept()

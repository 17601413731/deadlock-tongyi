"""设置对话框：把 config.yaml 里所有常用项做成界面。

设计原则：
- 只写"改了有意义"的项，改完点保存就写回 config.yaml 并重启接收服务
- 区域类字段（聊天区/输入行）配「框选」按钮，避免手填归一化坐标
- 翻译后端配「测试连接」，免得配错了不知道
"""

from __future__ import annotations

import html
import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..config import Config, save_config

logger = logging.getLogger(__name__)

MODEL_PRESETS = [
    "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
    "hf.co/tencent/Hy-MT2-7B-GGUF:Q8_0",
    "kaelri/hy-mt2:1.8b-q8_0",
    "kaelri/hy-mt2:1.8b-q4_K_M",
    "deepseek-v4-flash",
    "qwen-mt-flash",
]
BACKEND_PRESETS = [
    "http://localhost:11434/v1",
    "https://api.deepseek.com/v1",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
]


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("设置")
        self.setMinimumSize(680, 560)
        self._w: dict[str, object] = {}
        self._build()

    # ---------- 构建 ----------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._tab_source(), "来源")
        tabs.addTab(self._tab_ocr(), "OCR")
        tabs.addTab(self._tab_translate(), "翻译")
        tabs.addTab(self._tab_display(), "显示")
        tabs.addTab(self._tab_input(), "输入")
        tabs.addTab(self._tab_hotkey(), "热键")
        root.addWidget(tabs, 1)

        hint = QLabel(f"配置文件：{paths.default_config_path()}")
        hint.setStyleSheet("color:#8a93a5; font-size:11px;")
        hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(hint)

        buttons = QDialogButtonBox()
        open_btn = buttons.addButton("打开配置目录", QDialogButtonBox.ButtonRole.ActionRole)
        open_btn.clicked.connect(self._open_config_dir)
        test_btn = buttons.addButton("测试翻译后端", QDialogButtonBox.ButtonRole.ActionRole)
        test_btn.clicked.connect(self._test_backend)
        buttons.addButton("保存并应用", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- 各页 ----

    def _tab_source(self) -> QWidget:
        w, form = self._page()
        self._check(form, "source.require_game_focus", "只在游戏窗口前台时抓屏识别",
                    "强烈建议保持勾选：否则切到桌面时会把文件名/命令行当聊天翻译")
        self._combo(form, "source.kind", "接收来源", ["ocr", "console"],
                    "ocr=屏幕识别（万金油）；console=控制台日志（更准，但要看聊天是否写日志）")
        self._check(form, "source.fallback_to_ocr", "来源启动失败时自动改用 OCR")
        self._check(form, "app.enable_receive", "启用接收（英文→中文）")
        self._check(form, "app.enable_send", "启用发送（中文→英文）")
        self._line(form, "app.my_name", "我的游戏名（用于跳过自己的消息）", "留空则不跳过")
        self._line(form, "app.blocklist", "屏蔽词（逗号分隔）", "命中的消息不翻译",
                   transform="list")
        self._line(form, "console.game_dir", "Deadlock game 目录", "留空=自动探测")
        self._line(form, "console.log_path", "console.log 路径", "留空=自动探测")
        return w

    def _tab_ocr(self) -> QWidget:
        w, form = self._page()
        self._combo(form, "ocr.backend", "OCR 引擎", ["rapidocr", "windows"],
                    "rapidocr=离线自带模型（推荐）；windows=系统内建")
        self._region_row(form, "ocr.region", "聊天区域", "别人聊天文字出现的位置")
        self._spin(form, "ocr.interval_ms", "抓帧间隔(ms)", 200, 5000, 100)
        self._dspin(form, "ocr.change_threshold", "变化阈值", 0.0, 0.2, 0.005, 3,
                    "画面变化小于它就不跑 OCR，省 CPU")
        self._dspin(form, "ocr.min_confidence", "最低置信度", 0.1, 0.99, 0.05, 2)
        self._check(form, "ocr.detect", "整块检测（慢但区域未知时能用）",
                    "关掉=按行切条只识别（要求行高对得上）")
        self._spin(form, "ocr.rows", "切条行数", 1, 20, 1, "仅在关掉整块检测时生效")
        self._check(form, "ocr.filter_hud", "过滤 HUD 数字/界面词")
        self._spin(form, "ocr.upscale", "放大倍数", 1, 4, 1, "小字识别率关键")
        self._check(form, "ocr.invert", "反色预处理")
        self._spin(form, "ocr.max_lines", "每次最多取几行", 1, 20, 1)
        return w

    def _tab_translate(self) -> QWidget:
        w, form = self._page()
        self._combo(form, "translate.base_url", "后端地址", BACKEND_PRESETS, editable=True)
        self._line(form, "translate.api_key", "API Key", "本地 Ollama 填 none 即可",
                   password=True)
        self._combo(form, "translate.model", "模型", MODEL_PRESETS, editable=True,
                    tip="7B=质量最好；1.8B=更快")
        self._dspin(form, "translate.temperature", "温度", 0.0, 1.5, 0.1, 2,
                    "短句建议 0，否则模型爱加解释")
        self._spin(form, "translate.max_tokens", "最大输出 token", 32, 2048, 32)
        self._dspin(form, "translate.timeout_s", "超时(秒)", 1.0, 120.0, 1.0, 1)
        self._spin(form, "translate.context_window", "上下文轮数", 0, 10, 1,
                   "短句消歧最有效；云端单轮模型请设 0")
        self._check(form, "translate.glossary", "注入术语表（只注入本句命中的）")
        self._check(form, "translate.exact_match", "整句短语直译（聊天轮盘零延迟）")
        self._spin(form, "translate.max_glossary_terms", "最多注入术语数", 0, 30, 1)
        return w

    def _tab_display(self) -> QWidget:
        w, form = self._page()
        self._check(form, "display.overlay", "在游戏内显示悬浮译文")
        self._combo(form, "display.anchor", "悬浮窗位置", ["chat", "bottom", "custom"],
                    "chat=贴聊天区 / bottom=底部居中 / custom=自定义像素")
        self._line(form, "display.custom_pos", "自定义位置(x,y)", "仅在 custom 时生效",
                   transform="intlist")
        self._combo(form, "display.mode", "显示内容", ["replace", "both"],
                    "replace=只显示中文 / both=英文原文+中文")
        self._line(form, "display.font_family", "字体", "")
        self._spin(form, "display.font_size", "字号", 9, 32, 1)
        self._dspin(form, "display.opacity", "不透明度", 0.2, 1.0, 0.02, 2)
        self._spin(form, "display.max_lines", "最多显示几行", 1, 20, 1)
        self._dspin(form, "display.hide_after_s", "无新消息后隐藏(秒)", 0.0, 120.0, 1.0, 1,
                    "0=不自动隐藏")
        return w

    def _tab_input(self) -> QWidget:
        w, form = self._page()
        self._combo(form, "input.handoff", "交付方式", ["clipboard", "inject"],
                    "clipboard=零注入（英文进剪贴板，你自己粘贴）；inject=允许模拟按键")
        self._combo(form, "input.trigger", "触发方式", ["space_taps", "hotkey"],
                    "space_taps=聊天框里连按空格")
        self._line(form, "input.tap_key", "连击键", "默认 space")
        self._spin(form, "input.taps", "连按次数", 2, 8, 1)
        self._dspin(form, "input.tap_window_s", "连击时间窗(秒)", 0.3, 5.0, 0.1, 1)
        self._check(form, "input.require_game_focus", "只在游戏窗口前台时响应")
        self._region_row(form, "input.input_region", "聊天输入行区域",
                         "聊天框打开时 To (ALL): 那一行的位置")
        self._check(form, "input.show_original", "悬浮窗同时显示中文原文")
        self._combo(form, "input.level", "注入等级（handoff=inject 时用）",
                    ["L1", "L2", "L3"],
                    "L1=注入并发送 / L2=只注入 / L3=只复制")
        self._check(form, "input.auto_send", "注入后自动回车发送")
        self._spin(form, "input.key_delay_ms", "逐字注入间隔(ms)", 5, 200, 5,
                   "太快会被游戏吞掉")
        self._spin(form, "input.max_chars", "英文最长字数", 20, 1000, 10, "防刷屏")
        return w

    def _tab_hotkey(self) -> QWidget:
        w, form = self._page()
        self._line(form, "hotkey.send_box", "呼出中文输入小窗", "keyboard 库语法，如 alt+t")
        self._line(form, "hotkey.send_clipboard", "翻译剪贴板内容", "如 alt+y")
        self._line(form, "hotkey.toggle_receive", "暂停/恢复接收", "如 alt+g")
        self._line(form, "hotkey.retranslate_last", "重译最近一条", "如 alt+r")
        self._combo(form, "ui.log_level", "日志级别", ["DEBUG", "INFO", "WARNING"])
        self._check(form, "ui.start_minimized", "启动时不显示主面板（只留托盘）")
        return w

    # ---- 控件工厂 ----

    def _page(self) -> tuple[QWidget, QFormLayout]:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setVerticalSpacing(8)
        return widget, form

    @staticmethod
    def _get(cfg: Config, dotted: str):
        section, field = dotted.split(".")
        return getattr(getattr(cfg, section), field)

    @staticmethod
    def _set(cfg: Config, dotted: str, value) -> None:
        section, field = dotted.split(".")
        setattr(getattr(cfg, section), field, value)

    def _line(self, form, key, label, tip="", transform=None, password=False) -> None:
        edit = QLineEdit()
        value = self._get(self.cfg, key)
        if transform == "list":
            edit.setText(", ".join(value or []))
        elif transform == "intlist":
            edit.setText(", ".join(str(v) for v in (value or [])))
        else:
            edit.setText(str(value if value is not None else ""))
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        if tip:
            edit.setToolTip(tip)
        self._w[key] = (edit, transform)
        form.addRow(label, edit)

    def _combo(self, form, key, label, items, tip="", editable=False) -> None:
        box = QComboBox()
        box.addItems(items)
        if editable:
            box.setEditable(True)
        current = str(self._get(self.cfg, key))
        if current in items:
            box.setCurrentText(current)
        elif editable:
            box.setCurrentText(current)
        if tip:
            box.setToolTip(tip)
        self._w[key] = box
        form.addRow(label, box)

    def _check(self, form, key, label, tip="") -> None:
        box = QCheckBox()
        box.setChecked(bool(self._get(self.cfg, key)))
        if tip:
            box.setToolTip(tip)
        self._w[key] = box
        form.addRow(label, box)

    def _spin(self, form, key, label, lo, hi, step, tip="") -> None:
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(int(self._get(self.cfg, key)))
        if tip:
            spin.setToolTip(tip)
        self._w[key] = spin
        form.addRow(label, spin)

    def _dspin(self, form, key, label, lo, hi, step, decimals, tip="") -> None:
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setDecimals(decimals)
        spin.setValue(float(self._get(self.cfg, key)))
        if tip:
            spin.setToolTip(tip)
        self._w[key] = spin
        form.addRow(label, spin)

    def _region_row(self, form, key, label, tip) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        value = self._get(self.cfg, key)
        text = QLabel(", ".join(f"{v:.3f}" for v in value))
        text.setStyleSheet("color:#9aa4b2;")
        btn = QPushButton("框选")
        btn.setToolTip(tip)

        def pick() -> None:
            self._pending_region = key
            self._picker = _MiniPicker(self)
            self._picker.picked.connect(self._on_region_picked)
            self._picker.start()

        btn.clicked.connect(pick)
        layout.addWidget(text, 1)
        layout.addWidget(btn)
        self._w[key] = (text, None)
        form.addRow(label, row)

    def _on_region_picked(self, region: list) -> None:
        key = getattr(self, "_pending_region", None)
        if not key:
            return
        label, _ = self._w[key]           # type: ignore[misc]
        label.setText(", ".join(f"{v:.3f}" for v in region))
        label.setProperty("picked_region", region)
        self._pending_region = None

    # ---- 动作 ----

    def _open_config_dir(self) -> None:
        target = Path(paths.default_config_path()).parent
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "打开失败", str(e))

    def _test_backend(self) -> None:
        self._apply_to_cfg()
        from ..chat.glossary import Glossary
        from ..translate.client import ChatTranslator
        import asyncio

        async def probe():
            tr = ChatTranslator(self.cfg.translate, Glossary())
            try:
                return await tr.ping()
            finally:
                await tr.close()

        try:
            ok, detail = asyncio.run(probe())
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)
        QMessageBox.information(
            self, "翻译后端",
            ("✅ 可用\n\n" if ok else "❌ 不可用\n\n") + html.escape(detail) +
            ("\n\n提示：本地 Ollama 要先 `ollama serve`；" if not ok else "")
        )

    def _apply_to_cfg(self) -> None:
        for key, widget in self._w.items():
            if isinstance(widget, tuple):
                label, transform = widget
                if transform is None:
                    region = label.property("picked_region")
                    if region:
                        self._set(self.cfg, key, [float(v) for v in region])
                    continue
                text = label.text()          # type: ignore[attr-defined]
                if transform == "list":
                    self._set(self.cfg, key,
                              [p.strip() for p in text.split(",") if p.strip()])
                elif transform == "intlist":
                    nums = [int(float(p)) for p in text.replace("，", ",").split(",")
                            if p.strip()]
                    self._set(self.cfg, key, nums)
                continue
            if isinstance(widget, QLineEdit):
                self._set(self.cfg, key, widget.text().strip())
            elif isinstance(widget, QComboBox):
                self._set(self.cfg, key, widget.currentText().strip())
            elif isinstance(widget, QCheckBox):
                self._set(self.cfg, key, widget.isChecked())
            elif isinstance(widget, QSpinBox):
                self._set(self.cfg, key, widget.value())
            elif isinstance(widget, QDoubleSpinBox):
                self._set(self.cfg, key, widget.value())

    def _save(self) -> None:
        self._apply_to_cfg()
        save_config(self.cfg)
        self.accept()


class _MiniPicker(QWidget):
    """设置页里用的迷你框选器（复用主界面的实现）。"""

    from PySide6.QtCore import Signal
    picked = Signal(list)

    def __init__(self, parent=None):
        from ..ui.region_picker import RegionPicker

        super().__init__(parent)
        self._inner = RegionPicker()
        self._inner.picked.connect(self.picked.emit)

    def start(self) -> None:
        self._inner.start()

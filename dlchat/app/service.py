"""编排层：来源 -> 去重 -> 翻译 -> 信号；以及"我说的话"-> 注入。

线程模型：
    主线程(Qt)  ──信号──  ChatService(QObject, 主线程)  ←─ 工作线程(asyncio)
工作线程里跑一个 asyncio 事件循环：轮询来源、串行翻译（保证顺序）、
处理待发送队列。所有对外通知都走 Qt 信号，UI 不碰工作线程的状态。
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

from PySide6.QtCore import QObject, Signal

from ..chat.glossary import Glossary
from ..chat.line import ChatLine
from ..chat.parser import is_translatable
from ..chat.tracker import LineTracker
from ..config import Config
from ..input.injector import InjectResult, TextInjector
from ..sources.base import ChatSource
from ..translate.cache import TranslationCache
from ..translate.client import ChatTranslator

logger = logging.getLogger(__name__)

# 控制台来源连续多久没有任何聊天行，就提示用户先跑一次实测脚本
CONSOLE_EMPTY_WARN_S = 90.0


class ChatService(QObject):
    line_received = Signal(object)      # ChatLine（原文先到，UI 可先占位）
    line_translated = Signal(object)    # ChatLine（translated 已填）
    outbound_translated = Signal(object)  # 功能2：中文原文 + 英文译文
    injection_done = Signal(object)     # InjectResult
    status_changed = Signal(str)
    error_occurred = Signal(str)
    backend_status = Signal(bool, str)

    def __init__(self, cfg: Config, parent: QObject | None = None):
        super().__init__(parent)
        self.cfg = cfg
        self.glossary = Glossary()
        self._thread: threading.Thread | None = None
        self._running = False
        self._paused = False
        self._outbox: queue.Queue[tuple[str, bool | None]] = queue.Queue()
        self._injector = TextInjector(cfg.input)
        self._source: ChatSource | None = None
        self._translator: ChatTranslator | None = None
        self._last_line: ChatLine | None = None
        self._source_name = ""
        self._line_reader = None
        self._converting = False
        self._grabber = None      # 与读输入行共用的抓帧器
        self._ocr = None          # 与读输入行共用的 OCR 引擎（单实例）
        # 自己刚发出去（复制到剪贴板/注入）的英文：自己的消息随后也会出现在聊天条上，
        # 不要再把它翻回中文显示一遍。
        self._self_echo: deque[str] = deque(maxlen=20)

    # ---------- 生命周期 ----------

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._thread_main, daemon=True,
                                        name="chat-service")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._source is not None:
            try:
                self._source.stop()
            except Exception:  # noqa: BLE001
                pass
        if self._thread is not None:
            self._thread.join(timeout=4.0)
            self._thread = None
        self.status_changed.emit("已停止")

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        self.status_changed.emit("已暂停（不再翻译新消息）" if paused else "已恢复")

    # ---------- 功能2：我说的话 ----------

    def submit_text(self, chinese: str, auto_send: bool | None = None) -> None:
        """把中文交给工作线程翻译并注入。"""
        text = (chinese or "").strip()
        if not text:
            return
        self._outbox.put((text, auto_send))

    def submit_clipboard(self) -> None:
        text = self._injector.get_clipboard()
        if text.strip():
            self.submit_text(text)
        else:
            self.injection_done.emit(InjectResult(False, self.cfg.input.level, "剪贴板是空的"))

    def convert_input_line(self) -> None:
        """零注入路径的主入口：读游戏聊天输入行 -> 翻译 -> 进剪贴板。

        由连击触发器（或热键）调用，回调发生在键盘监听线程上，所以这里只入队。
        """
        self._outbox.put(("__read_input__", None))

    @property
    def converting(self) -> bool:
        return self._converting

    def game_focused(self) -> bool:
        """游戏窗口是否在前台（连击触发用它避免在桌面/其他窗口误触发）。"""
        try:
            return self._injector.game_window_focused()
        except Exception:  # noqa: BLE001
            return False

    def calibrate_input_line(self, save_path: str | None = None) -> str:
        """校准输入行区域：抓一张、跑 OCR，返回给界面看的说明。"""
        try:
            from .. import paths
            from ..input.line_reader import InputLineReader

            grabber, ocr = self._ocr_resources()
            reader = self._line_reader or InputLineReader(self.cfg, grabber, ocr)
            self._line_reader = reader
            target = save_path or str(paths.output_dir() / "input_line.png")
            raw, clean = reader.preview(target)
        except Exception as e:  # noqa: BLE001
            return f"读取失败: {e}"
        return (f"OCR 原文: {raw!r}\n清洗后: {clean!r}\n"
                f"（裁剪图已存 {target}；聊天框要打开且里面有字）")

    def retranslate_last(self) -> None:
        """重译最近一条（OCR 认错时手动补救）。"""
        if self._last_line is None:
            self.status_changed.emit("还没有可重译的消息")
            return
        line = self._last_line
        self._outbox.put((f"__retranslate__{line.text}", None))

    # ---------- 自检 ----------

    def ping_backend(self) -> None:
        def _run() -> None:
            async def _do():
                tr = ChatTranslator(self.cfg.translate, self.glossary)
                try:
                    return await tr.ping()
                finally:
                    await tr.close()

            try:
                ok, detail = asyncio.run(_do())
            except Exception as e:  # noqa: BLE001
                ok, detail = False, str(e)
            self.backend_status.emit(ok, detail)

        threading.Thread(target=_run, daemon=True, name="backend-ping").start()

    # ---------- 工作线程 ----------

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as e:  # noqa: BLE001
            logger.exception("ChatService 崩了")
            self.error_occurred.emit(f"服务线程异常: {e}")
        finally:
            self._running = False

    async def _main(self) -> None:
        # 允许外部先塞一个 translator（测试注入用）；没塞才自己造
        if self._translator is None:
            self._translator = ChatTranslator(self.cfg.translate, self.glossary)
        tracker = LineTracker(ignore_speakers=[self.cfg.app.my_name]
                              if self.cfg.app.my_name else [])
        cache = TranslationCache()

        self.status_changed.emit("正在启动聊天来源...")
        source = await asyncio.to_thread(self._create_source)
        if source is None:
            # 关键：来源挂了只影响"看"，"说"必须照常可用。
            # 原来这里直接 return，结果整个发送链路（依赖本循环处理待发队列）
            # 一起静默失效——用户按什么都没反应。
            self.error_occurred.emit(
                "没有可用的聊天来源（控制台日志与 OCR 都不可用）："
                "'看别人说话'不可用，但'我说话'仍然可用")
            self.status_changed.emit("接收不可用 · 发送可用")
        else:
            self._source = source
            self._source_name = source.name
            self.status_changed.emit(
                f"运行中 · 来源: {source.name} · {source.status().detail}")

        # 预热翻译后端（不阻塞主循环）
        asyncio.create_task(self._prewarm())

        started = time.monotonic()
        last_activity = time.monotonic()
        warned = False
        idle_sleep = 0.05 if (source is not None and source.name == "console") else 0.08

        while self._running:
            # 1) 收消息（没有可用来源时 skips，只保留"说"的能力）
            if source is not None:
                try:
                    raw_lines = await asyncio.to_thread(source.poll)
                except Exception as e:  # noqa: BLE001
                    logger.warning("来源轮询失败: %s", e)
                    raw_lines = []

                fresh = tracker.update(raw_lines)
                for line in fresh:
                    if self._is_blocked(line):
                        continue
                    last_activity = time.monotonic()
                    warned = False
                    self.line_received.emit(line)
                    self._last_line = line
                    await self._translate_line(line, cache)

            # 2) 发消息（功能2）——不依赖接收来源是否可用
            await self._drain_outbox()

            # 3) 控制台来源长时间没有任何聊天 -> 提示实测
            if (source is not None and source.name == "console" and not warned
                    and time.monotonic() - started > CONSOLE_EMPTY_WARN_S
                    and last_activity < started + 1.0):
                warned = True
                self.status_changed.emit(
                    "控制台日志里还没读到聊天内容：可能聊天不写日志，"
                    "建议改用 OCR 来源（先跑 scripts/spike_console_log.py 确认）")

            await asyncio.sleep(idle_sleep)

        try:
            if source is not None:
                source.stop()
        finally:
            if self._translator is not None:
                await self._translator.close()
            if self._line_reader is not None:
                try:
                    self._line_reader.close()
                except Exception:  # noqa: BLE001
                    pass
                self._line_reader = None
            self._close_ocr_resources()

    # ---------- 内部 ----------

    async def _prewarm(self) -> None:
        if self._translator is None:
            return
        ok = await self._translator.prewarm()
        self.backend_status.emit(ok, "翻译后端已预热" if ok else "翻译后端预热失败（首次翻译会慢）")

    async def _translate_line(self, line: ChatLine, cache: TranslationCache) -> None:
        if self._paused or not self.cfg.app.enable_receive:
            return
        if self._is_self_echo(line.text):
            logger.debug("跳过自己刚发出去的消息: %r", line.text)
            return
        if not is_translatable(line):
            line.translated = line.text
            self.line_translated.emit(line)
            return

        cached = cache.get(line.text, "en->zh")
        if cached:
            line.translated = cached
            self.line_translated.emit(line)
            return

        assert self._translator is not None
        try:
            translated = await self._translator.translate_full(line.text, "en->zh")
        except Exception as e:  # noqa: BLE001
            logger.warning("翻译失败: %s", e)
            line.error = str(e)
            self.error_occurred.emit(f"翻译失败: {e}")
            return
        if not translated:
            line.error = "空译文"
            return
        line.translated = translated
        cache.put(line.text, "en->zh", translated)
        self.line_translated.emit(line)

    async def _drain_outbox(self) -> None:
        while True:
            try:
                text, auto_send = self._outbox.get_nowait()
            except queue.Empty:
                return
            await self._handle_outbound(text, auto_send)

    async def _handle_outbound(self, text: str, auto_send: bool | None) -> None:
        if self._translator is None:
            return
        # 零注入路径：从游戏聊天输入行读中文
        if text == "__read_input__":
            await self._convert_input_line()
            return
        if text.startswith("__retranslate__"):
            if self._last_line is not None:
                await self._translate_line(self._last_line, TranslationCache())
            return
        if not self.cfg.app.enable_send:
            self.injection_done.emit(InjectResult(False, "clipboard", "发送功能已关闭（配置里 enable_send=false）"))
            return

        english = await self._translator.translate_full(text, "zh->en")
        if not english:
            self.injection_done.emit(InjectResult(False, self.cfg.input.handoff, "没翻出英文，已放弃"))
            return
        await self._deliver(text, english, auto_send)

    async def _convert_input_line(self) -> None:
        """读输入行 -> 翻译 -> 交付（默认只进剪贴板，不注入）。"""
        if self._converting:
            return
        if not self.cfg.app.enable_send:
            self.status_changed.emit("发送功能已关闭")
            return
        self._converting = True
        try:
            if self._line_reader is None:
                from ..input.line_reader import InputLineReader

                self.status_changed.emit("正在初始化输入行识别...")
                grabber, ocr = self._ocr_resources()
                self._line_reader = InputLineReader(self.cfg, grabber, ocr)
            chinese = await asyncio.to_thread(self._line_reader.read)
            if not chinese:
                self.injection_done.emit(InjectResult(
                    False, "clipboard",
                    "输入行没读到内容：确认聊天框是打开的、并且已校准输入行区域"))
                return
            self.status_changed.emit(f"读到输入行: {chinese[:40]}")
            english = await self._translator.translate_full(chinese, "zh->en")
            if not english:
                self.injection_done.emit(InjectResult(False, "clipboard", "没翻出英文，已放弃"))
                return
            await self._deliver(chinese, english, None)
        except Exception as e:  # noqa: BLE001
            logger.exception("转换输入行失败")
            self.error_occurred.emit(f"转换输入行失败: {e}")
        finally:
            self._converting = False

    async def _deliver(self, source_text: str, english: str,
                       auto_send: bool | None) -> None:
        """把英文交给用户：默认只写剪贴板（零注入），可选自动注入。"""
        if len(english) > self.cfg.input.max_chars:
            english = english[: self.cfg.input.max_chars].rstrip()
        # 自己的消息随后会出现在聊天条上，先记下来（接收方向要跳过它）
        self._remember_self(english)
        self.outbound_translated.emit(ChatLine(text=source_text, translated=english,
                                               target="self", source="input"))

        zero_inject = (self.cfg.input.handoff == "clipboard") or self.cfg.app.read_only
        if zero_inject:
            self._injector.set_clipboard(english)
            self.injection_done.emit(InjectResult(
                True, "clipboard",
                f"英文已进剪贴板 → 聊天框里按 Ctrl+A 再 Ctrl+V 覆盖，回车发送\n{english}"))
            return

        result = await asyncio.to_thread(self._injector.send, english, None, auto_send)
        self.injection_done.emit(result)

    def _create_source(self) -> ChatSource | None:
        wanted = [self.cfg.source.kind]
        if self.cfg.source.fallback_to_ocr and "ocr" not in wanted:
            wanted.append("ocr")
        if "console" not in wanted and self.cfg.source.fallback_to_ocr:
            wanted.append("console")

        for kind in wanted:
            source = self._build_source(kind)
            if source is None:
                continue
            try:
                if source.start():
                    logger.info("聊天来源: %s (%s)", kind, source.status().detail)
                    return source
                logger.warning("来源 %s 启动失败: %s", kind, source.status().detail)
            except Exception as e:  # noqa: BLE001
                logger.warning("来源 %s 异常: %s", kind, e)
            try:
                source.stop()
            except Exception:  # noqa: BLE001
                pass
        return None

    def _build_source(self, kind: str) -> ChatSource | None:
        if kind == "console":
            from ..sources.console_log import ConsoleLogSource

            return ConsoleLogSource(self.cfg.console)
        if kind == "ocr":
            from ..sources.screen_ocr import ScreenOCRSource

            try:
                grabber, ocr = self._ocr_resources()
                return ScreenOCRSource(self.cfg.ocr, ocr, grabber,
                                       known_phrases=self.glossary.phrase_keys,
                                       ui_strings=self.glossary.zh_ui_strings,
                                       owns_resources=False,
                                       focus_check=(self.game_focused
                                                    if self.cfg.source.require_game_focus
                                                    else None))
            except Exception as e:  # noqa: BLE001
                logger.error("OCR 来源构造失败: %s", e)
                return None
        return None

    # ---------- 共享的 OCR 资源 ----------

    def _ocr_resources(self):
        """抓帧器 + OCR 引擎全局只建一套。

        实测：两个 OCR 引擎实例同时跑会互相抢线程，单帧从 100ms 变成 8 秒。
        接收方向和"读输入行"共用这一套（引擎内部有锁，串行化调用）。
        """
        if self._grabber is None:
            from ..capture.ocr import create_ocr
            from ..capture.screen import ScreenGrabber

            self._grabber = ScreenGrabber()
            self._ocr = create_ocr(self.cfg.ocr.backend,
                                   min_confidence=self.cfg.ocr.min_confidence,
                                   upscale=self.cfg.ocr.upscale,
                                   invert=self.cfg.ocr.invert,
                                   det_limit_side=self.cfg.ocr.det_limit_side,
                                   det_limit_type=self.cfg.ocr.det_limit_type)
        return self._grabber, self._ocr

    def _close_ocr_resources(self) -> None:
        if self._grabber is not None:
            try:
                self._grabber.close()
            except Exception:  # noqa: BLE001
                pass
            self._grabber = None
        self._ocr = None

    def _is_blocked(self, line: ChatLine) -> bool:
        text = line.text.lower()
        return any(w.strip().lower() in text
                   for w in self.cfg.app.blocklist if w and w.strip())

    # ---------- 自己的消息 ----------

    @staticmethod
    def _norm_text(text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", (text or "").lower())

    def _remember_self(self, english: str) -> None:
        """记住自己发出去的英文，避免它出现在聊天条时又被翻回中文。"""
        key = self._norm_text(english)
        if key:
            self._self_echo.append(key)

    def _is_self_echo(self, text: str) -> bool:
        key = self._norm_text(text)
        if not key:
            return False
        for remembered in self._self_echo:
            if key == remembered:
                return True
            if len(remembered) < 8:
                continue  # 短句不做模糊匹配，避免 "gg" 把 "gg wp" 也吃掉
            if key in remembered or remembered in key:
                return True
            # OCR 抖动：一两个字母认错
            if abs(len(key) - len(remembered)) <= max(3, len(remembered) * 0.25):
                if SequenceMatcher(None, key, remembered).ratio() >= 0.88:
                    return True
        return False

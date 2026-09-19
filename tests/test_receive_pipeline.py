"""接收链路端到端测试：假的 console.log -> ChatService -> Qt 信号。

不抓屏、不联网、不碰游戏，验证"来源→解析→去重→翻译→回传"整条编排是真的通的。

注意：ChatService 在工作线程里发 Qt 信号，跨线程投递是**排队**的，主线程必须跑
事件循环才能收到（真实程序里 Qt 主循环一直在跑）。所以测试里手动 processEvents()。
"""

import tempfile
import time
import unittest
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from dlchat.app.service import ChatService
from dlchat.config import Config


def ensure_app() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


def pump_until(pred, timeout_s: float = 8.0) -> bool:
    """一边跑事件循环一边等条件成立。"""
    app = ensure_app()
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.05)
    app.processEvents()
    return pred()


class _FakeTranslator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def translate_full(self, text: str, direction: str) -> str:
        self.calls.append((text, direction))
        return f"[zh]{text}"

    async def prewarm(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class ReceivePipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "console.log"
        self.log.write_text("", encoding="utf-8")

        cfg = Config()
        cfg.source.kind = "console"          # 只用控制台来源，避免抓屏
        cfg.source.fallback_to_ocr = False
        cfg.console.log_path = str(self.log)
        cfg.console.tail_from_end = True
        cfg.translate.context_window = 0
        self.cfg = cfg

    def tearDown(self):
        self.tmp.cleanup()

    def _start(self):
        ensure_app()
        service = ChatService(self.cfg)
        service._translator = _FakeTranslator()  # noqa: SLF001
        events = {"line": [], "translated": [], "status": [], "errors": []}
        service.line_received.connect(events["line"].append)
        service.line_translated.connect(events["translated"].append)
        service.status_changed.connect(events["status"].append)
        service.error_occurred.connect(events["errors"].append)
        service.start()
        # 等来源就绪：状态里出现"运行中"或报错
        pump_until(lambda: any("运行中" in s or "失败" in s for s in events["status"]), 6.0)
        return service, events

    def _append(self, *lines: str):
        with open(self.log, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")

    def test_chat_line_flows_through(self):
        service, events = self._start()
        try:
            self._append("[All Chat][Bob (3)]: he's low, dive him")
            pump_until(lambda: bool(events["translated"]), 8.0)

            self.assertTrue(events["line"], "应收到 line_received")
            self.assertTrue(events["translated"], "应收到 line_translated")
            got = events["translated"][0]
            self.assertEqual(got.text, "he's low, dive him")
            self.assertEqual(got.speaker, "Bob")
            self.assertEqual(got.translated, "[zh]he's low, dive him")
            self.assertEqual(got.source, "console")
            self.assertEqual(service._translator.calls[0][1], "en->zh")  # noqa: SLF001
            self.assertFalse(events["errors"])
        finally:
            service.stop()

    def test_duplicate_lines_translated_once(self):
        service, events = self._start()
        try:
            self._append("[All Chat][Bob (3)]: gg wp",
                         "[All Chat][Bob (3)]: gg wp",
                         "[ALL] Bob: gg wp")
            pump_until(lambda: bool(events["translated"]), 8.0)
            pump_until(lambda: False, 1.0)   # 再等 1 秒确认没有第二条
            self.assertEqual(len(events["translated"]), 1, "重复行只应翻译一次")
        finally:
            service.stop()

    def test_noise_lines_ignored(self):
        service, events = self._start()
        try:
            self._append("Connecting to server...",
                         "Failed to load something",
                         "NET_SetConVar x 1")
            pump_until(lambda: False, 1.5)
            self.assertEqual(events["line"], [])
        finally:
            service.stop()

    def test_chinese_message_shown_without_translation(self):
        service, events = self._start()
        try:
            self._append("[All Chat][老王 (4)]: 中路没人")
            pump_until(lambda: bool(events["translated"]), 8.0)
            got = events["translated"][0]
            self.assertEqual(got.translated, got.text)      # 原样展示
            self.assertEqual(service._translator.calls, [])  # 不调用翻译  # noqa: SLF001
        finally:
            service.stop()

    def test_blocklist_filters(self):
        self.cfg.app.blocklist = ["noob"]
        service, events = self._start()
        try:
            self._append("[All Chat][Troll (5)]: you are a noob")
            pump_until(lambda: False, 1.5)
            self.assertEqual(events["line"], [])
        finally:
            service.stop()

    def test_own_messages_skipped(self):
        self.cfg.app.my_name = "MyName"
        service, events = self._start()
        try:
            self._append("[All Chat][MyName (2)]: testing my own line")
            pump_until(lambda: False, 1.5)
            self.assertEqual(events["line"], [])
        finally:
            service.stop()


if __name__ == "__main__":
    unittest.main()

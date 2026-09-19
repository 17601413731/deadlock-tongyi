"""零注入链路端到端测试（用假翻译器/假读行器，不碰真实剪贴板、不联网）。"""

import asyncio
import unittest

from dlchat.app.service import ChatService
from dlchat.config import Config


class _FakeTranslator:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def translate_full(self, text: str, direction: str) -> str:
        self.calls.append((text, direction))
        return {"zh->en": "mid is open", "en->zh": "中路没人"}.get(direction, text)

    async def close(self) -> None:
        pass


class _FakeReader:
    def __init__(self, text: str):
        self.text = text
        self.reads = 0

    def read(self) -> str:
        self.reads += 1
        return self.text

    def close(self) -> None:
        pass


class _FakeInjector:
    """记录剪贴板写入；一旦有人调用 send() 就报错（零注入模式下不该发生）。"""

    def __init__(self):
        self.clipboard: str | None = None
        self.sends = 0

    def set_clipboard(self, text: str) -> bool:
        self.clipboard = text
        return True

    def get_clipboard(self) -> str:
        return self.clipboard or ""

    def send(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.sends += 1
        raise AssertionError("零注入模式下不应该调用键盘注入")


def _make_service(reader_text: str, **cfg_updates) -> tuple[ChatService, dict]:
    cfg = Config()
    cfg.app.read_only = False          # 故意设成非只读，验证 handoff=clipboard 仍然零注入
    cfg.input.handoff = "clipboard"
    for key, value in cfg_updates.items():
        section, field = key.split(".")
        setattr(getattr(cfg, section), field, value)

    service = ChatService(cfg)
    service._translator = _FakeTranslator()      # noqa: SLF001
    service._line_reader = _FakeReader(reader_text)  # noqa: SLF001
    service._injector = _FakeInjector()          # noqa: SLF001

    events = {"outbound": [], "injected": [], "status": [], "errors": []}
    service.outbound_translated.connect(events["outbound"].append)
    service.injection_done.connect(events["injected"].append)
    service.status_changed.connect(events["status"].append)
    service.error_occurred.connect(events["errors"].append)
    return service, events


class ZeroInjectPipelineTest(unittest.TestCase):
    def test_reads_input_line_translates_and_copies(self):
        service, events = _make_service("中路没人")
        asyncio.run(service._convert_input_line())  # noqa: SLF001

        self.assertEqual(service._injector.clipboard, "mid is open")  # noqa: SLF001
        self.assertEqual(service._injector.sends, 0)  # noqa: SLF001
        self.assertEqual(len(events["outbound"]), 1)
        line = events["outbound"][0]
        self.assertEqual(line.text, "中路没人")
        self.assertEqual(line.translated, "mid is open")
        self.assertTrue(events["injected"][0].ok)
        self.assertIn("Ctrl+A", events["injected"][0].detail)

    def test_translator_receives_zh_to_en_direction(self):
        service, _ = _make_service("推中路")
        asyncio.run(service._convert_input_line())  # noqa: SLF001
        self.assertEqual(service._translator.calls, [("推中路", "zh->en")])  # noqa: SLF001

    def test_empty_input_line_reports_instead_of_translating(self):
        service, events = _make_service("")
        asyncio.run(service._convert_input_line())  # noqa: SLF001
        self.assertEqual(events["outbound"], [])
        self.assertFalse(events["injected"][0].ok)
        self.assertIn("没读到内容", events["injected"][0].detail)
        self.assertEqual(service._translator.calls, [])  # noqa: SLF001

    def test_concurrent_trigger_is_ignored(self):
        service, events = _make_service("中路没人")
        service._converting = True  # noqa: SLF001
        asyncio.run(service._convert_input_line())  # noqa: SLF001
        self.assertEqual(events["outbound"], [])
        self.assertEqual(service._injector.clipboard, None)  # noqa: SLF001

    def test_enable_send_false_blocks(self):
        service, events = _make_service("中路没人", **{"app.enable_send": False})
        asyncio.run(service._convert_input_line())  # noqa: SLF001
        self.assertEqual(events["outbound"], [])
        self.assertEqual(service._injector.clipboard, None)  # noqa: SLF001

    def test_long_translation_truncated(self):
        service, events = _make_service("很长的话")
        service._translator.translate_full = _long_translation  # noqa: SLF001
        service.cfg.input.max_chars = 10
        asyncio.run(service._convert_input_line())  # noqa: SLF001
        self.assertEqual(len(events["outbound"][0].translated), 10)

    def test_manual_submit_also_uses_clipboard_handoff(self):
        """手动输入框/剪贴板路径同样遵守 handoff=clipboard。"""
        service, events = _make_service("随便")
        service._outbox.put(("撤", None))  # noqa: SLF001
        asyncio.run(service._drain_outbox())  # noqa: SLF001
        self.assertEqual(service._injector.clipboard, "mid is open")  # noqa: SLF001
        self.assertEqual(service._injector.sends, 0)  # noqa: SLF001


async def _long_translation(text: str, direction: str) -> str:
    return "x" * 50


if __name__ == "__main__":
    unittest.main()

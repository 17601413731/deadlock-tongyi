"""自己的消息回声过滤测试。

场景：你连按空格转换、粘贴、发送之后，这条英文也会显示在聊天条上被 OCR 读到。
如果不处理，工具会把它当成"队友说的话"再翻回中文，刷出一条没有意义的中文。
"""

import unittest

from dlchat.app.service import ChatService
from dlchat.chat.line import ChatLine
from dlchat.config import Config


class SelfEchoTest(unittest.TestCase):
    def setUp(self):
        self.service = ChatService(Config())

    def test_exact_echo_detected(self):
        self.service._remember_self("mid is open")  # noqa: SLF001
        self.assertTrue(self.service._is_self_echo("mid is open"))  # noqa: SLF001

    def test_case_and_punctuation_insensitive(self):
        self.service._remember_self("Mid is open!")  # noqa: SLF001
        self.assertTrue(self.service._is_self_echo("mid is open"))  # noqa: SLF001

    def test_ocr_jitter_tolerated_for_long_text(self):
        self.service._remember_self("need help with urn please")  # noqa: SLF001
        # OCR 少认一个字母
        self.assertTrue(self.service._is_self_echo("need help with urn pleae"))  # noqa: SLF001
        # OCR 额外多出几个字符（比如把名字前缀带进来了）
        self.assertTrue(self.service._is_self_echo(  # noqa: SLF001
            "Bob need help with urn please"))

    def test_other_players_not_filtered(self):
        self.service._remember_self("mid is open")  # noqa: SLF001
        self.assertFalse(self.service._is_self_echo("push mid now"))  # noqa: SLF001

    def test_short_text_not_fuzzy_matched(self):
        """短句不做包含匹配，避免 'gg' 把 'gg wp' 也吃掉。"""
        self.service._remember_self("gg")  # noqa: SLF001
        self.assertFalse(self.service._is_self_echo("gg wp"))  # noqa: SLF001

    def test_empty_never_matches(self):
        self.service._remember_self("")  # noqa: SLF001
        self.assertFalse(self.service._is_self_echo(""))  # noqa: SLF001

    def test_line_skipped_in_translate_path(self):
        """走完整翻译入口时，自己的消息不应该产生翻译事件。"""
        import asyncio

        self.service._remember_self("mid is open")  # noqa: SLF001
        events = []
        self.service.line_translated.connect(events.append)
        line = ChatLine(text="mid is open", speaker="Me", source="ocr")
        asyncio.run(self.service._translate_line(line, None))  # noqa: SLF001
        self.assertEqual(events, [])
        self.assertEqual(line.translated, "")


if __name__ == "__main__":
    unittest.main()

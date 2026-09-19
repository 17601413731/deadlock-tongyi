"""聊天行解析测试。"""

import unittest

from dlchat.chat.line import TARGET_ALL, TARGET_ALLIES
from dlchat.chat.parser import is_translatable, parse_line, parse_lines


class ParserTest(unittest.TestCase):
    def test_server_log_format(self):
        """server.dll 的打印格式：[All Chat][名字 (3)]: 内容"""
        line = parse_line("[All Chat][Bob (3)]: mid no")
        self.assertIsNotNone(line)
        self.assertEqual(line.speaker, "Bob")
        self.assertEqual(line.text, "mid no")
        self.assertEqual(line.target, TARGET_ALL)

    def test_allies_tag(self):
        line = parse_line("[ALLIES] Zed: push walker")
        self.assertEqual(line.target, TARGET_ALLIES)
        self.assertEqual(line.speaker, "Zed")
        self.assertEqual(line.text, "push walker")

    def test_plain_name_prefix(self):
        line = parse_line("Alice: he's low")
        self.assertEqual(line.speaker, "Alice")
        self.assertEqual(line.text, "he's low")

    def test_bare_text(self):
        line = parse_line("gg wp everyone")
        self.assertEqual(line.speaker, "")
        self.assertEqual(line.text, "gg wp everyone")

    def test_noise_rejected(self):
        for raw in ("Failed to load something", "Connecting to server...",
                    "NET_SetConVar", "   ", "[ALL]"):
            self.assertIsNone(parse_line(raw), raw)

    def test_chinese_line_kept(self):
        line = parse_line("[全部] 老王: 中路没人")
        self.assertEqual(line.text, "中路没人")
        self.assertEqual(line.lang, "zh")
        self.assertFalse(is_translatable(line))

    def test_english_translatable(self):
        self.assertTrue(is_translatable(parse_line("mid no")))

    def test_mixed_is_translatable(self):
        line = parse_line("老王: push 中路")
        self.assertEqual(line.lang, "mixed")
        self.assertTrue(is_translatable(line))

    def test_batch(self):
        lines = parse_lines(["bob: aaa", "Failed to x", "ccc"])
        self.assertEqual([l.text for l in lines], ["aaa", "ccc"])

    def test_fingerprint_ignores_case_and_punctuation(self):
        a = parse_line("Mid No!")
        b = parse_line("mid   no")
        self.assertEqual(a.fingerprint, b.fingerprint)


if __name__ == "__main__":
    unittest.main()

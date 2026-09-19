"""提示词构造测试：静态前缀必须逐字节稳定（前缀缓存的前提）。"""

import unittest

from dlchat.translate.prompt import (
    build_messages,
    build_system,
    build_user_message,
)

KEEP = ["gg", "ez", "wp"]


class PromptTest(unittest.TestCase):
    def test_system_is_static_across_terms(self):
        """system 里不能出现具体术语对（否则每句都变，KV 前缀缓存全失效）。"""
        a = build_system("en->zh", KEEP)
        b = build_system("en->zh", KEEP)
        self.assertEqual(a, b)
        self.assertNotIn("=中路", a)
        self.assertNotIn("魂瓮", a)

    def test_system_contains_keep_list(self):
        text = build_system("en->zh", KEEP)
        self.assertIn("gg, ez, wp", text)

    def test_user_message_carries_terms(self):
        msg = build_user_message("push mid", [("mid", "中路")], "en->zh")
        self.assertTrue(msg.startswith("TERMS:"))
        self.assertIn("mid=中路", msg)
        self.assertTrue(msg.endswith("push mid"))

    def test_user_message_without_terms_is_plain(self):
        self.assertEqual(build_user_message("gg", [], "en->zh"), "gg")

    def test_messages_shape(self):
        messages = build_messages("mid no", "en->zh", [("mid", "中路")], KEEP)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(messages[-1]["content"].splitlines()[-1], "mid no")
        roles = [m["role"] for m in messages]
        self.assertIn("assistant", roles, "应包含少样本示例")

    def test_prefix_identical_when_terms_differ(self):
        m1 = build_messages("push mid", "en->zh", [("mid", "中路")], KEEP)
        m2 = build_messages("urn pls", "en->zh", [("urn", "魂瓮")], KEEP)
        self.assertEqual(m1[0], m2[0], "system 前缀必须一致")
        self.assertEqual(len(m1), len(m2))

    def test_history_appended(self):
        messages = build_messages("mid no", "en->zh", [], KEEP,
                                  history=[("gg", "打得不错")])
        contents = [m["content"] for m in messages]
        self.assertIn("打得不错", contents)

    def test_zh_to_en_system(self):
        text = build_system("zh->en", KEEP)
        self.assertIn("Deadlock", text)
        self.assertIn("TERMS", text)


if __name__ == "__main__":
    unittest.main()

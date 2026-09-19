"""过滤器测试（第二轮）：游戏不在前台时读到的桌面内容必须被挡住。

背景：实测把 DSH 窗口里的这些东西当成聊天翻译了——
    docs / tests / scripts / packaging scripts / chcp 65001 >nul
    rem To see which interpreter is used: run.bat --selftest / set "PY=python
所以除了"必须游戏前台才抓屏"之外，过滤器也要能挡住文件名和命令行。
"""

import unittest

from dlchat.chat.filter import looks_like_chat

# 实测读到的桌面垃圾（全都应该被挡住）
DESKTOP_JUNK = [
    "docs",
    "tests",
    "scripts",
    "packaging scripts",
    "docs tests",
    "chcp 65001 >nul",
    'rem To see which interpreter is used: run.bat --selftest',
    'set "PY=python"',
    "run.bat --selftest",
    "docs/glossary.json",
    "python -m dlchat --selftest",
    "C:\\Users\\Hlliang\\Desktop\\deadlock-tongyi",
    ".venv\\Scripts\\python.exe",
    "spike_out",
    "config.yaml",
]

# 真实聊天（一条都不能被误杀）
REAL_CHAT = [
    "mid no",
    "he's low, dive him",
    "push B and get urn",
    "careful, they're rotating to blue lane",
    "mid boss in 30 seconds, group up",
    "why did you dive their walker alone",
    "7 is smurfing",
    "stop feeding noob",
    "need help with urn pls",
    "gg wp",
    "b b b",
    "ty",
    "wp",
]


class DesktopJunkTest(unittest.TestCase):
    def test_desktop_junk_rejected(self):
        for text in DESKTOP_JUNK:
            self.assertFalse(looks_like_chat(text), f"不该当聊天: {text!r}")

    def test_real_chat_accepted(self):
        for text in REAL_CHAT:
            self.assertTrue(looks_like_chat(text), f"被误杀了: {text!r}")

    def test_repeated_token_ok_when_chatty(self):
        self.assertTrue(looks_like_chat("b b b"))
        self.assertTrue(looks_like_chat("push push"))

    def test_repeated_unknown_token_rejected(self):
        self.assertFalse(looks_like_chat("docs docs docs"))
        self.assertFalse(looks_like_chat("mmm mmm mmm"))

    def test_two_unknown_words_rejected(self):
        # 两个普通词常见于文件名堆叠
        self.assertFalse(looks_like_chat("packaging scripts"))
        self.assertFalse(looks_like_chat("release notes"))

    def test_three_word_sentence_accepted(self):
        self.assertTrue(looks_like_chat("stop feeding noob"))
        self.assertTrue(looks_like_chat("7 is smurfing"))

    def test_single_long_word_accepted(self):
        self.assertTrue(looks_like_chat("pushing"))
        self.assertFalse(looks_like_chat("scripts"))

    def test_chinese_still_accepted(self):
        self.assertTrue(looks_like_chat("中路没人"))
        self.assertTrue(looks_like_chat("撤"))


if __name__ == "__main__":
    unittest.main()

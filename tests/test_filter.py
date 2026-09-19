"""HUD 噪声过滤测试：这些判断直接决定聊天窗里会不会刷满 "45"、"FPS:221"。"""

import unittest

from dlchat.chat.filter import is_hud_noise, looks_like_chat, looks_like_player_name


class FilterTest(unittest.TestCase):
    def test_hud_numbers_are_noise(self):
        for text in ("45", "5 vs 7", "06:49", "2/1/0", "1090/1283", "0.87", "0%",
                     "+2.4", "2:17", "FPS:221", "28ms", "D", "F", "3", "402",
                     "× 2/1/0", "1×0"):
            self.assertTrue(is_hud_noise(text), text)
            self.assertFalse(looks_like_chat(text), text)

    def test_real_chat_passes(self):
        for text in ("mid no", "he's low", "gg", "push b", "wp", "need help urn",
                     "careful enemy missing", "why did you dive", "come mid now"):
            self.assertTrue(looks_like_chat(text), text)

    def test_known_phrases_pass(self):
        known = {"gg", "wp", "missing blue", "on my way"}
        self.assertTrue(looks_like_chat("Missing Blue", known))
        self.assertTrue(looks_like_chat("on my way", known))

    def test_single_short_word_rejected(self):
        # 单个短词多为 HUD/技能键，不作为聊天
        self.assertFalse(looks_like_chat("hp"))
        self.assertFalse(looks_like_chat("Q"))

    def test_numbers_never_chat(self):
        self.assertFalse(looks_like_chat("12345"))
        self.assertFalse(looks_like_chat("3.14"))

    def test_ui_words_rejected(self):
        self.assertFalse(looks_like_chat("shop"))
        self.assertFalse(looks_like_chat("cooldown"))

    def test_chinese_passes(self):
        self.assertTrue(looks_like_chat("中路没人"))
        self.assertTrue(looks_like_chat("撤"))

    def test_chinese_names_are_names(self):
        self.assertTrue(looks_like_player_name("小懒虫睡觉觉"))
        self.assertTrue(looks_like_player_name("比狗勾还狗勾"))

    def test_hero_label_text_is_not_chat(self):
        # 实测截图里 OCR 出来的界面文字；官方本地化里的中文串应被过滤
        ui = {"对局技巧", "取消", "设置", "未知"}
        self.assertFalse(looks_like_chat("对局技巧", None, ui))
        # 但玩家真打的句子不会被误杀（不是全等匹配）
        self.assertTrue(looks_like_chat("中路没人", None, ui))

    def test_english_names_are_names(self):
        self.assertTrue(looks_like_player_name("Bob"))
        self.assertFalse(looks_like_player_name("this is a long sentence here"))


if __name__ == "__main__":
    unittest.main()

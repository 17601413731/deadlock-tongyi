"""译文长度预算：通道装不下的译文必须**主动截断并告知**，而不是让它静默失败。

背景：桥把结果经 HTML 文档标题传回游戏，非 ASCII 全部转义成 \\uXXXX
（一个汉字 = 6 个字符），标题超过 900 字符会被整包替换成 payload_too_long，
引擎实测约 479 字符就开始截断。而 MAX_TEXT 允许 4000 字符的输入 ——
一条长消息以前的表现是「翻译失败」，点开面板是「未知原因」。
"""

import unittest

from dlchat.bridge.server import (MAX_TEXT, TRANSLATION_BUDGET, TRUNCATION_SUFFIX,
                                  fit_translation)


class FitTranslationTest(unittest.TestCase):
    @staticmethod
    def _body(text: str) -> str:
        """去掉截断标记，拿到真正的译文部分。

        不能用 rstrip(TRUNCATION_SUFFIX)：marker 是 " ..."，
        rstrip 会把它当成字符集合，把结尾的空格和句号一起啃掉。
        """
        return text[: -len(TRUNCATION_SUFFIX)] if text.endswith(TRUNCATION_SUFFIX) else text

    def test_short_text_untouched(self):
        text = "中路没人"
        self.assertEqual(fit_translation(text, "en->zh"), (text, False))

    def test_exactly_at_budget_untouched(self):
        text = "中" * TRANSLATION_BUDGET["en->zh"]
        self.assertEqual(fit_translation(text, "en->zh"), (text, False))

    def test_over_budget_is_truncated_with_marker(self):
        out, truncated = fit_translation("中" * 300, "en->zh")
        self.assertTrue(truncated)
        self.assertTrue(out.endswith(TRUNCATION_SUFFIX))
        self.assertLessEqual(len(out), TRANSLATION_BUDGET["en->zh"])

    def test_truncation_marker_is_ascii(self):
        """标记必须是纯 ASCII：非 ASCII 每个字符要占 6 个转义字符。"""
        self.assertTrue(TRUNCATION_SUFFIX.isascii(), TRUNCATION_SUFFIX)

    def test_truncates_at_chinese_punctuation(self):
        """中文没有词边界：断点只认中文标点，绝不认空格。"""
        first = "对面三个人在中路推进，我们的卫士已经掉了，别去打大怪了，"
        second = "先回来守高地，等我大招好了再开团。"
        out, truncated = fit_translation(first + second * 3, "en->zh")
        self.assertTrue(truncated, "文本应该超过预算")
        # 断点取的是预算内**最后**一个中文标点（不是第一个），所以只断言"切在标点后"
        self.assertTrue(self._body(out).endswith("。"), out)
        self.assertLessEqual(len(out), TRANSLATION_BUDGET["en->zh"])

    def test_ascii_period_is_not_a_breakpoint_for_chinese(self):
        """英文句点在中英混排里出现时，不能当成中文的断句点。

        把半角点放在第 10 个字符（`max` 会取到它），如果它被当成断点，
        切出来就只有「第一句话结束了.」—— 正确结果应该继续往后切在中文标点上。
        """
        text = "第一句话结束了." + "第二句还在继续" * 3 + "。末尾还很长" * 6
        out, _ = fit_translation(text, "en->zh")
        self.assertNotEqual(out, "第一句话结束了." + TRUNCATION_SUFFIX)
        self.assertTrue(self._body(out).endswith("。"), out)

    def test_long_chinese_without_punctuation_is_hard_cut(self):
        """整段没有标点也不能返回超长文本（宁可硬切）。"""
        out, truncated = fit_translation("中" * 300, "en->zh")
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), TRANSLATION_BUDGET["en->zh"])

    def test_english_cut_does_not_split_a_word(self):
        text = ("come back to base right now because " * 10) + "guardian"
        out, truncated = fit_translation(text, "zh->en")
        self.assertTrue(truncated)
        self.assertNotIn("becaus" + TRUNCATION_SUFFIX, out)
        self.assertNotIn("guardian", out, "被截掉的部分不该出现")

    def test_ascii_direction_gets_its_own_budget(self):
        """中->英的预算按英文字符算，和汉字预算分开。"""
        self.assertGreater(TRANSLATION_BUDGET["zh->en"], 0)
        out, truncated = fit_translation("word " * 200, "zh->en")
        self.assertTrue(truncated)
        self.assertLessEqual(len(out), TRANSLATION_BUDGET["zh->en"])

    def test_escaped_length_stays_under_title_gate(self):
        """截断后的最坏情况：整包仍在 900 字符标题门禁以内。

        hints（displayMode/keySet/... 约 260 字符）+ 6 倍转义的最坏情况，
        必须留出安全余量，否则又会变成 payload_too_long（玩家看到"未知原因"）。
        """
        for direction, budget in TRANSLATION_BUDGET.items():
            with self.subTest(direction=direction):
                out, _ = fit_translation("中" * 400, direction)
                worst = len(out) * 6 + 260
                self.assertLess(worst, 900, f"{direction} 的最坏整包长度 {worst} 会撞标题门禁")

    def test_budget_much_smaller_than_input_limit(self):
        """量级差就是"为什么以前会静默失败"，别把预算调到 MAX_TEXT 附近。"""
        for budget in TRANSLATION_BUDGET.values():
            self.assertLess(budget * 6, MAX_TEXT)


if __name__ == "__main__":
    unittest.main()

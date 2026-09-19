"""术语表测试（依赖 data/ 下的生成文件）。"""

import unittest

from dlchat.chat.glossary import Glossary


class GlossaryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.g = Glossary()

    def test_data_loaded(self):
        self.assertGreater(len(self.g.terms), 1000, "术语表太小，先跑 scripts/build_glossary.py")
        self.assertGreater(len(self.g.phrases), 20)
        self.assertIn("gg", self.g.keep)

    def test_hero_alias_extracted(self):
        """英雄条目的别名来自游戏自己的搜索关键字。"""
        haze = self.g.terms.get("Haze")
        self.assertIsNotNone(haze)
        self.assertTrue(haze["zh"])

    def test_exact_phrase_wheel(self):
        self.assertEqual(self.g.exact_phrase("Missing Blue"), "蓝路敌人消失")

    def test_exact_phrase_is_punctuation_insensitive(self):
        self.assertEqual(self.g.exact_phrase("missing blue!"), "蓝路敌人消失")

    def test_terms_for_english(self):
        hits = dict(self.g.terms_for("push mid and urn", "en->zh"))
        self.assertIn("mid", hits)
        self.assertIn("urn", hits)

    def test_terms_for_word_boundary(self):
        """miss 不该命中 missing 之外的东西，也不该命中别的词内部。"""
        hits = dict(self.g.terms_for("midnight", "en->zh"))
        self.assertNotIn("mid", hits)

    def test_slang_protects_keep_words(self):
        out, stash = self.g.apply_slang("mid no gg")
        self.assertIn("中路", out)
        self.assertTrue(stash)
        restored = self.g.restore(out, stash)
        self.assertIn("gg", restored)

    def test_keep_tokens(self):
        tokens = self.g.keep_tokens("gg ez wp")
        self.assertIn("gg", tokens)
        self.assertIn("ez", tokens)

    def test_reverse_slang_for_zh_to_en(self):
        out = self.g.reverse_slang("中路没人，撤")
        self.assertIn("mid", out)

    def test_terms_for_chinese(self):
        hits = dict(self.g.terms_for("中路没人", "zh->en"))
        self.assertTrue(hits, "中->英方向应能反查出术语")


if __name__ == "__main__":
    unittest.main()

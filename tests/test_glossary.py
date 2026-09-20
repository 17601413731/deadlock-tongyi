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
        out, stash, _locked = self.g.apply_slang("mid no gg")
        self.assertIn("中路", out)
        self.assertTrue(stash)
        restored = self.g.restore(out, stash)
        self.assertIn("gg", restored)

    # ---- 替换账本（apply_slang 的第三个返回值）----
    # 背景：正文被改写成中英混杂之后，terms_for 再也找不到原来的英文词，
    # 于是最该锁术语的短句一条 TERMS 都拿不到。账本就是用来补这个的。

    def test_slang_ledger_records_substitutions(self):
        out, _stash, locked = self.g.apply_slang("hes low dive him")
        self.assertIn("残血", out)
        self.assertIn(("low", "残血"), locked)

    def test_slang_ledger_prefers_longest_term(self):
        """"mid boss" 命中后不该再记一条 "mid=中路" 把长词的意思顶掉。

        slang.json 里既有 "mid boss"（中路BOSS）也有 "mid"（中路），
        按长度倒序替换后账本里只能留长的那条 —— 否则提示词会自相矛盾。
        """
        _out, _stash, locked = self.g.apply_slang("mid boss is up")
        sources = [en.lower() for en, _ in locked]
        self.assertIn("mid boss", sources)
        self.assertNotIn("mid", sources)

    def test_slang_ledger_skips_stashed_keep_words(self):
        """被占位符保护起来的词没有被替换，不该进账本。

        用 gg/wp/ult/afk：它们是**保留英文**那一类，会被 stash 成占位符，
        不该出现在替换账本里（否则提示词会说"这些词已预先译好"）。
        """
        _out, stash, locked = self.g.apply_slang("gg wp ult afk")
        self.assertTrue(stash)
        sources = [en.lower() for en, _ in locked]
        for word in ("gg", "wp", "ult", "afk"):
            self.assertNotIn(word, sources, f"{word} 是保留词，不该进替换账本")

    def test_keep_and_slang_do_not_overlap(self):
        """两张表不能有交集：重叠会让**两条规则同时失效**（stash 先跑，
        词被换成占位符，模型既看不到它、俚语替换也不会发生）。"""
        keep = {w.lower() for w in self.g.keep}
        slang = {k.lower() for k in self.g.slang}
        self.assertEqual(keep & slang, set(),
                         "keep_as_is 与 slang 有交集，请按 _slang_overrides 的说明处理")

    def test_kept_words_are_protected_not_translated(self):
        """afk/ult/b 这类词现在的规矩是"保留英文原样"，所以要被 stash 保护起来。

        以前它们**同时在**两张表里 → stash 先跑、俚语替换永远不会发生，
        结果是既不翻也不解释。现在文件层面已经清干净（slang.json 不再重复这些词），
        行为是确定的：进 stash、译后原样还原。
        """
        for word in ("afk", "ult", "b"):
            with self.subTest(word=word):
                prepared, stash, locked = self.g.apply_slang(f"{word} now")
                self.assertNotIn(word, prepared, f"{word} 应该被占位符保护起来")
                self.assertEqual(list(stash.values()), [word])
                self.assertNotIn(word, [en.lower() for en, _ in locked])

    def test_reverse_index_skips_removed_slang_entries(self):
        """清理掉 slang 里的重复词之后，反向索引不该再拿它当术语。"""
        for word in ("afk", "ult", "b"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.g.slang)

    def test_slang_ledger_keys_are_source_words(self):
        """账本里的 src 必须是原文里真实出现过的英文词（提示词里要拿它做锚点）。"""
        for text in ("push mid", "b b b", "urn pls", "stop feeding noob"):
            _out, _stash, locked = self.g.apply_slang(text)
            for en, _zh in locked:
                self.assertIn(en.lower(), text.lower())


class ZhTermNoiseTest(unittest.TestCase):
    """中->英方向：常用字/UI 词条被当术语注入，会把模型带偏（全是实测踩过的句子）。"""

    @classmethod
    def setUpClass(cls):
        cls.g = Glossary()

    def _terms(self, text: str) -> set[str]:
        return {zh for zh, _en in self.g.terms_for(text, "zh->en", limit=12)}

    def test_single_char_shang_not_injected(self):
        """「上=go」曾把「马上到」这类句子带偏 —— 单字一律不注入。"""
        for text in ["马上到", "早上好", "上路没人", "打完这波上高地", "线上等我"]:
            with self.subTest(text=text):
                self.assertNotIn("上", self._terms(text))

    def test_ta_men_pronoun_not_injected(self):
        """「他们」来自菜单文本（英文写成 "They're"），不是游戏术语。"""
        self.assertNotIn("他们", self._terms("我送他们回家"))
        self.assertNotIn("他们", self._terms("他们打野"))

    def test_multi_char_game_terms_still_work(self):
        """回归保护：别把好的也一起删了（去噪只该挡常用字/UI 词条）。"""
        self.assertIn("抱团", self._terms("抱团上"))
        self.assertIn("越塔", self._terms("越塔"))
        self.assertIn("别送了", self._terms("别送了"))
        self.assertIn("魂瓮", self._terms("魂瓮要没了"))
        self.assertIn("中路", self._terms("中路来人"))

    def test_longest_match_wins_no_duplicate(self):
        """长词命中后不该再塞一条它的子串（否则提示词自相矛盾）。

        这条是去重 bug 的回归测试：以前 fallback 循环把外层变量 en 覆盖了，
        去重比对读到的是错的值。
        """
        self.assertEqual(self._terms("抱团推"), {"抱团推"})
        self.assertEqual(self._terms("越塔杀他"), {"越塔杀他"})
        self.assertEqual(self._terms("别送了"), {"别送了"})

    def test_curated_single_char_is_allowed_by_policy(self):
        """单字白名单：**人工审校层**的单字放行，兜底索引的单字一律拦掉。

        直接测策略函数而不是造句子 —— 真实数据里「送/撤/塔」总会被更长的
        审校词条（送了/撤退/推塔）先命中，用句子断言会变成在测"哪个词条更长"。
        """
        for single in ("送", "撤", "塔"):
            with self.subTest(curated=single):
                self.assertTrue(self.g._zh_allowed(single, curated=True))
        self.assertFalse(self.g._zh_allowed("上", curated=True), "黑名单优先于单字白名单")
        self.assertFalse(self.g._zh_allowed("秒"), "兜底索引的单字要拦掉")

    def test_blocklist_file_is_loaded(self):
        self.assertTrue(self.g._zh_block, "zh_term_blocklist.json 没读到")
        self.assertIn("上", self.g._zh_block)

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

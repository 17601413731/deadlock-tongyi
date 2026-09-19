"""译文清洗测试：小模型的爱犯毛病都在这挡住。

实测（2026-09-12，Ollama + Hy-MT2）：
  · 1.8B 会把提示词里的 "TERMS: a=b" 那行抄进译文
  · 两个尺寸都会偶尔加引号/前缀/控制符
  · 整句由词典直译时要能绕过模型（ty -> 谢谢，不再被翻成"没事"）
"""

import unittest

from dlchat.chat.glossary import Glossary
from dlchat.config import TranslateSection
from dlchat.translate.client import ChatTranslator


def _translator() -> ChatTranslator:
    cfg = TranslateSection(base_url="http://localhost:11434/v1")
    return ChatTranslator(cfg, Glossary(), data_only=True)


class PostprocessTest(unittest.TestCase):
    def setUp(self):
        self.tr = _translator()

    def _clean(self, raw, direction="en->zh"):
        return self.tr._postprocess(raw, {}, direction, "src")  # noqa: SLF001

    def test_strips_terms_leak(self):
        raw = "TERMS: walker=机甲\n你干嘛独自去冲他们的机甲？"
        self.assertEqual(self._clean(raw), "你干嘛独自去冲他们的机甲？")

    def test_strips_terms_leak_multiline(self):
        raw = "TERMS: mid=中路\nTERMS: urn=魂瓮\n中路拿魂瓮"
        self.assertEqual(self._clean(raw), "中路拿魂瓮")

    def test_keeps_normal_text_with_word_terms(self):
        # 译文里正常出现 "terms" 不该被误删（只在行首且有冒号才算）
        self.assertEqual(self._clean("这是 terms 的用法"), "这是 terms 的用法")

    def test_strips_quotes_and_prefix(self):
        self.assertEqual(self._clean('"中路没人"'), "中路没人")
        self.assertEqual(self._clean("翻译：中路没人"), "中路没人")
        self.assertEqual(self._clean("Translation: mid is open", "zh->en"),
                         "mid is open")

    def test_strips_control_tokens(self):
        self.assertEqual(self._clean("中路没人<｜hy-Assistant｜>"), "中路没人")

    def test_collapses_newlines(self):
        self.assertEqual(self._clean("中路\n没人"), "中路 没人")

    def test_rejects_refusal(self):
        self.assertEqual(self._clean("抱歉，我无法完成这个翻译"), "")

    def test_rejects_untranslated_english(self):
        # 英->中方向输出还是纯英文长句 -> 当成失败（触发重试）
        self.assertEqual(self._clean("the mid lane is currently empty"), "")

    def test_short_ascii_allowed(self):
        # gg 这类保留词本来就该是英文
        self.assertEqual(self._clean("gg"), "gg")


class DictionaryShortcutTest(unittest.IsolatedAsyncioTestCase):
    """整句被俚语词典覆盖时不应该调用模型（data_only 模式没有 client，会直接报错）。"""

    async def test_slang_only_message_bypasses_model(self):
        tr = _translator()
        self.assertIsNone(tr._client)  # noqa: SLF001  data_only 模式没有后端
        self.assertEqual(await tr.translate_full("ty", "en->zh"), "谢谢")
        self.assertEqual(await tr.translate_full("thx", "en->zh"), "谢谢")
        self.assertEqual(await tr.translate_full("omw", "en->zh"), "在路上")

    async def test_keep_as_is_survives_shortcut(self):
        tr = _translator()
        self.assertEqual(await tr.translate_full("gg wp", "en->zh"), "gg wp")

    async def test_mixed_message_still_needs_model(self):
        tr = _translator()
        # "mid no" 里的 no 不在词典，必须走模型；data_only 没有 client，
        # 应该优雅地返回空串（而不是抛异常，也不该乱给结果）
        self.assertEqual(await tr.translate_full("mid no", "en->zh"), "")


if __name__ == "__main__":
    unittest.main()

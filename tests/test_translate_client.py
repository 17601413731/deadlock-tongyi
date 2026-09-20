"""翻译客户端：本地后端必须绕过系统代理（否则拿到假的 503）。

另外半边是 DeepSeek 接入的硬约束：
  · 它**默认开思考模式**（effort=high），一句短聊天会先产出一大段思维链，
    所以必须显式发 thinking:{"type":"disabled"}；
  · 但别的 OpenAI 兼容端点收到没见过的字段可能直接 400，所以只能按端点分流。
下面每个断言都对着"实际发出去的请求体"，不是对着我们的中间变量。
"""

import json
import unittest

import httpx

from dlchat.chat.glossary import Glossary
from dlchat.config import TranslateSection
from dlchat.translate.client import (ChatTranslator, build_http_client, describe_error,
                                     is_deepseek_url, is_local_url)


class LocalUrlTest(unittest.TestCase):
    def test_local_urls_detected(self):
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:11434/v1",
                    "http://127.0.0.2:8080/v1", "http://[::1]:11434/v1"):
            self.assertTrue(is_local_url(url), url)

    def test_remote_urls_not_local(self):
        for url in ("https://api.deepseek.com/v1",
                    "https://api.openai.com/v1",
                    "http://192.168.1.50:11434/v1",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"):
            self.assertFalse(is_local_url(url), url)

    def test_local_gets_proxy_bypassing_client(self):
        client = build_http_client("http://127.0.0.1:11434/v1", 5.0)
        self.assertIsNotNone(client, "本地后端必须给出绕过代理的 httpx 客户端")
        self.assertFalse(client.trust_env)
        import asyncio

        asyncio.run(client.aclose())

    def test_remote_gets_default_behavior(self):
        self.assertIsNone(build_http_client("https://api.deepseek.com/v1", 5.0))

    def test_translator_uses_bypassing_client_for_local(self):
        cfg = TranslateSection(base_url="http://localhost:11434/v1", api_key="none")
        tr = ChatTranslator(cfg, Glossary(), data_only=False)
        self.assertIsNotNone(tr._http_client)  # noqa: SLF001
        self.assertFalse(tr._http_client.trust_env)  # noqa: SLF001
        import asyncio

        asyncio.run(tr.close())

    def test_translator_keeps_proxy_for_cloud(self):
        cfg = TranslateSection(base_url="https://api.deepseek.com/v1", api_key="x")
        tr = ChatTranslator(cfg, Glossary(), data_only=False)
        self.assertIsNone(tr._http_client)  # noqa: SLF001
        import asyncio

        asyncio.run(tr.close())

    def test_data_only_creates_no_client(self):
        cfg = TranslateSection(base_url="http://localhost:11434/v1")
        tr = ChatTranslator(cfg, Glossary(), data_only=True)
        self.assertIsNone(tr._client)  # noqa: SLF001
        self.assertIsNone(tr._http_client)  # noqa: SLF001


class DeepSeekUrlTest(unittest.TestCase):
    def test_deepseek_detected(self):
        for url in ("https://api.deepseek.com/v1", "https://api.deepseek.com",
                    "https://api.deepseek.com/anthropic"):
            self.assertTrue(is_deepseek_url(url), url)

    def test_other_endpoints_not_deepseek(self):
        # 混进来的相似域名不能误判（否则会给别人的端点发 thinking 字段）
        for url in ("https://api.deepseek.com.evil.test/v1",
                    "https://api.openai.com/v1",
                    "http://localhost:11434/v1",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1"):
            self.assertFalse(is_deepseek_url(url), url)


class ExtraBodyTest(unittest.TestCase):
    """按端点分流：本地发 keep_alive，DeepSeek 发 thinking，别的端点什么都不发。"""

    def _body(self, base_url, **over):
        cfg = TranslateSection(base_url=base_url, **over)
        return ChatTranslator(cfg, Glossary(), data_only=True)._extra_body()  # noqa: SLF001

    def test_local_gets_keep_alive_only(self):
        body = self._body("http://localhost:11434/v1", keep_alive="60m")
        self.assertEqual(body, {"keep_alive": "60m"})
        self.assertNotIn("thinking", body)

    def test_deepseek_disables_thinking(self):
        body = self._body("https://api.deepseek.com/v1", thinking="off")
        self.assertEqual(body, {"thinking": {"type": "disabled"}})
        self.assertNotIn("keep_alive", body, "云端不认 keep_alive，发过去是噪音")

    def test_deepseek_thinking_auto_sends_nothing(self):
        # auto = 不表态（给'我就想看思维链'的调试场景留的口子）
        self.assertIsNone(self._body("https://api.deepseek.com/v1", thinking="auto"))

    def test_third_party_endpoint_gets_nothing(self):
        self.assertIsNone(self._body("https://dashscope.aliyuncs.com/compatible-mode/v1"))
        self.assertIsNone(self._body("https://api.openai.com/v1", keep_alive="60m"))


class RequestBodyTest(unittest.IsolatedAsyncioTestCase):
    """真正发一次请求，断言实际出去的 JSON（这才是 DeepSeek 那边看到的东西）。"""

    async def _capture(self, cfg: TranslateSection) -> dict:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content.decode("utf-8")))
            chunks = [{"id": "1", "object": "chat.completion.chunk", "created": 0,
                       "model": cfg.model,
                       "choices": [{"index": 0, "finish_reason": None,
                                    "delta": {"content": "中路没人"}}]}]
            body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
            body += "data: [DONE]\n\n"
            return httpx.Response(200, content=body.encode("utf-8"), headers={
                "Content-Type": "text/event-stream"})

        tr = ChatTranslator(cfg, Glossary(), data_only=False)
        await tr.close()                       # 丢掉它自己建的客户端
        tr._client = _MockClient(httpx.MockTransport(handler))  # noqa: SLF001
        out = await tr.translate_full("mid no", "en->zh")
        self.assertEqual(out, "中路没人")
        return seen

    async def test_deepseek_request_disables_thinking(self):
        body = await self._capture(TranslateSection(
            base_url="https://api.deepseek.com/v1", api_key="sk-test",
            model="deepseek-flash", thinking="off"))
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["thinking"], {"type": "disabled"})
        self.assertEqual(body["temperature"], 0.0, "短句必须温度 0")
        self.assertNotIn("keep_alive", body)
        # 术语/少样本提示词照旧：静态 system + 逐条 few-shot
        self.assertEqual(body["messages"][0]["role"], "system")

    async def test_local_request_keeps_keep_alive(self):
        body = await self._capture(TranslateSection(
            base_url="http://localhost:11434/v1", api_key="none",
            model="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M", thinking="off"))
        self.assertEqual(body["keep_alive"], "60m")
        self.assertNotIn("thinking", body)


class HintPipelineTest(unittest.TestCase):
    """译前改写（俚语替换）之后，术语约束必须跟着一起下发。

    背景（实测）：`apply_slang` 把 "mid/urn/low" 替换成中文之后，`terms_for` 在
    改写后的文本上再也找不到这些英文词 —— 结果最该锁术语的短句
    （"push mid and get urn"）一条 TERMS 都没拿到，模型只能自由发挥。
    修法：`apply_slang` 返回替换账本，由 `_hints_for` 合成提示行。
    """

    def setUp(self):
        self.g = Glossary()
        self.tr = ChatTranslator(
            TranslateSection(base_url="http://localhost:11434/v1"),
            self.g, data_only=True)

    def _en_zh(self, text: str) -> str:
        prepared, stash, locked = self.tr._prepare(text, "en->zh")  # noqa: SLF001
        terms = self.tr._hints_for(prepared, "en->zh", locked)      # noqa: SLF001
        from dlchat.translate.prompt import build_messages
        msgs = build_messages(prepared, "en->zh", terms,
                              keep_all=self.g.keep, locked=locked)
        return msgs[-1]["content"]

    def test_locked_line_carries_substituted_terms(self):
        msg = self._en_zh("push mid and get urn")
        first = msg.splitlines()[0]
        self.assertTrue(first.startswith("LOCKED:"), first)
        self.assertIn("mid=中路", first)
        self.assertIn("urn=魂瓮", first)

    def test_body_keeps_the_rewritten_text(self):
        """正文仍是改写后的文本（模型看到的就是它），LOCKED 只是词义表。"""
        msg = self._en_zh("mid no")
        self.assertTrue(msg.endswith("中路 no"))

    def test_no_locked_line_when_nothing_substituted(self):
        msg = self._en_zh("nice fight")
        self.assertNotIn("LOCKED:", msg)

    def test_locked_never_duplicates_a_terms_entry(self):
        """同一个来源词不能既在 LOCKED 又在 TERMS 里出现两次。

        「push」同时命中了 slang 和术语表（两边都是 推进）——必须只留一条，
        否则提示词里同一对词出现两遍，白烧 token 还容易让模型当成两件事。
        """
        msg = self._en_zh("push mid and get urn")
        lines = [ln for ln in msg.splitlines() if ln.startswith(("LOCKED:", "TERMS:"))]
        self.assertTrue(lines, msg)
        seen: list[str] = []
        for line in lines:
            for pair in line.split(":", 1)[1].split(";"):
                src = pair.split("=")[0].strip().lower()
                if src:
                    seen.append(src)
        self.assertEqual(len(seen), len(set(seen)), f"有重复来源词：{seen}\n{msg}")

    def test_zh_to_en_has_no_locked_line(self):
        prepared, stash, locked = self.tr._prepare("中路没人", "zh->en")  # noqa: SLF001
        self.assertEqual((prepared, stash, locked), ("中路没人", {}, []))


class ContextWindowTest(unittest.TestCase):
    """上下文只给接收方向；发送方向不该带屏幕上别人的聊天历史。"""

    def setUp(self):
        self.g = Glossary()

    def _tr(self, rounds: int) -> ChatTranslator:
        return ChatTranslator(
            TranslateSection(base_url="http://localhost:11434/v1",
                             context_window=rounds),
            self.g, data_only=True)

    def test_receive_direction_keeps_history(self):
        tr = self._tr(1)
        tr._remember("en->zh", "mid no", "中路没人")      # noqa: SLF001
        self.assertEqual(tr._history_for("en->zh"), [("mid no", "中路没人")])  # noqa: SLF001

    def test_send_direction_never_keeps_history(self):
        tr = self._tr(1)
        tr._remember("zh->en", "别送了", "stop feeding")  # noqa: SLF001
        self.assertEqual(tr._history_for("zh->en"), [])   # noqa: SLF001

    def test_history_is_capped_by_rounds(self):
        tr = self._tr(1)
        for i in range(5):
            tr._remember("en->zh", f"line {i}", f"第{i}句")  # noqa: SLF001
        self.assertEqual(len(tr._history_for("en->zh")), 1)   # noqa: SLF001

    def test_zero_rounds_disables_context(self):
        tr = self._tr(0)
        tr._remember("en->zh", "mid no", "中路没人")      # noqa: SLF001
        self.assertEqual(tr._history_for("en->zh"), [])   # noqa: SLF001

    def test_reset_context_clears_it(self):
        tr = self._tr(2)
        tr._remember("en->zh", "a", "甲")                 # noqa: SLF001
        tr.reset_context()
        self.assertEqual(tr._history_for("en->zh"), [])   # noqa: SLF001


class SourceLanguagePromptTest(unittest.TestCase):
    """非英语源语言（俄语）要用自己的提示词，不能拿"英译中"硬套。

    背景：以前 mod 把西里尔字母的消息判成"非英文"直接丢掉（静默失败）；
    更早的版本则是当成英文硬翻，输出里夹着没翻的俄文、又被"无汉字即失败"丢掉。
    """

    def setUp(self):
        self.g = Glossary()
        self.tr = ChatTranslator(
            TranslateSection(base_url="http://localhost:11434/v1"),
            self.g, data_only=True)

    def _system(self, source_lang: str) -> str:
        from dlchat.translate.prompt import build_messages
        msgs = build_messages("привет", "en->zh", [], keep_all=self.g.keep,
                              source_lang=source_lang)
        return msgs[0]["content"]

    def test_russian_gets_its_own_system_prompt(self):
        ru = self._system("ru")
        self.assertIn("俄语", ru)
        self.assertNotIn("玩家会发英文聊天", ru)

    def test_russian_gets_russian_fewshot(self):
        """few-shot 是"输出长什么样"的唯一示范，源语言错配会把模型带偏。

        以前俄语消息配的是英译中的示例（"mid no → 中路没人"），模型会以为
        源语言是英文 —— 西里尔字母被当人名原样带进译文，然后被"无汉字即失败"丢掉。
        """
        from dlchat.translate.prompt import build_messages, fewshot
        ru = fewshot("en->zh", "ru")
        self.assertTrue(ru)
        self.assertTrue(all(any("\u0400" <= ch <= "\u04ff" for ch in src)
                            for src, _ in ru), "俄语 few-shot 的原文必须是西里尔字母")
        msgs = build_messages("привет", "en->zh", [], keep_all=[], source_lang="ru")
        contents = [m["content"] for m in msgs]
        self.assertTrue(any("мид" in c for c in contents), "应带上俄语示例")
        self.assertFalse(any(c == "mid no" for c in contents), "不该混进英文示例")

    def test_greek_shares_the_russian_prompt(self):
        from dlchat.translate.prompt import fewshot
        self.assertEqual(fewshot("en->zh", "el"), fewshot("en->zh", "ru"))

    def test_english_prompt_unchanged(self):
        self.assertIn("玩家会发英文聊天", self._system("en"))

    def test_unknown_source_falls_back_to_english(self):
        self.assertEqual(self._system("xx"), self._system("en"))

    def test_zh_to_en_ignores_source_language(self):
        from dlchat.translate.prompt import build_messages
        a = build_messages("别送了", "zh->en", [], keep_all=[], source_lang="ru")[0]
        b = build_messages("别送了", "zh->en", [], keep_all=[], source_lang="en")[0]
        self.assertEqual(a, b)

    def test_system_prefix_stays_static_per_language(self):
        """同一源语言下 system 必须逐字节稳定（前缀缓存的前提）。"""
        self.assertEqual(self._system("ru"), self._system("ru"))
        from dlchat.translate.prompt import build_messages
        m1 = build_messages("привет", "en->zh", [("mid", "中路")], keep_all=["gg"],
                            source_lang="ru")
        m2 = build_messages("пока", "en->zh", [], keep_all=["gg"], source_lang="ru")
        self.assertEqual(m1[0], m2[0])


class ErrorMessageTest(unittest.TestCase):
    """云端配错时必须给出"能照着修"的一句话，而不是 translate_failed。"""

    def _err(self, status):
        req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
        resp = httpx.Response(status, request=req)
        return httpx.HTTPStatusError("boom", request=req, response=resp)

    def test_401_says_key_problem_and_where_to_fix(self):
        msg = describe_error(self._err(401))
        self.assertIn("API Key", msg)
        self.assertIn("8791/settings", msg)

    def test_402_says_balance(self):
        self.assertIn("余额", describe_error(self._err(402)))

    def test_429_says_rate_limited(self):
        self.assertIn("限流", describe_error(self._err(429)))

    def test_500_says_server_side(self):
        self.assertIn("DeepSeek", describe_error(self._err(503)))

    def test_timeout_says_proxy(self):
        msg = describe_error(httpx.ConnectTimeout("timed out"))
        self.assertIn("超时", msg)

    def test_unknown_error_still_readable(self):
        self.assertIn("boom", describe_error(RuntimeError("boom")))


class _MockClient:
    """只实现 ChatTranslator 用到的那一小块：chat.completions.create。"""

    def __init__(self, transport: httpx.MockTransport):
        import openai

        self._openai = openai.AsyncOpenAI(
            api_key="sk-test", base_url="https://api.deepseek.com/v1",
            http_client=httpx.AsyncClient(transport=transport))

    @property
    def chat(self):
        return self._openai.chat


if __name__ == "__main__":
    unittest.main()

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

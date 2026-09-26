"""本地翻译桥的协议测试（不联网、不依赖模型）。

重点是**协议必须和游戏内 mod 对齐**：BabelTower 的 Panorama 侧按这套约定说话，
字段错了游戏里就会显示"桥未运行"或译文空白。
"""

import json
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

from dlchat import paths as dlchat_paths
from dlchat.bridge.server import (BridgeApp, BridgeServer, bridge_page, decode_provider,
                                  decode_separator)
from dlchat.config import Config
from dlchat.settings import AppSettings, settings_path

# 游戏通道的硬上限：compact 设置响应写进 HTML 文档标题再读回来，实测 479 字符会被
# 截断成半截 JSON（面板上一片 undefined）。
#   380 = 自检脚本的警戒线（模型名一长就可能超过，只是警告）
#   440 = 桥自己的硬上限（_fit_compact 会主动裁字段，保证不越过这条线）
COMPACT_LIMIT = 380
COMPACT_HARD_LIMIT = 440
# 本机真实存在的最长模型名（本地来源的"最坏情况"）
LONG_LOCAL_MODEL = "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _StubTranslator:
    """假装是本地模型：原样加前缀返回，便于断言走的是哪条路。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.last_error = ""

    async def translate_full(self, text: str, direction: str,
                             source_lang: str = "en") -> str:
        self.calls.append((text, direction, source_lang))
        return f"[{direction}]{text}"

    async def prewarm(self) -> bool:
        return True

    async def close(self) -> None:
        pass


def _app() -> BridgeApp:
    cfg = Config()
    cfg.translate.model = "test-model"
    app = BridgeApp(cfg)
    app.translator = _StubTranslator()

    def _fake_run(coro):
        # 直接把协程跑完（stub 是纯 async 函数，不需要事件循环线程）
        import asyncio

        return asyncio.run(coro)

    app._run_async = _fake_run              # noqa: SLF001
    return app


# 整个测试模块都把用户目录指到临时目录。
# 为什么要在模块级而不是各测试的 setUp 里：BridgeApp 一构造就读
# %APPDATA%\deadlock-tongyi\settings.json，而 HttpProtocolTest 是在 setUpClass 里构造的
# —— 实例级 patch 还没生效。不隔离的话，跑一次测试就会把用户正在用的设置改掉
# （自检脚本踩过同样的坑）。
_module_tmp = tempfile.TemporaryDirectory()
_module_patch = mock.patch.object(dlchat_paths, "user_dir",
                                  lambda: Path(_module_tmp.name))
_module_patch.start()


def tearDownModule():                       # noqa: N802  (unittest 约定的名字)
    _module_patch.stop()
    _module_tmp.cleanup()


class _IsolatedSettingsTest(unittest.TestCase):
    """需要一个干净用户目录的测试：这里只是把"隔离已生效"显式声明出来。"""

    def setUp(self):
        # 每个测试都从"没保存过设置"开始：否则前一个测试写下的
        # provider=deepseek 会被下一个测试的 app 读走，表现成"翻译突然失败"。
        settings_path().unlink(missing_ok=True)

    def tearDown(self):
        settings_path().unlink(missing_ok=True)

    def assert_isolated(self) -> None:
        """自证：写的是临时目录里的文件，不是用户那份。"""
        self.assertEqual(settings_path().parent, Path(_module_tmp.name))


class _RestoringSettingsTest(_IsolatedSettingsTest):
    """类级别共用一个 app 的测试（如 HTTP 全链路）。

    这类测试里"切来源"的用例会把 app 的设置改掉，如果不管，后面的用例就在
    provider=deepseek 的状态上跑 —— 表现为一串莫名其妙的 502（实测踩到过）。
    所以每个用例跑完都把 app 的设置恢复原样。
    """

    app: BridgeApp

    def setUp(self):
        super().setUp()
        self._saved = (self.app.settings, self.app.cache, self.app.translator)

    def tearDown(self):
        # translator 也要还原：切来源会触发 _rebuild_translator()，把测试用的 stub
        # 换成一个真的客户端 —— 后面的用例就会真去请求外网（实测跑出过 502 和
        # 一条到 api.deepseek.com 的连接）。
        (self.app.settings, self.app.cache, self.app.translator) = self._saved
        super().tearDown()


class DirectionTest(unittest.TestCase):
    def test_zh_to_en(self):
        self.assertEqual(BridgeApp._direction("中路没人", "auto", "en"), "zh->en")

    def test_en_to_zh(self):
        self.assertEqual(BridgeApp._direction("mid no", "auto", "zh-Hans"), "en->zh")

    def test_already_target_skipped(self):
        self.assertIsNone(BridgeApp._direction("中路没人", "auto", "zh-Hans"))
        self.assertIsNone(BridgeApp._direction("mid no", "auto", "en"))

    def test_explicit_source_wins(self):
        self.assertEqual(BridgeApp._direction("hi", "zh", "en"), "zh->en")
        self.assertEqual(BridgeApp._direction("hi", "en", "zh-CN"), "en->zh")

    # ---- 非拉丁字母的语言（俄语）----
    # 以前 mod 把西里尔字母判成"非英文"直接丢掉，玩家看到的是"这条永远不翻"。

    def test_russian_auto_is_detected_and_sent_to_zh(self):
        self.assertEqual(BridgeApp._detect_language("привет как дела"), "ru")
        self.assertEqual(BridgeApp._direction("привет как дела", "auto", "zh-Hans"),
                         "en->zh")

    def test_russian_to_english_is_left_alone(self):
        """没有"俄->英"的提示词，就别硬翻（原样返回比瞎翻好）。"""
        self.assertIsNone(BridgeApp._direction("привет", "ru", "en"))

    def test_greek_detected(self):
        self.assertEqual(BridgeApp._detect_language("καλημέρα"), "el")

    def test_detection_order_prefers_chinese(self):
        """中英混排（"上 mid"）必须判成中文，不能因为字母少就判英文。"""
        self.assertEqual(BridgeApp._detect_language("上 mid"), "zh")

    def test_detected_language_reported_honestly(self):
        """回包里的 detectedLanguage 以前是按方向猜的（俄语会被报成 en）。"""
        self.assertEqual(BridgeApp._detected("en->zh", "ru"), "ru")
        self.assertEqual(BridgeApp._detected("en->zh", "en"), "en")
        self.assertEqual(BridgeApp._detected("en->zh", ""), "en")


class BridgePageTest(unittest.TestCase):
    def test_page_implements_title_protocol(self):
        html = bridge_page({"id": ["42"], "op": ["translate"]})
        self.assertIn("document.title", html)
        self.assertIn("'LCT' + id", html)
        self.assertIn("42", html)
        self.assertIn("/api/v1/", html)
        self.assertIn("bridge_timeout", html)   # 超时要能回一个错误而不是干等

    def test_page_op_sanitized(self):
        html = bridge_page({"id": ["1"], "op": ["translate';alert(1)//"]})
        self.assertNotIn("alert", html)


class AppLogicTest(unittest.TestCase):
    def test_translate_uses_stub(self):
        app = _app()
        r = app.translate("mid no", "auto", "zh-Hans")
        self.assertTrue(r["ok"])
        self.assertEqual(r["detectedLanguage"], "en")
        self.assertTrue(r["translation"])

    def test_second_call_hits_cache(self):
        app = _app()
        app.translate("mid no", "auto", "zh-Hans")
        r2 = app.translate("mid no", "auto", "zh-Hans")
        self.assertTrue(r2.get("viaCache"))
        self.assertEqual(app.stats["cache_hits"], 1)

    def test_empty_text_rejected(self):
        self.assertFalse(_app().translate("   ", "auto", "zh-Hans")["ok"])

    def test_already_target_language_passthrough(self):
        r = _app().translate("中路没人", "auto", "zh-Hans")
        self.assertTrue(r["ok"])
        self.assertEqual(r["skipped"], "already_target_language")
        self.assertEqual(r["translation"], "中路没人")

    def test_health_shape(self):
        h = _app().health()
        for key in ("ok", "name", "version", "provider", "providers", "chatLog"):
            self.assertIn(key, h)
        self.assertIn("terms", h["glossary"])

    def test_health_does_not_wait_for_translation_backend(self):
        app = _app()
        for provider, base_url in (("local", "http://localhost:11434/v1"),
                                   ("deepseek", "https://api.deepseek.com/v1")):
            with self.subTest(provider=provider):
                app.settings = AppSettings(provider=provider, base_url=base_url,
                                           model="test-model")
                with mock.patch.object(app, "backend_status",
                                       side_effect=AssertionError("health probed backend")):
                    self.assertTrue(app.health()["ok"])

    def test_cloud_settings_do_not_probe_ollama(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1")
        with mock.patch("dlchat.bridge.server._no_proxy_opener",
                        side_effect=AssertionError("cloud called Ollama probe")):
            self.assertEqual(app.backend_status(), {})
            self.assertEqual(app.settings_view(compact=True)["vram"], -1)
            self.assertEqual(app.settings_view()["backend"], {})

    def test_health_reports_which_files_are_in_use(self):
        """"我改了怎么没反应"要能问出答案。

        项目目录的 config.yaml 和 %APPDATA% 的 settings.json 是两份文件、优先级还不一样。
        答案放在**完整设置视图**里，不放 health —— health 每 15 秒被游戏问一次，
        而且要经 HTML 标题通道传回去（长度硬上限 ~900 字符），塞进去就没余量了。
        """
        app = _app()
        h = app.health()
        self.assertNotIn("settingsFile", h, "health 要留短：标题通道有长度上限")
        resource = app.settings_view()["resource"]
        self.assertTrue(resource["settingsFile"])
        self.assertTrue(resource["configFile"])
        self.assertEqual(Path(resource["settingsFile"]).parent, settings_path().parent)

    def test_health_stays_small(self):
        """health 是被游戏反复拉取的，必须留足标题通道的余量。"""
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   api_key="sk-" + "x" * 24)
        blob = json.dumps(app.health(), ensure_ascii=False)
        self.assertLess(len(blob), 700, f"health 涨到 {len(blob)} 字符了")

    def test_gamenames_shape(self):
        g = _app().game_names()
        self.assertTrue(g["ok"])
        self.assertGreater(g["count"], 100)
        self.assertIsInstance(g["names"], dict)

    def test_config_has_no_secrets(self):
        cfg = _app().config_view()["config"]
        blob = json.dumps(cfg, ensure_ascii=False).lower()
        for bad in ("apikey", "api_key", "secret", "token"):
            self.assertNotIn(bad, blob)


class ProviderCodeTest(unittest.TestCase):
    """来源在游戏通道里是单字母码（字段名和取值都要短）。"""

    def test_decodes_letters_and_names(self):
        self.assertEqual(decode_provider("l"), "local")
        self.assertEqual(decode_provider("d"), "deepseek")
        self.assertEqual(decode_provider("o"), "openai")
        self.assertEqual(decode_provider("deepseek"), "deepseek")
        self.assertEqual(decode_provider(" deepseek "), "deepseek")

    def test_unknown_is_none_not_a_guess(self):
        # 认不出来必须回 None（= 不改来源），绝不猜一个值去覆盖用户设置
        for bad in ("", None, "claude", "云", "1"):
            self.assertIsNone(decode_provider(bad), bad)


class DeepSeekProviderTest(_IsolatedSettingsTest):
    """mod 面板切到 DeepSeek 后，桥要按来源给模型列表、给状态、给错误提示。"""

    def test_cloud_provider_lists_deepseek_models(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="sk-test")
        out = app.list_models()
        self.assertEqual(out["provider"], "deepseek")
        self.assertIn("deepseek-flash", out["models"])
        # 退役的别名不该再出现在下拉里（选了照样能用，但会误导）
        self.assertNotIn("deepseek-v4-flash", out["models"])

    def test_panel_provider_argument_wins_over_saved_one(self):
        """用户还没点保存，面板已经切到 DeepSeek —— 列表必须按面板上的来源给。"""
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        out = app.list_models("deepseek")
        self.assertEqual(out["provider"], "deepseek")
        self.assertEqual(out["models"], ["deepseek-flash", "deepseek-v4-pro"])

    def test_local_provider_asks_ollama_not_the_cloud(self):
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        asked: list[str] = []
        app._ollama_models = lambda base: (asked.append(base), [])[1]  # noqa: SLF001
        app.list_models("local")
        # 面板停在"本地"但当前生效的是云端地址时，也必须问本地那个地址
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1")
        app.list_models("local")
        self.assertIn("http://localhost:11434", asked[0])

    def test_health_reports_active_provider_not_the_config_default(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="sk-test")
        h = app.health()
        self.assertEqual(h["provider"], "deepseek:deepseek-flash")
        self.assertTrue(h["keySet"])
        self.assertEqual(h["providerLabel"], "DeepSeek 云端")

    def test_health_flags_missing_key(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="")
        self.assertFalse(app.health()["keySet"])

    def test_settings_test_without_key_says_where_to_configure(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="")
        out = app.settings_test()
        self.assertFalse(out["ok"])
        self.assertIn("8791/settings", out["hint"] or "")
        self.assertFalse(out["keySet"])

    def test_settings_test_rejects_the_literal_none_key(self):
        """默认值是字面量 "none"，它不算"配好了" —— 否则会拿着它去请求，拿回一个 401。"""
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="none")
        out = app.settings_test()
        self.assertFalse(out["ok"])
        self.assertFalse(out["keySet"])

    def test_api_key_is_masked_in_settings_view(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="sk-abcdefghijklmnop")
        view = app.settings_view()
        self.assertNotIn("sk-abcdefghijklmnop", json.dumps(view))
        self.assertTrue(view["api_key"])
        self.assertTrue(view["keySet"])

    def test_translate_error_is_carried_through_to_the_mod(self):
        """云端配错时，游戏面板要看到"能照着修"的那句话，而不是 empty_translation。"""
        app = _app()
        stub = _StubTranslator()
        stub.last_error = ("API Key 无效或未设置"
                           "（在 http://localhost:8791/settings 里填）")

        async def _fail(text, direction, source_lang="en"):
            return ""

        stub.translate_full = _fail
        app.translator = stub
        out = app.translate("mid no", "en", "zh-Hans")
        self.assertFalse(out["ok"])
        self.assertIn("API Key", out["error"])

    def test_switching_provider_rewrites_model_and_base_url(self):
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        out = app.update_settings({"prv": "d"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(app.settings.provider, "deepseek")
        self.assertEqual(app.settings.base_url, "https://api.deepseek.com/v1")
        # 本地模型名在云端不存在，必须自动换成该来源的有效模型
        self.assertEqual(app.settings.model, "deepseek-flash")
        # 回执里也要带上新来源，面板据此立刻刷新显示
        self.assertEqual(out["settings"]["prv"], "d")

    def test_switching_provider_accepts_the_pv_spelling(self):
        """mod 发的字段叫 pv，桥两种写法都得认 —— 认错了就是"说保存成功、其实没变"。"""
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        app.update_settings({"pv": "d"})
        self.assertEqual(app.settings.provider, "deepseek")

    def test_switching_back_to_local_picks_an_installed_model(self):
        app = _app()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="sk-test")
        # 假装本机 Ollama 装着这些模型（离线，不问真的）
        app._ollama_models = lambda base: ["hy-mt2:1.8b-q8_0", LONG_LOCAL_MODEL]  # noqa: SLF001
        app.update_settings({"pv": "l"})
        self.assertEqual(app.settings.provider, "local")
        self.assertEqual(app.settings.base_url, "http://localhost:11434/v1")
        # 本地没有固定清单 -> 取本机装着的第一个；留空的话下一次翻译会 400
        self.assertEqual(app.settings.model, "hy-mt2:1.8b-q8_0")

    def test_empty_model_gives_a_readable_error_instead_of_a_400(self):
        """Ollama 没在跑时本地清单是空的，模型名会是空串。

        这时候直接报"model is required"玩家看不懂；要给一句能照着做的话。
        """
        app = _app()
        app.settings = AppSettings(provider="local", model="",
                                   base_url="http://localhost:11434/v1")
        out = app.translate("mid no", "en", "zh-Hans")
        self.assertFalse(out["ok"])
        self.assertIn("翻译模型", out["error"])
        # 指路必须指向**真的能打开面板**的方式：F8 那个键绑定实测无效，早就删了
        self.assertIn("/tongyi", out["error"])
        self.assertNotIn("F8", out["error"])

    def test_switching_provider_keeps_a_valid_explicit_model(self):
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        app.update_settings({"prv": "d", "model": "deepseek-v4-pro"})
        self.assertEqual(app.settings.model, "deepseek-v4-pro")

    def test_unknown_provider_does_not_change_anything(self):
        app = _app()
        app.settings = AppSettings(provider="local", model=LONG_LOCAL_MODEL,
                                   base_url="http://localhost:11434/v1")
        app.update_settings({"pv": "zzz"})
        self.assertEqual(app.settings.provider, "local")
        self.assertEqual(app.settings.model, LONG_LOCAL_MODEL)


class SeparatorTest(_IsolatedSettingsTest):
    """双语模式下中英之间拼什么。只是拼给你看的一串字，但选错了很难看。"""

    def test_decodes_letter_codes_and_names(self):
        self.assertEqual(decode_separator("p"), "pipe")
        self.assertEqual(decode_separator("f"), "full")
        self.assertEqual(decode_separator("s"), "space")
        self.assertEqual(decode_separator("full"), "full")
        for bad in ("", None, "x", "竖线"):
            self.assertIsNone(decode_separator(bad), bad)

    def test_compact_ships_the_short_code(self):
        app = _app()
        app.settings = AppSettings(separator="full")
        payload = app.settings_view(compact=True, with_backend=False)
        self.assertEqual(payload["sep"], "f")

    def test_translate_hints_ship_the_real_separator(self):
        """mod 拼输入框那串字时用它，所以必须是能直接拼的字符串，不是选项名。"""
        app = _app()
        for choice, want in (("pipe", " | "), ("full", " ｜ "), ("space", "  ")):
            app.settings = AppSettings(separator=choice)
            self.assertEqual(app._ui_hints()["separator"], want, choice)  # noqa: SLF001

    def test_save_then_hints_follow(self):
        app = _app()
        out = app.update_settings({"separator": "space"})
        self.assertTrue(out["ok"], out)
        self.assertEqual(app.settings.separator, "space")
        self.assertEqual(app._ui_hints()["separator"], "  ")  # noqa: SLF001

    def test_bad_separator_is_rejected_not_silently_kept(self):
        app = _app()
        out = app.update_settings({"separator": "斜线"})
        self.assertFalse(out["ok"])
        self.assertIn("invalid_settings", out["error"])


class ApiKeyPrecedenceTest(_IsolatedSettingsTest):
    """密钥取哪一份 —— 这条链上任何一步出错，表现都是"云端 401"，很难查。"""

    def _write(self, payload: dict) -> None:
        settings_path().write_text(json.dumps(payload, ensure_ascii=False),
                                   encoding="utf-8")

    def test_old_settings_with_literal_none_key_is_migrated(self):
        """老版本把 "none"（= 本地不需要密钥）写进了覆盖层。

        覆盖层优先级高于 config.yaml，所以这五个字符会把 config.yaml 里配好的密钥
        压死 —— 云端一切换就 401。迁移要把它清成空。

        注意：这里给 config 一个**字面量**密钥，不用项目 config.yaml 的值 ——
        默认配置里现在是 `${DEEPSEEK_API_KEY}` 占位符，本机没设这个环境变量时
        展开结果就是它自己，断言会变成在测"占位符没展开"（另一件事）。
        """
        self._write({"defaults_version": 3, "provider": "deepseek",
                     "model": "deepseek-flash", "api_key": "none"})
        cfg = Config()
        cfg.translate.api_key = "sk-from-config"
        app = BridgeApp(cfg)
        self.assertEqual(app.settings.api_key, "sk-from-config")   # "none" 不算密钥
        self.assertTrue(app.health()["keySet"])
        # 迁移结果要落盘，否则每次启动都要重来一遍
        back = json.loads(settings_path().read_text(encoding="utf-8"))
        self.assertNotEqual(back["api_key"], "none")
        self.assertGreaterEqual(back["defaults_version"], 4)

    def test_default_provider_migration_moves_endpoint_too(self):
        """默认来源从"本机 Ollama"改成"DeepSeek 云端"时，端点必须跟着走。

        只换 provider/model、留着 localhost:11434 的 base_url 的话，结果是
        "来源显示云端、请求发去打不开的本地端口"，报错还很难看懂。
        """
        self._write({"defaults_version": 4, "provider": "local",
                     "model": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
                     "base_url": "http://localhost:11434/v1", "api_key": "sk-mine"})
        app = _app()
        # 用户自己填过的密钥不能被这次迁移弄丢
        self.assertEqual(app.settings.api_key, "sk-mine")
        cfg = Config()
        from dlchat.settings import apply_to_config

        applied = apply_to_config(cfg, app.settings).translate
        self.assertEqual(applied.base_url, "https://api.deepseek.com/v1")
        self.assertEqual(applied.model, "deepseek-flash")

    def test_config_key_is_used_when_overlay_has_none(self):
        """覆盖层空着 -> 用 config.yaml 的（里面可以是 ${ENV} 展开后的结果）。"""
        cfg = Config()
        cfg.translate.api_key = "sk-from-config"
        app = BridgeApp(cfg)
        app.translator = _StubTranslator()
        app.settings = AppSettings(provider="deepseek", model="deepseek-flash",
                                   base_url="https://api.deepseek.com/v1",
                                   api_key="")
        from dlchat.settings import apply_to_config

        self.assertEqual(apply_to_config(cfg, app.settings).translate.api_key,
                         "sk-from-config")

    def test_env_placeholder_in_overlay_is_expanded(self):
        """在网页里填 ${DEEPSEEK_API_KEY} 是给用户留的口子，不能被当字面量发出去。"""
        import os

        self._write({"api_key": "${DLCHAT_TEST_KEY_X}"})
        os.environ["DLCHAT_TEST_KEY_X"] = "sk-expanded-123"
        self.addCleanup(os.environ.pop, "DLCHAT_TEST_KEY_X", None)
        app = _app()
        self.assertEqual(app.settings.api_key, "sk-expanded-123")


class CompactPayloadTest(_IsolatedSettingsTest):
    """compact 设置响应是最容易被撑爆的一条：字段长度直接决定面板会不会变 undefined。"""

    def _compact(self, provider, model):
        app = _app()
        app.settings = AppSettings(provider=provider, model=model,
                                   api_key="sk-abcdefghijklmnop")
        app.stats = {"requests": 128, "cache_hits": 55, "errors": 0}
        app._latencies = {"en->zh": [812.0], "zh->en": [210.0]}  # noqa: SLF001
        app.backend_status = lambda: {}
        payload = app.settings_view(compact=True, with_backend=False)
        return json.dumps(payload, ensure_ascii=False), payload

    def test_stays_under_the_title_channel_limit(self):
        cases = [("local", LONG_LOCAL_MODEL),
                 ("deepseek", "deepseek-flash"),
                 ("deepseek", "deepseek-v4-pro")]
        for provider, model in cases:
            with self.subTest(provider=provider, model=model):
                blob, _ = self._compact(provider, model)
                self.assertLess(len(blob), COMPACT_LIMIT,
                                f"{provider}/{model} 的 compact 响应 {len(blob)} 字符，"
                                f"超过 {COMPACT_LIMIT} 会被标题通道截断")

    def test_carries_provider_as_short_code(self):
        _, payload = self._compact("deepseek", "deepseek-flash")
        self.assertEqual(payload["prv"], "d")
        # 短键：字段名本身也是要省的地方（长键名加起来能吃掉 60+ 字符）
        for key in ("disp", "trig", "model", "keep", "out", "keySet"):
            self.assertIn(key, payload)
        self.assertNotIn("display_mode", payload)

    def test_no_secret_in_compact(self):
        blob, _ = self._compact("deepseek", "deepseek-flash")
        self.assertNotIn("sk-abcdefghijklmnop", blob)

    def test_a_long_model_name_still_fits(self):
        """126 字符的模型名照样塞得下（330→421 字符）—— 这就是字段名压成短键换来的空间。

        这个长度已经超过 agent 自检里的 380 警戒线（只是警告，不是错误），
        真正的硬上限是 440。
        """
        blob, payload = self._compact("local",
                                      "hf.co/" + "very-long-org/" * 8 + "m:Q4_K_M")
        self.assertLess(len(blob), COMPACT_HARD_LIMIT)
        self.assertFalse(payload.get("trimmed"), "还没到上限就不该裁字段")

    def test_absurdly_long_model_name_gets_trimmed_not_truncated(self):
        """再长下去（用户真能起这么长）就必须**主动裁字段**。

        宁可少显示几个统计、把模型名截短显示，也不能让包被路截断成半截 JSON ——
        那种表现是面板上一片 undefined，看着像设置全丢了。
        """
        blob, payload = self._compact("local", "hf.co/" + "z" * 300 + ":Q4_K_M")
        self.assertLess(len(blob), COMPACT_HARD_LIMIT)
        self.assertTrue(payload.get("trimmed"))
        # 核心字段一个都不能少
        for key in ("prv", "model", "disp", "trig", "keep", "out", "gloss",
                    "recv", "send", "keySet"):
            self.assertIn(key, payload)


class HttpProtocolTest(_RestoringSettingsTest):
    """真正起一个 HTTP 服务，按游戏侧的方式请求。"""

    @classmethod
    def setUpClass(cls):
        # app 在类级别构造一次，所以这里要先自己把用户设置清干净
        # （实例级 setUp 在 setUpClass 之前跑不到）。
        settings_path().unlink(missing_ok=True)
        cls.port = _free_port()
        cls.app = _app()
        cls.server = BridgeServer(cls.app, cls.port)
        cls.server.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()
        settings_path().unlink(missing_ok=True)

    def _get(self, path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=10) as r:
            return r.status, r.read().decode("utf-8")

    def _post(self, path: str, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_health(self):
        status, body = self._get("/api/v1/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_gamenames(self):
        status, body = self._get("/api/v1/gamenames")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_bridge_page_is_html(self):
        status, body = self._get("/bridge?id=9&op=translate&text=hi")
        self.assertEqual(status, 200)
        self.assertIn("LCT", body)

    def test_settings_page_is_served(self):
        """配置 API Key 的唯一入口。

        这条以前是坏的：server.py 用了 SETTINGS_PAGE 却从没 import 过它，
        表现是打开 http://localhost:8791/settings 直接断连（NameError）。
        没有协议测试盯着这一页，所以一直没人发现。
        """
        status, body = self._get("/settings")
        self.assertEqual(status, 200)
        self.assertIn("<!DOCTYPE html>", body)
        self.assertIn('id="api_key"', body)
        self.assertIn("/api/v1/settings", body)

    def test_settings_page_only_configures_the_api_key(self):
        """这一页**只**配 API Key：别的开关都在游戏内 mod 面板，两处都能改会让人猜。"""
        _, body = self._get("/settings")
        for other in ("术语表", "温度", "模型常驻", "译文显示方式", "触发键"):
            self.assertNotIn(other, body, f"{other} 不该出现在这一页")

    def test_translate_post(self):
        status, body = self._post("/api/v1/translate",
                                  {"text": "mid no", "targetLanguage": "zh-Hans"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_translate_get_with_d_param(self):
        """游戏侧 $.AsyncWebRequest 只能发 GET，请求体走 ?d=<JSON>。"""
        payload = json.dumps({"text": "mid no", "targetLanguage": "zh-Hans"})
        status, body = self._get(f"/api/v1/translate?d={urllib.parse.quote(payload)}")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_translate_get_with_plain_params(self):
        status, body = self._get("/api/v1/translate?text=mid+no&target=zh-Hans")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["ok"])

    def test_bad_request_when_text_missing(self):
        status, body = self._post("/api/v1/translate", {"targetLanguage": "zh-Hans"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])

    def test_test_endpoint(self):
        status, body = self._post("/api/v1/test", {})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_log_endpoint_is_accepted_and_ignored(self):
        status, body = self._post("/api/v1/log", {"lines": ["x"]})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_unknown_path_404(self):
        try:
            status, _ = self._get("/nope")
        except urllib.error.HTTPError as e:
            status = e.code
        self.assertEqual(status, 404)

    def test_models_endpoint_follows_the_requested_provider(self):
        """游戏侧 $.AsyncWebRequest 只能发 GET，来源走 ?d=<JSON> 传。"""
        import urllib.parse

        payload = json.dumps({"provider": "deepseek"})
        status, body = self._get(
            f"/api/v1/models?d={urllib.parse.quote(payload)}")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["provider"], "deepseek")
        self.assertIn("deepseek-flash", data["models"])

    def test_settings_write_does_not_touch_the_real_user_file(self):
        """HTTP 全链路也不许把用户的 settings.json 改掉（用户目录被隔离到临时目录）。"""
        path = settings_path()
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        self._post("/api/v1/settings", {"pv": "d"})
        self.assertTrue(path.exists(), "保存必须落盘（否则重启就丢了）")
        self.assertNotEqual(path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()

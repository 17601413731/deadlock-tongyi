"""翻译客户端：OpenAI 兼容接口（本地 Ollama / 云端 DeepSeek 等都走这里）。

与 fanyi-v5 的语音翻译器相比，这里多了三件事：
1. 整句短语直译（聊天轮盘）——命中就零延迟返回，不烧模型
2. 术语约束（官方术语表 + 社区俚语 + 保留英文清单）
3. 译后清洗——小模型常见毛病：漏控制符、加引号、加"翻译："、输出拼音
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from typing import AsyncIterator
from urllib.parse import urlsplit

import httpx
from openai import AsyncOpenAI

from ..chat.glossary import Glossary
from ..config import TranslateSection
from .prompt import build_messages

logger = logging.getLogger(__name__)

_LATIN_RE = re.compile(r"[A-Za-z]")

# 本地后端地址（这些要走直连，绕开系统代理）
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}

# DeepSeek 官方端点。只有它认 thinking 开关；别的 OpenAI 兼容端点收到未知字段
# 有的会直接 400，所以必须按端点分流，不能无脑发。
DEEPSEEK_HOST = "api.deepseek.com"


def is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local")


def is_deepseek_url(url: str) -> bool:
    """是不是 DeepSeek 官方端点（决定要不要发 thinking / 报云端错误文案）。"""
    host = (urlsplit(url).hostname or "").lower()
    return host == DEEPSEEK_HOST or host.endswith("." + DEEPSEEK_HOST)


def describe_error(exc: BaseException) -> str:
    """把后端异常翻译成"玩家看得懂、能照着修"的一句话。

    背景：以前所有失败都汇成一句 ``translate_failed``，云端配错了（key 没填 / 余额空 /
    限流）在游戏里完全看不出来 —— 而这是本工具唯一需要用户自己配的东西。
    状态码优先（最准），拿不到再退回关键词匹配。
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        resp = getattr(exc, "response", None)
        status = getattr(resp, "status_code", None)
    if status == 401 or status == 403:
        return "API Key 无效或未设置（在 http://localhost:8791/settings 里填）"
    if status == 402:
        return "账户余额不足，请到 DeepSeek 平台充值"
    if status == 429:
        return "请求被限流（稍后会自动恢复；也可在面板切回本地 Ollama）"
    if isinstance(status, int) and 500 <= status < 600:
        return f"DeepSeek 服务端错误（HTTP {status}），稍后重试"

    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "401" in low or "invalid_api_key" in low or "authentication" in low:
        return "API Key 无效或未设置（在 http://localhost:8791/settings 里填）"
    if "402" in low or "insufficient balance" in low:
        return "账户余额不足，请到 DeepSeek 平台充值"
    if "429" in low or "rate limit" in low:
        return "请求被限流（稍后会自动恢复；也可在面板切回本地 Ollama）"
    if "timeout" in low or "timed out" in low:
        return "请求超时（云端要能出网：检查系统代理是否在跑）"
    if "connect" in low or "getaddrinfo" in low or "name resolution" in low:
        return "连不上后端（网络/代理问题）"
    return text[:160]


def build_http_client(base_url: str, timeout_s: float) -> httpx.AsyncClient | None:
    """本地后端返回一个绕过系统代理的 httpx 客户端；云端返回 None（用默认行为）。

    为什么必须这么做：Windows 上开着代理（例如 v2rayN 设了 127.0.0.1:10808）时，
    httpx 只读 ProxyServer、**不读系统的"绕过代理"列表**，于是连 http://127.0.0.1:11434
    这种本地 Ollama 请求也会被塞进代理，直接拿到 HTTP 503 —— 表现为"翻译后端连不上"，
    非常难查。云端地址保持走代理（你可能正需要它）。
    """
    if not is_local_url(base_url):
        return None
    return httpx.AsyncClient(trust_env=False, timeout=timeout_s)

# 小模型可能漏出来的控制符 / 特殊 token
_CONTROL_RE = re.compile(r"<[｜|][^>]*[｜|]>|<\|[^|]*\|>|</?s>|<eos>|<pad>")
# 模型把提示词里的 "TERMS: a=b; c=d" / "LOCKED: ..." 那行当正文抄进译文了
# （实测 1.8B 会这样）
_TERMS_LEAK_RE = re.compile(r"^\s*(?:TERMS|LOCKED)\s*[:：].*$", re.I | re.M)
# 连同 LOCKED 下面那句中文说明一起吃掉（模型偶尔会连着抄）
_LOCKED_NOTE_RE = re.compile(r"^\s*（LOCKED[^）]*）\s*$", re.M)
# 模型爱加的前缀
_PREFIX_RE = re.compile(
    r"^\s*(翻译|译文|中文|英文|translation|translated|output|english|chinese)\s*[:：]\s*",
    re.I,
)
_QUOTE_CHARS = "\"'“”‘’「」『』"
# 拒绝/道歉之类的失败输出
_REFUSAL_RE = re.compile(r"(抱歉|对不起|无法|不能|作为(一个)?(AI|人工智能)|I cannot|I'm sorry|as an AI)", re.I)


class ChatTranslator:
    def __init__(self, cfg: TranslateSection, glossary: Glossary,
                 data_only: bool = False):
        self.cfg = cfg
        self.glossary = glossary
        self._client: AsyncOpenAI | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._history: dict[str, deque] = {}
        self._last_request = 0.0
        self._lock = asyncio.Lock()
        self._ready = False
        self.last_clean = ""
        # 上一次失败的原因（人话，见 describe_error）。桥把它原样带给 mod 面板，
        # 否则游戏里只能看到一句笼统的"翻译失败"。
        self.last_error = ""
        if not data_only:
            self._http_client = build_http_client(cfg.base_url, cfg.timeout_s)
            if self._http_client is not None:
                logger.info("本地后端 %s：已绕过系统代理直连", cfg.base_url)
            self._client = AsyncOpenAI(
                api_key=cfg.api_key or "none",
                base_url=cfg.base_url,
                timeout=cfg.timeout_s,
                max_retries=0,  # 自己控制重试节奏
                http_client=self._http_client,
            )

    # ---------- 公共 API ----------

    async def translate(self, text: str, direction: str,
                        source_lang: str = "en") -> AsyncIterator[str]:
        """流式翻译；调用方拼接 token 即可。

        source_lang 只影响 system 提示词的选择（英/俄各一套），
        不影响方向判定 —— 方向由桥按 target 决定。
        """
        text = (text or "").strip()
        self.last_error = ""
        if not text:
            return

        exact = self._exact(text, direction)
        if exact is not None:
            yield exact
            return

        prepared, stash, locked = self._prepare(text, direction)
        # 俚语替换后整句已经没有拉丁字母（ty / b b b / gg / thx 这类）：
        # 该翻的都在词典里翻好了，直接返回，省一次模型调用，
        # 也避免模型把替换后的"谢谢"又翻成"没事"这种莫名其妙的结果。
        if direction == "en->zh" and not _LATIN_RE.search(prepared):
            done = re.sub(r"\s{2,}", " ", self.glossary.restore(prepared, stash)).strip()
            if done:
                logger.debug("整句由词典直译: %r -> %r", text, done)
                yield done
                return

        terms = self._hints_for(prepared, direction, locked)
        messages = build_messages(
            prepared, direction, terms,
            keep_all=self.glossary.keep,
            history=self._history_for(direction),
            extra=self.cfg.system_extra,
            locked=locked,
            source_lang=source_lang,
        )

        result = ""
        for attempt in range(self.cfg.max_retries + 1):
            result = ""
            try:
                await self._rate_limit()
                stream = await self._client.chat.completions.create(
                    model=self.cfg.model,
                    messages=messages,
                    temperature=self.cfg.temperature,
                    top_p=self.cfg.top_p,
                    max_tokens=self.cfg.max_tokens,
                    stream=True,
                    extra_body=self._extra_body(),
                )
                async for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    piece = getattr(delta, "content", None)
                    if piece:
                        result += piece
                        yield piece
            except Exception as e:  # noqa: BLE001
                detail = describe_error(e)
                self.last_error = detail
                logger.warning("翻译失败(第 %d 次): %s", attempt + 1, detail)
                # 配置类错误（key 错/欠费/限流）重试没有意义：同一秒再发一次还是同样的
                # 结果，只是把等待时间堆起来。只有网络抖动和空译文才值得重试。
                if getattr(e, "status_code", None) in (400, 401, 402, 403):
                    return
                # 超时不重试：这种超时基本都是"模型没在显存里"或"被游戏挤到 CPU"，
                # 重试等于把同一次生成再排一遍（下一次同样会超时），只会把
                # 36 秒的等待堆起来、还让游戏里的玩家以为功能坏了。
                if "timeout" in type(e).__name__.lower() or "timed out" in str(e).lower():
                    return
                if attempt < self.cfg.max_retries:
                    await asyncio.sleep(0.4 * (attempt + 1))
                    continue
                return

            cleaned = self._postprocess(result, stash, direction, text)
            if cleaned:
                self._remember(direction, text, cleaned)
                # 清洗后可能与流式 token 不完全一致（去掉引号/控制符/恢复占位符），
                # 调用方用 translate_full 时以这里的最终值为准。
                self.last_clean = cleaned
                return
            logger.warning("空译文(第 %d 次): %r", attempt + 1, text)
            if attempt < self.cfg.max_retries:
                await asyncio.sleep(0.4 * (attempt + 1))

    async def translate_full(self, text: str, direction: str,
                             source_lang: str = "en") -> str:
        """非流式便捷接口，返回清洗后的最终译文。"""
        self.last_clean = ""
        self.last_error = ""
        buf = ""
        self._last_direction = direction
        self._last_source_lang = source_lang
        async for token in self.translate(text, direction, source_lang):
            buf += token
        out = self.last_clean or self._postprocess(buf, {}, direction, text,
                                                   source_lang=source_lang)
        # 一个字都没产出、而且请求也没报错 —— 最可能是模型把整段输出都当成了思考
        # （DeepSeek 思维链走 reasoning_content，不进 content）。给个能照着修的提示，
        # 而不是让调用方只看到"空译文"。
        if not out and not self.last_error and is_deepseek_url(self.cfg.base_url):
            if getattr(self.cfg, "thinking", "auto") != "off":
                self.last_error = ("模型只输出了思考过程，没有译文："
                                   "把 config.yaml 的 translate.thinking 设成 off")
            else:
                self.last_error = "模型返回空译文（换一个模型试试）"
        return out

    def reset_context(self, direction: str | None = None) -> None:
        if direction is None:
            self._history.clear()
        else:
            self._history.pop(direction, None)

    async def prewarm(self) -> bool:
        """预热：让 Ollama 把模型载入显存，避免第一条消息等好几秒。"""
        try:
            await self.translate_full("gg", "en->zh")
            self.reset_context()
            self._ready = True
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("翻译后端预热失败: %s", e)
            return False

    async def ping(self) -> tuple[bool, str]:
        """自检：返回 (是否可用, 说明)。"""
        try:
            models = await self._client.models.list()
            names = [m.id for m in getattr(models, "data", [])][:6]
            return True, f"后端可用，模型示例: {', '.join(names) if names else '(未列出)'}"
        except Exception as e:  # noqa: BLE001
            return False, f"连不上翻译后端: {e}"

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._http_client = None

    # ---------- 内部 ----------

    def _extra_body(self) -> dict | None:
        """按端点分流附加参数（发错了会被拒参，所以不能合并成一个 dict）。

        · 本地 Ollama：keep_alive —— 默认空闲 5 分钟就把模型从显存卸载，下次翻译要
          重新载入（实测 5~40 秒），游戏里表现为"隔一会儿第一条特别慢"。设长一点，
          整局游戏模型都常驻。云端接口不认这个字段。
        · DeepSeek：thinking=disabled —— 它**默认开启思考模式且 effort=high**，一句
          "mid no" 会先产出几百上千 token 的思维链，直接撞 timeout；而且思考模式下
          temperature 被忽略、top_p 被抬到 >=0.95。游戏聊天翻译不需要思考。
        """
        extra: dict = {}
        if is_local_url(self.cfg.base_url):
            if getattr(self.cfg, "keep_alive", ""):
                extra["keep_alive"] = self.cfg.keep_alive
        elif is_deepseek_url(self.cfg.base_url):
            if getattr(self.cfg, "thinking", "auto") == "off":
                extra["thinking"] = {"type": "disabled"}
        return extra or None

    def _exact(self, text: str, direction: str) -> str | None:
        if not self.cfg.exact_match:
            return None
        hit = self.glossary.exact_phrase(text, direction)
        if hit:
            logger.debug("短语直译命中: %r -> %r", text, hit)
        return hit

    def _prepare(self, text: str, direction: str) -> tuple[str, dict[str, str],
                                                          list[tuple[str, str]]]:
        """译前改写。返回 (改写后文本, 占位符表, 已预先译好的词表)。"""
        if direction == "en->zh":
            return self.glossary.apply_slang(text)
        return text, {}, []

    def _hints_for(self, prepared: str, direction: str,
                   locked: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """给提示词准备**术语表命中**项（不含 locked，那一份单独传给 build_messages）。

        `locked` 里的词已经在译前被替换成中文了，属于最高优先级的约束
        （就是它们决定了正文里那几个中文字的读法），由 prompt 层单独渲染成 LOCKED 行；
        这里只负责把术语表命中项去重后给它 —— 同一个来源词不能两个地方都出现，
        否则提示行逐字重复，白烧 token 还容易让模型当成两件事。

        以前这里只查术语表，而正文已经被改写 —— 结果最该锁术语的那些短句
        （"push mid and get urn"）一条 TERMS 都拿不到。
        """
        limit = max(int(self.cfg.max_glossary_terms), 0)
        if not limit:
            return []
        taken = {src.lower() for src, _ in locked}
        out: list[tuple[str, str]] = []
        for src, dst in self.glossary.terms_for(prepared, direction,
                                                limit=limit + len(taken)):
            if src.lower() in taken:
                continue
            taken.add(src.lower())
            out.append((src, dst))
            if len(out) >= limit:
                break
        return out

    def _history_for(self, direction: str) -> list[tuple[str, str]]:
        # 对称地：发送方向不带上文（见 _remember）
        if self.cfg.context_window <= 0 or direction != "en->zh":
            return []
        hist = self._history.get(direction)
        return list(hist) if hist else []

    def _remember(self, direction: str, src: str, dst: str) -> None:
        # 只给**接收**方向记上下文：发送方向是"我自己要说的话"，
        # 屏幕上别人的聊天历史对它没有消歧价值，只会白烧 token。
        if self.cfg.context_window <= 0 or direction != "en->zh":
            return
        hist = self._history.get(direction)
        if hist is None:
            hist = deque(maxlen=self.cfg.context_window)
            self._history[direction] = hist
        hist.append((src, dst))

    async def _rate_limit(self) -> None:
        if self.cfg.min_request_interval_s <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self.cfg.min_request_interval_s - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    def _postprocess(self, raw: str, stash: dict[str, str], direction: str,
                     source: str = "", source_lang: str = "en") -> str:
        text = _CONTROL_RE.sub("", raw or "").strip()
        text = _TERMS_LEAK_RE.sub("", text).strip()   # 去掉被抄进来的 TERMS/LOCKED 行
        text = _LOCKED_NOTE_RE.sub("", text).strip()
        text = _PREFIX_RE.sub("", text)
        text = text.strip(_QUOTE_CHARS).strip()
        text = re.sub(r"\s*\n+\s*", " ", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        if stash:
            text = self.glossary.restore(text, stash)
        if not text:
            return ""
        if _REFUSAL_RE.search(text) and len(text) > 8:
            logger.warning("疑似拒绝/道歉输出，丢弃: %r", text[:60])
            return ""
        # 英/俄 -> 中：整句没有一个汉字，多半是复读原文或输出拼音
        # -> 当失败处理（会触发重试）。俄语方向尤其重要：西里尔字母被原样
        # 带回来时，玩家看到的是一串看不懂的俄文，比"翻译失败"更糟。
        if (direction == "en->zh" and len(text) > 12
                and not re.search(r"[\u4e00-\u9fff]", text)):
            logger.warning("译文疑似未翻译（无汉字，源语言 %s），丢弃: %r",
                           source_lang, text[:60])
            return ""
        return text

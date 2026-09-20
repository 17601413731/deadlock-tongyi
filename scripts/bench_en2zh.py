"""量化对比：英→中（游戏内英文聊天）在术语提示改动前后的质量。

为什么要这个：英→中是主路径（mod 把别人发的英文翻成中文显示，本地 7B 中位约 1.2 秒，
见 docs/mod-usage.md），但它**一直没有测试集** —— data/deadlock_testset.jsonl 只覆盖
中→英方向的 30 条。这里补上 data/deadlock_testset_en.jsonl（60 条真实英文聊天 +
人工参考译文），用**确定性检查**（不叫裁判模型）逐条打分，避免"凭感觉争论"。

  --variant legacy : 改动前 —— 术语提示没有传下去（terms=[]），
                     system 提示和少样本与 new 完全一致（这才是诚实的"before"基线）
  --variant new    : 改动后 —— Glossary().terms_for(text, "en->zh", limit=8) 注入 TERMS 行
  --compare        : 两个都跑，给对比表
  --dry-run        : 不叫模型，拿 zh_ref 自己当"模型输出"过一遍检查
                     （先证明检查器没写错：参考译文必须接近满分）

五项确定性检查（任一 flag = 该条不通过，全部写进 flags）：
  1. 术语命中     terms 里的词，译文里有没有对应的中文写法
  2. 未翻译残留   译文里 ≥4 个字母的拉丁串（不在 keep_as_is 里的）
  3. 拼音泄漏     ≥2 个连续小写字母词、且不是复读原文（例如 "zhonglu meiren"）
  4. 长度比       len(zh)/len(en)，>3.0 判"过度解释"（低阈值见下）
  5. keep 词      en 里出现的 keep_as_is 词，必须原样保留在译文里

**故意放宽的三处**（都写在代码注释里，别当 bug 修）：
  · 术语命中只要求"至少一种中文写法出现"；没命中但也没原样透传英文时算通过 ——
    同一个术语常有多种同样正确的说法（dive=越塔/上、jungle=野区/打野、souls=魂魄/钱）。
    真正严的指标是同时报出的**术语直命中率**：映射表里的写法真的出现在译文里。
  · 长度比的**低阈值用词数做尺度**，不用 0.5 的字符比：中文天生比英文短
    （"stop feeding" 12 字符 -> "别送了" 3 字符，字符比 0.25，但这是最自然的译文）。
    低于 0.5 的字符比会连同这些正确译文一起误判。
  · keep_as_is 与 slang.json 冲突的词（b / ult / cd / afk / brb / wp / ks / oom ...）
    不参与 keep 检查：项目自己的 slang 表就要把它们翻成中文，两张表互相矛盾是已知问题。

输出：
  · 终端：汇总（总通过率 + 术语直命中率 + 分 register 通过率 + 各 flag 计数）
          + 逐条 markdown 表（en | zh_ref | model_out | flags），可直接贴进文档
  · 记录：data/bench_en2zh_last.json（variant / model / base_url / 逐条结果 / 汇总），
          用于跨改动 diff（该文件已在 .gitignore 里）

用法：
    python scripts/bench_en2zh.py --dry-run -v
    python scripts/bench_en2zh.py --variant legacy
    python scripts/bench_en2zh.py --variant new
    python scripts/bench_en2zh.py --compare
    python scripts/bench_en2zh.py --base-url https://api.deepseek.com/v1 --model deepseek-flash

退出码：0 = 正常；1 = 测试集缺失/为空；2 = 后端连不上（打印中文排查提示，不抛 traceback）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
TESTSET = ROOT / "data" / "deadlock_testset_en.jsonl"
RECORD = ROOT / "data" / "bench_en2zh_last.json"

# 默认打本地 Ollama（和 bench_zh2en.py 同一个端点）；云端用 --base-url/--model 指过去。
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1/chat/completions"
DEFAULT_TIMEOUT = 120      # 首次请求可能要把 7B 模型载入显存（实测 30~40 秒）
HINT_LIMIT = 8             # 术语提示条数上限（和 --variant new 的调用约定一致）

REGISTERS = ("callout", "banter", "salt", "logistics")
REGISTER_LABEL = {"callout": "战术喊话", "banter": "闲聊", "salt": "互喷/甩锅",
                  "logistics": "非战术协同"}

HAN_RE = re.compile(r"[\u4e00-\u9fff]")
HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
LATIN_RUN_RE = re.compile(r"[A-Za-z]{4,}")
# 连续 ≥2 个小写字母词（"zhonglu meiren" 这种拼音串）
PINYIN_RUN_RE = re.compile(r"(?<![A-Za-z])[a-z]{2,}(?: +[a-z]{2,})+(?![A-Za-z])")

HIGH_RATIO = 3.0           # 长度比上限：超过就是过度解释
CHAR_LOW_RATIO = 0.5       # 规范里的字符比下限（只记录，不当判定依据，见 docstring）
MIN_WORDS_FOR_LOW = 4      # 英文词数少于这个数就不判"丢内容"（短喊话天生短）
MIN_HAN_PER_WORD = 0.6     # 每个英文词至少要有这么多汉字，否则算丢内容

# 本地地址要走直连（和 client.py 的 _LOCAL_HOSTS 一致）
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}
DEEPSEEK_HOST = "api.deepseek.com"


class BackendDown(RuntimeError):
    """后端连不上（网络/进程/key）。main 捕获后打印中文提示并以 2 退出。"""


# ---------------------------------------------------------------------------
# 后端调用（OpenAI 兼容；本地绕代理，云端走代理）
# ---------------------------------------------------------------------------

def is_local_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in _LOCAL_HOSTS or host.startswith("127.") or host.endswith(".local")


def is_deepseek_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == DEEPSEEK_HOST or host.endswith("." + DEEPSEEK_HOST)


def _endpoint(base_url: str) -> str:
    """允许只给到 /v1 这种根地址，自动补 /chat/completions。"""
    url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def call_ollama(messages: list[dict], model: str, base_url: str = DEFAULT_BASE_URL,
                api_key: str = "", timeout: int = DEFAULT_TIMEOUT,
                max_tokens: int = 128) -> str:
    """发一条 OpenAI 兼容的 chat 请求，返回译文文本。

    为什么本地地址要自己 build_opener：Windows 上开着代理时 urllib 会把
    http://127.0.0.1:11434 也塞进代理，拿到 503（和 bench_zh2en.py 踩的是同一个坑）。
    云端地址保持默认行为（你可能正需要代理才能出网）。
    """
    body: dict = {"model": model, "messages": messages, "temperature": 0.0,
                  "max_tokens": max_tokens}
    if is_local_url(base_url):
        body["keep_alive"] = "10m"       # 别让模型在一局中途被卸载
    elif is_deepseek_url(base_url):
        # DeepSeek 默认开思考模式，一句话会先吐几百上千 token 的思维链（还撞 timeout）
        body["thinking"] = {"type": "disabled"}

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(_endpoint(base_url), data=json.dumps(body).encode("utf-8"),
                                headers=headers)
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler({}))
              if is_local_url(base_url) else urllib.request.build_opener())
    with opener.open(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["choices"][0]["message"]["content"] or "").strip()


def describe_error(exc: BaseException) -> str:
    """把异常翻成"照着能修"的一句话（云端 401/402/429 光看 traceback 看不出来）。"""
    status = getattr(exc, "code", None)
    if status == 401 or status == 403:
        return "API Key 无效或未设置"
    if status == 402:
        return "账户余额不足"
    if status == 429:
        return "请求被限流"
    if status == 404:
        return "端点或模型名不存在（本地常见于模型没 pull 下来）"
    if isinstance(status, int) and 500 <= status < 600:
        return f"服务端错误 HTTP {status}"
    text = str(exc)
    low = text.lower()
    if "timed out" in low or "timeout" in low:
        return "请求超时"
    if "refused" in low or "getaddrinfo" in low or "name or service not known" in low:
        return "连接被拒绝 / 域名解析失败"
    return text[:160]


def backend_hint(base_url: str, api_key: str, err: str) -> str:
    """后端不可用时的中文排查提示（用户可能只是在游戏里忘了起 Ollama）。"""
    head = f"✗ 连不上翻译后端：{_endpoint(base_url)}\n  原因：{err}\n"
    if is_local_url(base_url):
        return (head + "  本地后端要先把 Ollama 起起来：\n"
                       "      ollama serve\n"
                       "      ollama list          # 确认模型已拉取\n"
                       "  或者改用云端：--base-url https://api.deepseek.com/v1 "
                       "--model deepseek-flash\n"
                       "  （云端需要密钥：环境变量 DEEPSEEK_API_KEY，或在网页设置页里填）")
    if is_deepseek_url(base_url):
        key_state = "已读到密钥" if api_key else "没有读到密钥"
        return (head + f"  云端后端需要密钥（当前：{key_state}）：\n"
                       "      setx DEEPSEEK_API_KEY sk-xxxx      # 然后重开终端\n"
                       "  或在 http://localhost:8791/settings 里填一次\n"
                       "  另外确认代理能出网（本地地址才会绕过系统代理）\n"
                       "  想改回本地：--base-url http://127.0.0.1:11434/v1")
    return head + "  检查端点地址、网络与代理设置；本地 Ollama 用 --base-url http://127.0.0.1:11434/v1"


def probe_backend(base_url: str, model: str, api_key: str) -> None:
    """跑一条最小请求确认后端活着；不通就抛 BackendDown（免得每条都在报错）。"""
    try:
        call_ollama([{"role": "user", "content": "gg"}], model,
                    base_url=base_url, api_key=api_key, max_tokens=8)
    except Exception as e:  # noqa: BLE001  连不上/鉴权失败都归到这里
        raise BackendDown(describe_error(e)) from e


def resolve_target(args: argparse.Namespace) -> tuple[str, str, str]:
    """决定这次要打的 (base_url, model, api_key)。"""
    base_url, model = args.base_url, args.model
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()

    try:
        from dlchat.config import load_config
        cfg = load_config()
        if not model:
            # 默认跟项目配置走（config.yaml 的 translate.model）
            model = cfg.translate.model
        if not api_key:
            from dlchat.settings import load_settings
            api_key = (load_settings(cfg).api_key or "").strip()
    except Exception as e:  # noqa: BLE001  配置缺失不该让 benchmark 挂掉
        print(f"⚠ 读项目配置失败（用默认值继续）：{e}")

    return (base_url or DEFAULT_BASE_URL, model or "deepseek-flash", api_key)


def warn_model_mismatch(base_url: str, model: str) -> None:
    """端点与模型对不上时先提醒一句。

    默认组合是"本地端点 + config.yaml 的模型名"，而 config.yaml 默认的是云端 ID
    （deepseek-flash）。本地 Ollama 上没这个名字，会拿到 404 —— 先提醒比让人对着
    "端点或模型名不存在" 猜要快得多。
    """
    if is_local_url(base_url) and model.lower().startswith("deepseek"):
        print(f"⚠ 端点指向本地（{_endpoint(base_url)}），但模型名是云端的 {model!r}；"
              "本地要指定已 pull 的模型，例如：\n"
              "    --model hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"
              "     # 先 ollama list 看本机有什么")


# ---------------------------------------------------------------------------
# 术语映射：把项目数据文件反向索引成「英文词 -> 中文写法」
# ---------------------------------------------------------------------------

class Checker:
    """确定性判分器。只依赖项目自带的数据文件，不调用模型。"""

    def __init__(self, glossary) -> None:
        self.g = glossary
        self.keep = set(glossary.keep)
        # keep_as_is 与 slang.json 的冲突词：以前两张表有 15 个词重叠
        # （b/ult/cd/afk/brb/wp/ks/oom...），项目自己的 slang 要把它们翻成中文，
        # keep 又要原样保留 —— 实测的后果是**两条规则同时失效**（词被 stash 成
        # 占位符，模型只看到 ⦁0⦁）。现在文件层面已经清干净：slang.json 不再重复
        # keep 里的词，所以这里只需要认"当前 slang 表里还有的词"。
        # 保留这条豁免是为了兼容旧数据/用户自己改过的表，不影响正确性。
        self.keep_conflict = {k.lower() for k in glossary.slang}
        self.keep_ref_drops = self._load_keep_ref_drops()
        self.index = self._build_index()
        self.names = self._load_names()
        self.official = {k.lower(): (v.get("zh") or "")
                         for k, v in glossary.terms.items() if isinstance(v, dict)}

    # ---- 映射表 ----

    def _load_keep_ref_drops(self) -> set[str]:
        """从测试集里推导"参考译文故意没保留的 keep 词"。

        不手写名单：手写的会过期（这次就过期了 —— keep_as_is 与 slang 清理完之后，
        名单里那 15 个词全成了误判）。这里直接读 zh_ref 自己：只有**参考译文**
        也没保留的 keep 词才豁免，模型真把它们翻掉了照样会被抓到。
        """
        path = ROOT / "data" / "deadlock_testset_en.jsonl"
        drops: set[str] = set()
        if not path.exists():
            return drops
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            ref = str(item.get("zh_ref") or "")
            if not ref:
                continue
            for tok in self.g.keep_tokens(str(item.get("en") or "")):
                if not re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])",
                                 ref, re.I):
                    drops.add(tok.lower())
        return drops

    def _build_index(self) -> dict[str, set[str]]:
        """英文词 -> 中文写法集合。

        来源（按可信度）：slang.json（社区黑话，最贴聊天）→ deadlock_zh2en.json 反向
        （人工审校的中→英，反过来用）→ 官方术语表 glossary.json（兜底）。
        另外把英文侧的每个词也当键（"feeding kills" 让 feeding 也能查到「送人头」）。
        """
        index: dict[str, set[str]] = {}
        word_re = re.compile(r"[a-z][a-z']+")

        def add(key: str, zh: str) -> None:
            key = (key or "").strip().lower()
            if key and zh:
                index.setdefault(key, set()).add(zh)

        for en, zh in self.g.slang.items():
            add(en, zh)
        for zh, en in self.g.zh_terms.items():          # data/deadlock_zh2en.json（中→英）
            add(en, zh)
            for w in word_re.findall(en.lower()):
                add(w, zh)
        return index

    def _load_names(self) -> dict[str, str]:
        """data/gamenames.json：英雄/物品名（400 条，名称保护的依据）。"""
        path = ROOT / "data" / "gamenames.json"
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
        return {str(k).lower(): v for k, v in data.items() if isinstance(v, str) and v}

    def renderings(self, token: str) -> list[str]:
        """某个英文术语可能的全部中文写法（只留汉字串，去掉标点和英文）。"""
        t = (token or "").strip().lower()
        cands: set[str] = set(self.index.get(t, ()))
        for key, zh in self.index.items():
            # 词形兜底：flanking -> flank（数据表里只有原形时也能查到）
            if len(key) >= 4 and t.startswith(key):
                cands |= zh
        if self.names.get(t):
            cands.add(self.names[t])
        if self.official.get(t):
            cands.add(self.official[t])
        runs: list[str] = []
        for c in cands:
            runs.extend(HAN_RUN_RE.findall(c))
        return sorted(set(runs), key=len, reverse=True)

    # ---- 单项检查 ----

    def mask_keep(self, text: str) -> str:
        """把译文里的 keep 词挖掉（再找拉丁残留/拼音时就不会误伤 gg、wp、diff）。"""
        out = text
        for tok in self.g.keep_tokens(text):      # 词边界 + 最长优先，和运行时同规则
            out = re.sub(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", " ", out, flags=re.I)
        return out

    def check_terms(self, out: str, terms: list[str]) -> tuple[list[str], list[str]]:
        """返回 (未命中的术语, 直命中的术语)。

        判定（宽松）：术语算 miss 只有两种情况 ——
          a) 译文里一个汉字都没有（等于没翻）；
          b) 该术语原样出现在译文里，且它前后 ±12 字符内没有汉字（英文漏出来了）。
        其余情况（译成了别的说法，例如 dive -> 上）算通过，因为中文同义说法太多。
        """
        miss: list[str] = []
        direct: list[str] = []
        has_han = bool(HAN_RUN_RE.search(out))
        for tok in terms:
            cands = self.renderings(tok)
            if any(c in out for c in cands):
                direct.append(tok)
                continue
            if not has_han:
                miss.append(tok)
                continue
            if tok.lower() in self.keep and tok.lower() not in self.keep_conflict:
                # keep_as_is 说这个词本来就该保留英文：原样出现即算命中
                if re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", out, re.I):
                    continue
            m = re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", out, re.I)
            if m and not HAN_RUN_RE.search(out[max(0, m.start() - 12):m.end() + 12]):
                miss.append(tok)
        return miss, direct

    def check_latin(self, out: str) -> list[str]:
        """未翻译残留：≥4 字母的拉丁串；专名（gamenames 里的英雄/物品）额外标注。"""
        runs = sorted({m.group(0) for m in LATIN_RUN_RE.finditer(self.mask_keep(out))})
        return [f"{w}(专名)" if w.lower() in self.names else w for w in runs]

    def check_pinyin(self, en: str, out: str) -> list[str]:
        """拼音泄漏：连续 ≥2 个小写字母词。整串都在原文里出现 = 复读原文，不算拼音。"""
        src_words = {w.lower() for w in re.findall(r"[A-Za-z']+", en)}
        leaks: list[str] = []
        for m in PINYIN_RUN_RE.finditer(self.mask_keep(out)):
            span = m.group(0)
            if all(tok in src_words for tok in span.split()):
                continue
            leaks.append(span)
        return leaks

    def check_length(self, en: str, out: str) -> tuple[float, list[str], bool]:
        """返回 (字符长度比, flags, 是否低于规范里的 0.5 字符比)。"""
        ratio = (len(out) / len(en)) if en else 0.0
        words = len(en.split())
        han = len(HAN_RE.findall(out))
        flags: list[str] = []
        if ratio > HIGH_RATIO:
            flags.append(f"长度比：{ratio:.2f}>3.0（过度解释）")
        # 低阈值用词数尺度：英文 ≥4 词、且汉字数不到 0.6×词数，才算"丢内容"
        if words >= MIN_WORDS_FOR_LOW and han < MIN_HAN_PER_WORD * words:
            flags.append(f"长度比：{ratio:.2f}（汉字 {han} 个 < 英文 {words} 词，像丢内容）")
        return ratio, flags, ratio < CHAR_LOW_RATIO

    def check_keep(self, en: str, out: str) -> tuple[list[str], list[str]]:
        """返回 (被翻掉的 keep 词, 豁免的 keep 词)。

        豁免分两种，都要记进结果里，不要静默跳过：
          · `keep_conflict`：slang.json 里还有同名条目（旧数据/用户自己改过的表）；
          · `keep_ref_drops`：**参考译文本身**就没保留这个词 —— 那是逐条复核过的
            决定（例如 "afk 1 min" 的参考译文是「挂机1分钟」：中文玩家读这句时
            心态上就是「挂机」，但用词上确实会打 afk，两种都对，参考取前者）。
            判定方式就是拿 zh_ref 自己比对，所以不存在"手写的豁免名单会过期"的问题。
        """
        missed, exempt = [], []
        for tok in self.g.keep_tokens(en):
            low = tok.lower()
            if low in self.keep_conflict or low in self.keep_ref_drops:
                exempt.append(tok)
                continue
            if not re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", out, re.I):
                missed.append(tok)
        return missed, exempt

    # ---- 一条记录 ----

    def check_line(self, item: dict, out: str) -> dict:
        en = item["en"]
        terms = [t for t in (item.get("terms") or []) if t]
        flags: list[str] = []

        miss, direct = self.check_terms(out, terms)
        if miss:
            flags.append("术语miss：" + ",".join(miss))
        latin = self.check_latin(out)
        if latin:
            flags.append("未翻译残留：" + ",".join(latin))
        leaks = self.check_pinyin(en, out)
        if leaks:
            flags.append("拼音泄漏：" + ",".join(leaks))
        ratio, len_flags, low_by_chars = self.check_length(en, out)
        flags.extend(len_flags)
        keep_missed, keep_exempt = self.check_keep(en, out)
        if keep_missed:
            flags.append("keep词被翻：" + ",".join(keep_missed))

        return {
            "en": en,
            "zh_ref": item["zh_ref"],
            "out": out,
            "terms": terms,
            "register": item.get("register", ""),
            "note": item.get("note", ""),
            "flags": flags,
            "ok": not flags,
            "term_miss": miss,
            "term_direct": direct,
            "ratio": round(ratio, 2),
            "ratio_low_by_chars": low_by_chars,
            "keep_exempt": keep_exempt,
        }


# ---------------------------------------------------------------------------
# 跑分
# ---------------------------------------------------------------------------

def score_model(variant: str, rows: list[dict], base_url: str, model: str,
                api_key: str, checker: Checker, verbose: bool) -> list[dict]:
    """把每条 en 送进模型，再逐条判分。

    legacy = terms=[]（术语提示没传下去）；new = Glossary().terms_for(..., limit=8)。
    两个变体的 system 提示、少样本、keep 清单、**原文**都完全一样：原文一律用原始 en
    （不调用 glossary.apply_slang —— 它是"译前锁定术语"的另一条路，会把原文改掉，
    还会顺带把 keep 词换成占位符，混进来就分不清是谁的功劳了）。
    """
    from dlchat.chat.glossary import Glossary
    from dlchat.translate.prompt import build_messages

    g = Glossary()
    results: list[dict] = []
    for i, item in enumerate(rows, 1):
        text = item["en"]
        terms = g.terms_for(text, "en->zh", limit=HINT_LIMIT) if variant == "new" else []
        messages = build_messages(text, "en->zh", terms, keep_all=g.keep)
        try:
            out = call_ollama(messages, model, base_url=base_url, api_key=api_key)
        except Exception as e:  # noqa: BLE001
            if i == 1:
                # 第一条就失败 = 后端根本没通（继续跑只会把每条都刷成同一句错误）
                raise BackendDown(describe_error(e)) from e
            out = ""
            res = checker.check_line(item, out)
            res["flags"].append("后端失败：" + describe_error(e))
            res["ok"] = False
            res["injected"] = [[s, d] for s, d in terms]
            results.append(res)
            print(f"  [{i}/{len(rows)}] ✗ 后端失败：{describe_error(e)}")
            continue
        res = checker.check_line(item, out)
        res["injected"] = [[s, d] for s, d in terms]
        results.append(res)
        if verbose:
            mark = "✓" if res["ok"] else "✗"
            hint = " ".join(f"{s}={d}" for s, d in terms) or "(无术语提示)"
            print(f"  [{i}/{len(rows)}] {mark} {text!r} -> {out!r}")
            print(f"        术语提示: {hint}")
            if res["flags"]:
                print(f"        标记: {'; '.join(res['flags'])}")
    return results


def score_dry_run(rows: list[dict], checker: Checker) -> list[dict]:
    """--dry-run：拿 zh_ref 自己当"模型输出"。参考译文必须能过自己的检查。"""
    results = []
    for item in rows:
        res = checker.check_line(item, item["zh_ref"])
        res["injected"] = []
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def aggregate(rows: list[dict]) -> dict:
    total = len(rows)
    passed = sum(1 for r in rows if r["ok"])
    term_total = sum(len(r["terms"]) for r in rows)
    term_direct = sum(len(r["term_direct"]) for r in rows)
    by_register = {}
    for reg in REGISTERS:
        sub = [r for r in rows if r["register"] == reg]
        if sub:
            ok = sum(1 for r in sub if r["ok"])
            by_register[reg] = {"total": len(sub), "passed": ok,
                                "rate": round(ok / len(sub) * 100, 1)}
    by_flag = Counter(f.split("：")[0] for r in rows for f in r["flags"])
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total * 100, 1) if total else 0.0,
        "term_total": term_total,
        "term_direct": term_direct,
        "term_direct_rate": round(term_direct / term_total * 100, 1) if term_total else 0.0,
        "flags": dict(by_flag),
        "by_register": by_register,
    }


def report(variant: str, rows: list[dict], verbose: bool) -> dict:
    """打印汇总 + 分 register 通过率 + 逐条 markdown 表；返回汇总 dict。"""
    agg = aggregate(rows)
    print(f"\n[{variant}] 通过 {agg['passed']}/{agg['total']} = {agg['pass_rate']:.0f}%"
          f" ｜ 术语直命中 {agg['term_direct']}/{agg['term_total']}"
          f" = {agg['term_direct_rate']:.0f}%")
    print("  分 register 通过率（风格要求本来就不一样）：")
    for reg, st in agg["by_register"].items():
        print(f"    {reg:<10}（{REGISTER_LABEL.get(reg, reg)}）"
              f" {st['passed']}/{st['total']} = {st['rate']:.0f}%")
    if agg["flags"]:
        detail = " · ".join(f"{k} × {v}" for k, v in sorted(agg["flags"].items()))
        print(f"  标记计数：{detail}")

    bad = [r for r in rows if not r["ok"]]
    if bad and not verbose:
        print(f"  未通过 {len(bad)} 条（加 -v 看逐条）：")
        for r in bad:
            print(f"    ✗ {r['en']!r} -> {r['out']!r}  {'; '.join(r['flags'])}")
    elif verbose:
        print("  逐条：")
        for r in rows:
            mark = "✓" if r["ok"] else "✗"
            print(f"    {mark} {r['en']!r} -> {r['out']!r}")
            if r["flags"]:
                print(f"        {'; '.join(r['flags'])}")
    return agg


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def markdown_table(rows: list[dict], title: str) -> None:
    """逐条对照表（可以直接贴进文档做人工复核）。"""
    print(f"\n### 逐条对照（{title}）\n")
    print("| en | zh_ref | model_out | flags |")
    print("|---|---|---|---|")
    for r in rows:
        flags = "; ".join(r["flags"]) or "✓"
        print(f"| {_cell(r['en'])} | {_cell(r['zh_ref'])} | {_cell(r['out'])} | {_cell(flags)} |")


def save_record(payload: dict) -> None:
    try:
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        RECORD.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n记录已写入 {RECORD.relative_to(ROOT)}（可用于跨改动 diff）")
    except OSError as e:
        print(f"⚠ 写记录失败 {RECORD}: {e}")


def make_record(variant: str, model: str, base_url: str, dry_run: bool,
                rows: list[dict], agg: dict) -> dict:
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "variant": variant,
        "model": model,
        "base_url": base_url,
        "dry_run": dry_run,
        "testset": str(TESTSET.relative_to(ROOT)),
        "hint_limit": HINT_LIMIT,
        "aggregate": agg,
        "lines": rows,
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def load_testset() -> list[dict]:
    """读测试集；文件缺失/为空/解析失败都返回空列表（调用方以 1 退出）。"""
    if not TESTSET.exists():
        print(f"✗ 测试集不存在：{TESTSET}")
        return []
    rows: list[dict] = []
    for lineno, line in enumerate(TESTSET.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"✗ 第 {lineno} 行不是合法 JSON：{e}")
            return []
        if not item.get("en") or not item.get("zh_ref"):
            print(f"✗ 第 {lineno} 行缺 en 或 zh_ref")
            return []
        rows.append(item)
    return rows


def validate_testset(rows: list[dict], checker: Checker) -> None:
    """测试集自检：字段/register/terms 是否成立。只警告，不阻断（--dry-run 才是硬门禁）。"""
    problems: list[str] = []
    for item in rows:
        en = item["en"]
        words = len(en.split())
        if words > 12:
            problems.append(f"{en!r} 超过 12 个词（{words}）")
        if item.get("register") not in REGISTERS:
            problems.append(f"{en!r} 的 register 不合法：{item.get('register')!r}")
        for tok in item.get("terms") or []:
            if not re.search(r"(?<![A-Za-z])" + re.escape(tok) + r"(?![A-Za-z])", en, re.I):
                problems.append(f"{en!r} 的术语 {tok!r} 没有出现在原文里")
            elif not checker.renderings(tok):
                problems.append(f"{en!r} 的术语 {tok!r} 在映射表里查不到中文写法"
                                f"（只能按「没有汉字才算 miss」的宽松规则判）")
    if problems:
        print(f"⚠ 测试集自检发现 {len(problems)} 处问题（不影响运行）：")
        for p in problems[:20]:
            print(f"    · {p}")


def main() -> int:
    ap = argparse.ArgumentParser(description="英→中聊天翻译质量跑分（确定性检查，不叫裁判模型）")
    ap.add_argument("--variant", choices=["legacy", "new"], default="new",
                    help="legacy=不注入术语提示（改动前）；new=注入命中的术语（改动后）")
    ap.add_argument("--compare", action="store_true", help="legacy 和 new 都跑，给对比表")
    ap.add_argument("--dry-run", action="store_true",
                    help="不叫模型：拿 zh_ref 自己过一遍检查（验证检查器 + 给个满分地板）")
    ap.add_argument("--base-url", default="", help=f"OpenAI 兼容端点，默认 {DEFAULT_BASE_URL}")
    ap.add_argument("--model", default="", help="模型名，默认取 config.yaml 的 translate.model")
    ap.add_argument("-v", "--verbose", action="store_true", help="逐条打印")
    args = ap.parse_args()

    from dlchat.chat.glossary import Glossary
    checker = Checker(Glossary())

    rows = load_testset()
    if not rows:
        print("✗ 测试集为空或读不出来，先补 data/deadlock_testset_en.jsonl")
        return 1
    validate_testset(rows, checker)

    # ---- dry-run：不碰后端，用参考译文自检 ----
    if args.dry_run:
        print(f"=== dry-run：{len(rows)} 条参考译文自检（不打模型）===")
        results = score_dry_run(rows, checker)
        agg = report("dry-run（zh_ref 自检）", results, args.verbose)
        markdown_table(results, "dry-run / zh_ref")
        save_record(make_record("dry-run", "(未调用模型)", "(未调用模型)", True, results, agg))
        if agg["passed"] < agg["total"]:
            print(f"\n✗ 参考译文自己都过不了检查（{agg['passed']}/{agg['total']}）："
                  f"要么改参考译文，要么改检查项，别带着已知误判去跑真模型")
            return 0      # 仍然算"跑通"：这是检查器的自检结果，不是后端故障
        print(f"\n✓ 参考译文 {agg['total']}/{agg['total']} 全部通过检查，检查器可信")
        return 0

    # ---- 真跑：先确认后端活着 ----
    base_url, model, api_key = resolve_target(args)
    print(f"后端：{_endpoint(base_url)}  模型：{model}"
          f"  密钥：{'已读到' if api_key else '无（本地不需要）'}")
    warn_model_mismatch(base_url, model)
    try:
        probe_backend(base_url, model, api_key)
    except BackendDown as e:
        print(backend_hint(base_url, api_key, str(e)))
        return 2

    variants = ["legacy", "new"] if args.compare else [args.variant]
    records = []
    rates: dict[str, float] = {}
    for variant in variants:
        label = f"{variant}（{'不注入术语提示' if variant == 'legacy' else '注入命中的术语'}）"
        print(f"\n=== 跑 {len(rows)} 条：{label} ===")
        try:
            results = score_model(variant, rows, base_url, model, api_key, checker, args.verbose)
        except BackendDown as e:
            print(backend_hint(base_url, api_key, str(e)))
            return 2
        agg = report(label, results, args.verbose)
        markdown_table(results, variant)
        rates[variant] = agg["pass_rate"]
        records.append(make_record(variant, model, base_url, False, results, agg))
        dead = agg["flags"].get("后端失败", 0)
        if dead > len(rows) // 2:
            print(f"\n✗ 过半请求失败（{dead}/{len(rows)}），后端多半中途挂了")
            save_record(records[0] if len(records) == 1 else {"runs": records})
            print(backend_hint(base_url, api_key, "过半请求失败"))
            return 2

    if args.compare:
        legacy, new = rates.get("legacy", 0.0), rates.get("new", 0.0)
        print(f"\n结论：通过率 {legacy:.0f}% -> {new:.0f}%"
              f"（{'+' if new >= legacy else ''}{new - legacy:.0f} 个百分点）")
        save_record({"ts": datetime.now().isoformat(timespec="seconds"),
                     "variant": "compare", "model": model, "base_url": base_url,
                     "dry_run": False, "testset": str(TESTSET.relative_to(ROOT)),
                     "hint_limit": HINT_LIMIT, "runs": records})
    else:
        save_record(records[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

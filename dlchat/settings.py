"""用户可调设置：默认值来自 config.yaml，用户改动存到覆盖层 settings.json。

为什么要覆盖层而不是直接改 config.yaml：
  · config.yaml 带大量注释，程序化重写会把注释吃光（那份注释本身就是文档）
  · 用户层和默认层分开后，"恢复默认"就是删掉覆盖层，语义干净
  · 覆盖层放在用户目录（`%APPDATA%\deadlock-tongyi\settings.json`，见 paths.py），升级项目不丢

生效方式：桥在收到改动后**热应用** —— 只有影响模型调用的字段变了才重建 translator，
并且清掉翻译缓存（否则旧模型的译文会继续命中）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from . import paths
from .config import _ENV_RE, resolve_env

logger = logging.getLogger(__name__)

# 翻译来源预设。**这是全项目唯一一份**：桥列模型、网页选来源、config 默认值都从这里取。
#   base  : 端点地址（OpenAI 兼容）
#   models: 该来源的模型清单。本地是"本机已装什么"（运行时问 Ollama），
#           云端是固定清单 —— 云端没有"列出可用模型"的可靠接口，写死反而更稳。
#   key_env: 建议放密钥的环境变量名（网页里那段提示用它）
PROVIDERS: dict[str, dict[str, Any]] = {
    "local": {
        "label": "本地 Ollama",
        "base_url": "http://localhost:11434/v1",
        "models": [],                      # 运行时问 Ollama /api/tags
        "key_env": "",
    },
    "deepseek": {
        "label": "DeepSeek 云端",
        # DeepSeek 官方端点。官方文档当前只有这两个模型 ID：
        #   deepseek-flash   —— V4.1-Flash，便宜，默认选它
        #   deepseek-v4-pro  —— V4-Pro，贵
        # 注意 deepseek-chat / deepseek-reasoner 已于 2026-07-24 退役，
        # deepseek-v4-flash 于 2026-09-10 退役（旧 ID 仍被接受但会按新模型计费）。
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "key_env": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "label": "其他 OpenAI 兼容端点",
        "base_url": "https://api.deepseek.com/v1",   # 保留旧行为：默认仍是 DeepSeek 地址
        "models": [],
        "key_env": "",
    },
}

# 兼容旧引用（settings_page / 测试在用）
PROVIDER_PRESETS: dict[str, str] = {k: v["base_url"] for k, v in PROVIDERS.items()}


def provider_models(provider: str) -> list[str]:
    """某来源的固定模型清单（本地为空，要运行时去问 Ollama）。"""
    return list((PROVIDERS.get(provider) or {}).get("models") or [])


def provider_label(provider: str) -> str:
    return (PROVIDERS.get(provider) or {}).get("label") or provider


def provider_of(base_url: str, model: str = "") -> str:
    """按端点地址反推来源（老的 settings.json 里没有 provider 字段时用）。"""
    url = (base_url or "").lower()
    if "11434" in url or "localhost" in url or "127.0.0.1" in url:
        return "local"
    if "deepseek" in url or (model or "").startswith("deepseek"):
        return "deepseek"
    return "openai"

TRIGGER_LABELS = {
    "triple_space": "连按三下空格",
    "double_space": "连按两下空格",
    "ctrl_enter": "Ctrl + Enter",
}

# 「上下文轮数」的显示文案。0 = 每句独立翻（最省 token）；
# 1 = 记住刚过去的那一句（默认，短句消歧收益最大）；2 = 再往前一句。
CONTEXT_LABELS = {0: "不带上文（每句独立）", 1: "带 1 轮（推荐）", 2: "带 2 轮"}
CONTEXT_CHOICES = tuple(sorted(CONTEXT_LABELS))

# 「我发出去的消息」在双语模式下，中文和英文之间拼什么。
# 键名要短：这个值要经 HTML 文档标题传回游戏（compact 包长度是硬约束）。
SEPARATOR_CHOICES = ("pipe", "full", "space")
SEPARATOR_LABELS = {
    "pipe": "中文 | 英文",
    "full": "中文 ｜ 英文",
    "space": "中文  英文（两个空格）",
}
SEPARATOR_TEXT = {
    "pipe": " | ",
    "full": " ｜ ",
    "space": "  ",
}


def separator_text(choice: str) -> str:
    """把选项名变成真正要拼进输入框的那串字符。"""
    return SEPARATOR_TEXT.get(choice, SEPARATOR_TEXT["pipe"])

# 这些字段一变就必须重建 translator（其余字段只影响渲染/开关）
MODEL_FIELDS = ("provider", "model", "base_url", "api_key", "temperature",
                "top_p", "max_tokens", "timeout_s", "context_rounds",
                "keep_alive", "glossary", "max_glossary_terms")

# ---------------------------------------------------------------------------
# 默认值迁移
# ---------------------------------------------------------------------------
# 版本 1 的默认值（历史）：
#   trigger=triple_space, display_mode=replace, outgoing_mode=english_only
# 版本 2：两下空格 / 双语 / 中英都发
# 版本 3（当前）：默认模型 Q6_K -> Q4_K_M
#   实测同一批 38 条测试（30 条中→英 + 8 条英→中）：Q6_K 与 Q4_K_M 术语命中都是 100%、
#   中位延迟 104ms vs 99ms，但 Q4_K_M 只占 4.9 GB 显存 —— 省下的 1.4 GB 直接降低
#   游戏闪退（D3D11 渲染层异常，实为显存吃紧）的风险。
#
# 为什么要这套机制：用户已经有 settings.json 了，**只改代码里的默认值不会生效**
# —— 文件里的旧值会盖住新默认值。下面这张表说明"哪些字段从哪个旧值升到哪个新值"，
# 只有当文件里的值**正好等于旧默认值**（说明用户没改过它）时才升级。
CURRENT_DEFAULTS_VERSION = 5
MIGRATIONS: dict[int, dict[str, tuple[str, str]]] = {
    1: {
        "trigger": ("triple_space", "double_space"),
        "display_mode": ("replace", "bilingual"),
        "outgoing_mode": ("english_only", "bilingual"),
    },
    2: {
        "model": ("hf.co/tencent/Hy-MT2-7B-GGUF:Q6_K",
                  "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"),
    },
    3: {
        # 旧版本把 "none"（= 本地不需要密钥）写进了覆盖层，而覆盖层**优先级高于
        # config.yaml**：于是 config.yaml 里配好的 ${DEEPSEEK_API_KEY} 会被这五个
        # 字符压住，云端一切换就 401。升级成空串 = "没配过，去读 config.yaml"。
        "api_key": ("none", ""),
    },
    4: {
        # 默认来源从"本机 Ollama"改成"DeepSeek 云端"（config.yaml 里也改了）。
        # 只在用户**没动过**来源（文件里还是 local）时迁移；自己切过来源的保持不动。
        #   · provider/model 换成云端那组；
        #   · base_url 清空 —— 留着一串 localhost:11434 配上 deepseek 来源，
        #     等于"来源写着云端、请求发去打不开的本地端口"，报错还很难看懂。
        #     清空之后由 apply_to_config 按 provider 填预设地址（云端官方端点）。
        "provider": ("local", "deepseek"),
        "model": ("hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M", "deepseek-flash"),
        "base_url": ("http://localhost:11434/v1", ""),
    },
}


def migrate_defaults(raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """把旧默认值升级到新默认值；返回 (更新后的 dict, 变更说明)。"""
    version = int(raw.get("defaults_version") or 1)
    changes: list[str] = []
    for ver in sorted(MIGRATIONS):
        if version > ver:
            continue
        for field, (old, new) in MIGRATIONS[ver].items():
            if raw.get(field, old) == old:
                raw[field] = new
                changes.append(f"{field}: {old} -> {new}")
    # 单字段的兜底（不进 MIGRATIONS 表）：老文件里的 "none" 一律当成"没配"。
    # 不这么做，覆盖层里的 "none" 会压住 config.yaml 的密钥，还会被当密钥发出去。
    if str(raw.get("api_key") or "").strip() == "none":
        raw["api_key"] = ""
        changes.append("api_key: none -> (空)")
    raw["defaults_version"] = CURRENT_DEFAULTS_VERSION
    return raw, changes


class AppSettings(BaseModel):
    """游戏内翻译的运行时设置。"""

    # 应用默认值的版本号：默认值改了就把这个数 +1，并在 MIGRATIONS 里登记
    # "旧默认值 -> 新默认值"。这样已存在的 settings.json 只在字段**仍是旧默认值**
    # （= 用户没动过）时被升级；用户自己调过的保持不动。
    defaults_version: int = CURRENT_DEFAULTS_VERSION

    # ---- 开关 ----
    receive_enabled: bool = True      # 英->中：把别人发的英文显示成中文
    send_enabled: bool = True         # 中->英：打中文 + 触发键 -> 英文

    # ---- 显示 ----
    # 默认双语：译文 + 小字原文都留着，看得懂也不丢原文
    display_mode: Literal["replace", "bilingual"] = "bilingual"
    show_original_on_hover: bool = True

    # ---- 发出去的消息（中->英之后写回输入框的内容）----
    #   english_only : 只留英文
    #   bilingual    : 中文原文 + 英文译文都留着，发出去两边都能看
    outgoing_mode: Literal["english_only", "bilingual"] = "bilingual"
    # 双语模式下中英之间的分隔符（见 SEPARATOR_TEXT）
    separator: Literal["pipe", "full", "space"] = "pipe"

    # ---- 输入触发 ----
    # 默认两下空格（比三下顺手；面板里可改回三下）
    trigger: Literal["triple_space", "double_space", "ctrl_enter"] = "double_space"

    # ---- 模型 ----
    # 默认 = DeepSeek 云端（config.yaml 里也是这一组；本机 Ollama 需要自己在面板里切）
    # local = 本机 Ollama（不出网）；deepseek = DeepSeek 官方端点；
    # openai = 任何别的 OpenAI 兼容端点（逃生通道）
    # 注意：这个字段只是**兜底**——真正生效的默认值由 config.yaml 的 base_url 反推
    # （见 defaults_from_config），所以改默认来源要连 config.yaml 一起改。
    provider: Literal["local", "deepseek", "openai"] = "deepseek"
    model: str = "deepseek-flash"
    base_url: str = "https://api.deepseek.com/v1"
    # "" = 还没配过（本地 Ollama 不需要，云端要先在网页里配一次）。
    # 注意**不要**用 "none" 当"没配"：覆盖层里的字面量 "none" 会被当成真密钥发出去，
    # 换回一个 401，看起来像"密钥错了"，其实是"根本没配"。老文件里的 "none" 由迁移清掉。
    api_key: str = ""
    temperature: float = 0.0
    top_p: float = 0.9
    max_tokens: int = 128
    # 最近 N 轮原文/译文作为上下文（短句消歧最有效：项目自己的调研里，
    # "段落短、需要上下文"的场景收益最大）。0 = 关闭。
    #
    # 为什么默认 1 而不是更大的数：一句 "on him" / "no" / "push" 没有上句就没法翻，
    # 但带太多轮会 (a) 让每句的输入 token 线性增长，(b) 把上一句的主语带进这一句
    # （跨句污染）。1 轮 = 只记住屏幕上刚过去的那一句，收益/风险比最好。
    #
    # 注意只作用于**接收**方向（别人发的英文）：发送方向是"我自己要说的话"，
    # 不需要屏幕上别人的聊天历史，见 client._history_for。
    context_rounds: int = 1
    timeout_s: float = 20.0
    keep_alive: str = "60m"           # 模型常驻时长，避免第一条重新载入

    # ---- 词典 ----
    glossary: bool = True

    model_config = {"extra": "ignore"}


def settings_path() -> Path:
    return paths.user_dir() / "settings.json"


def defaults_from_config(cfg: Any) -> AppSettings:
    """把 config.yaml 的值当作默认值（provider 按 base_url 反推）。"""
    t = cfg.translate
    return AppSettings(
        provider=provider_of(t.base_url, t.model),
        model=t.model,
        base_url=t.base_url,
        api_key=_clean_key(resolve_env(t.api_key or "")),
        temperature=t.temperature,
        top_p=t.top_p,
        max_tokens=min(int(t.max_tokens), 256),
        # 上下文轮数**故意不从 config.yaml 取**：以前这里写死 0，
        # 结果 config.yaml 里那行"最近 N 轮上下文（短句消歧最有效）"是句空话。
        # 现在它是用户设置里真正生效的一项（游戏内面板可调），config.yaml 的
        # translate.context_window 不再参与 —— 免得两处都能改、以谁为准要靠猜。
        context_rounds=AppSettings.model_fields["context_rounds"].default,
        timeout_s=t.timeout_s,
        keep_alive=t.keep_alive,
        glossary=bool(t.glossary),
    )


def load_settings(cfg: Any) -> AppSettings:
    """默认值 + 覆盖层合并；覆盖层损坏就退回默认（并留一条日志）。

    顺带做默认值迁移：用户没动过的字段会被升到新默认值，动过的原样保留。
    """
    base = defaults_from_config(cfg)
    path = settings_path()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        merged = {**base.model_dump(), **raw}
        merged, changes = migrate_defaults(merged)
        # api_key 单独一条规矩：空 = "没配过" -> 用 config.yaml 的值（含 ${ENV} 展开）。
        # 不这么做的话，迁移把 "none" 清成 ""，覆盖层就会把一个空密钥盖在
        # config.yaml 已经配好的密钥上面，云端照样 401。
        merged["api_key"] = _effective_key(merged.get("api_key"), base.api_key)
        settings = AppSettings(**merged)
        # 变更过、或者文件里还没有版本号 -> 落盘一次，免得每次启动重复迁移
        if changes or raw.get("defaults_version") != CURRENT_DEFAULTS_VERSION:
            if changes:
                logger.info("默认值已升级: %s", "; ".join(changes))
            save_settings(settings)
        return settings
    except (OSError, ValueError, ValidationError) as e:  # noqa: BLE001
        logger.warning("settings.json 读取失败，用默认值: %s", e)
        return base


def save_settings(settings: AppSettings) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def reset_settings() -> None:
    """恢复默认 = 删掉覆盖层。"""
    try:
        settings_path().unlink(missing_ok=True)
    except OSError as e:  # noqa: BLE001
        logger.warning("删除 settings.json 失败: %s", e)


def _clean_key(value: str) -> str:
    """把密钥规整成"配好了"或"没配"。

    留白和字面量 "none" 都算没配 —— 云端拿 "none" 当密钥只会得到 401，
    还不如老实走 config.yaml 里的值（或者干脆报"没配 Key"）。
    """
    text = (value or "").strip()
    return "" if text in ("", "none") else text


def _effective_key(settings_key: str, cfg_key: str) -> str:
    """算出这次真正要用的密钥。

    规矩（顺序很重要）：
      1. 覆盖层里配了真密钥 -> 用它
      2. 覆盖层是空的/"none" -> 用 config.yaml 的（它可能是 ${ENV} 展开后的结果）
      3. 两边都没有 -> 空串。**绝不把字面量 "none" 当密钥发出去**：那只会换回 401，
         而且报错看起来像"密钥错了"，其实是"根本没配"。

    两边都要过 resolve_env：只对覆盖层展开、对 config.yaml 不展开的话，
    config.yaml 里的 "${DEEPSEEK_API_KEY}"（环境变量没设时展开结果就是它自己）
    会被当成一个"看起来很正常的密钥"，health 报 keySet=true，翻译时才 401。
    展开结果仍是 ${...} 就说明这个环境变量没设 -> 当作没配。
    """
    cfg_resolved = resolve_env(cfg_key or "")
    if _ENV_RE.search(str(cfg_resolved)):
        cfg_resolved = ""
    return _clean_key(resolve_env(settings_key or "")) or _clean_key(cfg_resolved)


def apply_to_config(cfg: Any, settings: AppSettings) -> Any:
    """把设置落到 TranslateConfig 上（provider 决定 base_url 预设）。"""
    base_url = settings.base_url or PROVIDER_PRESETS.get(settings.provider, "")
    return cfg.model_copy(update={
        "translate": cfg.translate.model_copy(update={
            "base_url": base_url,
            # 这里必须比"真假"更严格：settings 里默认的 "none" 是真值，直接用它会让
            # config.yaml 里配好的密钥永远用不上，还会把 "none" 当密钥发出去。
            "api_key": _effective_key(settings.api_key, cfg.translate.api_key) or "none",
            "model": settings.model,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "max_tokens": settings.max_tokens,
            "context_window": max(int(settings.context_rounds), 0),
            "timeout_s": settings.timeout_s,
            "keep_alive": settings.keep_alive,
            "glossary": settings.glossary,
        })
    })


def mask_secret(secret: str) -> str:
    """给网页显示用的掩码：只留头尾，够确认"填的是哪一把 key"，又不可复原。"""
    s = (secret or "").strip()
    if not s or s == "none":
        return ""
    if len(s) <= 10:
        return s[:2] + "*" * (len(s) - 2)
    return f"{s[:6]}{'*' * 8}{s[-4:]}"


def is_key_set(settings: AppSettings) -> bool:
    """这把密钥算不算"配好了"（本地 Ollama 不需要密钥，永远算配好）。"""
    if settings.provider == "local":
        return True
    return bool(_clean_key(settings.api_key))


def effective_view(settings: AppSettings, stats: dict[str, Any],
                   latencies: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """给设置页看的完整视图（含实际生效值与统计）。"""
    view = settings.model_dump()
    view["api_key"] = mask_secret(settings.api_key)   # 明文密钥不出桥
    view["keySet"] = is_key_set(settings)
    view["providerLabel"] = provider_label(settings.provider)
    view["resource"] = {
        "baseUrl": settings.base_url or PROVIDER_PRESETS.get(settings.provider, ""),
        "stats": stats,
        "latencyMs": {k: _median(v) for k, v in (latencies or {}).items() if v},
        "settingsFile": str(settings_path()),
        # 到底是哪一份配置文件在生效？"我改了怎么没反应"十有八九是改错了文件
        # （项目目录的 config.yaml 和 %APPDATA% 那份是两处，优先级还不一样）。
        # 放在这里而不是 health 里：health 每 15 秒被游戏问一次，而它是要经
        # HTML 标题通道传回去的，长度有硬上限（实测 ~900 字符就废）。
        "configFile": str(paths.default_config_path()),
        "triggerLabel": TRIGGER_LABELS.get(settings.trigger, settings.trigger),
        "contextLabel": CONTEXT_LABELS.get(settings.context_rounds,
                                           f"{settings.context_rounds} 轮"),
    }
    return view


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 1)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 1)

"""配置模型与读写（pydantic + yaml）。

## 这里只剩**现役链路**真正读的配置

现役链路 = 游戏内 mod + 本地翻译桥：

    config.yaml  ──load_config()──►  Config(translate, bridge)
                                        │
                     settings.py 把用户覆盖层（%APPDATA%\\settings.json）叠上去
                                        ▼
                     ChatTranslator / BridgeServer

历史上这里还有 app / hotkey / source / console / ocr / display / input / ui 八个
Section，全部属于**外置桌面版**（截屏 OCR + 键盘注入 + Qt 界面）。那条路线已经在
2026-09-13 被 mod 方案取代、2026-09-20 删除代码；这些 Section 现役链路一个字都不读，
留着只会让人以为"改 config.yaml 的 OCR 区域有用"。需要时看 git 历史。

**玩家实际会改的东西在哪**：
  · API Key / 来源 / 模型 / 翻译开关  → 游戏内 `/tongyi` 面板，或网页 http://localhost:8791/settings
  · 端口 / 是否预热                  → 本文件 bridge 段
  · 翻译参数（温度、超时、上下文…）  → 游戏内面板（存进 %APPDATA%\\deadlock-tongyi\\settings.json，
                                        优先级高于本文件的 translate 段）
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from . import paths

CONFIG_PATH = Path("config.yaml")   # 兼容旧引用；实际用 paths.default_config_path()


class TranslateSection(BaseModel):
    # 默认来源 = DeepSeek 云端官方端点（现役 ID：deepseek-flash / deepseek-v4-pro）。
    # 想用本机 Ollama：base_url="http://localhost:11434/v1"、api_key="none"、
    # model="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"（游戏内 /tongyi 面板也能切，不必改代码）。
    base_url: str = "https://api.deepseek.com/v1"
    # 默认留空 = "还没配密钥"：游戏里（/tongyi 面板 / 网页）填过一次就存在 settings.json，
    # 这里留空才不会把它压住。要放环境变量就写 "${DEEPSEEK_API_KEY}"，但注意
    # 环境变量没设时展开结果就是这串占位符本身，等于没有密钥。
    api_key: str = ""
    model: str = "deepseek-flash"
    # DeepSeek 的"思考模式"**默认是开启的（effort=high）**：一句话它先输出几百上千
    # token 的思维链，直接撞 timeout_s；而且思考模式下 temperature 被忽略、top_p 被
    # 抬到 >=0.95，本项目调好的"温度固定 0"全部失效。游戏聊天翻译不需要思考。
    #   off  = 给 DeepSeek 端点显式发 thinking:{"type":"disabled"}（推荐）
    #   auto = 不发这个字段（给别的 OpenAI 兼容端点用，免得被拒参）
    # 只对 DeepSeek 端点生效，其他端点（含本地 Ollama）一律不发。
    thinking: Literal["auto", "off"] = "off"
    # 本地 Ollama 的模型常驻时长。默认 5 分钟空闲就卸载，下次翻译要重新载入
    # （5~40 秒），游戏里表现为"隔一会儿第一条特别慢"。设长一点整局都常驻。
    # 只对本地地址生效（云端接口不认这个字段）。"-1" = 永不卸载。
    keep_alive: str = "60m"
    temperature: float = 0.0
    top_p: float = 0.9
    max_tokens: int = 256
    # 首次请求要把模型载入显存（7B Q6 约 30~40 秒）。设太短会白等重试，
    # 设长一点更划算：预热之后单句只要 0.1~1.3 秒。
    timeout_s: float = 30.0
    max_retries: int = 2
    # ⚠️ 这个字段**已废弃**：上下文轮数改由用户设置里的 context_rounds 管
    # （游戏内 /tongyi 面板可调，默认 1 轮，存 settings.json）。
    # 保留字段是为了让老的 config.yaml 不会因为多一个键而报错；
    # apply_to_config() 会用 settings.context_rounds 覆盖它。
    context_window: int = 0
    # 术语表注入：命中的术语才注入，避免 prompt 过长拖慢速度
    glossary: bool = True
    max_glossary_terms: int = 12
    # 整句命中 phrases.json 时直接返回，不调用模型
    exact_match: bool = True
    # 限制请求速率（秒）。本地模型建议 0；云端建议 0.2 以上。
    min_request_interval_s: float = 0.0
    # 额外 system 提示（可留空）
    system_extra: str = ""


class BridgeConfig(BaseModel):
    """本地翻译桥：给 Deadlock 游戏内 mod 当翻译后端。

    桥只监听本机回环（127.0.0.1 + ::1），不对外暴露。
    """

    enabled: bool = True
    port: int = 8791
    # 启动桥时预热本地模型（首次约 30-40 秒把模型载入显存）
    warmup: bool = True


class Config(BaseModel):
    translate: TranslateSection = TranslateSection()
    bridge: BridgeConfig = BridgeConfig()


_ENV_RE = re.compile(r"\$\{(\w+)\}")


def resolve_env(value: Any) -> Any:
    """把字符串里的 ${VAR} 换成环境变量（递归处理 dict/list）。

    config.yaml 用它把密钥放在环境变量里。**设置覆盖层（settings.json）的值也要过
    这一道**：网页里填 `${DEEPSEEK_API_KEY}` 时，用户期望的就是"从环境变量读"，
    而不是把这 19 个字符当密钥发出去。
    """
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, dict):
        return {k: resolve_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env(v) for v in value]
    return value


# 兼容旧名（内部/测试在用）
_resolve_env = resolve_env


def load_config(path: str | Path | None = None) -> Config:
    """读取配置。path 为空时按 paths.default_config_path() 的优先级找。"""
    p = Path(path) if path is not None else paths.default_config_path()
    if not p.exists():
        return Config()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return Config(**_resolve_env(raw))

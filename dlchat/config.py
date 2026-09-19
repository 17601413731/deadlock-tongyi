"""配置模型与读写（pydantic + yaml）。

设计取舍：
- 单文件 config.yaml，所有开关都在这里，GUI 设置页写回它。
- 字符串里的 ${VAR} 会从环境变量解析，便于把 API key 放在环境变量里。
- 屏幕区域按 1920x1080 基准存归一化坐标（x/y/w/h 都是 0~1），换分辨率不用重设。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

from . import paths

CONFIG_PATH = Path("config.yaml")   # 兼容旧引用；实际用 paths.default_config_path()


class AppSection(BaseModel):
    """全局开关。"""

    # receive=英文->中文显示；send=中文->英文注入。两个可独立开关。
    enable_receive: bool = True
    enable_send: bool = True
    # 只读模式：只翻译显示，绝不向游戏注入任何按键。默认 True，安全优先。
    read_only: bool = True
    # 你自己的游戏内名字：用于跳过自己发的消息（可留空）
    my_name: str = ""
    # 完全不翻译、不显示的关键词（拉黑刷屏的人/内容，逗号分隔）
    blocklist: list[str] = Field(default_factory=list)


class HotkeySection(BaseModel):
    """全局热键（keyboard 库语法）。"""

    # 呼出中文输入小窗（功能2 的主入口）
    send_box: str = "alt+t"
    # 把剪贴板内容当成"我要说的话"翻译并注入
    send_clipboard: str = "alt+y"
    # 临时暂停/恢复接收翻译（打团时想清静）
    toggle_receive: str = "alt+g"
    # 把最近一条收到的英文重译一遍（OCR 出错时手动补救）
    retranslate_last: str = "alt+r"
    # 在游戏里截一张图，之后在静态图上框选区域
    # （无边框全屏游戏里没法用浮层直接框选，必须先截图）
    snapshot: str = "alt+p"


class SourceSection(BaseModel):
    """聊天来源：console=控制台日志（准）；ocr=屏幕识别（保底）。"""

    kind: Literal["console", "ocr"] = "ocr"
    fallback_to_ocr: bool = True  # console 不可用时自动降级到 ocr
    # 只在游戏窗口前台时才抓屏识别。
    # 必须默认开：切到桌面/浏览器/本工具窗口时，那块区域里是别的内容，
    # 不挡住就会把桌面上的文字当聊天翻译（实测踩过这个坑）。
    require_game_focus: bool = True


class ConsoleSourceSection(BaseModel):
    # 留空则自动探测 Deadlock 安装目录（默认走 D 盘的 Steam 库）
    game_dir: str = ""
    # 留空则自动探测 console.log 的常见路径
    log_path: str = ""
    # 额外候选路径（支持 ${ENV} 与 %USERPROFILE%）
    extra_candidates: list[str] = Field(default_factory=list)
    # 控制台日志里聊天行的匹配（正则，可多条）
    line_patterns: list[str] = Field(default_factory=lambda: [
        r"^\s*\[(?P<chan>All Chat|Allies Chat|Party Chat|Team Chat)\]\s*\[(?P<name>.+?)\s*\(\d+\)\]:\s*(?P<msg>.+?)\s*$",
        r"^\s*\[(?P<chan>ALL|ALLIES|PARTY|TEAM)\]\s*(?P<name>[^:]{1,32}):\s*(?P<msg>.+?)\s*$",
    ])
    poll_interval_ms: int = 120
    # 启动时从文件末尾开始（True），或从头把历史也读进来（False）
    tail_from_end: bool = True


class OCRSection(BaseModel):
    backend: Literal["rapidocr", "windows"] = "rapidocr"
    # 归一化坐标（相对屏幕宽高，0~1）。
    # 实测（1920x1080 真实对局截图）：
    #   y 0.000~0.086  12 个英雄头像
    #   y 0.086~0.107  等级数字（要排除，否则会被当聊天）
    #   y 0.19~0.30    聊天气泡（最新在上，每人最多 3 条，10 秒淡出）
    # 所以默认框"头像下方到气泡堆叠底"这一带。
    region: list[float] = Field(default_factory=lambda: [0.0, 0.10, 1.0, 0.33])
    # 是否用「框选聊天区域」校准过。没校准过时界面会一直提醒——
    # 实测踩过坑：没校准时那块区域里是桌面内容，会把文件名当聊天翻译。
    region_calibrated: bool = False
    interval_ms: int = 700          # 抓帧间隔
    # 画面变化阈值（0~1）。低于它就不跑 OCR，省 CPU。
    change_threshold: float = 0.010
    min_confidence: float = 0.55
    # 检测器输入尺寸限制。必须是 max + 一个不太大的值：
    # 默认的 min/736 会把"又宽又扁"的聊天条短边放大到 736，
    # 检测输入变成上千万像素，实测单帧 4~7 秒。
    det_limit_side: int = 960
    det_limit_type: Literal["max", "min"] = "max"
    # True=整块文本检测+识别（默认，聊天条用这个）
    # False=按 rows 切条只做识别（每行约 90ms，但要求行高完全对得上，
    #      实测容易把两行粘成一行，只在"输入行"这种天生一行的场景用）
    detect: bool = True
    rows: int = 6                   # detect=False 时把区域切成几条
    filter_hud: bool = True         # 过滤掉 HUD 数字/UI 词，避免翻译垃圾
    # 预处理：聊天文字是浅色小字 + 半透明底，放大+反色后识别率更高
    upscale: int = 2
    invert: bool = False
    # 同一个屏幕区域里，最多取几行
    max_lines: int = 8


class TranslateSection(BaseModel):
    # 默认来源 = DeepSeek 云端官方端点（现役 ID：deepseek-flash / deepseek-v4-pro）。
    # 想用本机 Ollama：base_url="http://localhost:11434/v1"、api_key="none"、
    # model="hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"（游戏内 F8 面板也能切，不必改代码）。
    base_url: str = "https://api.deepseek.com/v1"
    # 默认留空 = "还没配密钥"：游戏里（F8 面板 / 网页）填过一次就存在 settings.json，
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
    # 最近 N 轮原文/译文作为上下文（短句消歧最有效）。0 = 关闭。
    context_window: int = 3
    # 术语表注入：命中的术语才注入，避免 prompt 过长拖慢速度
    glossary: bool = True
    max_glossary_terms: int = 12
    # 整句命中 phrases.json 时直接返回，不调用模型
    exact_match: bool = True
    # 限制请求速率（秒）。本地模型建议 0；云端建议 0.2 以上。
    min_request_interval_s: float = 0.0
    # 额外 system 提示（可留空）
    system_extra: str = ""


class DisplaySection(BaseModel):
    overlay: bool = True
    # 悬浮窗锚点：chat=贴左下聊天区；bottom=屏幕底部居中
    anchor: Literal["chat", "bottom", "custom"] = "chat"
    custom_pos: list[int] = Field(default_factory=lambda: [40, 640])  # 绝对像素 x,y
    font_family: str = "Microsoft YaHei"
    font_size: int = 15
    opacity: float = 0.88
    max_lines: int = 5
    # 译文显示方式：replace=只显示中文；both=英文原文+中文
    mode: Literal["replace", "both"] = "replace"
    hide_after_s: float = 25.0   # 无新消息后自动淡出


class InputSection(BaseModel):
    """中文->英文 的交付方式。

    默认 handoff="clipboard"：**零键盘注入**。你在游戏聊天框里打中文 -> 连按 3 次
    空格触发 -> 工具 OCR 读出中文并翻译 -> 英文进剪贴板 + 悬浮窗显示 -> 你自己
    Ctrl+A、Ctrl+V、回车。工具只截屏 + 监听键盘，不注入任何按键。

    handoff="inject" 才启用旧的自动注入（L1/L2/L3），默认关闭。
    """

    handoff: Literal["clipboard", "inject"] = "clipboard"

    # ---- 零注入路径：触发方式 ----
    trigger: Literal["space_taps", "hotkey"] = "space_taps"
    tap_key: str = "space"
    taps: int = 3
    tap_window_s: float = 1.5
    require_game_focus: bool = True   # 只在游戏窗口前台时响应（聊天框打开时才算）
    # 是否用「框选输入行」校准过；没校准时界面会提醒
    input_region_calibrated: bool = False
    # 聊天输入行的归一化区域 [左, 上, 右, 下]，聊天框打开时才有内容
    input_region: list[float] = Field(default_factory=lambda: [0.28, 0.30, 0.74, 0.37])
    show_original: bool = True        # 悬浮窗同时显示中文原文，方便核对 OCR

    # ---- 注入路径（handoff="inject" 时才用）----
    level: Literal["L1", "L2", "L3"] = "L2"
    auto_send: bool = False        # 注入后自动回车发送（默认关）
    keep_clipboard: bool = True    # 注入前保存剪贴板，完后恢复
    key_delay_ms: int = 35         # 逐字注入间隔（太小会被游戏吞）
    open_chat_key: str = "enter"   # 打开聊天框的键
    clear_first: bool = True       # 注入前是否先清空聊天框（Ctrl+A 再 Delete）
    max_chars: int = 200           # 英文译文超过这个长度就截断（防刷屏）
    send_prefix: str = ""          # 例如 "[CN] "
    # 「我发出去的消息」在双语模式下，中文原文和英文译文之间的分隔符。
    #   pipe  = "中文 | 英文"（半角竖线，默认）
    #   full  = "中文 ｜ 英文"（全角竖线，中文字体里字形更稳）
    #   space = "中文  英文"（老行为，两个空格）
    # 只是拼给你看的一串字，翻错了一眼能看见；游戏里渲染不对就换个选项。
    separator: Literal["pipe", "full", "space"] = "pipe"


class UIConfig(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    start_minimized: bool = False
    log_level: str = "INFO"


class BridgeConfig(BaseModel):
    """本地翻译桥：给 Deadlock 游戏内 mod（BabelTower 的 UI）当翻译后端。

    桥只监听本机回环（127.0.0.1 + ::1），不对外暴露。
    """

    enabled: bool = True
    port: int = 8791
    # 启动桥时预热本地模型（首次约 30-40 秒把模型载入显存）
    warmup: bool = True


class Config(BaseModel):
    app: AppSection = AppSection()
    hotkey: HotkeySection = HotkeySection()
    source: SourceSection = SourceSection()
    console: ConsoleSourceSection = ConsoleSourceSection()
    ocr: OCRSection = OCRSection()
    translate: TranslateSection = TranslateSection()
    bridge: BridgeConfig = BridgeConfig()
    display: DisplaySection = DisplaySection()
    input: InputSection = InputSection()
    ui: UIConfig = UIConfig()


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


def save_config(cfg: Config, path: str | Path | None = None) -> None:
    p = Path(path) if path is not None else paths.default_config_path()
    data = cfg.model_dump(mode="json")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                     encoding="utf-8")
    except OSError as e:
        logging.getLogger(__name__).warning("写配置失败 %s: %s", p, e)

"""桥自检：把游戏侧真正会走的那几条路全部跑一遍（含 op 白名单与 payload 大小）。

为什么需要它：
  · 游戏内的通道是把响应写进 HTML 文档标题再读回来，**payload 太长会被截断**，
    于是表现为"读取失败：bad_json"——所以这里会打印每个响应的字符数；
  · 桥页面有个 op 白名单，新增 op（settings / settings/test / models）忘记放行时
    会被静默降级成 translate，只有从页面这条路上测才能发现。

用法：
    python scripts/bridge_selftest.py [port]
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 离线算 compact 长度时用的假用户目录（绝不碰真实的 settings.json）
_TMP_DIR = Path(tempfile.gettempdir()) / "dlchat-selftest-scratch"

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
BASE = f"http://127.0.0.1:{PORT}"
FAILS: list[str] = []

# 自检开始/结束时用来快照与还原的字段。
# ⚠ 故意**不含 api_key**：读回来的 api_key 是掩码（不可能是明文），照着还原会
# 把用户真正的密钥覆盖成 "sk-abc****" 这种垃圾。密钥不归自检管。
SNAPSHOT_FIELDS = ("receive_enabled", "send_enabled", "display_mode", "outgoing_mode",
                   "show_original_on_hover", "trigger", "keep_alive", "glossary",
                   "model", "provider", "base_url")


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAILS.append(name)


def get(path: str, timeout: int = 30):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return r.read().decode("utf-8")


def post(path: str, payload) -> dict:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def page_op(op: str, d: str) -> str:
    """从 /bridge 页面里解析出它最终会调用的 op（白名单是否放行）。"""
    html = get(f"/bridge?id=z&op={op}&d={d}")
    m = re.search(r"var op = '([^']+)'", html)
    return m.group(1) if m else "?"


def main() -> int:
    print(f"=== 桥自检 {BASE}")
    # 自检会改设置（含"恢复默认"），先记下用户当前的设置，跑完还原 —— 测试工具不该
    # 顺手把用户配置清掉。
    snapshot = None
    try:
        snap_raw = get("/api/v1/settings?d=%7B%22view%22%3A%22compact%22%7D")
        snap = json.loads(snap_raw)
        if snap.get("persisted"):
            snapshot = {k: snap[k] for k in SNAPSHOT_FIELDS if k in snap}
    except Exception as e:  # noqa: BLE001
        print(f"  （读取当前设置失败，跳过还原）: {e}")

    print("[1] op 白名单（页面必须原样放行，降级成 translate 就是 bug）")
    for op in ("translate", "health", "settings", "settings%2Ftest", "models", "log"):
        resolved = page_op(op, "%7B%7D")
        want = op.replace("%2F", "/")
        check(f"op={want}", resolved == want, f"页面解析为 {resolved}")

    print("[2] 游戏侧 payload 大小（标题通道有长度上限，超了会被截断）")
    compact = get("/api/v1/settings?d=%7B%22view%22%3A%22compact%22%7D")
    # 两级门禁，因为这两个数各自有据可依：
    #   · 380 = 日常警戒线。实测 479 字符会被截断成半截 JSON（前端只解析出
    #     {"ok":true}，面板上一片 undefined），留 100 字符余量足够。
    #   · 440 = 硬上限。本机最长的本地模型名（hf.co/tencent/...:Q4_K_M，40 字符）
    #     已经占到 378；再长的模型名（ollama 允许 70+ 字符）就会顶穿 380。
    #     这种时候要的是"能跑 + 有报告"，而不是把面板变成一片 undefined。
    WARN, HARD = 380, 440
    check(f"compact 设置 < {WARN} 字符（警戒）", len(compact) < WARN,
          f"{len(compact)} 字符")
    check(f"compact 设置 < {HARD} 字符（必须）", len(compact) < HARD,
          f"{len(compact)} 字符")
    for provider, model in _worst_case_models():
        n = len(_compact_size(provider, model))
        check(f"  {provider}/{_short(model)} < {HARD}", n < HARD, f"{n} 字符")
        if n >= WARN:
            print(f"    ⚠ 已超警戒线 {WARN}：模型名太长，面板会少显示几个字段")
    check("compact 是合法 JSON", _is_json(compact))
    for field in ("disp", "trig", "model", "keep", "out"):
        check(f"compact 带 {field}（短键）", f'"{field}"' in compact)
    check("compact 带来源（单字母码 prv）", '"prv"' in compact)
    check("compact 带密钥状态 keySet", '"keySet"' in compact)
    check("compact 带分隔符（单字母码 sep）", '"sep"' in compact)
    models = get("/api/v1/models")
    check("模型列表可读", _is_json(models),
          f"{len(models)} 字符 / {len(json.loads(models).get('models', []))} 个")
    for prov in ("local", "deepseek"):
        one = get(f"/api/v1/models?d=%7B%22provider%22%3A%22{prov}%22%7D")
        data = json.loads(one) if _is_json(one) else {}
        check(f"模型列表跟随来源 {prov}", data.get("provider") == prov,
              f"{data.get('models')}")
    health = get("/api/v1/health")
    # health 被游戏每 15 秒拉一次，而且要经 HTML 标题通道传回去（实测 ~900 字符就废）。
    # 所以卡在 700：留足余量，也给以后加字段的人一个明确的红线。
    check("health < 700 字符", len(health) < 700, f"{len(health)} 字符")
    h = json.loads(health) if _is_json(health) else {}
    check("health 报的是当前生效来源", ":" in str(h.get("provider")),
          f"provider={h.get('provider')} keySet={h.get('keySet')}")
    check("health 不带文件路径（那是完整视图的事）", "settingsFile" not in h)

    print("[3] 设置读写")
    # 注意两种响应的键名不一样：
    #   · 保存回执里的 settings 是 **compact**（短键 disp/out/trig/model/prv）
    #   · GET /api/v1/settings 不带 view 时是完整视图（长键 display_mode/...）
    r = post("/api/v1/settings", {"display_mode": "bilingual"})
    check("写入生效", r.get("ok") and r["settings"]["disp"] == "bilingual",
          str(r.get("settings", {}).get("disp")))
    # 回执必须小：游戏侧通道写进 HTML 文档标题，太长会被截断成非法 JSON
    # （实测 897 字符的回执就会触发前端 event_bad_json）
    receipt = len(json.dumps(r, ensure_ascii=False))
    check("保存回执 < 500 字符", receipt < 500, f"{receipt} 字符")
    back = json.loads(get("/api/v1/settings?d=%7B%22view%22%3A%22compact%22%7D"))
    check("读回一致", back.get("disp") == "bilingual")
    r2 = post("/api/v1/settings", {"reset": True})
    # 和"当前代码里的默认值"比，别写死字面量 —— 默认值改过一次（双语/两下空格），
    # 写死会导致自检误报。
    from dlchat.settings import AppSettings as _S
    default_mode = _S().display_mode
    check("恢复默认", r2.get("ok") and r2["settings"]["disp"] == default_mode,
          f"默认 {default_mode}")
    full = json.loads(get("/api/v1/settings"))
    check("完整视图用长键", full.get("display_mode") is not None
          and full.get("provider") is not None)
    check("完整视图里的密钥是掩码", "sk-" not in json.dumps(full.get("api_key") or ""),
          str(full.get("api_key"))[:12] or "（没配）")

    print("[4] 试翻（两个方向）")
    t = post("/api/v1/settings/test", {"text": "he is low, dive him"})
    if t.get("hint"):
        # 云端没配 Key 时会走到这里：要的是"说清楚 + 给入口"，不是一句 unknown
        check("没配 Key 时说清楚并给入口", "8791/settings" in t["hint"], t["hint"])
    else:
        check("试翻返回译文+延迟",
              t.get("ok") and t.get("translation") and isinstance(t.get("ms"), int),
              f"{t.get('translation')!r} {t.get('ms')}ms | "
              f"back={t.get('back')!r} {t.get('backMs')}ms")
    tsize = len(json.dumps(t, ensure_ascii=False))
    check("试翻回执 < 500 字符", tsize < 500, f"{tsize} 字符")

    print("[5] 翻译响应带渲染提示（mod 靠它即时跟随设置）")
    tr = post("/api/v1/translate",
              {"text": "mid no", "sourceLanguage": "en", "targetLanguage": "zh-Hans"})
    hints = {k: tr.get(k) for k in ("displayMode", "outgoingMode", "receiveEnabled",
                                    "sendEnabled", "trigger", "provider", "keySet",
                                    "separator")}
    check("渲染提示齐全", all(v is not None for v in hints.values()), str(hints))

    print("[5b] 双语分隔符跟着设置走")
    for choice, want in (("pipe", " | "), ("full", " ｜ "), ("space", "  ")):
        r = post("/api/v1/settings", {"separator": choice})
        if not r.get("ok"):
            check(f"分隔符 {choice} 可保存", False, str(r.get("error")))
            continue
        trh = post("/api/v1/translate",
                   {"text": "mid no", "sourceLanguage": "en", "targetLanguage": "zh-Hans"})
        check(f"分隔符 {choice} 生效", trh.get("separator") == want,
              repr(trh.get("separator")))
    post("/api/v1/settings", {"separator": "pipe"})

    print("[6] 我发出去的消息：只发英文 / 中英都发")
    r = post("/api/v1/settings", {"outgoing_mode": "bilingual"})
    check("可保存", r.get("ok") and r["settings"]["out"] == "bilingual")
    back = json.loads(get("/api/v1/settings?d=%7B%22view%22%3A%22compact%22%7D"))
    check("compact 读取带上该字段", back.get("out") == "bilingual")
    tr2 = post("/api/v1/translate",
               {"text": "mid no", "sourceLanguage": "en", "targetLanguage": "zh-Hans"})
    check("翻译响应跟着变成 bilingual", tr2.get("outgoingMode") == "bilingual",
          str(tr2.get("outgoingMode")))
    post("/api/v1/settings", {"reset": True})

    print("[7] 网页设置页（配 API Key 的唯一入口）")
    page = get("/settings")
    check("页面能打开", "<!DOCTYPE html>" in page and 'id="api_key"' in page,
          f"{len(page)} 字符")
    check("只配 API Key，别的设置不在这里",
          all(k not in page for k in ("术语表", "温度", "模型常驻", "译文显示方式")))
    check("页面说明了去哪改别的（游戏内 F8）", "F8" in page)

    print(f"\n[结果] {'全部通过' if not FAILS else '失败项: ' + ', '.join(FAILS)}")
    if snapshot:
        try:
            post("/api/v1/settings", snapshot)
            print("[还原] 已恢复自检前的设置")
        except Exception as e:  # noqa: BLE001
            print(f"[还原] 失败：{e}")
    return 0 if not FAILS else 1


def _is_json(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except Exception:  # noqa: BLE001
        return False


def _worst_case_models() -> list[tuple[str, str]]:
    """各来源里最长的模型名 —— compact 响应的长度就是被它顶上去的。"""
    from dlchat.settings import provider_models

    rows: list[tuple[str, str]] = []
    for name in ("local", "deepseek"):
        models = provider_models(name)
        if name == "local":
            # 本地清单是运行时问 Ollama 的，预设表里是空的；本机实测最长就是这个
            models = ["hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M"]
        if models:
            rows.append((name, max(models, key=len)))
    return rows


def _compact_size(provider: str, model: str) -> str:
    """离线算出 compact 响应会长成什么样。

    直接问生产代码要那个包（用假的 translator/后端），而不是在这里抄一份字段表 ——
    抄一份的下场就是两边慢慢跑偏，门禁测的是"复印件"而不是真东西。
    """
    from unittest import mock

    from dlchat import paths
    from dlchat.bridge.server import BridgeApp
    from dlchat.config import Config
    from dlchat.settings import AppSettings

    class _NoopTranslator:
        last_error = ""

        async def translate_full(self, text, direction):
            return ""

        async def prewarm(self):
            return True

        async def close(self):
            pass

    with mock.patch.object(paths, "user_dir", lambda: _TMP_DIR):
        app = BridgeApp(Config())
    app.translator = _NoopTranslator()
    app.settings = AppSettings(provider=provider, model=model or "x",
                               api_key="sk-" + "x" * 24)
    app.stats = {"requests": 128, "cache_hits": 55, "errors": 0}
    app._latencies = {"en->zh": [812.0], "zh->en": [210.0]}   # noqa: SLF001
    app.backend_status = lambda: {}
    payload = app.settings_view(compact=True, with_backend=False)
    return json.dumps(payload, ensure_ascii=False)


def _short(model: str) -> str:
    return model if len(model) <= 24 else model[:21] + "..."


if __name__ == "__main__":
    raise SystemExit(main())

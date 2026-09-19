"""复现"保存了但没落地"：发一个和游戏侧完全一样的保存请求，看响应与文件。

用法：python scripts/settings_probe.py [port]
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8791
BASE = f"http://127.0.0.1:{PORT}"

# 游戏内面板保存时发的字段（ui.local）
GAME_PAYLOAD = {
    "receive_enabled": True,
    "send_enabled": True,
    "display_mode": "replace",
    "show_original_on_hover": True,
    "trigger": "triple_space",
    "keep_alive": "60m",
    "glossary": True,
    "model": "hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M",
}

# 面板在 payload 为空时会发的"默认请求对象"（页面里的兜底 req）
PAGE_DEFAULT = {
    "operation": "settings", "text": "", "sourceLanguage": "auto",
    "targetLanguage": "zh-Hans",
}


def post(payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + "/api/v1/settings", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def main() -> int:
    from dlchat.settings import settings_path
    path = settings_path()
    print(f"设置文件: {path}")
    print(f"  保存前存在? {path.exists()}")

    print("\n[1] 用游戏面板的真实字段保存")
    code, body = post(GAME_PAYLOAD)
    print(f"  HTTP {code}  {json.dumps(body, ensure_ascii=False)[:160]}")
    print(f"  保存后存在? {path.exists()}"
          + (f"  ({path.stat().st_size} B)" if path.exists() else ""))
    if path.exists():
        print("  内容:", path.read_text(encoding="utf-8")[:200].replace("\n", " "))

    print("\n[2] 用页面兜底的默认对象保存（payload 为空时会发生）")
    code, body = post(PAGE_DEFAULT)
    print(f"  HTTP {code}  {json.dumps(body, ensure_ascii=False)[:160]}")

    print("\n[3] 重启后是否读得回来（模拟桥重启）")
    import importlib
    from dlchat import settings as S
    from dlchat.config import load_config
    importlib.reload(S)
    s = S.load_settings(load_config())
    print(f"  读回 display_mode={s.display_mode} trigger={s.trigger} "
          f"model={s.model} keep_alive={s.keep_alive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

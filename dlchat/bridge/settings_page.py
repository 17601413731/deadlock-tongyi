"""一页只干一件事：配云端翻译的 API Key。

## 为什么这个页面存在，而且只有这一个输入框

翻译本身、开关、显示方式、模型选择**全在游戏内的 mod 面板**（聊天框输入 `/tongyi`，
或点输入框那行的「设置」）。唯一没法在游戏里做的事是**输入密钥**：Panorama 没有密码框、
读不到剪贴板，让玩家在聊天框里敲 `sk-...` 既不安全也难用。

所以这页刻意只留一个 API Key 输入框 —— 再加上一堆开关，就会出现"两个地方都能改、
以谁为准"的疑问，那不是玩家想要的东西。

## 为什么密钥存在桥这一侧

密钥只有桥用来向 DeepSeek 发请求，mod（Panorama JS）根本不需要知道它。存在
`%APPDATA%\\deadlock-tongyi\\settings.json`（用户覆盖层，config.yaml 不动），
**保存即刻生效**、重启桥和游戏后依然有效。

页面自包含：不引任何外部 CSS/JS/字体（游戏机可能没外网），深色、紧凑。
"""

from __future__ import annotations

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>通译 · API Key</title>
<style>
  :root{
    --bg:#14161a; --panel:#1b1e24; --panel2:#21252c; --line:#2c313a;
    --text:#e6e9ee; --dim:#9aa4b2; --accent:#4da3ff; --ok:#3fbf6f; --bad:#e05c5c;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);min-height:100vh;
       font:14px/1.6 "Segoe UI","Microsoft YaHei",system-ui,sans-serif;
       display:flex;align-items:center;justify-content:center;padding:24px}
  .card{width:100%;max-width:560px;background:var(--panel);border:1px solid var(--line);
        border-radius:14px;padding:26px 28px 22px}
  h1{font-size:17px;margin:0 0 4px;font-weight:600;letter-spacing:.3px}
  .sub{color:var(--dim);font-size:12.5px;margin-bottom:20px}
  label{display:block;font-size:13px;color:var(--dim);margin-bottom:7px}
  .field{display:flex;gap:10px;flex-wrap:wrap}
  input[type=text]{flex:1;min-width:220px;background:var(--panel2);color:var(--text);
      border:1px solid var(--line);border-radius:9px;padding:10px 12px;font:inherit;
      font-family:Consolas,"Cascadia Mono",monospace;outline:none}
  input[type=text]:focus{border-color:var(--accent)}
  button{background:var(--panel2);color:var(--text);border:1px solid var(--line);
         border-radius:9px;padding:10px 18px;font:inherit;cursor:pointer}
  button:hover{border-color:var(--accent)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#08111d;
                 font-weight:600}
  button.primary:hover{filter:brightness(1.08)}
  .hint{color:var(--dim);font-size:12.5px;margin-top:12px}
  .hint code{background:#0f1115;border:1px solid var(--line);border-radius:5px;
             padding:1px 6px;font-size:12px}
  .kv{display:flex;justify-content:space-between;gap:12px;padding:6px 0;
      border-bottom:1px dashed rgba(255,255,255,.06);font-variant-numeric:tabular-nums}
  .kv:last-child{border-bottom:0}
  .kv span:first-child{color:var(--dim)}
  .tag{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;
       border:1px solid var(--line);color:var(--dim)}
  .tag.ok{color:var(--ok);border-color:rgba(63,191,111,.5)}
  .tag.bad{color:var(--bad);border-color:rgba(224,92,92,.5)}
  .status{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}
  pre{background:#0f1115;border:1px solid var(--line);border-radius:10px;padding:11px 13px;
      margin:12px 0 0;white-space:pre-wrap;word-break:break-word;min-height:20px;
      font:13px/1.5 Consolas,"Cascadia Mono",monospace}
  #toast{position:fixed;left:50%;transform:translateX(-50%);bottom:26px;background:#0f1115;
         border:1px solid var(--line);border-radius:10px;padding:10px 18px;opacity:0;
         transition:opacity .2s;pointer-events:none}
  #toast.show{opacity:1}
</style>
</head>
<body>
<div class="card">
  <h1>云端翻译 API Key</h1>
  <div class="sub">填一次就永久生效（存在 <code>settings.json</code>，桥和游戏重启后依然有效）</div>

  <label for="api_key">DeepSeek API Key</label>
  <div class="field">
    <input type="text" id="api_key" spellcheck="false" autocomplete="off"
           placeholder="sk-...">
    <button class="primary" id="save">保存</button>
  </div>

  <div class="hint">
    · 在 <b>platform.deepseek.com</b> 的 API keys 页面创建，形如 <code>sk-xxxxxxxx</code><br>
    · 本机用 <b>Ollama</b> 时不需要填这一项<br>
    · 想改用环境变量：这里填 <code>${DEEPSEEK_API_KEY}</code>，桥会去读系统环境变量<br>
    · 翻译来源（本地 / DeepSeek）、模型、显示方式都在<b>游戏内 mod 面板</b>里改 ——
      聊天框输入 <b>/tongyi</b>，或点聊天输入框那一行右边的「设置」
  </div>

  <div class="status">
    <div class="kv"><span>当前翻译来源</span><span id="s_provider">-</span></div>
    <div class="kv"><span>当前模型</span><span id="s_model">-</span></div>
    <div class="kv"><span>我发出去的消息</span><span id="s_format">-</span></div>
    <div class="kv"><span>API Key</span><span id="s_key" class="tag">-</span></div>
    <button id="test" style="margin-top:12px">试翻一句</button>
    <pre id="s_test">保存后点"试翻一句"，验证 key 能不能真的用</pre>
  </div>
</div>
<div id="toast"></div>

<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var toastTimer = null;

  function toast(msg) {
    var el = $("toast");
    el.textContent = msg;
    el.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.classList.remove("show"); }, 2400);
  }

  function api(path, body) {
    var opts = body
      ? { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body) }
      : { method: "GET" };
    return fetch(path, opts).then(function (r) { return r.json(); });
  }

  function fill(data) {
    // 只显示掩码，明文不回浏览器；用户没动这个框就表示"不修改"。
    // 掩码留在 dataset 上做比较 —— 保存回执是给游戏面板的**精简包**（不含密钥），
    // 不能拿它判断"用户动没动过这一栏"。
    var masked = data.api_key || "";
    $("api_key").value = masked;
    $("api_key").dataset.masked = masked;
    $("s_provider").textContent = (data.providerLabel || data.provider || "-")
      + "  (" + (data.provider || "-") + ")";
    $("s_model").textContent = data.model || "-";
    var mode = data.outgoing_mode === "bilingual" ? "中英都发" : "只发英文";
    var sep = data.separator || " | ";
    $("s_format").textContent = data.outgoing_mode === "bilingual"
      ? mode + "（中文" + sep + "英文）" : mode;
    var tag = $("s_key");
    var local = data.provider === "local";
    tag.textContent = local ? "本地不需要" : (data.keySet ? "已配置" : "未配置");
    tag.className = "tag " + (local || data.keySet ? "ok" : "bad");
  }

  function reload() {
    return api("/api/v1/settings").then(fill).catch(function (e) {
      toast("连不上桥：" + e);
    });
  }

  $("save").onclick = function () {
    var box = $("api_key");
    var value = box.value.trim();
    if (value && value === box.dataset.masked) {
      toast("内容没改动");
      return;
    }
    api("/api/v1/settings", { api_key: value }).then(function (r) {
      if (!r || !r.ok) {
        toast("保存失败：" + ((r && r.error) || "未知错误"));
        return;
      }
      toast(value ? "已保存并立即生效" : "已清空 API Key");
      // 回执里的 settings 是游戏面板用的精简包（没有密钥字段），所以重新读一次完整视图
      reload();
    }).catch(function (e) { toast("保存失败：" + e); });
  };

  $("test").onclick = function () {
    var box = $("s_test");
    box.textContent = "测试中…（云端首次可能要等一两秒）";
    api("/api/v1/settings/test", { text: "he is low, dive him", source: "en",
                                   target: "zh-Hans" }).then(function (r) {
      if (r && r.ok) {
        box.textContent = "英->中  " + r.translation + "   (" + r.ms + " ms)\n"
          + "中->英  " + (r.back || "-") + "   (" + (r.backMs || "-") + " ms)";
      } else {
        box.textContent = "失败：" + ((r && r.error) || "未知错误")
          + (r && r.hint ? "\n" + r.hint : "");
      }
    }).catch(function (e) { box.textContent = "失败：" + e; });
  };

  reload();
})();
</script>
</body>
</html>
"""

# 游戏内翻译（mod 方案）—— 本项目的最终路线

## 结论：用 BabelTower 的 mod UI + 我们自己的 Python 翻译桥

2026-09-13 决定转向 mod 方案。原因很直接：外置方案（截屏 OCR + 键盘注入）**本质上不可靠** ——
需要校准区域（无边框全屏游戏里连框选都做不了）、依赖屏幕布局、还要模拟按键。
而 mod 方案是**天生在游戏里生效**的：读的是游戏 UI 的文字，显示的是游戏内的译文。

参考项目：[c1375rick/BabelTower](https://github.com/c1375rick/BabelTower)（GPL-3.0）——
一个已经验证可用的 Deadlock 聊天翻译 mod。我们**不重复造它的 UI**（那部分要在游戏里反复调试，
且它已经稳定），只把它的**翻译后端（本地 Node 桥 + Bing）换成我们自己的 Python 桥**。

```
┌─────────────────── 游戏进程 ───────────────────┐
│ Panorama 聊天 UI（BabelTower 的 chat.xml/js）  │
│   扫描聊天行 → 去重/缓存 → 隐藏 HTML 面板       │
│   ├─ 译文追加显示在原消息下方（双语/仅译文）     │
│   └─ 发送前翻译（按快捷键把要说的话翻成英文）     │
└───────────────────────┬────────────────────────┘
                        │ http://localhost:8791（仅本机）
┌───────────────────────┴────────────────────────┐
│ ★ 我们的 Python 翻译桥（dlchat/bridge/）        │
│   /api/v1/translate → 术语表 + DeepSeek 云端（默认）│
│   3926 条术语 / 118 条整句直译 / 俚语 / 保留词   │
│   来源可切：DeepSeek 云端（默认）/ 本地 Ollama    │
└────────────────────────────────────────────────┘
```

## 为什么这样比直接用 BabelTower 更好

| 维度 | BabelTower 自带桥（Node.js） | 我们的桥（Python） |
|---|---|---|
| 翻译引擎 | Bing 公共接口（免 Key）/ Azure / DeepL / OpenAI | **DeepSeek 云端 `deepseek-flash`**（默认），游戏内面板一键切 **本地 Ollama Hy-MT2-7B** |
| 隐私 | 聊天内容发往微软/第三方 | 本地来源**不出本机**；切到 DeepSeek 后聊天内容会出网（面板会写明） |
| 成本 | 公共接口限流，长期用要么被限流要么付费 | 0 |
| 术语覆盖 | 内置 2801 条 + 自适应学习 | **3926 条**（从游戏本地化自动生成）+ **118 条整句直译** + 73 条俚语 + 56 条保留英文 |
| 名称保护 | 285 条英雄/物品名 | **400 条**（含社区别名，如 Warden→沃督/守望者/警长） |
| 术语约束方式 | 查表替换 | 查表 + **提示词注入**（只注入本句命中的 ≤12 条）+ 译后校验 |
| 额外运行时 | 需要装 Node.js 18+ | **不需要**（Python 环境已有） |
| 复用 | —— | 复用本项目已调好的 translator/提示词/缓存/术语表（147 个测试覆盖） |

实测对比（本机 Ollama，游戏运行时）：

```
英→中  mid no                  -> 中路没人
       he's low dive him       -> 他残血，冲啊
       push B and get urn      -> 推进到B位置拿魂瓮
       need help with urn pls  -> 需要帮忙处理魂瓮，快点
       stop feeding noob       -> 别送了，菜鸟
       gg wp                   -> gg wp            （保留英文，符合中国玩家习惯）
中→英  中路没人，我去拿魂瓮      -> mid's empty, gonna grab the urn
      他残血，上               -> he's low, push
      别送了                   -> stop feeding
```

## 怎么用（三步）

### 1. 装 mod（游戏内 UI 层）

从 [BabelTower Releases](https://github.com/c1375rick/BabelTower/releases) 拿 `pak01_dir.vpk`：

* **推荐**：用 Deadlock Mod Manager 导入（自动分配空闲 pak 槽位）
* 或手动：复制到 `Deadlock/game/citadel/addons/`，改名成空闲的 `pakNN_dir.vpk`
  （`NN` 取一个游戏没用到的编号，别覆盖自带 pak）

⚠️ mod 是**客户端资源覆盖**，社区通用做法；但每次游戏大版本更新后可能要重新适配。

### 2. 启动我们的桥（翻译大脑）

```powershell
cd C:\Users\Hlliang\Desktop\deadlock-tongyi
ollama serve                      # 本地翻译模型（已有）
python scripts\run_bridge.py      # 桥：监听 127.0.0.1 和 ::1 的 8791
```

自检：

```powershell
curl http://127.0.0.1:8791/api/v1/health
curl -X POST http://127.0.0.1:8791/api/v1/translate -H "Content-Type: application/json" -d "{\"text\":\"mid no\",\"targetLanguage\":\"zh-Hans\"}"
```

### 3. 游戏内

* 别人发外语 → 译文自动显示在原消息下方
* 你说的话：设置面板（聊天框输入 `/tr` 回车）里把**目标语言**设成简中、
  **发送前翻译**设成想要的方式（仅译文 / 双语）——服务商选项随便选，我们的桥不理会 provider
* 桥的状态：mod 面板会显示是否连上（它读 `/api/v1/health`）

## 协议参考（与 BabelTower 逐字节对齐，改动前先读这段）

游戏内 Panorama **不能直接发 HTTP**（Deadlock 移除了 `$.WebRequest`），所以走：
隐藏 HTML 面板加载 `GET /bridge?id=..&op=..&text=..&source=..&target=..`
→ 页面内 JS 同源 fetch → 结果写进 `document.title`（`LCT<id>` + JSON）→ Panorama 轮询读取。

| 端点 | 方法 | 说明 |
|---|---|---|
| `/bridge` | GET | 隐藏面板页面（内容由 `bridge_page()` 生成） |
| `/settings` | GET | **配 API Key 的网页**（只有这一个输入框）；游戏没开也能用 |
| `/api/v1/health` | GET | mod 用它判断"桥是否在运行"，并展示**当前生效来源**（`deepseek:deepseek-flash`）与 `keySet` |
| `/api/v1/gamenames` | GET | 英雄/物品名表（mod 启动时同步，用于名称保护） |
| `/api/v1/translate` | POST/GET | `{text, sourceLanguage, targetLanguage}` → `{ok, translation, detectedLanguage}` |
| `/api/v1/test` | POST | 面板的「测试」按钮 |
| `/api/v1/config` | GET/POST | 面板读写配置（本桥只读展示，不含密钥） |
| `/api/v1/log` | POST | 聊天日志（本桥接受但忽略） |
| `/api/v1/models` | GET | 模型列表，**按来源分流**：`?d={"provider":"l"}` 问 Ollama `/api/tags`；云端回固定清单（不联网、省一次串行往返） |
| `/api/v1/settings` | GET/POST | 不带 `view` = 完整视图（长键 + 掩码密钥）；`view=compact` = 游戏面板用的小包（**短键** `recv/send/disp/out/hover/trig/keep/gloss/prv`，< 380 字符） |

### 游戏通道的长度约束（改 compact 字段前必读）

compact 响应会被写进 HTML `document.title` 再读回来，**实测 479 字符会被截断**成半截
JSON（面板上一片 undefined）。所以：字段名一律用短键、`_fit_compact()` 兜底裁剪
（先扔统计字段、再压模型名显示长度），`scripts/bridge_selftest.py` 有两级门禁
（380 警戒 / 440 必须）。模型名是用户自己起的，长度由不得我们 —— 这就是短键存在的理由。


**必须同时绑 `127.0.0.1` 和 `::1`**：Windows 上 `localhost` 可能解析到 IPv6 回环，
只绑 IPv4 会让游戏判定"桥未运行"（这是 BabelTower 踩过的坑，我们照做）。

GET 兼容：游戏侧 `$.AsyncWebRequest` 只能发 GET，所以请求体也支持 `?d=<JSON>`。

## 许可与致谢

* 本项目**不包含** BabelTower 的代码；我们只实现了与它兼容的本地 HTTP 协议
  （协议是接口约定，不是代码复制）。仓库里的 `reference-BabelTower/`（若存在）只是本地参考，
  不参与构建。
* BabelTower 采用 **GPL-3.0**：如果你把它的 mod 与我们的桥一起分发给别人，
  它的部分需要按 GPL-3.0 提供源码 —— 自用不受影响。
* 术语表/名称表来自 Deadlock 游戏自带的本地化文件（版权归 Valve），仅本地用于术语对齐。

## 已验证 / 待验证

✅ 桥的协议层：健康检查、名称表、隐藏面板页面、POST/GET 两种调用方式（23 个测试）
✅ 真实翻译：英→中、中→英 都通过本地 Hy-MT2-7B 跑通（上面那张表就是实测输出）
✅ 游戏侧可行性：BabelTower 已证明 Panorama 能读聊天行、能显示译文、能发送前翻译
⏳ 待你验证：装 mod + 起桥，进游戏看译文是否正常显示（这一步必须在游戏里做）

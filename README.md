# deadlock-tongyi（通译 / Tongyi）

Deadlock（异锁）**文字聊天**双向翻译小工具。

> 名字：**通译**（英文 Tongyi）。游戏内的 mod 面板、状态行、聊天命令用的都是这个名字：
> 状态行显示「通译 就绪」，聊天框里输入 `/tongyi`（或 `/通译`；旧命令 `/dlchat` 仍然可用）
> 打开设置面板。仓库/可执行文件名是 `deadlock-tongyi`。

| 方向 | 做什么 | 怎么实现 |
|---|---|---|
| 看 | 队友/对手打的**英文**聊天 → **中文** | 聊天来源（控制台日志 或 屏幕 OCR）→ 术语约束翻译 → 游戏内悬浮窗 |
| 说 | 我打的**中文** → **英文**，送进聊天框 | **零注入**：你在游戏聊天框打中文 → 连按 3 次空格 → 工具 OCR 读出 + 翻译 → 英文进剪贴板 → 你自己 Ctrl+A / Ctrl+V / 回车 |

设计上刻意**不做**的事：不读游戏内存、不注入 DLL、不碰游戏文件、**默认不模拟按键**。

### 零注入的"说"链路（默认）

```
你在游戏聊天框里正常打中文（输入法照常用）
        ↓  连按 3 次空格（连击窗口 1.5s）
工具：只监听键盘 + 截一小块输入行  ← 不注入任何按键
        ↓  OCR 读出中文 → 术语约束翻译
英文：写进剪贴板 + 悬浮窗显示给你确认
        ↓  你自己按 Ctrl+A（全选）→ Ctrl+V（覆盖）→ 回车发送
```

为什么这样设计：模拟键盘输入是唯一有反作弊风险面的部分（Valve 的 Trusted Mode 会阻止
第三方程序与游戏交互）。把最后三下按键留给你自己，工具就只剩"截屏 + 键盘监听"，
和 Discord/OBS 一个量级。想全自动的话，把 `input.handoff` 改成 `inject` 即可（默认关）。

---

## 为什么中文输入放在自己的窗口里（备用路径）

Deadlock 里用输入法直接打中文历史上有把游戏搞崩的报告（崩溃栈指向 SDL 的 Windows IME 路径）。
如果你在游戏里打中文没问题（当前 build 带 `imemanager.dll`，支持中文输入法），就用上面
那条零注入链路；如果打中文有问题，改用 `Alt+T` 呼出**我们自己的输入框**（输入法完全正常），
打完回车，英文同样进剪贴板。

---

## 安装

```bash
cd C:\Users\Hlliang\Desktop\deadlock-tongyi
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[ocr]"
```

`[ocr]` 会额外装 RapidOCR（Apache-2.0，自带小模型，CPU 离线）。不装也能用控制台日志来源。

翻译后端二选一（改 `config.yaml`）：

* **云端 DeepSeek**（**默认**：官方端点 + `deepseek-flash`）
  * **首选：游戏内 mod 面板切**（不用改文件）——按 F8 → 「翻译来源」切到
    `DeepSeek 云端` → 「翻译模型」选 `deepseek-flash` → 「保存并生效」。
    API Key 在浏览器里配一次：`http://localhost:8791/settings`（**那一页只有这一个
    输入框**，填完永久生效）。
  * 或者写进 `config.yaml` 当启动默认：
  ```yaml
  translate:
    base_url: "https://api.deepseek.com/v1"
    api_key: ""                      # 留空 = 用游戏里填的；或直接写 sk-... 或 ${DEEPSEEK_API_KEY}
    model: "deepseek-flash"          # 官方现役 ID；deepseek-v4-pro 更贵
    thinking: "off"                  # 必须 off，见下
  ```
  * ⚠️ **思考模式必须关**：DeepSeek **默认开思考模式且 effort=high**，一句 "mid no"
    会先产出一大段思维链，直接撞 `timeout_s`；而且思考模式下 `temperature` 被忽略、
    `top_p` 被抬到 ≥0.95，本项目的"温度固定 0"全部失效。代码只对 DeepSeek 端点发
    `thinking:{"type":"disabled"}`（别的兼容端点收到未知字段可能直接 400，所以按端点分流）。
  * ⚠️ 模型 ID 会退役：`deepseek-chat`/`deepseek-reasoner` 已于 2026-07-24 退役，
    `deepseek-v4-flash` 于 2026-09-10 退役（旧 ID 仍被接受但会按新模型计费）。
    现役只有 `deepseek-flash`（V4.1-Flash，推荐）和 `deepseek-v4-pro`。
* ⚠️ **系统代理坑（已自动处理）**：你机器上开着 `127.0.0.1:10808` 的系统代理，而 httpx
  **不读 Windows 的"绕过代理"列表**，会把 `http://127.0.0.1:11434` 也塞进代理，拿到假的
  `HTTP 503`。代码里对本地地址强制 `trust_env=False` 直连，云端地址仍走代理。

验证翻译链路（12 条真实聊天句 + 延迟统计）：

```bash
python scripts/spike_translate.py
python scripts/spike_translate.py --model kaelri/hy-mt2:1.8b-q8_0   # 对比 1.8B 速度
```

启动：双击 `run.bat`，或 `python -m dlchat`。

---

## 桌面端（打包成 exe）

```powershell
build.bat          # 一键打包，产出 dist\deadlock-tongyi\
```

打包后：

```
dist\deadlock-tongyi\deadlock-tongyi.exe        ← 双击即用（无控制台）
dist\deadlock-tongyi\deadlock-tongyi-cli.exe    ← 命令行版，跑 --selftest 排查
```

* 方案：**PyInstaller `--onedir`**（不用 onefile：启动慢 + 杀软误报多）；要给别人安装再加一层 Inno Setup 即可
* 配置和日志都在 **`%APPDATA%\deadlock-tongyi\`**（程序目录只读也能用）
* 已有**单实例保护**（两份会抢热键/抓屏/注入）；想多开加 `--allow-multi`
* 体积约 250~400MB（PySide6 + onnxruntime 占大头，**不含 torch**）

详见 `docs/packaging.md`。

### 让桥跟着游戏一起启动（不用每次手动开）

游戏内的 mod 跑在 Panorama 沙箱里，**没法自己拉起外部程序**，所以用 Steam 的「启动选项」
把游戏启动命令包一层。配一次即可：

```powershell
make_launch_option.bat     # 生成启动选项并复制到剪贴板，粘到 Steam 里就行
```

之后点「开始游戏」会自动起桥、游戏退出后自动关（不常驻、不需要管理员权限）。
给玩家用的无窗口启动器打包：

```powershell
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build_pkgs packaging\bridge.spec
# 产出 dist\bridge\tongyi-launch.exe（约 58MB，不含 PySide6/OCR）
```

细节见 `docs/launcher.md`。

---

## 实测结论（2026-09-12，本机 build 实测 + 资料核对）

先说结论：**Deadlock 没有可用的聊天 API**，所以本工具只能"看屏幕 + 模拟键盘"。
这些结论都写进了 `docs/research/`，下面是最影响设计的几条：

| 结论 | 证据 |
|---|---|
| **没有任何官方/第三方聊天接口** | Steamworks 的 `ISteamGameCoordinator` 官方标注"基本废弃、无全局访问器"；deadlock-api.com 的 118 个端点里 0 个聊天、0 个实时 |
| 聊天在内存/网络层是 protobuf | `CCitadelClientMsg_ChatMsg`(1005) 上行 / `CCitadelUserMsg_ChatMsg`(314) 下行；读取它 = 拦截网络，超出范围，不做 |
| **发送没有游戏内通道** | `say`/`say_team` 在本地 cvarlist 里是 `gamedll client_can_execute`，但控制台只在 Hideout/Sandbox/自定义房可用，且社区报告 2025-08 起 `say` 用于绑定失效 → 只能靠合成键盘输入 |
| 发送用注入是有先例的 | 现成项目 [deadlock-linux-dictation](https://github.com/KevinPequad/deadlock-linux-dictation) 就是把听写结果注入聊天框 |
| **聊天显示位置：顶部聊天条 + 世界空间气泡** | convar `chat_top_bar_max_messages=6`（"最多 6 个聊天面板"）、`citadel_chat_fade_time=10`(+7 延长)；实测截图 OCR 到英雄头顶的 `GG`（置信度 0.96） |
| **OCR 完全可用** | 同一张实测截图：识别 28 行，玩家名/聊天文字置信度 0.92~1.00（PP-OCRv6 small，CPU 离线） |
| OCR 速度是唯一瓶颈 | 全屏 1920×1080 做文本检测：CPU ~7s、CUDA ~5s（且是游戏同时运行时的数字）→ 所以默认走"**切条只识别**"快路径 |
| 游戏窗口类名/标题 | SDL3（`SDL_app`）+ 标题含 Deadlock/Citadel，注入前会校验窗口，找不到就拒绝注入 |

自检命令（不用开游戏也能跑）：

```bash
python -m dlchat --selftest      # 依赖/剪贴板/热键/窗口/抓帧/OCR/日志/术语表/翻译后端
python scripts/bench_ocr.py      # OCR 在你这台机器上的真实速度（切条 vs 整块）
```

---

## 先做这几步实测（决定用哪条路）

功能能不能达到"全自动"，取决于游戏侧的四个未知数。脚本都写好了：

### 0. 控制台能不能发聊天？（2 分钟，最省事的发送方案）

进 Hideout 或自定义房，按 `F7` 开控制台，输入：

```
say hello
```

* 你的聊天框出现了 `hello` → 控制台发送可行（但控制台在正式对局里不可用，实战价值有限）
* 没反应 → 和社区报告一致，发送只能靠注入

顺便可以试 `chat_fake_player_say_all 0 hello`（开发命令，本地伪造一条聊天显示）——
如果它生效，就能**不用队友配合**地测 OCR 链路。

### 1. 聊天到底写不写日志？（最准的读取方案）

Deadlock 的 `client.dll` 里有 `say` / `say_team` / `messagemode`，`server.dll` 打印聊天用
`[All Chat][名字 (3)]: 内容`，引擎支持 `-con_logfile` 启动参数。如果聊天会进日志，
功能1 就是 100% 准确、零 CPU 占用。

```bash
# 1) Steam -> Deadlock -> 属性 -> 启动选项，试： -con_logfile console.log
#    （不行再试 -consolelog / -console -con_logfile console.log；
#      进游戏按 F7 开控制台敲 con_logfile console.log 也可以）
# 2) 进 Hideout，让人发一条英文聊天
python scripts/spike_console_log.py --watch 90
```

有输出 → 把 `config.yaml` 的 `source.kind` 改成 `console`。
没输出 → 保持 `ocr`，走下面第 2 步。

### 2. OCR 认不认得出聊天文字？

```bash
python scripts/spike_ocr.py                # 用配置里的区域
python scripts/spike_ocr.py --full         # 抓整屏（想让我帮你看就发这张图）
python scripts/spike_ocr.py --watch 10     # 看聊天滚动时的连续识别效果
```

* 图片存在 `spike_out/`，`ocr_*.png` 是画了识别框的标注图。
* 区域不对就在界面上点「框选聊天区域」，或直接改 `config.yaml` 的 `ocr.region`（归一化 0~1）。
* 聊天条位置还没最终确认（`chat_top_bar_*` 说明在顶部条，但也可能是世界气泡），
  **发我一张"有人正在打字"的截图**最快解决。

### 3. 零注入链路（默认路径，先跑这个）

```bash
python scripts/spike_input_line.py --preview   # 抓聊天输入行 + OCR，校准区域
python scripts/spike_input_line.py --once      # 读一次并翻译 + 进剪贴板
python scripts/spike_input_line.py --taps      # 真实监听：连按 3 次空格触发
```

聊天框打开、里面有字，`--preview` 显示 `清洗后: '...'` 就说明读通了。

### 4. 能不能往聊天框里注入文字？（只在你想开自动注入时测）

```bash
python scripts/spike_input.py                 # 只探测，不碰游戏
python scripts/spike_input.py --go --inject   # 打开聊天框并注入 hello test
python scripts/spike_input.py --go --paste    # 测试 Ctrl+V
```

脚本最后会告诉你怎么回报结果（A 正常注入 / B 被屏蔽 / C 开不了聊天框 / D 崩溃）。

---

## OCR 性能（本机实测，详见 `docs/ocr-benchmark.md`）

| 场景 | 耗时 | 结论 |
|---|---|---|
| 校准好的小区域 420×60（det+rec） | **≈100 ms** | ✅ 默认方案，3~5 fps 没问题 |
| 单行紧裁剪（rec-only） | 54~131 ms/行 | ✅ 用于"读输入行"，裁剪必须紧 |
| 全屏 1920×1080（det+rec） | 1~4 秒 | ⚠️ 只能偶尔跑（世界气泡猎取） |
| 两个 OCR 引擎实例并存 | 100ms → **8.6 秒** | ❌ 已修：全局单实例 + 锁 |

---

## 使用

**两种用法**：桌面端（`deadlock-tongyi.exe`，下面是它的热键），或者游戏内 mod
（`/tongyi` 打开设置面板，连按两下空格触发转换）。

| 操作 | 作用 |
|---|---|
| 聊天框里打完中文后**连按 3 次空格** | 转换：英文进剪贴板 + 悬浮窗显示（零注入主路径） |
| 然后 `Ctrl+A` → `Ctrl+V` → `回车` | 覆盖并发送（这三下是你自己的真实按键） |
| `Alt+T` | 呼出中文输入小窗（游戏里打中文有问题时用这条） |
| `Alt+Y` | 把剪贴板内容当作要说的话，翻译后送出 |
| `Alt+G` | 暂停/恢复接收翻译（打团时清静） |
| `Alt+R` | 重译最近一条（OCR 认错时补救） |
| 界面「校准输入行」 | 聊天框开着、里面有字时点一下，看 OCR 读得对不对 |

交付方式（`config.yaml` 的 `input.handoff`，界面也能切）：

* **`clipboard`（默认，推荐）** 英文只进剪贴板 + 悬浮窗，最后一粘贴由你完成 → 零注入
* `inject` 允许工具模拟按键自动注入，等级 `L1` 注入并发送 / `L2` 注入不发送 / `L3` 只复制

连击触发（`input.trigger: space_taps`，可按需改）：

```yaml
input:
  taps: 3                  # 连按几次
  tap_window_s: 1.5        # 几次之间允许的最大间隔
  require_game_focus: true # 只在游戏前台响应（聊天框没开时空格=跳跃，不会误触发）
  input_region: [0.28, 0.30, 0.74, 0.37]   # 聊天输入行的位置，用「校准输入行」确认
```

---

## 术语表

游戏自己的多语言文件就是最好的术语来源，脚本自动抽取：

```bash
python scripts/build_glossary.py
```

产出（已生成好，随游戏补丁重跑即可）：

| 文件 | 内容 | 来源 |
|---|---|---|
| `data/glossary.json` | 约 **3900** 条 EN→中文（英雄/装备/技能/状态/UI），**带别名** | 游戏本地化文件自动生成 |
| `data/phrases.json` | 约 **118** 条整句直译（聊天轮盘等），命中即返回、不调模型 | 同上 |
| `data/slang.json` | 社区俚语（gank/push/miss/b…） | 手工维护 |
| `data/keep_as_is.json` | 保留英文不翻译（gg/ez/ks/xd…） | 手工维护 |

要点：

* 只把**本句命中的**术语注入 prompt（最多 12 条），不整包塞，避免拖慢首字延迟。
* system 提示逐字节不变（术语放在用户消息里），这样后端的 **KV 前缀缓存**才生效。
* 温度固定 0：短句最容易出现"模型自己加解释"。
* 官方中文名会随补丁改（例如 Haze 暗影→岚梦），所以 `glossary.json` 里存了别名，
  社区旧叫法也能认。

---

## 目录结构

```
dlchat/
  config.py            配置模型（pydantic）+ yaml 读写
  chat/                聊天行模型、解析、去重追踪、术语表
  capture/             区域抓帧（dxcam/mss）、OCR（RapidOCR/Windows）
  sources/             ChatSource 抽象：console_log / screen_ocr
  translate/           提示词、OpenAI 兼容客户端、缓存
  input/               注入（L1/L2/L3）、能力自检
  app/                 编排服务（线程 + Qt 信号）、全局热键
  ui/                  悬浮窗、主面板、中文输入小窗、区域框选
scripts/
  build_glossary.py    从游戏本地化生成术语表
  spike_console_log.py 实测①聊天是否写日志
  spike_ocr.py         实测②OCR 识别效果
  spike_input.py       实测③能否注入
tests/                 解析/去重/术语表/提示词 单测（36 个）
```

跑测试：

```bash
python -m unittest discover -s tests -t .
python -m dlchat --selftest        # 环境自检（含翻译后端连通性）
```

---

## 已知限制与风险

* **聊天显示形式未确认**：Deadlock 的聊天可能是"说话人头顶的世界气泡"而不是固定角落文字。
  若是气泡，就只能 OCR「按 Enter 打开的聊天面板」（`spike_ocr.py --full` 能看出来）。
  这也是把截图发我最快解决的原因。
* **反作弊**：只读截屏没有任何被封记录（注意：这是"没有证据"，不等于"证明安全"）。
  真正有风险面的是**自动输入**——Valve 的 Trusted Mode 会阻止第三方程序与游戏交互。
  因此默认只读、默认 L2 不自动发送、注入只针对聊天文本并限速；
  **绝不做游戏内操作自动化**（连点/压枪那类是 VACNet 明确针对的）。
* **聊天刷屏会被举报**：注入有 `max_chars` 上限，别拿它做刷屏。
* **模型许可**：Hy-MT2 的许可需要自己确认（有资料说 Apache-2.0，与 Hunyuan 社区许可
  "排除欧盟/英国/韩国"的说法冲突）；自己用无所谓，要分发/商用请先核对仓库 LICENSE。
* **中文注入**：CS2 有中文字体缺字问题、Deadlock 有西里尔字母间距 bug；
  本工具只注入英文，不注入中文。


# 1. 编译 + 打包游戏 mod（产出 dist_mod\...\pak01_dir.vpk）
python scripts\stage_compile.py --pack

# 2. 打包翻译桥（产出 dist\bridge\tongyi-launch.exe，约 58MB）
python -m PyInstaller --clean --noconfirm --distpath dist --workpath build_pkgs packaging\bridge.spec

# 3. 组装玩家 zip（跑完弹一行 "Done: dist\deadlock-tongyi-players.zip"）
packaging\package_player_zip.bat
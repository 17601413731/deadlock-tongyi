# 使用手册（一步步照做）

> 结论先说：**代码写完了、90 个测试全绿，但"能用"还差三步**——装翻译后端、校准两个区域、真机跑一遍。
> 下面按顺序做，第 1、3 步是必须的，第 2 步做完才准。

---

## 第 1 步：把翻译后端跑起来（必须）

**默认已经是 DeepSeek 云端**（`config.yaml` 里配好了官方端点 + `deepseek-flash`），
所以只需要配一次 API Key：

**① 浏览器里配（推荐，永久生效）**：桥起来之后打开
<http://localhost:8791/settings>，把那一个输入框填上 `sk-...` 保存即可
（存在 `settings.json` 里，桥和游戏重启后都还在）。

**② 或者写进 `config.yaml`**：

```yaml
translate:
  base_url: "https://api.deepseek.com/v1"
  api_key: "sk-你的key"        # 也可以写 "${DEEPSEEK_API_KEY}" 从环境变量读
  model: "deepseek-flash"      # 官方现在的模型 ID；deepseek-v4-pro 更贵更慢
  thinking: "off"              # 必须 off：DeepSeek 默认开思考模式，会让短句等到超时
```

> 游戏内面板按 F8 也能切来源/模型（点了立刻生效）。`api_key` 留空 = "用游戏里
> 填过的那份"；**别把占位符和环境变量同时用**，环境变量没设时占位符会盖掉已存的密钥。

**想改用本机 Ollama（不出网）**：本机现在**只有模型没有 Ollama 程序**
（`D:\software\ollama` 下只剩 `models`，21.7GB）。模型不用重新下，装回程序即可自动复用
（环境变量 `OLLAMA_MODELS` 已经指向那里）。

```powershell
# 去 ollama.com/download 装 Windows 版，然后：
ollama serve
ollama list        # 应该能看到:
                   #   hf.co/tencent/Hy-MT2-7B-GGUF:Q4_K_M   ← 本地来源用这个
                   #   kaelri/hy-mt2:1.8b-q8_0             ← 想更快时用
```

然后在游戏内 F8 面板把「翻译来源」切到 `本地 Ollama`（或改 `config.yaml`）。

## 第 2 步：让桥跟着游戏一起启动（推荐，一次配置）

不用再每次手动开 `start_bridge.bat`：

1. 双击项目根目录的 **`make_launch_option.bat`**（会把启动选项复制到剪贴板）
2. Steam → 库 → 右键 **Deadlock** → 属性 → 通用 → **启动选项** → `Ctrl+V`
3. 以后点「开始游戏」就自动起桥，**游戏退出后桥自己关**

细节、还原方法、排查表见 [launcher.md](launcher.md)。

验证后端：

```powershell
cd C:\Users\Hlliang\Desktop\deadlock-tongyi
python scripts\spike_translate.py
```

12 条真实聊天句会逐条翻译并打印延迟。**这一步能出中文，才继续往下。**

---

## 第 2 步：装依赖（一般已就绪）

```powershell
cd C:\Users\Hlliang\Desktop\deadlock-tongyi
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[ocr]"
```

---

## 第 3 步：校准两个区域（必须，一次就够）

区域是唯一"必须看着你屏幕才能定"的东西。两个区域都存进 `config.yaml`，之后不用再管。

### 3a. 输入行区域（决定"说"能不能用）

1. 启动工具：双击 `run.bat`，或 `python -m dlchat`
2. 进游戏，**按回车打开聊天框**，随便打几个中文字（别发出去）
3. 切回工具窗口 → 点 **「框选输入行」** → 拖框把 `To (ALL): 你打的字` **这一整条**圈起来
4. 工具会自动读一次并把结果显示在日志区：
   * `清洗后: '你打的字'` → ✅ 成功
   * `清洗后: ''` → 再框一次，稍微放大一点范围

> 命令行等价做法：
> ```powershell
> python scripts\spike_input_line.py --preview     # 看它读到了什么
> ```
> 裁剪图存在 `spike_out/input_line.png`，可以直接看框得准不准。

### 3b. 聊天区域（决定"看"能不能用）

1. 进游戏，等**有人打字**（或者你先自己发一条，别人回你）
2. 切回工具 → 点 **「框选聊天区域」** → 把**别人聊天文字出现的那一块**圈起来
   （点击穿透悬浮窗的位置也建议一起调：`config.yaml` 的 `display.anchor`）
3. 工具会在主面板打印读到的原始行（`📥 [OCR] ...`）和译文

> 判断标准：主面板出现 `📥 [OCR] xxx` 说明读到了；只有译文没有原始行说明被 HUD 过滤挡了。
> 命令行排查：
> ```powershell
> python scripts\spike_ocr.py --watch 20      # 连续 20 秒看 OCR 读到什么
> python scripts\spike_ocr.py --full          # 抓整屏（发我这张图我帮你定位）
> ```

### 3c.（可选）确认聊天到底在屏幕哪儿

游戏 convar 里有 `chat_top_bar_max_messages=6`（最多 6 个聊天面板）和
`citadel_chat_fade_time=10`（10 秒淡出），所以大概率在**顶部条**。
但最靠谱的是你截一张"有人正在打字"的图发我。

---

## 日常怎么用

### 看（别人英文 → 我中文）

开着工具就行，队友/对手发英文 → 悬浮窗和主面板出中文。不想看时：

* `Alt+G` 暂停/恢复
* 主面板「暂停」按钮
* 关掉接收：`config.yaml` 里 `app.enable_receive: false`

### 说（我中文 → 英文，零注入）

```
1. 游戏里按回车打开聊天框
2. 正常打中文（输入法随便用）
3. 连按 3 次空格     ← 触发
4. 看悬浮窗确认英文对不对
5. Ctrl+A（全选）→ Ctrl+V（覆盖）→ 回车发送
```

第 5 步的三下是**你自己的真实按键**，工具一次键盘注入都没有 —— 这是刻意的设计（见 README 的安全说明）。

三种交付方式（`config.yaml` 的 `input.handoff`，界面也能切）：

| 值 | 行为 | 风险面 |
|---|---|---|
| `clipboard`（默认） | 英文进剪贴板 + 悬浮窗，你自己粘贴 | 只截屏 + 键盘监听 |
| `inject` + `level: L2` | 工具自动注入英文到聊天框，不发送 | 有模拟按键 |
| `inject` + `level: L1` | 注入并自动回车发送 | 同上，且"以你名义说话" |

### 热键与托盘

| 操作 | 作用 |
|---|---|
| 连按 3 次空格 | 转换当前聊天输入行（主路径） |
| `Alt+T` | 呼出中文输入小窗（游戏里打中文有问题时用） |
| `Alt+Y` | 把剪贴板内容翻译后送出 |
| `Alt+G` | 暂停/恢复接收 |
| `Alt+R` | 重译最近一条（OCR 认错时补救） |
| 托盘右键 | 显示主面板 / 中文输入框 / 转换聊天输入行 / 暂停恢复 / 退出 |

---

## 出问题时按这个顺序排查

```powershell
python -m dlchat --selftest              # 一键看：依赖/剪贴板/键盘/窗口/抓帧/OCR/术语表/代理/后端
python scripts\spike_translate.py        # 翻译后端通不通
python scripts\spike_input_line.py --preview   # 输入行读不读得到
python scripts\spike_ocr.py --watch 20   # 聊天区读不读得到
python scripts\bench_ocr.py              # OCR 速度（游戏开着时也测一次）
python scripts\spike_console_log.py --watch 90 # 试试控制台日志路线（比 OCR 更准）
```

常见症状对照：

| 症状 | 原因 | 处理 |
|---|---|---|
| 自检里"翻译后端 ❌" | Ollama 没起 / key 不对 | 第 1 步 |
| 连按空格没反应 | 输入行区域没校准 / 游戏不在前台 | 第 3a 步；`require_game_focus` 可关 |
| 读了但读到的是空 | 框太大或位置偏 | 重新「框选输入行」，范围贴近那一行文字 |
| 主面板没有任何 `📥` | 聊天区域不对 | 第 3b 步 |
| 出现一堆数字垃圾 | 区域框太大，圈进了 HUD | 缩小区域；`ocr.filter_hud` 保持 true |
| 悬停窗位置挡视线 | 锚点默认在左下 | `display.anchor: bottom` 或 `custom` + `custom_pos` |

---

## 当前完成度

| 功能 | 状态 |
|---|---|
| 英文聊天 → 中文（OCR/控制台日志双来源、去重、HUD 过滤、术语约束翻译、悬浮窗） | ✅ 代码完成 + 端到端测试通过 |
| 中文 → 英文（三空格触发、读输入行、翻译、剪贴板/可选注入） | ✅ 代码完成 + 端到端测试通过 |
| 术语表（游戏本地化自动生成 3926 条 + 118 整句 + 俚语/保留词） | ✅ 完成并可随补丁重生成 |
| 能力自检（依赖/窗口/抓帧/OCR/后端/代理） | ✅ 完成 |
| 单元测试 | ✅ 90 个全绿 |
| **真实模型翻译质量** | ⏳ 等 Ollama 装回后跑 `spike_translate.py` |
| **两个区域的真机校准** | ⏳ 等你在游戏里框一次 |
| GUI 设置页（现在改配置要编辑 `config.yaml`） | ⏳ 待做 |
| 打包分发（PyInstaller） | ⏳ 待做（现在用 venv + run.bat） |

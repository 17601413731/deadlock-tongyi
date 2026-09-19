# 通译（Tongyi）mod：编译与安装

我们自己的 Deadlock 聊天翻译 mod（不依赖 BabelTower）。这份文档记录的是**实测踩出来的**
工具链事实——这些结论花了不少时间才确认，改动构建链前先读一遍，能省掉重复试错。

## 一、结论先行

| 事项 | 结论 |
|------|------|
| 编译器 | 必须用 **CSDK 12** 的 `game\bin_cs2\win64\resourcecompiler.exe` |
| 工程目录形状 | 输入路径必须是 `<CSDK>\content\citadel_addons\<addon>\panorama\...` |
| 输出 | 必须显式 `-o`，产物扩展名规范化为 `.vxml_c / .vjs_c / .vcss_c` |
| 安装 | 编译产物打成 VPK，替换 `Deadlock\game\citadel\addons\pak01_dir.vpk` |
| 游戏内通信 | 隐藏 `<HTML>` 面板 + `document.title` 轮询（`localhost`，串行单槽） |

## 二、为什么不能直接用 CS2 / Deadlock 自带的 resourcecompiler

三个坑，逐个排掉的：

1. **CS2 零售版的 `resourcecompiler.exe` 只认自己安装目录内的东西。**
   工程放在 `C:\...` 时它报 `stage\game\core\pak01.vpk Failed to load file (missing)`——
   文件明明存在。把同样的工程挪进 CS2 安装目录（`<CS2>\content\citadel_addons\...` +
   `<CS2>\game\citadel\...`）后，pak 立刻挂载成功。也就是说它的 FileSystem 有个
   **安装根目录 sandbox**。
2. **过了 sandbox 之后缺 Workshop Tools 的模块。** CS2 零售版 `bin\win64` 里没有
   `modtools.dll`，报 `CAppSystemDict:Unable to load module modtools (Dependency of
   application), error 126`。社区所谓的 "Reduced CSDK 12" 就是把 CS2 Workshop Tools
   与 Deadlock 的修正合并出来的工具集，正是缺这一块。
3. **Deadlock 自己带的 `resourcecompiler.dll`（54 MB）配 CS2 的壳能跑，但缺
   `modeldoc_utils.dll`。** 从 CS2 目录借这个 DLL 会报 `error 127`（导出符号对不上，
   两边 engine DLL 版本不一致），此路不通。

所以：`python scripts/fetch_csdk.py --download`（约 2.4 GiB，解到 `D:\csdk12`）。
注意 CSDK 官方文档提醒**不要放在 OneDrive 同步目录**（桌面/文档）里，会出权限问题。

### CSDK 里四套二进制，只有 `bin_cs2` 能用

`bin` / `bin_tools` / `bin_server` 的 `particles.dll` 与 `resourcecompiler.dll` 的
schema 对不上，编译直接中止：

```
ParticleFloatType_t
    Mismatch - Member Count
    Module 1 - resourcecompiler.dll:particleslib
    Module 2 - particles.dll:particleslib
ERROR: Schema mismatches reported! Aborting to prevent data corruption.
```

`bin_cs2`（文档里说"只用于 GUIMapCompiler"）反而是自洽的那一套：

```
OK: 1 compiled, 0 failed, 0 skipped, 0m:01s
```

### resourcecompiler 的两个"路径即配置"行为

- **mod 名与 game 根目录来自输入路径**：`<root>\content\citadel_addons\<addon>\panorama\x.js`
  → mod=`<addon>`，game root=`<root>\game`。路径不对就报
  `Unable to determine mod from file "..."`。
- **`-game <目录>`** 指定 gameinfo 所在目录（帮助文本写的是 "path to a gameinfo.gi file"，
  实际给目录，给文件会报 `Can't find 'gameinfo.gi\gameinfo.gi'`）。

## 三、构建流程（`scripts/stage_compile.py`）

```
mod/panorama/{layout,scripts,styles}         我们的源码
        │  同步到 <CSDK>\content\citadel_addons\dlchat\panorama
        ▼
bin_cs2\win64\resourcecompiler.exe -i <源文件> -o <CSDK>\game\citadel_addons\dlchat\panorama\*.{vxml_c,vjs_c,vcss_c}
        │
        ▼
dist_mod\pak01_dir.vpk                       我们自己写的 VPK 打包器（与引擎产物逐字节同构）
        │
        ▼
Deadlock\game\citadel\addons\pak01_dir.vpk   安装（旧文件备份成 .bak）
```

```bat
install_mod.bat                     :: 检查游戏没在跑 -> 编译 -> 打包 -> 安装
python scripts\stage_compile.py --pack            :: 只编译+打包
python scripts\stage_compile.py --install         :: 编译+打包+安装
```

> 装的时候 Deadlock 必须完全退出：引擎会锁住 `addons\pak01_dir.vpk`，
> 占用时报 `PermissionError: [WinError 32] 另一个程序正在使用此文件`。
>
> Deadlock Mod Manager 也把它的 mod 装在这个位置（`.dmm.json` 记录启用列表）。
> 我们的 VPK 会顶掉当前那个 `pak01_dir.vpk`，所以要么在 DMM 里停用 BabelTower，
> 要么就别在 DMM 里再点应用——否则它会把文件合并回去。

## 三·五、最容易踩的静默失败：VPK 内路径必须带 `panorama/` 前缀

VPK 的根是 **addon 目录**（`game/citadel_addons/<addon>/`），不是里面的 `panorama/`：

```
正确:  panorama/layout/chat.vxml_c        <- 游戏按这个路径去覆盖原版
错误:  layout/chat.vxml_c                 <- 游戏根本不会去这儿找
```

搞错前缀的后果是**完全静默**：游戏正常启动、聊天照常工作、不报任何错、
桥的日志一条都没有 —— 看起来就像"mod 没做对"，其实只是没被加载。
第一版就是这么翻车的（包内 4 个文件全少了一层 `panorama/`）。

`stage_compile.pack()` 现在用 `REQUIRED_PATHS` 兜底：缺任何一个关键资源就直接中止，
不让这种包出门。对照基准是 BabelTower 的包（它是能用的），路径形状完全一致。

另外，加了个"布局是否真的生效"的探针：`#DLChatStatus` 的初值写死成 `dlchat`。
布局一旦加载，输入框旁就会出现这个字样（哪怕脚本挂了）；
布局没生效则什么都不会出现。省得再靠猜。

## 四、游戏内运行时（Panorama）的三个硬约束1. **`$.AsyncWebRequest` 已被移除**——函数还在，但一调用就同步抛
   `AsyncWebRequest has been removed`。只用 `typeof` 检查会误判成"可用"。
2. **运行时 `$.CreatePanel("HTML", ...)` 拿不到可用的 HTML 面板**，必须在布局 XML 里
   用 `<HTML id="..." />` 声明，再用 `FindChildTraverse` 找。
3. **HTML 面板的 URL 必须用 `localhost`，不能用 `127.0.0.1`**（对回环 IP 有拦截）。
   桥因此必须同时绑 `127.0.0.1` 和 `::1`（`BridgeServer` 已经这么做了）。

通信协议：`SetURL` 打开 `http://localhost:8791/bridge?id=<id>&op=<op>&d=<JSON>`，
页面 fetch 桥 API，把结果写进 `document.title`，Panorama 轮询 `panel.title`。
因为是单槽通道，**同一时刻只能有一个在途请求**——我们的传输层是串行队列，
用递增的唯一 id 前缀匹配响应，迟到的旧响应直接丢弃。

### 编码坑（实测）

`document.title` 对非 ASCII 的处理没有保证，中文可能在路上变成 `?`。桥页面里所有响应
都先做 `\uXXXX` 转义（`asciiJson`），标题通道全程纯 ASCII。

另一个坑出在**测试脚本**上：PowerShell 的 `Invoke-RestMethod -Body '<含中文的JSON>'`
会把中文编坏，桥收到乱码后模型会回一句 `wtf`——一度以为是翻译链路坏了。
测桥请用 `python scripts/bridge_smoke.py`（显式 UTF-8）。

## 五、联调工具

| 工具 | 用途 |
|------|------|
| `python scripts/bridge_smoke.py` | 双向翻译冒烟（UTF-8 正确） |
| `python scripts/mod_log.py` | 读游戏侧推到桥上的诊断日志（boot/翻译/失败） |
| `python scripts/probe_backend.py` | 四种请求形态问模型，排查后端 |
| `python scripts/probe_pipeline.py` | 逐层排查 BridgeApp → ChatTranslator → 模型 |
| `python scripts/extract_vpk.py` | 从游戏 pak 里按路径提取文件 |
| `python scripts/red2.py` | 解析/导出 `*_c` 的块结构（RED2/DATA/LaCo…） |
| `tools\vrf\Source2Viewer-CLI.exe -i x.vxml_c -d` | 把编译后的布局反解回 XML |

`mod/panorama/layout/*.xml` 的基线就是从游戏自身的 `chat.vxml_c` /
`citadel_hud_top_bar_chat.vxml_c` 反解出来的，改动处都标了 `[dlchat]`。
Valve 更新 UI 后重新反解一次照着抄即可。

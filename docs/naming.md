# 命名与改名记录（通译 / Tongyi）

一个项目上同时骑着三个名字，改名前先看清是哪一层，别混着改。

| 层 | 现在的值 | 谁看得到 | 改它的代价 |
|---|---|---|---|
| **A 产品名** | `deadlock-tongyi`（exe、仓库、`%APPDATA%`） | 玩家 | 低（机械替换） |
| **B 游戏内显示名** | **通译**（面板标题、状态行、`/tongyi` 命令） | 玩家 | 低（显示串） |
| **C 内部名** | `dlchat`（Python 包、addon 目录、`dlchat.vjs_c`、DOM id） | 没人 | **高，不要动** |

一句话记法：**A 是装的东西，B 是游戏里看到的字，C 是代码里的形状。** C 层改了没有任何
收益，却能把"游戏静默加载失败、连报错都没有"这种最难查的问题引进来。

## A 层：`deadlock-fanyi` → `deadlock-tongyi`

| 位置 | 说明 |
|---|---|
| `dlchat/paths.py` `APP_NAME` | 决定 `%APPDATA%\deadlock-tongyi\`（配置/密钥/日志/截图） |
| `dlchat/single_instance.py` `MUTEX_NAME` | 单实例互斥体 |
| `dlchat/launcher.py` `LAUNCHER_MUTEX` | 启动器互斥体 —— **必须和上面那个同一批改**，只改一个的话新老版本互相看不见，能各起一份抢热键 |
| `pyproject.toml` `name` / `[project.scripts]` | 包名 `deadlock-tongyi`；控制台脚本名保留 `dlchat-launch`（不是玩家可见的名字，改了反而让文档里的 `dlchat-launch --stay` 失效） |
| `packaging/bridge.spec` | 产出 `build\.work\bridge\{tongyi-launch.exe, tongyi-launch-cli.exe}` |
| `make_launch_option.bat`、`packaging/player/START_HERE.bat`、`packaging/package_player_zip.bat`、`start_bridge.bat` | 产物路径、进程名（`taskkill /IM tongyi-launch.exe`）、提示文案 |
| `packaging/package_player_zip.bat` | 玩家包：`build\tongyi-players.zip`，内含 `tongyi_launch\` + `mod\tongyi-pak01_dir.vpk` |

### `%APPDATA%` 迁移（别删）

老用户的 `settings.json`（**里面是网页里填的 API Key**）、`config.yaml`、`logs\`、
`spike_out\` 都在旧目录 `%APPDATA%\deadlock-fanyi\` 里。`paths._migrate_legacy_user_dir()`
在首次运行、且新目录还不存在时整体搬过去：

* 目标已存在 → 什么都不做（不会覆盖用户正在用的东西）
* 搬迁失败 → 只记一条日志，按全新安装继续（不能让程序起不来）
* ⚠ 调用顺序不能改：**必须先迁移再 `mkdir`**，否则目标目录先被建出来，迁移条件永远不成立

## B 层：游戏内显示名 = 通译

| 位置 | 现在的内容 |
|---|---|
| `mod/panorama/layout/chat.xml` | 状态行初值 `通译`（兼作"布局有没有生效"探针）；面板标题 `通译 · 聊天翻译设置` |
| `mod/panorama/scripts/dlchat.js` | 状态灯文案 `通译 就绪 / 桥不通 / 脚本错误 / 通道 / 探针`；`MOD_TAG = "tongyi-mod/1.0.0"`；命令 `/tongyi`、`/通译`、`/设置`、`/cfg`，旧的 `/dlchat` 仍然可用 |
| `dlchat/bridge/settings_page.py` | 网页标题 `通译 · API Key` |
| 玩家文档 ×2 | `packaging/player/README-zh.txt`（总说明）、`packaging/player/MOD-README-zh.txt`（补丁说明）。**只有这两份**会进玩家包（`package_player_zip.bat` 从这里拷），改完记得重新打包 |

改 `/命令` 时注意 `checkSettingsCommand()` 里的比较方式：中文别名要原样比，
只有 ASCII 命令能 `toLowerCase()`。

## C 层：名字保持 `dlchat`（刻意不改）

`dlchat/` 包、`-m dlchat`、`DLCHAT_CONFIG` 环境变量、`DLChatSet_*` 等 DOM id、
日志名、`dlchat-bridge/1.0.0` 协议版本号。

**addon 资源名尤其别改**：`scripts/stage_compile.py` 的 `ADDON = "dlchat"` 绑定磁盘目录
`<CSDK>\content\citadel_addons\dlchat\panorama\`（resourcecompiler 从输入路径推断 mod 名，
对不上直接 "Unable to determine mod from file"），而 `REQUIRED_PATHS` 又绑定
`panorama/scripts/dlchat.vjs_c`、`panorama/styles/dlchat.vcss_c`——布局里的 include 也是按这两个
名字写的。三处任一处不同步，表现都是**游戏里毫无反应、没有报错**。

玩家在 DMM 里看到的 mod 名字是导入时自己起的（文档里建议填 `通译`），跟这些内部名无关。

## 改完之后的手工动作

1. **工作目录改名**（可选）：`deadlock-fanyi\` → `deadlock-tongyi\`。
   已知会连带失效的地方：文档里的 `cd` 路径、`.idea` 工程配置，以及
   **Steam 启动选项里那条绝对路径**（重跑 `make_launch_option.bat` 再粘一次即可）。
2. `python scripts/stage_compile.py --pack` 重新打包 mod，再到 DMM 里重新导入，游戏里才会
   显示新名字。**改名字不改变 VPK 的内部结构**，所以旧包照常能跑，只是还写着 dlchat。
3. 启动器重新打包：`python -m PyInstaller --clean --noconfirm --distpath build/.work --workpath build/.work/pyinstaller packaging\bridge.spec`
   然后 `packaging\package_player_zip.bat`。

## 顺带说明（与命名无关，别改错）

* `fanyi-v5`（出现在 `dlchat/translate/client.py`）是**另一个语音翻译项目**，不是本项目的旧名。
* `dlchat.js` 的 header 注释、`[dlchat]` 日志前缀属于 C 层，保持不动。

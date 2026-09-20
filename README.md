# deadlock-tongyi（通译 / Tongyi）

Deadlock（异锁）**文字聊天双向翻译**小工具。

| 方向 | 做什么 |
|---|---|
| **看** | 队友/对手打的英文聊天 → 就地显示中文 |
| **说** | 你打的中文 → 翻译成英文送出 |

翻译靠一个**游戏内 mod**（Panorama）+ 一个**本机翻译桥**（Python）：mod 直接读写游戏
自己的聊天界面，桥负责调用模型——不读游戏内存、不注入 DLL、不改游戏文件。

```
英文聊天  →  mod 从聊天界面读到  →  本机桥翻译  →  就地替换成中文
中文输入  →  连按两下空格  →  本机桥翻译  →  输入框就地变成中英对照
```

默认**不模拟按键**：mod 是在游戏自己的界面层里替换文字，不需要伪造键盘输入。

---

## 下载

到 [**Releases**](../../releases/latest) 下载 `tongyi-players.zip`（约 32 MB），**不需要装 Python**：

1. 解压到普通目录（别放 `Program Files`，会没有写权限）
2. 双击 `tongyi_launch\START_HERE.bat`。它会**自动**生成一行 Steam 启动选项并放进剪贴板，
   你只要去 Steam 里 `Ctrl+V` 粘贴：库 → 右键 Deadlock → 属性 → 启动选项（只需配这一次）
3. 用 Deadlock Mod Manager 导入 `mod\tongyi-pak01_dir.vpk`
4. 先开一次游戏，再在浏览器打开 `http://localhost:8791/settings`，把 DeepSeek
   API Key 粘进去保存

第 4 步要在**游戏运行期间**做 —— 桥跟着游戏一起启动、游戏退出就关，平时端口是没开的。

包里的 `README-zh.txt` 是完整中文说明（DMM 下载地址、游戏内设置面板、常见问题都在那）。

## 热键

| 操作 | 作用 |
|---|---|
| 聊天框里打完中文后**连按两下空格** | 就地翻译成中英对照，回车发送 |
| 游戏内 `/tongyi` | 打开 mod 设置面板 |

## 源码结构

```
dlchat/       翻译桥（HTTP 服务，mod 通过它调模型）
mod/          游戏内 mod 源码（Panorama layout / scripts / styles）
data/         术语表（~3500 条）与短语语料（117 条）+ 俚语/保留词/黑名单
scripts/      构建、诊断、联调、数据生成与质检工具
packaging/    打包脚本（桥的启动器 + 玩家包组装）
tests/        单元测试（164 个）
docs/         详细文档
```

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .
python -m unittest discover -s tests -t .    # 164 个测试
node scripts\js_check.js                     # mod 的离线测试台（改 JS 后必跑）
python scripts\check_data_quality.py         # 术语/俚语数据质检
```

> 只有三个运行依赖（openai / pydantic / PyYAML）。早些版本这里是桌面程序：
> Qt 界面 + 截屏 OCR + 模拟按键，那套代码已于 2026-09-20 移除 —— 现役方案
> 在游戏自己的界面层里读写信聊天，不需要 OCR、不注入按键。

打包玩家包（三步，顺序不能换；产物全部落在 `build/`）：

```powershell
python scripts\stage_compile.py --pack   # 1. 编译 mod → build\tongyi-pak01_dir.vpk
python -m PyInstaller --clean --noconfirm --distpath build/.work --workpath build/.work/pyinstaller packaging\bridge.spec
                                         # 2. 打包翻译桥 → build\.work\bridge\
packaging\package_player_zip.bat         # 3. 组包 → build\tongyi-players.zip（唯一交付物）
                                         #    顺便把桥挪到 build\tongyi-launch\（Steam 启动选项用）
```

> `build/` 里只有三样东西是给人看的：`tongyi-players.zip`（发玩家）、
> `tongyi-pak01_dir.vpk`（DMM 导入）、`tongyi-launch\`（Steam 启动选项 / 排查）；
> 其余中间产物都在 `build\.work\`。整个目录随时可以 `rm -rf build` 重建。

## 文档

| 文件 | 内容 |
|---|---|
| [docs/mod-usage.md](docs/mod-usage.md) | 游戏内 mod 使用说明（含排查表） |
| [docs/mod-build.md](docs/mod-build.md) | mod 编译与安装（需要 Valve CSDK 12）+ 联调工具 |
| [docs/bridge.md](docs/bridge.md) | mod 与翻译桥的通信协议 |
| [docs/data.md](docs/data.md) | 术语表/俚语/黑名单怎么维护、怎么质检、怎么跑分 |
| [docs/launcher.md](docs/launcher.md) | 让桥跟着游戏自动启动 |
| [docs/phrase-corpus.md](docs/phrase-corpus.md) | 语料来源与术语取舍（含"官方译名 vs 玩家叫法"） |
| [docs/naming.md](docs/naming.md) | 改名时哪些地方必须同步 |
| [docs/research/](docs/research/) | Deadlock 聊天接口的调研结论 |

## 注意

* 需要一个翻译后端：默认 DeepSeek 云端，要自备 API Key（Key 只存在你自己电脑上，
  也可以写进 `config.yaml`）；能在游戏内设置面板切成
  本机 Ollama（不出网）。
* 翻译桥要开着才能翻，它跟着游戏一起启动、游戏退出就关 —— 所以配 Key、
  看状态这类事都要在**游戏运行期间**做。
* 配置和日志在 `%APPDATA%\deadlock-tongyi\`，不在程序目录里。

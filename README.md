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

到 [**Releases**](../../releases/latest) 下载 `deadlock-tongyi-players.zip`（约 36 MB），**不需要装 Python**：

1. 解压到普通目录（别放 `Program Files`，会没有写权限）
2. 双击 `tongyi_launch\START_HERE.bat`
3. 用 Deadlock Mod Manager 导入 `mod\tongyi-pak01_dir.vpk`
4. 浏览器打开 `http://localhost:8791/settings` 填一次 DeepSeek API Key

## 热键

| 操作 | 作用 |
|---|---|
| 聊天框里打完中文后**连按两下空格** | 就地翻译成中英对照，回车发送 |
| 游戏内 `/tongyi` 或 `F8` | 打开 mod 设置面板 |

## 源码结构

```
dlchat/       翻译桥（HTTP 服务，mod 通过它调模型）
mod/          游戏内 mod 源码（Panorama layout / scripts / styles）
data/         术语表（3926 条）与短语语料（118 条）
scripts/      构建、诊断、联调工具
packaging/    打包脚本（mod 的 pak + 桥的启动器）
tests/        单元测试
docs/         详细文档
```

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -e .
python -m unittest discover -s tests -t .    # 205 个测试
```

打包：`python scripts\stage_compile.py --pack` 出 mod，`packaging\package_player_zip.bat` 组装玩家包。

## 文档

| 文件 | 内容 |
|---|---|
| [docs/mod-usage.md](docs/mod-usage.md) | 游戏内 mod 使用说明 |
| [docs/mod-build.md](docs/mod-build.md) | mod 编译与安装（需要 Valve CSDK 12） |
| [docs/bridge.md](docs/bridge.md) | mod 与翻译桥的通信协议 |
| [docs/launcher.md](docs/launcher.md) | 让桥跟着游戏自动启动 |
| [docs/research/](docs/research/) | Deadlock 聊天接口的调研结论 |

## 注意

* 需要一个翻译后端：默认 DeepSeek 云端，要自备 API Key；也能在游戏内 F8 面板切成
  本机 Ollama（不出网）。
* 翻译桥要开着才能翻（双击 `tongyi_launch\START_HERE.bat` 装好后，桥会跟着游戏一起启动）。
* 配置和日志在 `%APPDATA%\deadlock-tongyi\`，不在程序目录里。

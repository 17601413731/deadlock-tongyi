# 让翻译桥跟着游戏一起启动（不用再手动开）

## 它解决什么

以前每次玩之前都要手动双击 `start_bridge.bat`，忘了就没有中文。现在把游戏本身的启动
命令包一层：**点"开始游戏"就自动起桥，游戏退出后桥自己关掉**，全程不用管。

不需要管理员权限、不常驻后台、不写注册表 —— 只在游戏运行期间存在。

## 原理（一句话）

Steam 的「启动选项」原本就是给游戏加参数的。我们把它改成先启动**我们的启动器**
（`tongyi-launch.exe`），启动器再把 Steam 原本要启动的游戏原样拉起来：

```
点"开始游戏"
   └─> tongyi-launch.exe          ← 我们加的
         ├─ 在本进程内把翻译桥起起来（无窗口）
         └─> Deadlock 本体         ← Steam 的 %command% 原样透传
               └─ 你退出游戏后，启动器退出，桥跟着结束
```

桥跑在**启动器自己的进程里**（不是另开一个进程），所以：

* 只有一个后台进程，没有窗口
* 游戏一退，桥必然跟着退，不会留下"你没在玩但桥还开着"
* 路径带空格也不会出错（我们不拼字符串，直接把 Steam 给的参数列表原样传下去）

## 怎么配（一次就够）

1. 双击 **`make_launch_option.bat`**（项目根目录），它会把启动选项复制到剪贴板；
2. Steam → 库 → 右键 **Deadlock** → 属性 → 通用 → **启动选项** → `Ctrl+V`；
3. 关掉属性窗口，点「开始游戏」。

粘贴进去的内容长这样（路径按你机器上的位置）：

```
"C:\Users\你\Desktop\AiApp\deadlock-tongyi\build\tongyi-launch\tongyi-launch.exe" %command%
```

> ⚠️ 那对引号不能删：路径里有空格，少了引号 Steam 会把整串当成游戏的参数。
> `%command%` 也不能删，它就是"游戏本体 + 你原来填的其他参数"。

**想还原**：把启动选项清空即可（游戏照常能玩，只是又回到"手动开桥"）。

## 怎么确认它在工作

- 游戏里：聊天输入框旁边的**状态灯是绿的**（灰/红=桥没连上）；
- 电脑上：`%APPDATA%\deadlock-tongyi\logs\launcher.log` 会写"桥已就绪，开始启动游戏"，
  游戏退出时写"游戏已退出"。

## 排查

| 现象 | 原因 / 处理 |
|---|---|
| 点了开始游戏**没反应** | 启动选项里的引号/路径写错了。重跑 `make_launch_option.bat` 再粘一次；路径换了位置（移动过文件夹）也要重跑 |
| 游戏正常开，但状态灯红/灰 | 看 `logs\launcher.log`：里面会写"桥启动失败"的原因（端口被占、依赖缺失、密钥没配…） |
| 日志里写"已有启动器在运行" | 你点了两次「开始游戏」。第二次只开游戏、不重复起桥，正常现象 |
| 想临时只开游戏、不起桥 | 启动选项里加 `--no-bridge`（调试用） |
| 想只起桥不开游戏 | 命令行跑 `tongyi-launch.exe --stay` |
| 不想用启动器了 | 清空 Steam 启动选项，回到手动 `start_bridge.bat` |

### 附：为什么 `make_launch_option.bat` 里全是英文

cmd.exe 解析 `.bat` 是**按字节**来的。某些汉字的 UTF-8 字节里含有 cmd 当成运算符的字节
（`&` `|` `<` `>`），一行会被从中间切断，症状就是刷一屏
`'xxx' 不是内部或外部命令`。这个脚本第一版写满中文注释，正好踩中：
`echo ... -> Steam ...` 里的箭头、以及注释里几个汉字，把后面几行全拆散了。

所以这个 bat **保持纯 ASCII**：报错信息和参数都用英文，中文说明放在这份文档里。
同理，以后加 bat 脚本也照这个规矩（项目里别的 bat 只有英文提示，所以一直没出问题）。

## 开发时（没打包也能用）

`make_launch_option.bat` 在找不到 `build\tongyi-launch\tongyi-launch.exe` 时会自动退回到源码模式：

```
pythonw -m dlchat.launcher %command%
```

（`pythonw` = 不弹控制台窗口。用 `python` 会闪一个黑框，功能一样。）

## 打包（发给别人时）

```powershell
python -m PyInstaller --clean --noconfirm --distpath build/.work --workpath build/.work/pyinstaller packaging\bridge.spec
```

产出 `build\.work\bridge\`：`tongyi-launch.exe`（无窗口，给 Steam 用）
+ `tongyi-launch-cli.exe`（有窗口，排查用）。这个包**不含**桌面界面、OCR 那一套
—— 聊天翻译这条链路用不到它们。

## 打成能直接发给玩家的 zip

```powershell
packaging\package_player_zip.bat
```

它做四件事：把玩家文件（`START_HERE.bat` + `README-zh.txt`）拷进暂存区、
把 `config.yaml` 也提到 exe 旁边（PyInstaller 默认会把它塞进 `_internal\`，
玩家打开文件夹看不到它）、把 mod 包（`build\tongyi-pak01_dir.vpk`）放进 `mod\`、
然后压成 `build\tongyi-players.zip`（约 32MB）。最后它顺手把桥从 `build\.work\bridge\`
**移动**到 `build\tongyi-launch\`（Steam 启动选项指向的就是这里），并清掉暂存区。

玩家拿到后的三步：**解压 → 双击 `START_HERE.bat` → 按它的提示粘一次 Steam 启动选项**，
之后正常点「开始游戏」就行。

### 两个只在打包版里才会出现的坑（都踩过并修了）

1. **HTTPS 全部失败**（`ssl.py ... FileNotFoundError`）：打包后
   `ssl.create_default_context()` 拿不到系统证书库，httpx 一建客户端就抛异常 ——
   源码运行完全正常，只有打包版复现。修法见 `dlchat/launcher.py` 的 `use_bundled_ca()`：
   把 `SSL_CERT_FILE` 指到 certifi 自带的 `cacert.pem`。
2. **`START_HERE.bat` 里不能出现中文文件名**：脚本是纯 ASCII，写中文名会触发
   cmd 的字节解析问题（见下）。所以说明文件叫 `README-zh.txt`，内容仍是中文。

打包日志在 `%APPDATA%\deadlock-tongyi\logs\launcher.log`，
里面会有一行 `HTTPS 证书: ...`，**打包版第一次跑一定要看这一行**有没有出现。

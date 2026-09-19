# 桌面端打包方案（推荐 + 已实现）

## 结论：PyInstaller `--onedir`，外面再套一层 Inno Setup 安装包

```
打包：  pyinstaller --onedir  →  dist\deadlock-tongyi\  （一个文件夹 + 两个 exe）
分发：  压缩成 zip 直接发给别人  ←── 够用
       或 Inno Setup 打成 setup.exe（开始菜单/桌面快捷方式/卸载/开机自启）←── 像正规软件
```

产出两个 exe（共用同一份代码，只差有没有控制台窗口）：

| 文件 | 用途 |
|---|---|
| `deadlock-tongyi.exe` | 主程序，**双击即用，不弹黑框** |
| `deadlock-tongyi-cli.exe` | 命令行版，跑 `--selftest` 和排查问题（保留控制台输出） |

## 为什么是 onedir 而不是别的

| 方案 | 结论 | 原因 |
|---|---|---|
| **PyInstaller onedir** | ✅ **选它** | 启动快（无解压）、杀软误报率低、PySide6/onnxruntime 的钩子成熟、目录可直接被 Inno Setup 打包 |
| PyInstaller onefile | ❌ | 每次启动把 ~300MB 解压到临时目录（慢 5~10 秒）；自解压 + 全局键盘钩子最容易被杀软盯上 |
| Nuitka | ⚠️ 备选 | 启动更快、体积更小、误报更少，但 PySide6 + onnxruntime + rapidocr 的插件收集更折腾，构建要十几分钟。**如果 PyInstaller 出来被杀软误报，再换它** |
| cx_Freeze / Briefcase | ❌ | 没有明显优势，生态资料少 |
| Electron / Tauri 重写 | ❌ | 这工具要的是 Win32 五件套（全局键盘钩子、点击穿透悬浮窗、IME 输入窗、DXGI 抓帧、窗口前台判定），Python+Qt 一套就够；Tauri 得自己写 Rust 插件，Electron 得跨进程调原生模块，包体还更大 |

## 已经做好的准备

打包最容易踩的坑是"程序往自己目录写文件"——装到 `Program Files` 后没有写权限。已经改造完：

| 类型 | 位置 | 说明 |
|---|---|---|
| 只读资源（`data/*.json` 术语表、OCR 模型） | bundle 内 | 随 exe 一起打包 |
| 配置 `config.yaml` | **`%APPDATA%\deadlock-tongyi\`** | 找不到就复制内置默认；开发时/便携版优先用程序目录或当前目录的那份 |
| 校准截图、日志 | `%APPDATA%\deadlock-tongyi\spike_out\`、`\logs\` | 永远可写 |

另外补了两个桌面端必需品：

* **单实例保护**（`dlchat/single_instance.py`）：两份会抢热键、抢抓屏、抢注入，用命名互斥体挡掉；想多开加 `--allow-multi`
* **日志落盘**：`%APPDATA%\deadlock-tongyi\logs\dlchat.log`，出问题可以直接看

## 怎么打包

```powershell
cd C:\Users\Hlliang\Desktop\deadlock-tongyi
build.bat
```

脚本做了四件事：生成图标 → 清理旧产物 → 跑 PyInstaller → 打印结果路径。
第一次约 5~15 分钟（要收集 PySide6 + onnxruntime）。

验证：

```powershell
dist\deadlock-tongyi\deadlock-tongyi-cli.exe --selftest   # 应看到 路径: 打包 exe | ...
dist\deadlock-tongyi\deadlock-tongyi.exe                  # 双击，托盘出现图标
```

## 打包后的路径会变成

```
dist\deadlock-tongyi\
├─ deadlock-tongyi.exe          主程序
├─ deadlock-tongyi-cli.exe      命令行版
├─ config.yaml                 默认配置模板（首次运行复制到 %APPDATA%）
├─ data\glossary.json 等        术语表
├─ _internal\                  Python 运行时 + PySide6 + onnxruntime + OCR 模型
└─ ...
```

体积参考：约 250~400MB（PySide6 和 onnxruntime 占大头）。**没有 torch/funasr**（那些留在 fanyi-v5）。

## 后续可做（按性价比排序）

1. **Inno Setup 安装包**：开始菜单 + 桌面快捷方式 + 卸载 + 开机自启选项（脚本半天内能写完，需要装 Inno Setup）
2. **内置开机自启开关**：写 `HKCU\...\Run` 注册表，比让用户自己拖快捷方式友好
3. **代码签名证书**：没有证书时 Windows SmartScreen 会提示"未知发布者"，自用无所谓，要发给别人再考虑
4. **自动更新**：先不做，等真有别人用再说

## 已知注意点

* **杀软误报**：装了全局键盘钩子的程序被误报是常态。onedir + 不压缩（`upx=False`）已经是最不容易误报的组合；真被拦就把整个 `dist\deadlock-tongyi` 目录加白名单
* **不做管理员权限**：键盘钩子、抓屏、剪贴板都不需要提权，保持普通用户运行（UAC 弹窗反而吓人）
* **首次启动稍慢**：第一次要加载 OCR 模型（约 1~2 秒），之后就快了
* **config.yaml 位置**：给用户看的时候要说清楚在 `%APPDATA%\deadlock-tongyi\config.yaml`，不在程序目录里

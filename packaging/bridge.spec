# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出 dist/bridge/（给玩家用的"启动器 + 桥"，**不含**桌面界面）。

产出：
  tongyi-launch.exe   无窗口。给 Steam 启动选项用：先起翻译桥，再启动游戏，
                      游戏退出后自己结束（桥在同一个进程里，所以不会留残留进程）。

和 packaging/deadlock-tongyi.spec（桌面版）的区别：
  · 不打包 PySide6 / OCR（rapidocr、onnxruntime、dxcam）—— 聊天翻译这条链路用不到，
    体积能小一个数量级，也少一堆杀软敏感的动态库
  · 控制台版 tongyi-launch-cli.exe 保留，排查时能看到输出

用法：pyinstaller --clean --noconfirm packaging/bridge.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

SPEC_DIR = Path(SPECPATH).resolve()               # noqa: F821 - PyInstaller 注入
ROOT = SPEC_DIR.parent

datas = []
hiddenimports = []

# 只读资源：术语表（Glossary 在启动时就要读）+ 默认配置模板 + README
datas += [(str(ROOT / "data"), "data")]
datas += [(str(ROOT / "config.yaml"), ".")]
datas += [(str(ROOT / "README.md"), ".")]

hiddenimports += ["yaml", "pydantic", "openai", "httpx", "httpcore", "anyio"]
# 本地地址要直连（绕过系统代理），httpx 的 SSL/代理实现得被收集进来
datas += collect_data_files("certifi")

# 这些在桌面版里也是排除项；这里更要排干净，不然包体白涨
excludes = [
    "torch", "torchaudio", "torchvision", "funasr", "modelscope",
    "faster_whisper", "ctranslate2", "sounddevice", "edge_tts",
    "matplotlib", "scipy", "pandas", "notebook", "IPython", "tkinter",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "shiboken6",
    "rapidocr", "onnxruntime", "dxcam", "mss", "PIL", "numpy",
    "keyboard", "pyperclip", "win32gui", "win32api", "win32clipboard",
    "tests", "scripts",
]

a = Analysis(                                     # noqa: F821
    [str(SPEC_DIR / "entry_launch.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)                                 # noqa: F821

exe_gui = EXE(                                    # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="tongyi-launch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                    # UPX 压缩最容易招杀软误报
    console=False,                                # 无窗口：Steam 启动时不该弹黑框
    icon=str(SPEC_DIR / "icon.ico"),
)
exe_cli = EXE(                                    # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="tongyi-launch-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,                                 # 排查用，保留输出
    icon=str(SPEC_DIR / "icon.ico"),
)
coll = COLLECT(                                   # noqa: F821
    exe_gui, exe_cli,
    a.binaries, a.datas,
    strip=False,
    upx=False,
    name="bridge",
)

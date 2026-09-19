# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：产出 dist/deadlock-tongyi/ 文件夹（onedir）。

为什么用 onedir 而不是 onefile：
  · onefile 每次启动都要把 ~300MB 解压到临时目录，启动慢 5~10 秒
  · onefile 的自解压行为最容易被杀软误报（我们还要装全局键盘钩子，更敏感）
  · onedir 目录可以直接用 Inno Setup 打成安装包

产出两个 exe：
  deadlock-tongyi.exe      主程序（无控制台窗口）
  deadlock-tongyi-cli.exe  命令行版（跑 --selftest 和排查脚本用）

用法：pyinstaller --clean --noconfirm packaging/deadlock-tongyi.spec
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

# SPECPATH = 本 spec 所在目录（packaging/）；ROOT = 项目根目录
SPEC_DIR = Path(SPECPATH).resolve()               # noqa: F821 - PyInstaller 注入
ROOT = SPEC_DIR.parent
ENTRY = SPEC_DIR / "entry_gui.py"
ICON = SPEC_DIR / "icon.ico"

datas = []
binaries = []
hiddenimports = []

# 只读数据：术语表 + 默认配置模板
datas += [(str(ROOT / "data"), "data")]
datas += [(str(ROOT / "config.yaml"), ".")]
datas += [(str(ROOT / "README.md"), ".")]

# OCR 引擎要带上模型和它自己的 config.yaml（rapidocr 会从包目录读配置）
for pkg in ("rapidocr", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] collect_all({pkg}) 失败: {exc}")

hiddenimports += [
    "keyboard", "pyperclip", "dxcam", "mss", "PIL", "yaml", "pydantic",
    "win32gui", "win32api", "win32clipboard", "win32con", "win32timezone",
    "openai", "httpx", "httpcore", "anyio",
    "PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
]
# 本地后端要走直连（绕过系统代理），确保 httpx 的 SSL/代理实现被收集
datas += collect_data_files("certifi")

# 这些大件一律不要（本工具不需要，能省 1GB+ 体积）
excludes = [
    "torch", "torchaudio", "torchvision", "funasr", "modelscope",
    "faster_whisper", "ctranslate2", "sounddevice", "edge_tts",
    "matplotlib", "scipy", "pandas", "notebook", "IPython", "tkinter",
    "PyQt5", "PyQt6", "PySide2", "sqlite3", "tests",
]

# onnxruntime-gpu 会把 CUDA/TensorRT 的 provider DLL 一起拖进来（1GB+），
# 而我们只用 CPU 推理（GPU 版还依赖本机缺失的 cuDNN9）。这里直接剔掉。
_EXCLUDE_DLL = (
    "providers_cuda", "providers_tensorrt", "providers_dml", "providers_openvino",
    "cudnn", "cublas", "cufft", "curand", "cusolver", "cusparse",
    "nvrtc", "nvjitlink", "tensorrt", "nvperf", "onnxruntime_providers_shared",
)
if binaries:
    _before = len(binaries)
    binaries = [(src, dst) for src, dst in binaries
                if not any(p in Path(src).name.lower() for p in _EXCLUDE_DLL)]
    print(f"[spec] 剔除 GPU provider DLL: {_before - len(binaries)} 个")

block_cipher = None

a = Analysis(                                   # noqa: F821
    [str(ENTRY)],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)   # noqa: F821

# ---------------------------------------------------------------------------
# 统一瘦身：PyInstaller 的 hook 会绕过上面的过滤，把 torch 的 CUDA 库和
# onnxruntime 的 GPU provider 偷偷塞进来（实测占 1.5GB+）。这里在 Analysis
# 之后直接过滤最终 TOC——这是唯一能兜住所有来源的位置。
# 保留：onnxruntime CPU、cv2（rapidocr 预处理要用）、cryptography（云端 HTTPS 要用）
# ---------------------------------------------------------------------------
from PyInstaller.building.datastruct import TOC      # noqa: E402

_DROP_PARTS = (
    "torch",              # 本工具完全不用（拉进来的都是 1GB 的 CUDA 库）
    "llvmlite",           # numba 的 JIT，用不上
    "av.libs", "av\\",    # PyAV
    "transformers",       # 只被 rapidocr 的可选模块牵连
    "babel", "pycountry",
    "providers_cuda", "providers_tensorrt", "providers_dml", "providers_openvino",
    "nvinfer", "cudnn", "cublas", "cufft", "curand", "cusolver", "cusparse",
    "nvrtc", "nvjitlink", "tensorrt", "nvperf",
)


def _keep(name: str) -> bool:
    low = str(name).lower().replace("/", "\\")
    return not any(part in low for part in _DROP_PARTS)


def _slim(toc, label: str):
    before = len(toc)
    out = TOC([entry for entry in toc if _keep(entry[0])])
    print(f"[spec] 瘦身 {label}: {before} -> {len(out)} 项")
    return out


a.binaries = _slim(a.binaries, "binaries")
a.datas = _slim(a.datas, "datas")

gui_exe = EXE(                                  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="deadlock-tongyi",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 主程序不弹黑框
    icon=str(ICON),
)
cli_exe = EXE(                                  # noqa: F821
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="deadlock-tongyi-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,           # 命令行版保留控制台，方便 --selftest
    icon=str(ICON),
)

coll = COLLECT(                                 # noqa: F821
    gui_exe, cli_exe, a.binaries, a.zipfiles, a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="deadlock-tongyi",
)

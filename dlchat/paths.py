"""统一路径管理：打包成 exe 之后不能往程序目录写东西。

三类路径要分清：
1. **只读资源**（术语表 data/*.json、OCR 模型）→ 打包后在 bundle 里，开发时在项目根目录
2. **可写配置**（config.yaml）→ `%APPDATA%\\deadlock-tongyi\\`；但开发时/便携版优先用
   当前目录或 exe 同目录的同名文件（谁先存在用谁）
3. **输出**（校准截图、日志）→ `%APPDATA%\\deadlock-tongyi\\`

这样打包后放进 Program Files 也能正常读写配置。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "deadlock-tongyi"

# 改名前的目录名（项目从 deadlock-fanyi 改名为 deadlock-tongyi）。
# 老用户的 settings.json / config.yaml / logs 都在旧目录里，尤其是**网页里填的
# API Key**——不搬就等于让每个人重填一遍。
LEGACY_APP_NAMES = ("deadlock-fanyi",)


def is_frozen() -> bool:
    """是否跑在 PyInstaller 打出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """只读资源所在目录。"""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def exe_dir() -> Path:
    return Path(sys.executable).resolve().parent if is_frozen() else bundle_dir()


def user_base() -> str:
    """%APPDATA%（或 Unix 的 XDG_CONFIG_HOME / home）。"""
    return os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME") or str(Path.home())


def user_dir() -> Path:
    """可写目录：配置、日志、校准截图都放这里。"""
    path = Path(user_base()) / APP_NAME
    # 顺序不能换：必须**先**迁移再建目录 —— mkdir 会把目标目录建出来，
    # 迁移的"目标已存在就跳过"这一条就永远成立，等于没迁移。
    _migrate_legacy_user_dir(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path.cwd()
    return path


def _migrate_legacy_user_dir(target: Path) -> None:
    """把旧名字的用户目录整体搬过来（只在首次运行、新目录还不存在时做一次）。

    规则刻意保守：
    * 目标目录**已经存在**（哪怕只有个空 logs\\）就什么都不做 —— 否则会把用户
      当前正在用的东西盖掉；
    * 旧目录不存在就直接返回（新用户）；
    * 搬迁失败（文件被占用、权限不足）只记一条日志，绝不抛异常：大不了回到
      "重新配一次 API Key"，不能让程序起不来。
    """
    if target.exists():
        return
    for legacy in LEGACY_APP_NAMES:
        source = target.parent / legacy
        if not source.is_dir():
            continue
        try:
            shutil.move(str(source), str(target))
            logger.info("已把用户目录从 %s 迁移到 %s", source, target)
        except OSError as e:  # noqa: BLE001
            logger.warning("用户目录迁移失败（忽略，按全新安装继续）: %s", e)
        return


def data_dir() -> Path:
    """术语表等只读数据。"""
    return bundle_dir() / "data"


def default_config_path() -> Path:
    """配置文件位置，按优先级：显式环境变量 > exe 同目录 > 当前目录 > 用户目录。"""
    env = os.environ.get("DLCHAT_CONFIG")
    if env:
        return Path(env)
    for candidate in (exe_dir() / "config.yaml", Path.cwd() / "config.yaml"):
        if candidate.exists():
            return candidate
    return user_dir() / "config.yaml"


def ensure_user_config(template: Path | None = None) -> Path:
    """首次运行时把内置默认配置复制到用户目录。"""
    target = user_dir() / "config.yaml"
    if target.exists():
        return target
    source = template or (bundle_dir() / "config.yaml")
    try:
        if source.exists():
            target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass
    return target


def output_dir() -> Path:
    """校准截图/调试输出目录。"""
    path = user_dir() / "spike_out"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path.cwd()
    return path


def log_dir() -> Path:
    path = user_dir() / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path.cwd()
    return path


def describe() -> str:
    """给自检用的一行说明。"""
    mode = "打包 exe" if is_frozen() else "源码运行"
    return (f"{mode} | 资源: {bundle_dir()} | 数据: {data_dir()} | "
            f"配置: {default_config_path()}")

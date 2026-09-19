"""从 Deadlock 的控制台日志里读聊天。

依据：Deadlock 的 client.dll 里注册了 say / say_team / messagemode / messagemode2，
server.dll 里聊天打印格式是 "[All Chat][Name (3)]: msg"；引擎支持 -con_logfile /
con_logfile 把控制台输出写文件（engine2.dll 里能看到这两个启动参数）。
CS2 已有同类工具就是 tail console.log 实现的。

注意：聊天是否真的会写进 console.log 需要实测（scripts/spike_console_log.py）。
如果实测不行，就换 OCR 来源（sources/screen_ocr.py）。
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

from ..chat.line import ChatLine
from ..chat.parser import parse_line
from ..config import ConsoleSourceSection
from .base import ChatSource, SourceStatus

logger = logging.getLogger(__name__)

DEFAULT_STEAM_GAME_DIRS = [
    r"D:\software\steam\steamapps\common\Deadlock\game",
    r"C:\Program Files (x86)\Steam\steamapps\common\Deadlock\game",
    r"D:\Steam\steamapps\common\Deadlock\game",
    r"D:\SteamLibrary\steamapps\common\Deadlock\game",
    r"E:\SteamLibrary\steamapps\common\Deadlock\game",
]
LOG_NAMES = ["console.log", "console_log.txt", "console.txt"]


class ConsoleLogSource(ChatSource):
    name = "console"

    def __init__(self, cfg: ConsoleSourceSection):
        self.cfg = cfg
        self._patterns = [re.compile(p) for p in cfg.line_patterns]
        self._path: Path | None = None
        self._offset = 0
        self._partial = ""
        self._status = SourceStatus()
        self._last_size = 0

    # ---- 生命周期 ----

    def start(self) -> bool:
        self._path = self._resolve_path()
        if self._path is None:
            self._status = SourceStatus(
                running=False,
                detail="找不到 console.log（需要用 -con_logfile 启动一次游戏）",
            )
            return False
        size = self._path.stat().st_size
        self._offset = size if self.cfg.tail_from_end else 0
        self._last_size = size
        self._partial = ""
        self._status = SourceStatus(running=True, detail="已连接控制台日志",
                                    extra=str(self._path))
        logger.info("控制台日志: %s (从 %d 字节开始)", self._path, self._offset)
        return True

    def stop(self) -> None:
        self._status = SourceStatus(running=False, detail="已停止")

    def status(self) -> SourceStatus:
        return self._status

    # ---- 轮询 ----

    def poll(self) -> list[ChatLine]:
        if self._path is None:
            return []
        try:
            size = self._path.stat().st_size
        except OSError:
            return []
        if size < self._offset:  # 日志被截断/重建
            logger.info("日志被截断，从头开始读")
            self._offset = 0
            self._partial = ""
        if size == self._offset:
            return []
        try:
            with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                data = f.read()
                self._offset = f.tell()
        except OSError as e:
            logger.warning("读日志失败: %s", e)
            return []
        self._last_size = size

        text = self._partial + data
        lines = text.split("\n")
        self._partial = lines.pop() if text and not text.endswith("\n") else ""
        out: list[ChatLine] = []
        for raw in lines:
            line = self._match(raw)
            if line is not None:
                out.append(line)
        return out

    # ---- 内部 ----

    def _match(self, raw: str) -> ChatLine | None:
        for pattern in self._patterns:
            m = pattern.match(raw)
            if not m:
                continue
            groups = m.groupdict()
            text = (groups.get("msg") or "").strip()
            if not text:
                continue
            from ..chat.line import normalize_target

            return ChatLine(text=text, speaker=(groups.get("name") or "").strip(),
                            target=normalize_target(groups.get("chan")),
                            source="console", raw=raw)
        # 配置的正则没命中时，退回通用解析
        return parse_line(raw, source="console")

    def _resolve_path(self) -> Path | None:
        candidates: list[Path] = []
        if self.cfg.log_path:
            candidates.append(Path(os.path.expandvars(self.cfg.log_path)))
        for extra in self.cfg.extra_candidates:
            candidates.append(Path(os.path.expandvars(extra)))
        for game_dir in self._game_dirs():
            candidates += [
                game_dir / "bin" / "win64" / name for name in LOG_NAMES
            ] + [game_dir / "citadel" / name for name in LOG_NAMES]
        # 游戏运行中时，日志通常是最近被修改的那个
        existing = [p for p in candidates if p.exists()]
        if not existing:
            return None
        existing.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return existing[0]

    def _game_dirs(self) -> list[Path]:
        dirs: list[Path] = []
        if self.cfg.game_dir:
            dirs.append(Path(os.path.expandvars(self.cfg.game_dir)))
        else:
            dirs += [Path(p) for p in DEFAULT_STEAM_GAME_DIRS]
        return [d for d in dirs if d.exists()]

    def wait_for_change(self, timeout_s: float) -> bool:
        """给低频轮询用：等到文件有变化或超时。"""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if self._path and self._path.stat().st_size != self._last_size:
                    return True
            except OSError:
                return False
            time.sleep(0.05)
        return False

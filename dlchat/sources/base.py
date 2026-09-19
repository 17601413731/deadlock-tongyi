"""聊天来源抽象：控制台日志 / 屏幕 OCR 都实现它。

新增来源只要实现 start/stop/poll，编排层（app/service.py）不用改。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..chat.line import ChatLine


@dataclass
class SourceStatus:
    running: bool = False
    detail: str = ""
    # 给 UI 用的补充信息（例如日志路径、OCR 后端）
    extra: str = ""


class ChatSource(ABC):
    name = "base"

    @abstractmethod
    def start(self) -> bool:
        """开始读取；返回是否成功启动（失败要给出 status().detail）。"""

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def poll(self) -> list[ChatLine]:
        """非阻塞地取出"本次新增"的聊天行。"""

    @abstractmethod
    def status(self) -> SourceStatus: ...

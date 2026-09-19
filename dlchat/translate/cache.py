"""译文缓存：同一句话反复刷屏时零成本。"""

from __future__ import annotations

import threading
from collections import OrderedDict


class TranslationCache:
    def __init__(self, max_size: int = 512):
        self._max = max_size
        self._data: OrderedDict[tuple[str, str], str] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, text: str, direction: str) -> str | None:
        key = (text.strip().lower(), direction)
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.hits += 1
                return self._data[key]
            self.misses += 1
            return None

    def put(self, text: str, direction: str, translated: str) -> None:
        if not translated:
            return
        key = (text.strip().lower(), direction)
        with self._lock:
            self._data[key] = translated
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> tuple[int, int]:
        with self._lock:
            return self.hits, self.misses

"""屏幕区域抓帧。

默认走 dxcam（DXGI Desktop Duplication，实测在 Deadlock 无边框窗口下可用），
失败则退回 mss（GDI BitBlt）。抓帧本身很便宜，所以按需抓单帧即可；
真正贵的是 OCR，由 change 检测挡住没变化的帧。
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ScreenGrabber:
    def __init__(self, output_idx: int = 0):
        self.output_idx = output_idx
        self.backend = "none"
        self._cam: Any = None
        self._sct: Any = None
        self.size: tuple[int, int] = (1920, 1080)
        self._init_backend()

    # ---- 初始化 ----

    def _init_backend(self) -> None:
        try:
            import dxcam

            self._cam = dxcam.create(output_idx=self.output_idx, output_color="RGB")
            if self._cam is not None:
                frame = self._cam.grab()
                if frame is not None:
                    self.size = (frame.shape[1], frame.shape[0])
                self.backend = "dxcam"
                logger.info("抓帧后端: dxcam, 屏幕 %dx%d", *self.size)
                return
        except Exception as e:  # noqa: BLE001
            logger.warning("dxcam 不可用(%s)，退回 mss", e)

        try:
            import mss

            self._sct = mss.mss()
            mon = self._sct.monitors[self.output_idx + 1]
            self.size = (mon["width"], mon["height"])
            self.backend = "mss"
            logger.info("抓帧后端: mss, 屏幕 %dx%d", *self.size)
        except Exception as e:  # noqa: BLE001
            logger.error("抓帧后端全部不可用: %s", e)
            self.backend = "none"

    # ---- 抓帧 ----

    def region_to_pixels(self, region_norm: list[float]) -> tuple[int, int, int, int]:
        """归一化区域 [x1,y1,x2,y2] (0~1) -> 像素 (left, top, right, bottom)。"""
        w, h = self.size
        x1, y1, x2, y2 = (max(0.0, min(1.0, float(v))) for v in region_norm)
        left, top = int(x1 * w), int(y1 * h)
        right, bottom = int(x2 * w), int(y2 * h)
        if right - left < 8 or bottom - top < 8:
            raise ValueError(f"区域太小: {region_norm}")
        return left, top, right, bottom

    def grab(self, region_norm: list[float]) -> np.ndarray | None:
        left, top, right, bottom = self.region_to_pixels(region_norm)
        try:
            if self._cam is not None:
                frame = self._cam.grab(region=(left, top, right, bottom))
                if frame is None:
                    frame = self._cam.grab(region=(left, top, right, bottom))
                return frame
            if self._sct is not None:
                raw = self._sct.grab({"left": left, "top": top,
                                      "width": right - left, "height": bottom - top})
                return np.asarray(raw)[:, :, :3][:, :, ::-1]  # BGRA -> RGB
        except Exception as e:  # noqa: BLE001
            logger.warning("抓帧失败: %s", e)
        return None

    def close(self) -> None:
        try:
            if self._cam is not None:
                self._cam.release()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._sct is not None:
                self._sct.close()
        except Exception:  # noqa: BLE001
            pass
        self._cam = None
        self._sct = None


def frame_diff(prev: np.ndarray | None, cur: np.ndarray | None,
               grid: tuple[int, int] = (64, 24)) -> float:
    """两张图降采样后的平均绝对差（0~1）。用于判断聊天区域是否变化。"""
    if cur is None:
        return 0.0
    if prev is None or prev.shape != cur.shape:
        return 1.0
    small_prev = _downscale(prev, grid)
    small_cur = _downscale(cur, grid)
    return float(np.abs(small_cur - small_prev).mean() / 255.0)


def _downscale(img: np.ndarray, grid: tuple[int, int]) -> np.ndarray:
    """按网格做均值池化（纯 numpy，避免引入 cv2 依赖）。"""
    gw, gh = grid
    h, w = img.shape[:2]
    gray = img.mean(axis=2) if img.ndim == 3 else img.astype(np.float32)
    ys = np.linspace(0, h, gh + 1).astype(int)
    xs = np.linspace(0, w, gw + 1).astype(int)
    out = np.zeros((gh, gw), dtype=np.float32)
    for i in range(gh):
        for j in range(gw):
            block = gray[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            out[i, j] = block.mean() if block.size else 0.0
    return out

"""OCR 引擎封装。

默认 RapidOCR（Apache-2.0，自带小模型，CPU 离线，约 27MB wheel）：
    pip install rapidocr
兼容旧包名 rapidocr_onnxruntime。若两者都没有，可退回 Windows 内建 OCR
（pip install winocr），识别率略差但零模型下载。
"""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

try:  # rapidocr 3.x 的输出类型（用于区分"没检测到文字"和解析失败）
    from rapidocr import RapidOCROutput
except Exception:  # noqa: BLE001
    RapidOCROutput = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@dataclass
class OCRLine:
    text: str
    score: float
    box: tuple[int, int, int, int]  # x1, y1, x2, y2


class OCREngine(ABC):
    name = "base"

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def recognize(self, image: np.ndarray) -> list[OCRLine]: ...


class RapidOCREngine(OCREngine):
    name = "rapidocr"

    def __init__(self, min_confidence: float = 0.5, upscale: int = 2, invert: bool = False,
                 det_limit_side: int = 960, det_limit_type: str = "max"):
        self.min_confidence = min_confidence
        self.upscale = max(1, upscale)
        self.invert = invert
        # 关键性能开关：rapidocr 默认 limit_type=min（把**短边**放大到 736）。
        # 顶部聊天条是 1920x86 这种又宽又扁的形状，短边放大后检测输入变成
        # 约 16400x736（1200 万像素），实测单帧 4~7 秒。
        # 改成 limit_type=max（限制**长边**）后同一区域减半以上。
        self.det_limit_side = int(det_limit_side)
        self.det_limit_type = det_limit_type if det_limit_type in ("min", "max") else "max"
        self._engine = None
        self._api = ""  # "v3" | "v1"
        # 实测：两个 OCR 引擎实例同时跑会互相抢线程，把 100ms 拖成 8 秒。
        # 所以全程序只保留一个实例，并用这把锁串行化调用（接收方向 + 读输入行共用）。
        self._lock = threading.Lock()

    def _engine_params(self) -> dict:
        return {
            "Det.limit_side_len": self.det_limit_side,
            "Det.limit_type": self.det_limit_type,
        }

    def load(self) -> None:
        params = self._engine_params()
        try:
            from rapidocr import RapidOCR  # 3.x

            try:
                self._engine = RapidOCR(params=params)
            except Exception as e:  # noqa: BLE001
                logger.warning("OCR 参数不被接受(%s)，改用默认参数", e)
                self._engine = RapidOCR()
            self._api = "v3"
            logger.info("OCR: rapidocr 3.x 已加载（det 限长边=%d/%s）",
                        self.det_limit_side, self.det_limit_type)
            return
        except Exception:  # noqa: BLE001
            pass
        try:
            from rapidocr_onnxruntime import RapidOCR  # 1.x

            self._engine = RapidOCR()
            self._api = "v1"
            logger.info("OCR: rapidocr_onnxruntime 已加载")
            return
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "未安装 OCR 引擎。请执行: pip install rapidocr"
            ) from e

    def recognize(self, image: np.ndarray) -> list[OCRLine]:
        img = self._preprocess(image)
        with self._lock:
            if self._engine is None:
                self.load()
            try:
                raw = self._engine(img)
            except Exception as e:  # noqa: BLE001
                logger.warning("OCR 失败: %s", e)
                return []
        return [l for l in self._parse(raw) if l.score >= self.min_confidence]

    # ---- 快路径：已知区域里是若干行文本时，跳过检测(det)直接识别(rec) ----

    def recognize_strips(self, image: np.ndarray, rows: int,
                         min_line_height: int = 8) -> list[OCRLine]:
        """把区域按行切成 rows 条，逐条只跑 rec。

        det（文本框检测）在大图上是主要开销；聊天条这类"位置已知、行数有限"的
        场景完全不需要 det。每一行独立 rec，顺便天然拿到行坐标。
        """
        if self._engine is None:
            self.load()
        rows = max(1, rows)
        h = image.shape[0]
        band = max(min_line_height, h // rows)
        out: list[OCRLine] = []
        y = 0
        while y < h:
            strip = image[y:min(h, y + band), :]
            if strip.shape[0] >= min_line_height:
                with self._lock:
                    out += self._rec_only(strip, y)
            y += band
        return [l for l in out if l.score >= self.min_confidence]

    def _rec_only(self, strip: np.ndarray, offset_y: int) -> list[OCRLine]:
        img = self._preprocess(strip)
        try:
            if self._api == "v3":
                raw = self._engine(img, use_det=False, use_cls=False, use_rec=True)
            else:
                raw = self._engine(img, use_det=False, use_cls=False, use_rec=True)
        except TypeError:
            # 老版本不接受这些开关：退回完整流程
            try:
                raw = self._engine(img)
            except Exception as e:  # noqa: BLE001
                logger.debug("rec-only 失败: %s", e)
                return []
        except Exception as e:  # noqa: BLE001
            logger.debug("rec-only 失败: %s", e)
            return []
        lines = self._parse(raw)
        for line in lines:
            x1, y1, x2, y2 = line.box
            if (x1, y1, x2, y2) == (0, 0, 0, 0):
                # rec-only 没有框：用整条区域兜底（调用方只需要大致位置）
                line.box = (0, offset_y, strip.shape[1], offset_y + strip.shape[0])
                continue
            line.box = (x1 // self.upscale, (y1 // self.upscale) + offset_y,
                        x2 // self.upscale, (y2 // self.upscale) + offset_y)
        return lines

    # ---- 内部 ----

    def _preprocess(self, image: np.ndarray) -> np.ndarray:
        """聊天文字是浅色小字压在半透明底上：放大 + 可选反色能明显提升识别率。"""
        img = image
        if self.upscale > 1:
            img = np.repeat(np.repeat(img, self.upscale, axis=0), self.upscale, axis=1)
        if self.invert:
            img = 255 - img
        return np.ascontiguousarray(img)

    def _parse(self, raw) -> list[OCRLine]:
        out: list[OCRLine] = []
        if raw is None:
            return out

        # 3.x: RapidOCROutput(boxes=..., txts=..., scores=...)
        # 只跑识别(rec-only)时返回的是 TextRecOutput：有 txts/scores，但没有 boxes。
        # 检测不到文字时 RapidOCROutput 的 txts 是 None —— 这是正常情况（那一带没文字），
        # 直接返回空列表，不要打日志刷屏。
        if isinstance(raw, RapidOCROutput) and getattr(raw, "txts", None) is None:
            return out
        txts = getattr(raw, "txts", None)
        boxes = getattr(raw, "boxes", None)
        scores = getattr(raw, "scores", None)
        if txts is not None:
            for i, text in enumerate(txts or []):
                if not text:
                    continue
                score = 1.0
                if scores is not None and i < len(scores):
                    try:
                        score = float(scores[i])
                    except (TypeError, ValueError):
                        score = 1.0
                box = (0, 0, 0, 0)
                if boxes is not None and i < len(boxes):
                    box = _box_tuple(boxes[i])
                out.append(OCRLine(text=str(text).strip(), score=score, box=box))
            return out

        # 1.x: (result, elapse)，result = [[box, text, score], ...]
        if isinstance(raw, tuple) and raw:
            raw = raw[0]
        if not hasattr(raw, "__iter__"):
            logger.debug("无法解析的 OCR 输出类型: %s", type(raw).__name__)
            return out
        for item in raw or []:
            try:
                box, text, score = item[0], item[1], float(item[2])
            except Exception:  # noqa: BLE001
                continue
            if text:
                out.append(OCRLine(text=str(text).strip(), score=score,
                                   box=_box_tuple(box)))
        return out


class WindowsOCREngine(OCREngine):
    """Windows 内建 OCR（Windows.Media.Ocr，通过 winocr 调用）。"""

    name = "windows"

    def __init__(self, min_confidence: float = 0.3, **_: object):
        self.min_confidence = min_confidence
        self._ocr = None

    def load(self) -> None:
        try:
            import winocr

            self._ocr = winocr
            logger.info("OCR: Windows.Media.Ocr 已加载")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("未安装 winocr。请执行: pip install winocr") from e

    def recognize(self, image: np.ndarray) -> list[OCRLine]:
        if self._ocr is None:
            self.load()
        from PIL import Image

        img = Image.fromarray(image)
        try:
            result = self._run(img)
        except Exception as e:  # noqa: BLE001
            logger.warning("Windows OCR 失败: %s", e)
            return []
        return result

    def _run(self, img) -> list[OCRLine]:
        import asyncio

        async def _do():
            return await self._ocr.recognize_pil(img, "en")

        res = asyncio.run(_do())
        out: list[OCRLine] = []
        for line in getattr(res, "lines", []) or []:
            words = getattr(line, "words", []) or []
            text = "".join(getattr(w, "text", "") for w in words) or getattr(line, "text", "")
            if not text.strip():
                continue
            xs = [getattr(w.bounding_rect, "x", 0) for w in words] or [0]
            ys = [getattr(w.bounding_rect, "y", 0) for w in words] or [0]
            ws = [getattr(w.bounding_rect, "width", 0) for w in words] or [0]
            hs = [getattr(w.bounding_rect, "height", 0) for w in words] or [0]
            out.append(OCRLine(text=text.strip(), score=1.0,
                               box=(int(min(xs)), int(min(ys)),
                                    int(max(xs) + max(ws)), int(max(ys) + max(hs)))))
        return out


def _box_tuple(box) -> tuple[int, int, int, int]:
    try:
        arr = np.asarray(box, dtype=float).reshape(-1, 2)
        xs, ys = arr[:, 0], arr[:, 1]
        return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    except Exception:  # noqa: BLE001
        return 0, 0, 0, 0


def create_ocr(backend: str = "rapidocr", **kw) -> OCREngine:
    if backend == "windows":
        return WindowsOCREngine(**kw)
    return RapidOCREngine(**kw)

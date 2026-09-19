"""抓帧与 OCR。"""

from .ocr import OCREngine, OCRLine, RapidOCREngine, WindowsOCREngine, create_ocr
from .screen import ScreenGrabber, frame_diff

__all__ = [
    "OCREngine",
    "OCRLine",
    "RapidOCREngine",
    "ScreenGrabber",
    "WindowsOCREngine",
    "create_ocr",
    "frame_diff",
]

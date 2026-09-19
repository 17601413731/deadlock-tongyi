"""抓屏识别的"游戏前台"闸门测试。

实测踩过的坑：游戏切到后台（桌面/浏览器/本工具窗口）时，聊天区域那块
屏幕上变成别的内容，工具照样 OCR 并翻译 —— 屏幕上出现一堆文件名、
批处理命令被翻成中文。修法是：游戏不在前台就完全不抓屏。
"""

import unittest

import numpy as np

from dlchat.config import OCRSection
from dlchat.sources.screen_ocr import ScreenOCRSource


class _FakeGrabber:
    backend = "fake"
    size = (1920, 1080)

    def __init__(self):
        self.grabs = 0

    def grab(self, region):
        self.grabs += 1
        return np.zeros((60, 200, 3), dtype=np.uint8)

    def close(self):
        pass


class _FakeOCR:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def load(self):
        pass

    def recognize(self, image):
        self.calls += 1
        from dlchat.capture.ocr import OCRLine

        return [OCRLine(text="mid no", score=0.9, box=(0, 0, 50, 20))]

    def recognize_strips(self, image, rows, min_line_height=8):
        return self.recognize(image)


def _make(focused: bool | None, interval_ms: int = 0):
    cfg = OCRSection(interval_ms=interval_ms, change_threshold=0.0)
    grabber, ocr = _FakeGrabber(), _FakeOCR()
    check = None if focused is None else (lambda: focused)
    src = ScreenOCRSource(cfg, ocr, grabber, owns_resources=False, focus_check=check)
    return src, grabber, ocr


class FocusGateTest(unittest.TestCase):
    def test_unfocused_never_grabs_or_ocrs(self):
        src, grabber, ocr = _make(focused=False)
        self.assertEqual(src.poll(), [])
        self.assertEqual(grabber.grabs, 0, "不在前台时不该抓屏")
        self.assertEqual(ocr.calls, 0, "不在前台时不该跑 OCR")

    def test_focused_grabs_and_returns_lines(self):
        src, grabber, ocr = _make(focused=True)
        lines = src.poll()
        self.assertEqual(grabber.grabs, 1)
        self.assertEqual(ocr.calls, 1)
        self.assertEqual([l.text for l in lines], ["mid no"])

    def test_no_focus_check_means_always_on(self):
        src, grabber, _ = _make(focused=None)
        src.poll()
        self.assertEqual(grabber.grabs, 1)

    def test_focus_check_exception_fails_open(self):
        """检查函数自己抛异常时，宁可继续工作也不要静默停摆。"""
        cfg = OCRSection(interval_ms=0, change_threshold=0.0)

        def boom():
            raise RuntimeError("no window api")

        src = ScreenOCRSource(cfg, _FakeOCR(), _FakeGrabber(),
                             owns_resources=False, focus_check=boom)
        self.assertEqual(len(src.poll()), 1)

    def test_regaining_focus_rebaselines_frame(self):
        """回到前台后要重新抓基准帧，否则和后台时的画面比变化会误判。"""
        state = {"focused": False}
        cfg = OCRSection(interval_ms=0, change_threshold=0.0)
        grabber, ocr = _FakeGrabber(), _FakeOCR()
        src = ScreenOCRSource(cfg, ocr, grabber, owns_resources=False,
                             focus_check=lambda: state["focused"])
        src.poll()
        self.assertIsNone(src._prev)          # noqa: SLF001
        state["focused"] = True
        src.poll()
        self.assertIsNotNone(src._prev)       # noqa: SLF001


if __name__ == "__main__":
    unittest.main()

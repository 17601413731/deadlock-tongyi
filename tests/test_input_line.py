"""输入行读取/清洗与连击触发测试（零注入路径的核心逻辑）。"""

import time
import unittest

from dlchat.input.line_reader import clean_input_line
from dlchat.input.space_trigger import MultiTapTrigger


class CleanInputLineTest(unittest.TestCase):
    def test_strips_english_placeholder(self):
        self.assertEqual(clean_input_line("To (ALL): 中路没人"), "中路没人")
        self.assertEqual(clean_input_line("To (ALLIES): 撤"), "撤")

    def test_strips_chinese_placeholder(self):
        self.assertEqual(clean_input_line("对（所有人）：他残血"), "他残血")
        self.assertEqual(clean_input_line("说：等我"), "等我")

    def test_strips_trailing_spaces_from_taps(self):
        # 用户连按三下空格留下的空白
        self.assertEqual(clean_input_line("To (ALL): 推中路    "), "推中路")

    def test_strips_edge_junk(self):
        self.assertEqual(clean_input_line("| 中路没人 |"), "中路没人")

    def test_placeholder_only_is_empty(self):
        for raw in ("To (ALL):", "To (ALL): ", "对（所有人）：", "", "   "):
            self.assertEqual(clean_input_line(raw), "", raw)

    def test_pure_symbols_rejected(self):
        self.assertEqual(clean_input_line("To (ALL): ---"), "")
        self.assertEqual(clean_input_line("To (ALL): 12345"), "")

    def test_english_message_kept(self):
        self.assertEqual(clean_input_line("To (ALL): push mid"), "push mid")

    def test_long_text_kept(self):
        text = "To (ALL): 我们三个人一起去打中路BOSS然后推塔"
        self.assertEqual(clean_input_line(text), "我们三个人一起去打中路BOSS然后推塔")


class MultiTapTriggerTest(unittest.TestCase):
    def _make(self, **kw):
        self.fired = []
        defaults = dict(key="space", taps=3, window_s=1.5,
                        on_fire=lambda: self.fired.append(time.monotonic()))
        defaults.update(kw)
        trigger = MultiTapTrigger(**defaults)
        trigger.armed = True
        return trigger

    def test_three_taps_fires_once(self):
        trigger = self._make()
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(len(self.fired), 1)
        self.assertEqual(trigger.fires, 1)

    def test_two_taps_do_not_fire(self):
        trigger = self._make()
        trigger._register_tap()  # noqa: SLF001
        trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])

    def test_counter_resets_after_fire(self):
        trigger = self._make()
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(len(self.fired), 2)

    def test_old_taps_outside_window_ignored(self):
        trigger = self._make(window_s=0.001)
        trigger._times = [time.monotonic() - 5.0]  # noqa: SLF001
        trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])

    def test_focus_guard_blocks(self):
        trigger = self._make(require_focus=lambda: False)
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])

    def test_focus_guard_allows(self):
        trigger = self._make(require_focus=lambda: True)
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(len(self.fired), 1)

    def test_busy_guard_blocks(self):
        trigger = self._make(is_busy=lambda: True)
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])

    def test_disarmed_never_fires(self):
        trigger = self._make()
        trigger.armed = False
        for _ in range(5):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])

    def test_custom_tap_count(self):
        trigger = self._make(taps=4)
        for _ in range(3):
            trigger._register_tap()  # noqa: SLF001
        self.assertEqual(self.fired, [])
        trigger._register_tap()  # noqa: SLF001
        self.assertEqual(len(self.fired), 1)


if __name__ == "__main__":
    unittest.main()

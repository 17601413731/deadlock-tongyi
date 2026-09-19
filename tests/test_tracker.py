"""去重追踪测试。"""

import unittest

from dlchat.chat.line import ChatLine
from dlchat.chat.tracker import LineTracker


def line(text: str, speaker: str = "Bob") -> ChatLine:
    return ChatLine(text=text, speaker=speaker)


class TrackerTest(unittest.TestCase):
    def test_exact_duplicate_dropped(self):
        tracker = LineTracker()
        self.assertEqual(len(tracker.update([line("mid no")])), 1)
        self.assertEqual(tracker.update([line("mid no")]), [])

    def test_case_and_punctuation_duplicate_dropped(self):
        tracker = LineTracker()
        tracker.update([line("Mid No")])
        self.assertEqual(tracker.update([line("mid no!")]), [])

    def test_ocr_jitter_dropped_by_fuzzy(self):
        tracker = LineTracker(similarity=0.9)
        tracker.update([line("push the walker now")])
        # OCR 少认一个字母
        self.assertEqual(tracker.update([line("push the walker no")]), [])

    def test_distinct_lines_kept(self):
        tracker = LineTracker()
        tracker.update([line("mid no")])
        fresh = tracker.update([line("careful enemy missing")])
        self.assertEqual(len(fresh), 1)

    def test_ignore_speaker(self):
        tracker = LineTracker(ignore_speakers=["myname"])
        self.assertEqual(tracker.update([line("hi", speaker="MyName")]), [])
        self.assertEqual(len(tracker.update([line("hi", speaker="Other")])), 1)

    def test_ttl_allows_repeat_after_expiry(self):
        tracker = LineTracker(ttl_s=0.0)
        self.assertEqual(len(tracker.update([line("gg")])), 1)
        # TTL=0 -> 上一条立即过期，同一句可以再次上报
        self.assertEqual(len(tracker.update([line("gg")])), 1)

    def test_same_batch_dedup(self):
        tracker = LineTracker()
        fresh = tracker.update([line("gg"), line("gg"), line("wp")])
        self.assertEqual([l.text for l in fresh], ["gg", "wp"])

    def test_reset(self):
        tracker = LineTracker()
        tracker.update([line("gg")])
        tracker.reset()
        self.assertEqual(len(tracker.update([line("gg")])), 1)


if __name__ == "__main__":
    unittest.main()

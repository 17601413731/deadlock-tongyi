"""窗口识别测试 —— 这次踩的坑必须锁死。

真实事故（2026-09-13）：原来用"标题包含 deadlock"认游戏窗口，结果把这四个都认成游戏：
    msedge.exe    「Deadlock 聊天翻译功能方案 — DSH 本地构建…」
    explorer.exe  「deadlock-tongyi - 文件资源管理器」
    pycharm64.exe 「deadlock-tongyi – run.bat」
    deadlock.exe  「Deadlock」类名 SDL_app   ← 只有这个是游戏
后果：
  · 切到浏览器时被判"游戏在前台" → 疯狂 OCR 桌面内容并翻译
  · 真在游戏里时被判"游戏不在前台" → 三空格被静默忽略
所以现在的规则是：**类名必须是 SDL_app，进程名必须是 deadlock/citadel**，标题只作为
读不到进程名时的兜底。
"""

import unittest

from dlchat.input.injector import WindowInfo, is_game_window


def win(cls, title, process="") -> WindowInfo:
    return WindowInfo(hwnd=1, cls=cls, title=title, pid=1234, process=process)


class GameWindowTest(unittest.TestCase):
    def test_real_game_window_matches(self):
        self.assertTrue(is_game_window(win("SDL_app", "Deadlock", "deadlock.exe")))

    def test_browser_with_deadlock_title_rejected(self):
        """罪魁祸首：浏览器标签标题里有 Deadlock。"""
        self.assertFalse(is_game_window(win(
            "Chrome_WidgetWin_1",
            "Deadlock 聊天翻译功能方案 — DSH 本地构建 - Microsoft Edge",
            "msedge.exe")))

    def test_explorer_and_pycharm_rejected(self):
        self.assertFalse(is_game_window(win(
            "CabinetWClass", "deadlock-tongyi - 文件资源管理器", "explorer.exe")))
        self.assertFalse(is_game_window(win(
            "SunAwtFrame", "deadlock-tongyi – run.bat", "pycharm64.exe")))

    def test_our_own_panel_rejected(self):
        """我们自己的窗口标题也带 Deadlock 和项目名。

        标题只是夹具：判定看的是类名 + 进程名（见上面的真实事故）。
        """
        self.assertFalse(is_game_window(win(
            "Qt6111QWindowIcon", "通译 · Deadlock 聊天翻译", "deadlock-tongyi.exe")))

    def test_other_sdl_game_rejected(self):
        """同样是 SDL_app，但进程不是 deadlock/citadel -> 不算。"""
        self.assertFalse(is_game_window(win("SDL_app", "Some Other Game", "other.exe")))

    def test_citadel_process_accepted(self):
        self.assertTrue(is_game_window(win("SDL_app", "Citadel", "citadel.exe")))

    def test_process_unknown_falls_back_to_title(self):
        """读不到进程名（权限不足）时，只认 SDL_app + 标题含 deadlock。"""
        self.assertTrue(is_game_window(win("SDL_app", "Deadlock", "")))
        self.assertFalse(is_game_window(win("SDL_app", "Unreal Editor", "")))
        # 关键：退回标题兜底时，类名仍然必须是 SDL_app
        self.assertFalse(is_game_window(win(
            "Chrome_WidgetWin_1", "Deadlock 聊天翻译功能方案", "")))

    def test_ime_windows_of_game_process_rejected(self):
        """游戏进程还会带 IME 窗口（类名 MSCTFIME UI / IME），不能当成主窗口。"""
        self.assertFalse(is_game_window(win("MSCTFIME UI", "MSCTFIME UI", "deadlock.exe")))
        self.assertFalse(is_game_window(win("IME", "Default IME", "deadlock.exe")))

    def test_class_case_insensitive(self):
        self.assertTrue(is_game_window(win("sdl_app", "Deadlock", "Deadlock.exe")))


if __name__ == "__main__":
    unittest.main()

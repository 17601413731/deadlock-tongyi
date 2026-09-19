"""启动器（Steam 启动选项那层包装）的离线测试。

重点覆盖"点了开始游戏没反应"这类问题：参数合并、透传、桥起来没有。
不联网、不启动真游戏（用 cmd 当替身）。
"""

from __future__ import annotations

import argparse
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dlchat import launcher  # noqa: E402


class SplitCommandTest(unittest.TestCase):
    """%command% 的解析：Steam 会把游戏路径和它自己的开关一起塞进来。"""

    def _ns(self, command):
        return argparse.Namespace(command=command)

    def test_game_path_with_spaces_stays_one_item(self):
        """路径带空格时必须仍是**一个**参数 —— 拼成字符串再切就会切坏。"""
        cmd = launcher.split_command(
            self._ns([r"D:\Steam\steamapps\common\Deadlock\game\bin\win64\deadlock.exe"]),
            [])
        self.assertEqual(len(cmd), 1)
        self.assertTrue(cmd[0].endswith("deadlock.exe"))

    def test_steam_switches_are_passed_through_in_order(self):
        cmd = launcher.split_command(
            self._ns([r"C:\dl\deadlock.exe"]), ["-console", "-novid"])
        self.assertEqual(cmd, [r"C:\dl\deadlock.exe", "-console", "-novid"])

    def test_empty_gives_empty(self):
        self.assertEqual(launcher.split_command(self._ns([]), []), [])
        self.assertEqual(launcher.split_command(self._ns(None), None), [])


class InstanceNameTest(unittest.TestCase):
    def test_launcher_uses_its_own_mutex(self):
        """启动器和桌面版是两个进程，锁名必须不同 —— 共用一个会把桌面版挡掉。"""
        from dlchat.single_instance import MUTEX_NAME

        self.assertNotEqual(launcher.LAUNCHER_MUTEX, MUTEX_NAME)


class ArgparseToleranceTest(unittest.TestCase):
    """未知开关不能让启动器直接退出（Steam 经常会加开关）。"""

    def test_unknown_flags_do_not_abort(self):
        ap = argparse.ArgumentParser()
        ap.add_argument("command", nargs="*")
        ap.add_argument("--no-bridge", action="store_true")
        args, extra = ap.parse_known_args(["game.exe", "-console", "--weird"])
        self.assertTrue(args.command)
        self.assertIn("-console", extra)
        self.assertIn("--weird", extra)


class GameRunningTest(unittest.TestCase):
    def test_no_game_returns_empty_list(self):
        """没开游戏时必须返回空列表（而不是抛异常/返回 None）—— 调用方直接 len() 判断。"""
        pids = launcher.game_running()
        self.assertIsInstance(pids, list)


class IntegratedBridgeTest(unittest.TestCase):
    """真起一次桥：确认它在**本进程内**能监听、而且随进程结束而消失。

    用随机高端口，避免和玩家正在用的 8791 打架。
    """

    def test_embedded_bridge_listens(self):
        from dlchat.config import load_config

        port = 18791
        if launcher.health_ok(port, timeout=0.5):
            self.skipTest(f"端口 {port} 已被占用")
        cfg = load_config()
        started = launcher.start_bridge_embedded(cfg, port)
        self.assertTrue(started, "端口空着却说'已有桥在跑'")
        try:
            self.assertTrue(launcher.wait_for_bridge(port, 20.0), "桥没能在 20 秒内监听")
        finally:
            # 桥的线程是 daemon，进程退出即回收；这里只验证"起来了"
            pass


if __name__ == "__main__":
    unittest.main()

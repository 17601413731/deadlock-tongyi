"""输入侧：读输入行、连击触发、注入与自检。"""

from .injector import InjectResult, TextInjector
from .line_reader import InputLineReader, clean_input_line
from .selftest import SelfTestReport, run_selftest
from .space_trigger import MultiTapTrigger

__all__ = [
    "InjectResult",
    "InputLineReader",
    "MultiTapTrigger",
    "SelfTestReport",
    "TextInjector",
    "clean_input_line",
    "run_selftest",
]

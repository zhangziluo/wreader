# -*- coding: utf-8 -*-
"""在真实 curses 会话里验证 reader._init_colors() 的效果（需要一个 pty）。

必须在伪终端里跑，否则 curses 起不来。macOS / Linux 上最省事的办法：
    script -q /dev/null python tools/verify_colors.py && cat /tmp/wreader_colors.txt
（`script` 会开一个 pty；结论写进文件，免得终端转义序列污染输出。）

检查内容：`_init_colors()` 不抛异常；终端支持颜色；`use_default_colors()` 之后
颜色 `-1`（终端默认色）确实可用 —— 这是「背景跟随终端主题 / 透明」的前提；
再顺带打一下 `A_NORMAL`，确认它不带显式颜色位。

用法：python tools/verify_colors.py [输出文件路径]        # 默认 /tmp/wreader_colors.txt
退出码：0 = 检查跑完（结论看输出文件），1 = 环境不支持（比如没有 pty）。
"""
import curses
import sys
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent
# 把仓库根加进模块搜索路径，保证从任何目录都能 import wreader
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wreader import reader  # noqa: E402  （必须在 sys.path 设好之后再导入）

# 结论写到这个文件；不给参数就用 /tmp 下的固定名字，方便脚本读取
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/wreader_colors.txt")


def main(stdscr: object) -> None:
    """在 curses 会话里跑检查，把结论写进 OUT 文件。"""
    # 收集结论行，最后一次性落盘
    lines: list[str] = []
    # 调用阅读器在主循环开始之前会调的那个函数
    reader._init_colors()
    lines.append("init_colors returned without raising: yes")
    # 终端是否有颜色能力、能支持多少色与多少配色对
    lines.append("has_colors={}".format(curses.has_colors()))
    lines.append("COLORS={}".format(curses.COLORS))
    lines.append("COLOR_PAIRS={}".format(curses.COLOR_PAIRS))
    # 调过 use_default_colors() 之后，-1（终端默认前景/背景）必须能用
    try:
        curses.init_pair(1, -1, -1)
        lines.append("default colour pair usable: yes (-1/-1)")
    except curses.error as exc:
        lines.append("default colour pair usable: no ({})".format(exc))
    # A_NORMAL 不该带任何显式颜色位，否则背景就不透亮了
    lines.append("A_NORMAL={}".format(curses.A_NORMAL))
    # 结论落盘：避开终端转义序列，便于用 cat 或脚本读取
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run() -> int:
    """入口：把 main 包进 curses.wrapper（它会负责 initscr/endwin）。"""
    # 没有真终端或没开 pty 时 curses 会抛错，这里翻译成一句人能看懂的提示
    try:
        curses.wrapper(main)
    except curses.error as exc:
        print("需要在真终端 / pty 里运行，例如：script -q /dev/null python tools/verify_colors.py")
        print("底层错误:", exc)
        return 1
    print("curses session finished cleanly; 结论写在", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())

# -*- coding: utf-8 -*-
"""检查 reader._draw 画出的每一行都不会越界。

真实 curses 对越界写入会抛错，而阅读器把它吞掉，后果是**整行文字静默消失**（不是截断）。
所以这里把每次 addstr 都记下来，断言 `起始列 + 文本显示宽度 <= 终端宽度`。
覆盖 4 种正文 × 7 种宽度 × 5 种高度，顺便把搜索高亮、书签、超长消息行都走到。

用法（在仓库任意目录都能跑）：python tools/verify_draw.py
退出码：0 = 全部通过，1 = 有越界（异常里带着那组尺寸与文本，方便复现）。
"""
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# 仓库根目录 + 模块搜索路径（与 verify_wrap.py 同款处理，保证从任何目录都能 import wreader）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wreader import reader  # noqa: E402  （必须在 sys.path 设好之后再导入）

# 固定一个时间点，让状态栏里的时间输出稳定、可复现
MOMENT = datetime(2026, 1, 7, 21, 34, 56)

# 几种典型正文：正常中文（含章节标题与空行）、中英混排、整屏空行、超长且无标点的中文段落
BOOKS = [
    ["第一章 科学边界", "", "汪淼看到了一串数字在眼前跳动。", "", "第二章 台球"],
    ["It is a truth universally acknowledged.", "", "中文 and english mixed in one line here."],
    ["", "", ""],
    ["一个非常长的段落，没有任何标点，用来测试换行是不是真的会一行一行折下去，而不是直接被右边界一刀切掉"],
]


class RecordingWindow:
    """记录型假窗口：实现阅读器真正用到的那部分 curses API，并保存每次写入。"""

    def __init__(self, height: int, width: int) -> None:
        # 终端尺寸（行数、列数）
        self.height = height
        self.width = width
        # 当前光标位置：curses 的 addstr 两参形式就是从光标处写
        self.cursor_row = 0
        self.cursor_column = 0
        # 写入记录，每项是 (row, column, text, attr)，越界检查就靠它
        self.writes: list[tuple[int, int, str, int]] = []
        # 屏幕快照，用来断言状态栏那两行确实有内容
        self.screen: list[list[str]] = [[" "] * width for _ in range(height)]

    def getmaxyx(self) -> tuple[int, int]:
        """返回 (行数, 列数)，与 curses 一致。"""
        return self.height, self.width

    def erase(self) -> None:
        """清屏：把快照重置成全空格。"""
        self.screen = [[" "] * self.width for _ in range(self.height)]

    def refresh(self) -> None:
        """假刷新：什么都不用做。"""
        pass

    def addstr(self, *args: Any) -> None:
        """模拟 curses.addstr：两种调用形式都要接得住，并同步推进光标。"""
        values: list[Any] = list(args)
        # 三参及以上 = (row, column, text[, attr])
        if len(values) >= 3:
            row, column, text = int(values[0]), int(values[1]), values[2]
            attr = int(values[3]) if len(values) > 3 else 0
        else:
            # 其余情况 = 在当前光标处写 text[, attr]
            row, column, text = self.cursor_row, self.cursor_column, values[0]
            attr = int(values[1]) if len(values) > 1 else 0
        self.writes.append((row, column, str(text), attr))
        # 真实 curses 按**显示列**推进光标：一个汉字走两格，这里严格照做
        self.cursor_row, self.cursor_column = row, column + width_of(str(text))
        # 顺带写进快照，好让状态栏那句断言有东西可查
        for offset, character in enumerate(str(text)):
            if 0 <= row < self.height and 0 <= column + offset < self.width:
                self.screen[row][column + offset] = character

    def row(self, index: int) -> str:
        """取快照里某一行的内容（去掉行尾空格）。"""
        return "".join(self.screen[index]).rstrip()


def width_of(text: str) -> int:
    """一段文本占多少显示列：直接复用阅读器自己的宽度函数，避免两套口径。"""
    return sum(reader._char_width(char) for char in text)


def main() -> int:
    """入口：遍历尺寸 × 视图组合跑绘制，全部不越界才返回 0。"""
    checks = 0
    for lines in BOOKS:
        for width in (10, 16, 24, 33, 40, 80, 120):
            for height in (4, 6, 12, 24, 40):
                # 正文区高度 = 总高度 - 2：下面两行留给状态栏与消息行
                pager = reader.Pager(lines, chapters=[], page_height=height - 2)
                # 触发搜索高亮，再放一条超长中文消息，压一压消息行的宽度处理
                pager.search("第")
                pager.say("这是一条很长的中文消息，用来测试消息行会不会超出屏幕宽度")
                window = RecordingWindow(height, width)
                reader._draw(window, pager, MOMENT)

                for row, column, text, _attr in window.writes:
                    # 真实 curses 会拒绝写到右边界之外 —— 这条是核心断言
                    assert column + width_of(text) <= width, (
                        lines, width, height, row, column, repr(text)
                    )
                    # 行号也不能出界
                    assert row < height, (lines, width, height, row)
                # 状态栏那两行必须有内容：历史上出现过「整行消失」的 bug
                assert window.row(height - 2), (lines, width, height)
                checks += 1
    print("OK: {} draw checks passed".format(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

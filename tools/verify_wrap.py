# -*- coding: utf-8 -*-
"""随机化的属性检查：确认 reader._wrap_line 折行时不会破坏终端上的三个前提。

检查的不变量：
  1. 折出来的每一行显示宽度都不超过给定宽度（宽度 1 时允许放一个全角字符，故下界是 2）；
  2. 不丢字符（只允许丢空格 —— 断行处的空格本来就会消失）；
  3. 原文非空时，不会折出空行。

用法（在仓库任意目录都能跑）：python tools/verify_wrap.py
退出码：0 = 全部通过，1 = 有反例（异常里带着反例文本与宽度，方便复现）。
"""
import random
import sys
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent
# 把仓库根加进模块搜索路径：这样从任何目录运行、甚至没装 pip install -e 也能 import wreader
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wreader import reader  # noqa: E402  （必须在 sys.path 设好之后再导入）

# 随机取样用的字符池：英文大小写 + 数字 + 常见半角标点 + 两个空格（让空格的占比更高）
# 再加上常用汉字与全角标点，专门压一压「汉字占 2 列」这条路径
ALPHABET = (
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789,.;:'-!?"
    "  "
    "汪淼数字在眼前跳动他抬头望向窗外的夜空秩序缓展开倒计时"
    "，。！？：；“”（）《》"
)


def check(text: str, width: int) -> None:
    """对一段文本 + 一个宽度跑三条不变量：任何一条被破坏就抛 AssertionError。"""
    lines = reader._wrap_line(text, width)
    # 不变量 1：每行显示宽度不超宽
    for line in lines:
        size = sum(reader._char_width(char) for char in line)
        assert size <= max(width, 2), (repr(text), width, repr(line), size)
    # 不变量 2：忽略空格后必须一字不少（断行只会吃掉空格）
    joined = "".join(lines).replace(" ", "")
    original = text.replace(" ", "")
    assert joined == original, (repr(text), width, repr(lines))
    # 不变量 3：原文非空时不允许折出空行
    if original:
        assert all(line for line in lines), (repr(text), width, repr(lines))


def main() -> int:
    """入口：跑随机用例 + 手工边界用例，全通过返回 0。"""
    # 固定随机种子：每次跑出来的用例完全一样，出问题能原地复现
    random.seed(20260107)
    cases = 0
    # 4000 段随机文本 × 一组由窄到宽的常用宽度
    for _ in range(4000):
        length = random.randint(1, 60)
        text = "".join(random.choice(ALPHABET) for _ in range(length))
        for width in (1, 2, 3, 5, 8, 13, 21, 34, 55, 89):
            check(text, width)
            cases += 1
    # 再补一批手写形状：空串、纯空格、单个全角字、前后空格、中英混排、带标点的英文单词
    for text in (
        "",
        " ",
        "   ",
        "a",
        "中",
        "a b",
        "a  b",
        "  leading and trailing  ",
        "中文中文中文",
        "mixed 中文 and english words here",
        "acknowledged,",
    ):
        for width in (1, 2, 3, 4, 5, 10, 39):
            check(text, width)
            cases += 1
    print("OK: {} checks passed".format(cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

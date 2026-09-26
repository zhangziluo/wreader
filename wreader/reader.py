"""Reader core: a curses paged reading experience.

``werd read <book_id>`` pages through the UTF-8 text that :mod:`wreader.library`
produced at import time.  The pager works in **source lines**: the stored file is
split on ``\\n`` exactly the way the importer split it, so
``progress["current_line"]``, ``progress["bookmarks"][].line`` and every
``chapters[].line_start`` are indexes into the same list.  One source line may
occupy more than one screen row (a long paragraph wraps), so pagination is measured
in **screen rows**: the next screen starts at the first row that did not fit, kept
as a ``(source line, offset)`` pair.  ``line_offset`` is the offset inside that line,
and it is display state only -- never written to disk, so
``progress["current_line"]`` stays a plain line index.

Keys
----
``j``/``k``/space and the arrow keys page the text, ``g`` jumps to a line,
``[``/``]`` hop between chapters, ``Tab`` opens the table of contents overlay (see
:mod:`wreader.toc`) and jumps to the chapter picked there, ``/`` searches and ``n``
walks to the next hit, ``b`` toggles a bookmark, ``?`` shows the key map and
``q``/``Q``/Ctrl-C leaves and saves the position.

``a`` switches on **automatic page turns** for hands-free reading: from then on the
pager walks ``reader.auto_scroll_step`` screen rows (default 1) every
``reader.auto_scroll_interval`` seconds (default 5), and ``>`` / ``<`` double or halve
the pace.  Any key press pushes the next turn back by one interval, so typing never
fights the timer, and the mode switches itself off at the end of the book.

Settings
--------
The ``[reader]`` and ``[stats]`` tables of ``~/.wreader/settings.toml`` drive the
front end (see :mod:`wreader.config`): ``page_scroll_step`` sets how much the page
keys move (``1`` = one screen) and ``page_overlap`` how many lines of the previous
screen stay visible after a page turn, ``auto_scroll_step`` / ``auto_scroll_interval``
set how far and how often the automatic page turns go,
``status_bar_format`` picks the status
segments, ``auto_save_interval`` writes the position while reading and
``store_history`` (``[reader]``) decides whether the session lands in the stats.

Everything outside the curses front end is a plain function over plain data, so
the paging, chapter and streak maths are testable without a terminal.
"""

# 延迟求值类型注解
from __future__ import annotations

# 全屏终端界面（Unix 自带，Windows 需额外包）
import curses
# 读会话现场（JSON）与写会话现场
import json
# 设置 locale，让 curses 正确显示中文宽字符
import locale
# 写会话现场时记下进程号，方便排查谁留下的
import os
# 判断 stdin/stdout 是不是真实终端
import sys
# 计时（monotonic 不受系统时间调整影响）
import time
# 查字符的东亚宽度，判断它是占 1 列还是 2 列（自动换行要用）
import unicodedata
# 日期用于连续阅读天数；datetime 用于会话起止；timedelta 做天数偏移
from datetime import date, datetime, timedelta
# 正文文件路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# 退出阅读器之后用 rich 打印一行摘要
from rich.console import Console

# 同包引用：配置、环境探测、地理、书库、统计成就、成就事件、目录
from . import (
    achievements,
    config,
    env,
    geo,
    library,
    stats,
    toc,
)

# 模块公开的名字（Pager 与几个纯函数，方便单测）
__all__ = [
    "DEFAULT_AUTO_SCROLL_INTERVAL",
    "DEFAULT_AUTO_SCROLL_STEP",
    "DEFAULT_PAGE_OVERLAP",
    "DEFAULT_STATUS_FORMAT",
    "NOTICE_SECONDS",
    "Pager",
    "SESSION_MARKER_FILENAME",
    "STATUS_TOKENS",
    "clear_marker",
    "format_status_bar",
    "help_lines",
    "marker_path",
    "open_reader",
    "read_lines",
    "read_marker",
    "reading_streak",
    "save_position",
    "save_session",
    "status_segment",
    "write_marker",
]

# 状态栏占 2 行（一行信息、一行提示/消息）
_STATUS_ROWS = 2
# 主循环的刷新间隔（毫秒），同时决定 get_wch 的等待上限
_TICK_MS = 1000
# 书签在行首显示的符号
_BOOKMARK_MARK = "★"

# 滚轮事件在终端里就是「button4 / button5 按下」（xterm 的约定）：滚轮上 = button4，滚轮下 = button5。
#
# ⚠️ 实测记录（2026-09-22，在真 pty 里灌 SGR 鼠标序列得到，详见 memory-bank/activeContext.md ⑫）：
#   - 灌 button4（滚轮上）→ curses 报 bstate=0x80000 = BUTTON4_PRESSED ✅
#   - 灌 button5（滚轮下）→ curses 只报 0x8000000（位置报告），**这套 Python/curses 根本没有
#     BUTTON5 这个概念**（`dir(curses)` 里没有任何 BUTTON5_*，mousemask 也报不出该位）。
#   所以这里**不做位移猜测**：拿得到 BUTTON5_PRESSED 就用（Termux / Linux 的 ncurses 有），
#   拿不到就是 0 —— 该平台上滚轮下不生效，而不是拿别的位去凑（那样会把 BUTTON_SHIFT 误判成滚轮）。
#   `bstate & 0` 恒为 0，所以下面的判断天然安全，不需要额外分支。
_WHEEL_UP = int(getattr(curses, "BUTTON4_PRESSED", 0))
_WHEEL_DOWN = int(getattr(curses, "BUTTON5_PRESSED", 0))

# 「按住拖动」时可能被报告为按下的按钮位；触摸屏通常是 button1
_DRAG_PRESSED = (
    int(getattr(curses, "BUTTON1_PRESSED", 0))
    | int(getattr(curses, "BUTTON2_PRESSED", 0))
    | int(getattr(curses, "BUTTON3_PRESSED", 0))
)
# 纯位置报告位：有些终端拖到一半就不再报按键位，只发这个；此时只要还在拖动就继续算位移
_MOUSE_MOTION = int(getattr(curses, "REPORT_MOUSE_POSITION", 0))

# 状态栏支持的片段名，在配置里用 | 连接；不认识的会被跳过而不是原样打印
#: The segments ``reader.status_bar_format`` understands, joined by ``|`` in the
#: format string.  An unknown segment is skipped rather than printed raw.
STATUS_TOKENS: Tuple[str, ...] = (
    "time",
    "book",
    "chapter",
    "position",
    "percent",
    "duration",
    "elapsed",
    "streak",
    "bookmarks",
)

# 默认状态栏：时间 | 章节 | 本章时长
#: The status bar the settings file documents: clock, chapter, chapter time.
DEFAULT_STATUS_FORMAT = "time|chapter|duration"

# 翻页时默认保留的上下文行数（与 config.SCHEMA 里 reader.page_overlap 的默认值一致）
#: Lines of the previous screen kept on a page turn (``reader.page_overlap``).
DEFAULT_PAGE_OVERLAP = 3

# -- 自动翻页（免手翻）-------------------------------------------------------
# 每两次自动前进之间的默认间隔（秒），对应 reader.auto_scroll_interval
#: Seconds between two automatic page turns (``reader.auto_scroll_interval``).
DEFAULT_AUTO_SCROLL_INTERVAL = 5.0
# 每次自动前进几行**屏幕行**，对应 reader.auto_scroll_step
#: Screen rows one automatic page turn moves (``reader.auto_scroll_step``).
DEFAULT_AUTO_SCROLL_STEP = 1
# 速度可调范围（秒）：比 0.5 秒还快人的眼睛跟不上，比 10 分钟还慢不如自己按 j
#: Slowest and fastest automatic pace, in seconds between two turns.
AUTO_SCROLL_MIN_INTERVAL = 0.5
AUTO_SCROLL_MAX_INTERVAL = 600.0
# 调速键每按一次，间隔乘 / 除这个倍数（间隔变小 = 翻得更快）
_AUTO_SPEED_FACTOR = 2.0
# 自动翻页开着时 get_wch 最少等多少毫秒：到点就能翻，又不至于空转烧 CPU
_AUTO_MIN_POLL_MS = 50
# 开关自动翻页的键，以及加速 / 减速键（都挑的空闲键，不与任何已有键位冲突）
_AUTO_TOGGLE_KEYS = ("a",)
_AUTO_FASTER_KEYS = (">", "+", "=")
_AUTO_SLOWER_KEYS = ("<", "-", "_")
# 自动翻页开着时，底部提示栏改显示这一行（{} 处填"每 N 秒 M 行（K 行/分钟）"）
_AUTO_HINT = "自动翻页中 · {} · a 暂停 > 加速 < 减速"

# 两个输入提示的前缀
_SEARCH_PROMPT = "搜索: "

# 底部常驻的快捷键提示
_HINT = "q退出 j/space翻页 a自动 g跳行 [/]章节 Tab目录 /搜索 n下一个 b书签 ?帮助"

# 目录浮层占屏幕宽度的比例（靠右显示），其余留给正文
_TOC_WIDTH_RATIO = 0.4
# 目录浮层底部的快捷键提示
_TOC_HINT = "↑↓ 选择  Enter 跳转  / 过滤  q/Esc 关闭"

# Tab 键：get_wch 多数情况返回 "\t"，个别终端上报 KEY_TAB
_TAB_KEYS = ("\t", int(getattr(curses, "KEY_TAB", 9)))
# -- 成就的屏内通知 ---------------------------------------------------------
# 解锁成就时在屏幕右上角闪的那块提示停留多久（秒）——规格要求 5 秒
#: Seconds the in-screen achievement notice stays on top of the text.
NOTICE_SECONDS = 5.0
# 通知框里最多列几个成就名（再多就只报个数，别把正文全盖住）
_NOTICE_MAX_ITEMS = 3
# 通知框左边留一列空隙，右边也留一列（最后一列 curses 写不了）
_NOTICE_PADDING = 2
# 通知框的标题与脚注
_NOTICE_TITLE = "🏆 成就解锁"
_NOTICE_FOOTER = "任意键继续读 · 5 秒后自动消失"

# -- 意外中断恢复 -----------------------------------------------------------
# 阅读会话的"在场证明"：进入阅读器时写、正常退出时删。下次开书时它还在，
# 说明上一次不是正常退出的（崩溃 / 断电 / kill），于是可以问一句要不要接着读。
#: Marker file proving a reading session is still in progress.
SESSION_MARKER_FILENAME = "reading_session.json"
# 恢复提示的按钮说明（_confirm 的 hint）
_RECOVER_HINT = "[y] 接着上次读    其他键 从头开始"
# 恢复提示里最多显示几行正文预览
_RECOVER_PREVIEW_LINES = 2

# -- 帮助页 -----------------------------------------------------------------
# 帮助页底部的操作提示
_HELP_FOOTER = "↑↓/j/k 滚动  q/Esc/Enter 关闭"
# 帮助页的正文：一行一条，`?` 打开的浮层按原样画（太宽会被裁）
_HELP_LINES: Tuple[str, ...] = (
    "werd 阅读器 · 快捷键一览",
    "",
    "【翻页】",
    "  j / 空格 / 回车 / ↓ / PgDn   下一页",
    "  k / ↑ / PgUp                 上一页",
    "  滚轮 / 触摸拖动               逐行滚动（手机上就是靠它）",
    "  a                            自动翻页开关（按行数自己往下走）",
    "  > / <                        自动翻页加速 / 减速",
    "  g                            跳到指定行（输入行号）",
    "  G                            跳到全书末尾",
    "",
    "【本章】",
    "  [ / ]                        上一章 / 下一章",
    "  Tab                          目录浮层（/ 过滤，回车跳转）",
    "",
    "【查找与书签】",
    "  /关键词                      搜索，n 跳到下一个命中",
    "  b                            加 / 删书签（行首的 ★）",
    "",
    "【其它】",
    "  ?                            本帮助页",
    "  q / Q / Ctrl-C               退出并保存进度",
    "  意外中断后再打开              会问要不要接着上次的位置读",
    "",
    "设置文件 ~/.wreader/settings.toml：werd config reader.page_height 40",
    "自动翻页速度：werd config reader.auto_scroll_interval 3（每 3 秒一行）",
)

# -- 成就的实时记账（Phase 2）-----------------------------------------------
# "连续翻页"认这些键：往下翻的、往上翻的、以及方向键都算一次翻页
# （KEY_* 一定存在，不像 KEY_TAB 那样要 getattr 兜底）
_PAGE_KEYS = (
    "j",
    "k",
    " ",
    "\n",
    "\r",
    curses.KEY_DOWN,
    curses.KEY_UP,
    curses.KEY_NPAGE,
    curses.KEY_PPAGE,
)
# "方向键"只认这四个：PageUp/PageDown 是独立按键，不算怀旧路线
_ARROW_KEYS = (curses.KEY_UP, curses.KEY_DOWN, curses.KEY_LEFT, curses.KEY_RIGHT)
# 会打断"只用方向键读这一章"的键：别的翻页方式与跳转（上面那四个方向键不在其中）
_ARROW_BREAKERS = (
    "j",
    "k",
    " ",
    "\n",
    "\r",
    "g",
    "G",
    "[",
    "]",
    "n",
    curses.KEY_NPAGE,
    curses.KEY_PPAGE,
    "\t",
)
# 一章里至少按了几下方向键才算"用方向键读完"（否则在章界上戳一下 ↓ 就能解锁）
_ARROW_CHAPTER_MIN_KEYS = 5

# 退出 curses 后用于打印摘要的 rich 控制台
console = Console()


def _now() -> datetime:
    """Return the current local time."""
    # 当前本地时间；单独包一层方便测试替换
    return datetime.now()


def _iso(moment: datetime) -> str:
    """Format *moment* the way the index stores timestamps."""
    # 与索引里的时间戳格式保持一致（精确到秒）
    return moment.isoformat(timespec="seconds")


def read_lines(file_path: str) -> List[str]:
    """Return the book text as lines, split exactly like the importer did."""
    # 导入时写入的 UTF-8 正文
    path = Path(str(file_path))
    # 文件不在了：抛出书库异常，由 CLI 统一提示
    if not path.is_file():
        raise library.LibraryError("book text is missing: {}".format(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise library.LibraryError("cannot read {}: {}".format(path, exc)) from exc
    # 必须与 library 里同样的方式规范化换行，行号才能对得上
    text = library.normalise_newlines(text)
    # 按 \n 切行；空文件返回空列表
    return text.split("\n") if text else []


def clamp(position: int, total: int) -> int:
    """Keep *position* inside ``[0, total - 1]``."""
    # 没有行时统一返回 0
    if total <= 0:
        return 0
    # 把位置夹进合法范围
    return max(0, min(int(position), total - 1))


def chapter_index_at(chapters: Sequence[Dict[str, Any]], position: int) -> int:
    """Index of the chapter holding *position*, or ``-1`` when there is none."""
    # -1 表示"不在任何章节里"（书没有章节信息时）
    index = -1
    # 章节按起始行升序排列，找到最后一个起始行 <= position 的就是当前章
    for order, chapter in enumerate(chapters):
        if int(chapter.get("line_start") or 0) <= position:
            index = order
        else:
            # 已经越过 position：不必再往后看
            break
    return index


def chapter_start(chapters: Sequence[Dict[str, Any]], index: int) -> int:
    """Start line of chapter *index*, or ``0`` when it is out of range."""
    # 下标越界就回到全书开头
    if index < 0 or index >= len(chapters):
        return 0
    return int(chapters[index].get("line_start") or 0)


def next_chapter_position(
    chapters: Sequence[Dict[str, Any]], position: int, total: int
) -> int:
    """Start line of the first chapter after *position*."""
    # 找第一个起始行大于当前位置的章节
    for chapter in chapters:
        start = int(chapter.get("line_start") or 0)
        if start > position:
            return clamp(start, total)
    # 后面没有章节了：跳到全书最后一行
    return clamp(total - 1, total)


def previous_chapter_position(
    chapters: Sequence[Dict[str, Any]], position: int, total: int
) -> int:
    """Start line of the chapter before the one holding *position*."""
    # 先确认当前在第几章
    index = chapter_index_at(chapters, position)
    # 已经在第一章（或没有章节信息）：回到全书开头
    if index <= 0:
        return 0
    # 跳到上一章的开头
    return clamp(chapter_start(chapters, index - 1), total)


def chapter_bounds(
    chapters: Sequence[Dict[str, Any]], position: int, total: int
) -> Tuple[int, int]:
    """Return the inclusive ``(first, last)`` source lines of the current chapter.

    A book without chapters is treated as a single chapter.
    """
    # 空书
    if total <= 0:
        return 0, 0
    index = chapter_index_at(chapters, position)
    # 没有任何章节信息：整本书当一章
    if index < 0:
        return 0, total - 1
    # 本章从哪开始
    start = clamp(chapter_start(chapters, index), total)
    # 本章到哪结束 = 下一章起始行 - 1；最后一章到全书末尾
    if index + 1 < len(chapters):
        following = clamp(int(chapters[index + 1].get("line_start") or 0), total)
        last = max(start, following - 1)
    else:
        last = total - 1
    return start, last


def reading_streak(day_strings: Iterable[str], today: Optional[date] = None) -> int:
    """Count consecutive reading days up to *today*.

    Today always counts: the session running right now is written to
    ``daily_read_time`` when it ends, so the figure shows what it is about to
    become.
    """
    today = today or date.today()
    # 把读过的日期收成集合，查起来 O(1)
    known = {str(day) for day in day_strings}
    # 今天一定算（本次会话结束时就会写进统计）
    known.add(today.isoformat())
    streak = 0
    cursor = today
    # 从今天往前连数
    while cursor.isoformat() in known:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def format_duration(seconds: float) -> str:
    """Render a duration as ``MM:SS``, or ``H:MM:SS`` past an hour."""
    # 负数兜成 0 并取整
    total = max(0, int(seconds))
    # 拆成小时 + 余秒，再把余秒拆成分钟 + 秒
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    # 超过一小时显示 H:MM:SS
    if hours:
        return "{}:{:02d}:{:02d}".format(hours, minutes, secs)
    # 否则显示 MM:SS
    return "{:02d}:{:02d}".format(minutes, secs)


def _format_seconds(seconds: float) -> str:
    """Render a number of seconds without trailing zeros: ``5``, ``2.5``, ``0.625``."""
    # 先按 3 位小数格式化，再剪掉尾部的 0 与小数点
    text = "{:.3f}".format(max(0.0, float(seconds)))
    trimmed = text.rstrip("0").rstrip(".")
    # 全零（或空串）兜成 "0"
    return trimmed or "0"


def _clamp_auto_interval(seconds: float) -> float:
    """Keep an automatic page-turn interval inside the usable range.

    The clamp is what stops a stuck ``>`` key from turning the pager into a strobe,
    and a stuck ``<`` from making a turn so rare that the mode looks broken.
    """
    # 上下界都取自模块常量，改范围只改一处
    return max(AUTO_SCROLL_MIN_INTERVAL, min(AUTO_SCROLL_MAX_INTERVAL, float(seconds)))


def find_matches(lines: Sequence[str], needle: str) -> List[int]:
    """Return the indexes of every line containing *needle*, case insensitive."""
    wanted = str(needle or "")
    # 空关键词不匹配任何行
    if not wanted:
        return []
    lowered = wanted.lower()
    # 简单子串匹配（大小写不敏感）
    return [index for index, line in enumerate(lines) if lowered in line.lower()]


# 一本书的阅读状态机：位置、搜索、书签、计时
class Pager:
    """Position, search state, bookmarks and stopwatches for one book."""

    def __init__(
        # 正文按 \n 切好的全部行
        self,
        lines: Sequence[str],
        # 章节表（title + line_start）
        chapters: Sequence[Dict[str, Any]] = (),
        # 从第几行开始读
        position: int = 0,
        # 没有终端尺寸时的回退每屏行数（真实终端里由 _draw 填入正文区行数）
        page_height: int = 24,
        book_id: str = "",
        title: str = "untitled",
        author: str = "unknown",
        # 已有书签
        bookmarks: Sequence[Dict[str, Any]] = (),
        # 连续阅读天数（状态栏显示用）
        streak: int = 0,
        # 翻页键一次走几屏
        page_scroll_step: float = 1.0,
        # 翻页时上下各保留几行上下文（0 = 关闭重叠）
        page_overlap: int = DEFAULT_PAGE_OVERLAP,
        # 滚轮/触摸一格滚几行
        wheel_scroll_step: int = 1,
        # 触摸拖动即滚动（手机终端）
        touch_scroll: bool = True,
        # 状态栏片段格式
        status_bar_format: str = DEFAULT_STATUS_FORMAT,
        # 自动保存间隔（秒），0 = 关闭
        auto_save_interval: int = 60,
        # 目录条目（章节表 + 百分比），供 Tab 浮层使用
        toc_entries: Sequence[Dict[str, Any]] = (),
        # 自动翻页：每几秒自动前进一次（``reader.auto_scroll_interval``）
        auto_scroll_interval: float = DEFAULT_AUTO_SCROLL_INTERVAL,
        # 自动翻页：每次自动前进几行屏幕行（``reader.auto_scroll_step``）
        auto_scroll_step: int = DEFAULT_AUTO_SCROLL_STEP,
    ) -> None:
        # 拷贝成列表，避免外部改动影响内部状态
        self.lines = list(lines)
        self.chapters = list(chapters)
        # 每屏至少 1 行
        self.page_height = max(1, int(page_height))
        self.book_id = book_id
        self.title = title
        self.author = author
        self.streak = int(streak)
        # -- runtime behaviour copied out of settings.toml -------------------
        #: how many pages the page keys move (``reader.page_scroll_step``)
        # 翻页步长（屏数），不能为负
        self.page_scroll_step = max(0.0, float(page_scroll_step))
        #: lines kept from the previous screen on a page turn (``reader.page_overlap``)
        # 翻页时上下保留的上下文行数，不能为负（0 = 不重叠）
        self.page_overlap = max(0, int(page_overlap))
        #: rows of the text area, refreshed by the curses layer on every frame
        # 正文区屏幕行数：_draw 每帧按真实终端填进来；没有终端时退回 page_height
        self.viewport_rows = self.page_height
        #: columns of the text area, ``None`` while no terminal size is known
        # 正文区列数：没有终端尺寸时为 None，此时按"一行 = 一屏行"处理
        self.viewport_width: Optional[int] = None
        #: how many wrapped rows of ``position`` are scrolled off the top already
        # 段内偏移：当前位置这一行顶部已经翻过去几条折行屏幕行（0 = 从这行开头显示）。
        # 它只是**显示用**状态、不落库 —— 落库的 current_line 永远是源行号。
        self.line_offset = 0
        #: lines one wheel tick moves (``reader.wheel_scroll_step``)
        # 滚轮/触摸一格滚几行，至少 1 行（否则滚了等于没滚）
        self.wheel_scroll_step = max(1, int(wheel_scroll_step))
        #: drag the finger to scroll the text (``reader.touch_scroll``)
        # 触摸拖动即滚动
        self.touch_scroll = bool(touch_scroll)
        #: the segments of the first status row (``reader.status_bar_format``)
        # 状态栏格式串（空值退回默认）
        self.status_bar_format = str(status_bar_format or DEFAULT_STATUS_FORMAT)
        #: seconds between position saves, 0 disables (``reader.auto_save_interval``)
        # 自动保存间隔，0 表示关闭
        self.auto_save_interval = max(0, int(auto_save_interval))
        # -- 自动翻页（a 键开关，免手翻）-----------------------------------
        #: seconds between two automatic page turns (``reader.auto_scroll_interval``)
        # 两次自动前进之间的间隔（秒），夹进可读范围后使用
        self.auto_scroll_interval = _clamp_auto_interval(auto_scroll_interval)
        #: screen rows one automatic turn moves (``reader.auto_scroll_step``)
        # 每次自动前进几行屏幕行，至少 1（否则自动模式等于空转）
        self.auto_scroll_step = max(1, int(auto_scroll_step))
        #: whether the text walks forward by itself right now (``a`` toggles it)
        # 自动翻页现在开着吗；会话开始时一律是关的（不落库、不跨会话记忆）
        self.auto_scroll = False
        #: monotonic time of the next automatic turn, ``0.0`` = not scheduled
        # 下一次自动前进的时刻（单调时钟）；0.0 = 没排期
        self.auto_scroll_deadline = 0.0
        #: the table of contents: ``[{"title", "line", "percentage"}, ...]``
        # 目录条目（由 toc.load_toc 备好），Tab 浮层直接读它
        self.toc = [dict(entry) for entry in toc_entries]
        # 起始位置夹到合法范围
        self.position = clamp(position, self.total)
        #: forward lines scrolled this session: the reading work actually done
        # 本次会话向前读了多少行（只统计前进，回退不抵消）
        self.lines_read = 0
        #: half open ``(start, end)`` line ranges walked through this session
        # 本次会话读过的行区间：退出时交给成就引擎，按区间去重统计字数
        self.read_ranges: List[Tuple[int, int]] = []
        # 书签拷贝一份（深拷贝每个字典）
        self.bookmarks = [dict(mark) for mark in bookmarks]
        # 搜索命中的行号列表
        self.matches: List[int] = []
        # 当前看到第几个命中，-1 表示还没开始
        self.match_cursor = -1
        # 每章累计耗时（秒）
        self.chapter_seconds: Dict[int, float] = {}
        # -- achievements: the reader's half of the bookkeeping (Phase 2) -----
        #: metrics as they stood when the book was opened (``{}`` = engine unreadable)
        # 开书那一刻的指标快照：判断"刚刚越过门槛了吗"要以它为基线
        self.baseline: Dict[str, int] = {}
        #: ``{metric: (required, ...)}`` parsed out of the achievement definitions
        # 成就定义里的门槛表（指标 -> 需要达到的数）；空表 = 本次会话不做实时判定
        self.thresholds: Dict[str, Tuple[int, ...]] = {}
        #: ``(metric, threshold)`` pairs already reported this session
        # 本次会话已经报过的门槛：同一条线不重复触发（也就不会重复写状态文件）
        self.fired: List[Tuple[str, int]] = []
        #: session counters reported to the engine as *deltas*
        # 本次会话累计的增量指标（方向键读完的章数、窄屏读完的章数、窄屏秒数）
        # 类型是 float：窄屏秒数要按小数累积，报给引擎时才截断成整数
        self.key_counters: Dict[str, float] = {
            name: 0.0 for name in achievements.COUNTER_METRICS
        }
        #: what those counters were at the last report (never cleared on its own)
        # 上次汇报时的取值：只有真的发出去了才推进，没撞门槛的增量不会丢
        self.reported: Dict[str, int] = {name: 0 for name in achievements.COUNTER_METRICS}
        #: session peaks reported to the engine as *maxima*
        # 本次会话的峰值指标（最长的空格连击、最长的一次连续翻页）
        self.key_maxima: Dict[str, int] = {name: 0 for name in achievements.MAX_METRICS}
        #: the runs currently being counted (a different key resets them)
        # 正在累积的两个连击长度（换了别的键就断）
        self.space_run = 0
        self.page_run = 0
        #: one chapter's "purity" for 方向键怀旧 / 窄屏挑战
        # 本章是否一个非方向键的翻页键都没用过、以及按了几个方向键
        self.arrow_only = True
        self.arrow_keys = 0
        #: when the terminal got narrower than ``achievements.NARROW_COLUMNS``
        # 终端进入"极限窄"（≤40 列）的时刻；None = 现在不窄（秒表停着）
        self.narrow_started: Optional[float] = None
        #: the terminal's real column count (``note_width``), 0 = not measured yet
        # 终端的真实列数（与 viewport_width 不同：那个是正文区宽度，已经扣掉书签列）
        self.terminal_width = 0
        #: marker left by an interrupted session, when it belongs to this book
        # 上一次"没正常退出"留下的现场（同一本书才有值，见 _offer_recovery）
        self.resume_marker: Dict[str, Any] = {}
        #: the in-screen notice (achievement unlocks while reading) and its deadline
        # 屏内通知的正文与过期时刻：解锁成就时在右上角亮 5 秒，不挡任何按键
        self.notice = ""
        self.notice_until = 0.0
        # 临时消息及其过期时刻
        self.message = ""
        self.message_until = 0.0
        # 上一刻所在的章节下标（-1 表示还没同步过）
        self._chapter_index = -1
        # 进入当前章节、以及进入本次会话的时刻
        self._chapter_entered = time.monotonic()
        self._session_entered = self._chapter_entered
        # 初始化时同步一次章节计时
        self._sync_chapter()

    @property
    def page_budget(self) -> int:
        """Screen rows one page key moves: ``page_scroll_step`` screens minus the overlap.

        The budget is counted in **screen rows**, not source lines, so a page turn
        lines up with what the terminal actually shows even when long paragraphs
        wrap onto several rows.  Never zero, so a page key always makes progress.
        """
        # 一屏的屏幕行数 × 屏数 = 整步长
        full_page = int(round(self.page_scroll_step * self.viewport_rows))
        # 再减掉重叠行：翻页后屏幕上下各留着前几行，读起来才连得上
        step = full_page - self.page_overlap
        # 至少 1 行：重叠比整屏还大时兜底，保证按键一定有反应
        return max(1, step)

    @property
    def total(self) -> int:
        """Number of lines in the book."""
        # 全书行数
        return len(self.lines)

    @property
    def percentage(self) -> float:
        """Reading position as a percentage; the last line counts as 100%."""
        # 复用 library 里的百分比算法（最后一行正好 100%）
        return library.position_percentage(self.position, self.total)

    @property
    def chapter_title(self) -> str:
        """Title of the chapter we are inside, or an empty string."""
        index = self.current_chapter()
        # 不在任何章节里
        if index < 0:
            return ""
        return str(self.chapters[index].get("title") or "")

    def current_chapter(self) -> int:
        """Index of the chapter holding the cursor, or ``-1``."""
        # 由当前位置反查章节下标
        return chapter_index_at(self.chapters, self.position)

    def chapter_bounds_here(self) -> Tuple[int, int]:
        """Inclusive ``(first, last)`` lines of the chapter we are inside."""
        # 当前章节的行号区间
        return chapter_bounds(self.chapters, self.position, self.total)

    def _row_texts(self, index: int, width: Optional[int]) -> List[str]:
        """Every screen row one source line owns, from its top downwards.

        One source line is one piece of text; a long paragraph is wrapped by
        :func:`_wrap_line`, which knows a CJK character is two columns wide.
        """
        # 一个源行就是一段显示文本
        text = self.lines[index]
        # 没有宽度信息（纯数据场景）：一段文本就是一屏行
        if width is None:
            return [text]
        # 有宽度：按显示宽度折行后返回
        return _wrap_line(text, int(width))

    def visible_rows(
        self, height: int, width: Optional[int] = None, offset: Optional[int] = None
    ) -> List[Tuple[int, str]]:
        """Return ``(source_line, text)`` for the rows that fit into *height*.

        With a *width* the text of one source line is wrapped into as many screen
        rows as it needs, so a long paragraph is never cut off at the right edge.
        Without it the text is handed over unwrapped (one source line per screen
        row) -- the historical behaviour, still handy for plain assertions.

        Drawing starts *offset* screen rows into ``self.position``, so a screen that
        was cut in the middle of a wrapped paragraph continues exactly there rather
        than jumping to the next source line.
        """
        # 最多能画多少行
        room = max(1, int(height))
        # 不指定就跟着当前段内偏移走
        start_offset = self.line_offset if offset is None else int(offset)
        # 从 (当前位置, 段内偏移) 往下灌，直到填满屏幕或读到结尾
        rows, _line, _offset = self._walk_forward(
            self.position, start_offset, room, width
        )
        # 兜底：偏移失效（比如窗口变宽、折行变少）导致一条都取不出来时，
        # 退回这行开头重来，宁可重复一点也绝不交白屏
        if not rows and start_offset:
            rows, _line, _offset = self._walk_forward(self.position, 0, room, width)
        return rows

    def _screen_rows(self, index: int, width: Optional[int]) -> int:
        """How many screen rows one source line takes in the current view.

        Wrapping is delegated to :func:`_wrap_line`, so double width CJK characters
        and latin word wrapping are counted exactly the way the screen draws them.
        """
        # 直接数这一行摊平后有几千屏幕行
        return len(self._row_texts(index, width))

    def _walk_forward(
        self, start: int, offset: int, budget: int, width: Optional[int]
    ) -> Tuple[List[Tuple[int, str]], int, int]:
        """Collect screen rows from ``(start, offset)``, at most *budget* of them.

        Returns ``(rows, line, offset)``: *rows* is what fits, and ``(line,
        offset)`` is the **first screen row that did not fit** -- precisely the
        coordinate the next screen has to start from.  Keeping that coordinate
        (rather than rounding up to the next source line) is what stops the tail of
        a wrapped paragraph from being skipped.
        """
        # 攒出来的屏幕行
        rows: List[Tuple[int, str]] = []
        index = clamp(start, self.total)
        # 还能再取几条屏幕行
        remaining = max(0, int(budget))
        # 起始行里还要跳过几条折行屏幕行
        skip = max(0, int(offset))
        # 一行一行往下取，直到取满预算或读到结尾
        while index < self.total and remaining > 0:
            chunks = self._row_texts(index, width)
            # 偏移越界（窗口变宽后折行条数会变少）：夹到最后一条，别让整行凭空消失
            if chunks:
                skip = min(skip, len(chunks) - 1)
            # 这一行从第 skip 条开始取
            position = skip
            skip = 0
            # 逐条屏幕行塞进结果
            while position < len(chunks) and remaining > 0:
                rows.append((index, chunks[position]))
                position += 1
                remaining -= 1
            # 预算刚好用完、而这一行还有剩：下一屏的屏顶就落在这条上
            if remaining == 0 and position < len(chunks):
                return rows, index, position
            index += 1
        # 取到预算用完或书末：下一屏从下一行的开头开始
        return rows, min(index, self.total), 0

    def next_top(
        self, screen_rows: int, width: Optional[int] = None
    ) -> Tuple[int, int]:
        """The ``(line, offset)`` that tops the screen *screen_rows* rows ahead.

        Advancing by **screen rows** instead of source lines is what stops a page
        turn from skipping text; also returning the intra-line offset is what stops
        it from skipping the tail of a paragraph the screen edge cut in half.
        """
        # 从当前屏顶往后走一屏，落点就是下一屏的屏顶
        rows, line, offset = self._walk_forward(
            self.position, self.line_offset, max(1, int(screen_rows)), width
        )
        # 一条都走不出来（已经在书末）：至少往下挪一行，保证按键有反应
        if not rows:
            return min(self.position + 1, self.total), 0
        return line, offset

    def previous_top(
        self, screen_rows: int, width: Optional[int] = None
    ) -> Tuple[int, int]:
        """The ``(line, offset)`` a screen of *screen_rows* rows would top going back.

        The mirror image of :meth:`next_top`: hand back the rows already scrolled
        past inside the current line first, then walk whole source lines upwards,
        and land on the coordinate that then tops the screen.
        """
        # 还要往上退多少屏幕行
        remaining = max(1, int(screen_rows))
        index = self.position
        # 先把当前行里已经翻过去的那几条退回来（段内偏移只在这里发生）
        if self.line_offset:
            if remaining <= self.line_offset:
                return index, self.line_offset - remaining
            remaining -= self.line_offset
        # 再一行一行往上退，直到凑满一屏或到达书首
        while index > 0 and remaining > 0:
            index -= 1
            chunks = self._screen_rows(index, width)
            # 这一行还不够退：整行退掉继续往上
            if remaining >= chunks:
                remaining -= chunks
                continue
            # 退到这一行中间：剩下的几条（从 chunks-remaining 起）就是新屏顶
            return index, chunks - remaining
        return max(0, index), 0

    # -- movement --------------------------------------------------------
    def move_to(self, position: int, offset: int = 0) -> None:
        """Jump to *position*, *offset* screen rows into that line (default: its top).

        The intra-line offset only matters to the paging code, where it lets a screen
        resume halfway down a wrapped paragraph.  Every other jump (goto, search,
        chapter, start/end) starts at the top of a line, so it keeps the default.
        """
        # 先把目标位置夹进合法范围
        target = clamp(position, self.total)
        # 只统计"向前"的位移，往回翻不抵消阅读量
        if target > self.position:
            self.lines_read += target - self.position
            # 记下这一趟读过的区间 [起点, 终点)：中间翻页、跳转、滚轮都经过这里
            self.read_ranges.append((self.position, target))
        self.position = target
        # 段内偏移不能为负；大到超出这一行的折行条数时由渲染侧夹住
        self.line_offset = max(0, int(offset))
        # 位置变了，章节计时可能需要滚动到下一章
        self._sync_chapter()

    def scroll(self, delta: int) -> None:
        """Move by *delta* **screen rows** (wrapping aware, so nothing is skipped).

        The wheel and the touch drag feed this, which is why one tick is one visible
        row: on a book full of long paragraphs a source line can be a whole screen
        tall, and stepping by source lines would fly past the text.
        """
        # 没要动就直接返回，免得白算一趟
        if not delta:
            return
        # 往后滚：用"下一屏"的算法；往前滚：用"上一屏"的算法
        if delta > 0:
            self.move_to(*self.next_top(int(delta), self.viewport_width))
        else:
            self.move_to(*self.previous_top(int(-delta), self.viewport_width))

    def next_page(self) -> None:
        """Advance one page, counted in screen rows so nothing is skipped."""
        # 按屏幕行推进：折行后的长段连"半截"也不会被跳过去
        self.move_to(*self.next_top(self.page_budget, self.viewport_width))

    def previous_page(self) -> None:
        """Go back one page, counted in screen rows like :meth:`next_page`."""
        # 往回也按屏幕行，和前进对称
        self.move_to(*self.previous_top(self.page_budget, self.viewport_width))

    # -- automatic page turns (hands free reading) -----------------------
    def set_auto_scroll(self, enabled: bool, now: Optional[float] = None) -> bool:
        """Turn the automatic page turns on or off; return the new state.

        Switching it on schedules the first turn one interval ahead, so the page is
        never yanked away at the very moment the mode is turned on.
        """
        # 先记住开关状态
        self.auto_scroll = bool(enabled)
        # 开着就排下一次；关掉时把时刻清零，免得下次打开立刻翻一屏
        self.auto_scroll_deadline = (
            self._auto_now(now) + self.auto_scroll_interval if self.auto_scroll else 0.0
        )
        return self.auto_scroll

    def toggle_auto_scroll(self, now: Optional[float] = None) -> bool:
        """Flip the automatic page turns; ``True`` when they are now on."""
        # 取反后交给 set_auto_scroll，排期逻辑只留一处
        return self.set_auto_scroll(not self.auto_scroll, now)

    def defer_auto_scroll(self, now: Optional[float] = None) -> None:
        """Push the next automatic turn back by one full interval.

        Every key press calls this: someone who is typing is reading at their own
        pace, and the timer must not steal the page from under them a moment later.
        """
        # 没开自动翻页就没什么可推的
        if not self.auto_scroll:
            return
        # 从"现在"重新排期（间隔可能刚被调速改过，所以每次都现读）
        self.auto_scroll_deadline = self._auto_now(now) + self.auto_scroll_interval

    def auto_scroll_wait(self, now: Optional[float] = None) -> Optional[float]:
        """Seconds until the next automatic turn; ``None`` when the mode is off."""
        # 关着的时候不存在"下一次"
        if not self.auto_scroll:
            return None
        # 已经过点的返回 0，调用方不用处理负数
        return max(0.0, self.auto_scroll_deadline - self._auto_now(now))

    def auto_scroll_tick(self, now: Optional[float] = None) -> bool:
        """Turn the page when the interval has elapsed; ``True`` when it did.

        It advances by :attr:`auto_scroll_step` **screen rows** -- the same unit the
        page keys use, so a paragraph too long for one screen is walked row by row
        instead of being skipped.  At the end of the book the mode switches itself
        off and says so: a hands-free mode that silently does nothing is worse than
        no mode at all.
        """
        # 没开自动翻页：这一轮什么都不做
        if not self.auto_scroll:
            return False
        moment = self._auto_now(now)
        # 还没到点：留给下一轮
        if moment < self.auto_scroll_deadline:
            return False
        # 到点了：先只算落点（不改位置），才好判断是不是已经到头了
        line, offset = self.next_top(self.auto_scroll_step, self.viewport_width)
        target = clamp(line, self.total)
        off = max(0, int(offset))
        # 落点与"现在"完全一样 → 屏幕已经停在书末，再翻也不动了
        if target == self.position and off == self.line_offset:
            self.set_auto_scroll(False, moment)
            self.say("已经读到全书末尾，自动翻页已停")
            return False
        # 真的往后挪一屏，并按新的时刻排下一次
        self.move_to(line, offset)
        self.set_auto_scroll(True, moment)
        return True

    def auto_scroll_pace(self) -> str:
        """Describe the automatic pace, e.g. ``每 5 秒 1 行（12 行/分钟）``."""
        # 每分钟走几行：把"速度"换算成一个更直观的数字
        per_minute = self.auto_scroll_step * 60.0 / self.auto_scroll_interval
        return "每 {} 秒 {} 行（{} 行/分钟）".format(
            _format_seconds(self.auto_scroll_interval),
            self.auto_scroll_step,
            _format_seconds(round(per_minute, 1)),
        )

    def adjust_auto_scroll_speed(self, factor: float) -> float:
        """Multiply the interval by *factor*; return the new interval (seconds).

        A **smaller** interval means faster turns, so the "faster" key passes a factor
        below one.  The value is clamped (:func:`_clamp_auto_interval`) and the next
        turn is rescheduled, so changing the speed is never followed instantly by a
        turn that was already due.
        """
        # 乘完再夹进范围；非正因子按 0.01 兜底，免得把间隔乘成 0
        self.auto_scroll_interval = _clamp_auto_interval(
            self.auto_scroll_interval * max(0.01, float(factor))
        )
        # 速度变了：从现在重新排期
        self.defer_auto_scroll()
        return self.auto_scroll_interval

    def _auto_now(self, now: Optional[float]) -> float:
        """The monotonic clock, unless the caller injected a fixed *now*."""
        # 注入时间是为了单测能精确驱动"到点了没有"
        return time.monotonic() if now is None else float(now)

    def to_start(self) -> None:
        """Jump to the first line."""
        self.move_to(0)

    def to_end(self) -> None:
        """Jump to the last line."""
        self.move_to(self.total - 1)

    def next_chapter(self) -> None:
        """Jump to the start of the next chapter."""
        # 由纯函数算出下一章的起始行
        self.move_to(next_chapter_position(self.chapters, self.position, self.total))

    def previous_chapter(self) -> None:
        """Jump to the start of the previous chapter."""
        self.move_to(
            previous_chapter_position(self.chapters, self.position, self.total)
        )

    def chapter_top(self) -> None:
        """Jump to the start of the chapter we are inside."""
        self.move_to(chapter_start(self.chapters, self.current_chapter()))

    # -- search ----------------------------------------------------------
    def search(self, needle: str) -> int:
        """Highlight every hit and jump to the first one at or after the cursor."""
        # 先算出所有命中的行号
        self.matches = find_matches(self.lines, needle)
        self.match_cursor = -1
        # 没有命中：直接返回 0
        if not self.matches:
            return 0
        # 默认跳到"当前位置之后的第一个命中"
        for order, index in enumerate(self.matches):
            if index >= self.position:
                self.match_cursor = order
                break
        # 后面没有命中了（比如已经在书末）：回到第一个命中
        if self.match_cursor < 0:
            self.match_cursor = 0
        self.move_to(self.matches[self.match_cursor])
        # 返回命中总数，给提示语用
        return len(self.matches)

    def next_match(self) -> bool:
        """Jump to the next hit; ``False`` when there is nothing to jump to."""
        # 还没搜过
        if not self.matches:
            return False
        # 循环前进（到最后一条后回到第一条）
        self.match_cursor = (self.match_cursor + 1) % len(self.matches)
        self.move_to(self.matches[self.match_cursor])
        return True

    @property
    def current_match(self) -> int:
        """Source line of the hit being visited, or ``-1``."""
        # 没有搜索结果，或游标无效
        if not self.matches or self.match_cursor < 0:
            return -1
        # 游标越界（比如搜索被清空过）
        if self.match_cursor >= len(self.matches):
            return -1
        return self.matches[self.match_cursor]

    def clear_search(self) -> None:
        """Forget the current search."""
        self.matches = []
        self.match_cursor = -1

    # -- bookmarks -------------------------------------------------------
    def is_bookmarked(self, index: int) -> bool:
        """Whether *index* carries a bookmark."""
        # 书签里的行号与 index 相同就说明标了
        return any(int(mark.get("line") or 0) == index for mark in self.bookmarks)

    def toggle_bookmark(self, index: Optional[int] = None) -> bool:
        """Add or remove the bookmark on *index*; ``True`` when one was added."""
        # 不传就用光标所在行
        line = self.position if index is None else int(index)
        # 已经有书签就删掉
        for order, mark in enumerate(self.bookmarks):
            if int(mark.get("line") or 0) == line:
                del self.bookmarks[order]
                return False
        # 没有就新增一条（带创建时间）
        self.bookmarks.append({"line": line, "label": "", "created": _iso(_now())})
        # 按行号排序，保证书签列表有序
        self.bookmarks.sort(key=lambda mark: int(mark.get("line") or 0))
        return True

    # -- translation -----------------------------------------------------
    def _sync_chapter(self) -> None:
        """Roll the per-chapter stopwatch over when the chapter changes."""
        # 现在在第几章
        index = self.current_chapter()
        # 用单调时钟，避免系统改时间导致负数
        now = time.monotonic()
        # 还在同一章：什么都不用做
        if index == self._chapter_index:
            return
        # 之前确实在某一章里：把它这次待的时长累加进 chapter_seconds
        if self._chapter_index >= 0:
            spent = now - self._chapter_entered
            self.chapter_seconds[self._chapter_index] = (
                self.chapter_seconds.get(self._chapter_index, 0.0) + spent
            )
            # 换章 = 上一章读完了：方向键怀旧 / 窄屏挑战在这里结算
            self.note_chapter_change()
        # 切到新章节，重新开始计时
        self._chapter_index = index
        self._chapter_entered = now

    def sync(self) -> None:
        """Called by the main loop before every repaint."""
        # 每次重绘前都检查一下有没有换章
        self._sync_chapter()

    def chapter_elapsed(self) -> float:
        """Seconds spent in the current chapter during this session."""
        # 已经结算过的累计时长
        spent = self.chapter_seconds.get(self._chapter_index, 0.0)
        # 如果还待在同一章，要把"正在进行的这一段"也算上
        if self.current_chapter() == self._chapter_index:
            spent += time.monotonic() - self._chapter_entered
        return spent

    def session_elapsed(self) -> float:
        """Seconds since this reading session started."""
        # 本次会话总时长
        return time.monotonic() - self._session_entered

    def say(self, text: str, seconds: float = 5.0) -> None:
        """Show *text* on the message row for a while."""
        self.message = str(text)
        # 记下过期时刻（默认显示 5 秒）
        self.message_until = time.monotonic() + seconds

    def current_message(self) -> str:
        """The message to show right now, or an empty string."""
        # 没过期就显示
        if self.message and time.monotonic() < self.message_until:
            return self.message
        # 过期了：返回空串，界面会退回显示快捷键提示
        return ""

    # -- achievements: what the reader counts while you read ---------------
    def note_key(self, key: Any) -> None:
        """Count one key press for the 操作彩蛋 achievements.

        Two different runs, both straight from the wording of the specification:

        * ``space_combo`` counts **consecutive spaces** -- any other key breaks it,
        * ``page_streak`` counts **consecutive page turns** -- opening a search box,
          jumping to a line or leaving the page keys breaks it.

        Arrow keys additionally feed ``arrow_keys`` (and leave ``arrow_only`` alone),
        which is what 方向键怀旧 needs: a whole chapter read without j/k/space/enter.
        """
        # 空格连击：是空格就 +1，其它任何键都清零
        self.space_run = self.space_run + 1 if key == " " else 0
        # 连续翻页：翻页键都算一次，别的键清零
        self.page_run = self.page_run + 1 if key in _PAGE_KEYS else 0
        # 峰值只往大里记（会话中间断了也不回退，这才是"最长的一次"）
        self.key_maxima["space_combo"] = max(self.key_maxima["space_combo"], self.space_run)
        self.key_maxima["page_streak"] = max(self.key_maxima["page_streak"], self.page_run)
        # 方向键：数一下，并且不打断"这一章只用方向键"
        if key in _ARROW_KEYS:
            self.arrow_keys += 1
            return
        # 别的翻页/跳转键：本章不再是"纯方向键"路线
        if key in _ARROW_BREAKERS:
            self.arrow_only = False

    def note_chapter_change(self) -> None:
        """Settle the chapter we just left: 方向键怀旧 and 窄屏挑战 both land here.

        A chapter counts as read with arrow keys only when at least
        ``_ARROW_CHAPTER_MIN_KEYS`` arrow presses happened inside it -- otherwise
        tapping ↓ once across a chapter boundary would be enough.  It counts as a
        narrow-screen read when the terminal was at most
        ``achievements.NARROW_CHAPTER_COLUMNS`` columns wide.  Either way the per
        chapter bookkeeping restarts for the new chapter.
        """
        # 方向键怀旧：本章一个别的翻页键都没按过，而且真的翻了几下
        if self.arrow_only and self.arrow_keys >= _ARROW_CHAPTER_MIN_KEYS:
            self.key_counters["arrow_chapters"] += 1
        # 窄屏挑战：这一章是在窄窗口里读完的（宽度未知时不算）
        width = self.terminal_width
        if 0 < width <= achievements.NARROW_CHAPTER_COLUMNS:
            self.key_counters["narrow_chapters"] += 1
        # 新的一章重新记账
        self.arrow_only = True
        self.arrow_keys = 0

    def note_width(self, width: int, now: Optional[float] = None) -> None:
        """Account the time spent at terminal *width* (the 极限尺寸 stopwatch).

        Only a window no wider than :data:`achievements.NARROW_COLUMNS` runs the clock,
        and the time is booked when the width *changes* -- never per frame, so a slow
        laptop does not spend its battery timing nothing.
        """
        # 单调时钟：系统改时间也不会让秒数变成负数
        moment = time.monotonic() if now is None else float(now)
        # 先结算上一段：还窄就继续计时，不窄就停表
        self._close_narrow(moment, keep_going=width <= achievements.NARROW_COLUMNS)
        # 刚进入窄窗口：从这里开始计时
        if width <= achievements.NARROW_COLUMNS and self.narrow_started is None:
            self.narrow_started = moment
        # 记住终端的真实列数：窄屏挑战与事件载荷都读它
        self.terminal_width = max(1, int(width))

    def close_width_window(self, now: Optional[float] = None) -> None:
        """Stop the narrow-window stopwatch and book what it measured (on exit)."""
        # 会话结束：把最后这一段窄屏时间也算进去
        self._close_narrow(time.monotonic() if now is None else float(now), keep_going=False)

    def _close_narrow(self, moment: float, keep_going: bool) -> None:
        """Book the seconds the narrow window has been open, then restart or stop it."""
        # 秒表没走：没什么可结算的
        if self.narrow_started is None:
            return
        spent = max(0.0, float(moment) - self.narrow_started)
        self.key_counters["narrow_seconds"] += spent
        # 还窄就从现在接着走，不窄就停表
        self.narrow_started = moment if keep_going else None

    def pending_deltas(self) -> Dict[str, int]:
        """Return the counters that grew since the last report, as whole numbers.

        Nothing is cleared here on purpose: a delta is only marked as reported once
        the engine has actually been told about it (:meth:`commit_report`), so a
        session that never crosses a threshold still hands its counters over at the
        end (``session_end``) instead of losing them.
        """
        deltas: Dict[str, int] = {}
        for name in achievements.COUNTER_METRICS:
            # 浮点累积（窄屏秒数）在这里截断成整数
            grown = int(self.key_counters.get(name, 0)) - int(self.reported.get(name, 0))
            if grown > 0:
                deltas[name] = grown
        return deltas

    def commit_report(self, deltas: Dict[str, int]) -> None:
        """Remember that *deltas* have been handed to the engine."""
        # 逐项推进"已汇报"水位（引擎那边是累加，重复发会多算）
        for name, step in deltas.items():
            self.reported[name] = int(self.reported.get(name, 0)) + int(step)

    def current_maxima(self) -> Dict[str, int]:
        """Return the session peaks, which the engine folds in with ``max``."""
        # 峰值可以重复上报（引擎取 max），所以不需要"已汇报"水位
        return {
            name: int(self.key_maxima.get(name, 0)) for name in achievements.MAX_METRICS
        }

    def metric_values(self) -> Dict[str, int]:
        """What each tracked metric is believed to be right now.

        Baseline (read once when the book was opened) plus this session's own counting.
        The reader deliberately does not re-read the state file mid-session: the engine
        owns the real numbers, and the deltas it receives in the event payload are
        exactly the ones counted here.
        """
        values: Dict[str, int] = {}
        # 增量类：基线 + 本次会话累计
        for name in achievements.COUNTER_METRICS:
            values[name] = int(self.baseline.get(name, 0)) + int(
                self.key_counters.get(name, 0)
            )
        # 峰值类：基线与会话峰值取大的那个
        for name in achievements.MAX_METRICS:
            values[name] = max(
                int(self.baseline.get(name, 0)), int(self.key_maxima.get(name, 0))
            )
        return values

    def announce(self, text: str, seconds: float = NOTICE_SECONDS) -> None:
        """Show *text* in the corner of the screen for a few seconds.

        Deliberately **not** a modal popup: the notice lives in the frame (``_draw``
        paints it while it lasts), so nothing blocks the reading loop and no key press
        is swallowed -- unlike the translation popup, which waits for a key.
        """
        self.notice = str(text)
        self.notice_until = time.monotonic() + max(0.0, float(seconds))

    def current_notice(self) -> str:
        """The in-screen notice to paint right now, or ``""`` once it expired."""
        # 没过期就显示；过期了返回空串，界面照常画正文
        if self.notice and time.monotonic() < self.notice_until:
            return self.notice
        return ""


def _addstr(window: Any, row: int, column: int, text: str, attr: int = 0) -> None:
    """Write *text* clipped to the window, so curses never overflows the row."""
    # 空文本不画
    if not text:
        return
    try:
        # 拿窗口尺寸，越界判断要用
        height, width = window.getmaxyx()
    except curses.error:
        # 窗口已经失效（比如正在 resize）
        return
    # 行或列越界就放弃（curses 在这种情况下会报错）
    if row < 0 or row >= height or column >= width:
        return
    # 右边只剩这么多列可用：先按显示宽度剪掉放不下的部分
    text = _clip_line(text, width - column)
    # 剪完一个字都放不下（终端太窄）：不画
    if not text:
        return
    try:
        # 实际写字符；text 超出右边界时 curses 会抛错
        window.addstr(row, column, text, attr)
    except curses.error:
        # 写到右下角最后一个字符是 curses 的著名限制，静默忽略
        pass


def _char_width(character: str) -> int:
    """How many terminal columns one character takes: two for CJK, else one."""
    # 东亚的 Wide / Fullwidth 字符（汉字、全角标点）在终端里占两列
    if unicodedata.east_asian_width(character) in ("W", "F"):
        return 2
    # 其余的（ASCII、半角符号）占一列
    return 1


def _text_width(text: str) -> int:
    """How many terminal columns *text* takes.

    ``len()`` counts characters, which is wrong the moment Chinese shows up: one
    Han character is twice as wide as an ASCII letter.  Every width decision in
    the reader goes through here instead.
    """
    # 逐字符累加各占的列数
    return sum(_char_width(character) for character in text)


def _clip_line(text: str, room: int) -> str:
    """Cut *text* down to *room* terminal columns, never splitting a character.

    Used as a last resort before handing a row to curses: writing past the right
    edge makes curses raise, and a swallowed error means the whole row silently
    disappears.  Clipping keeps as much as actually fits on screen instead.
    """
    # 没有可用列数：什么都放不下
    if room <= 0:
        return ""
    # 已经占掉的列数
    used = 0
    # 先假设整行都放得下
    cut = len(text)
    # 逐字符量宽度，第一个塞不下的字符就是切点
    for position, character in enumerate(text):
        width = _char_width(character)
        if used + width > room:
            cut = position
            break
        used += width
    # 按显示宽度切（不是按字符数切，否则中文还是会超出去）
    return text[:cut]


def _pad_line(text: str, room: int) -> str:
    """Clip *text* to *room* columns, then pad it back out to exactly *room*.

    The padding is not cosmetic: a row has to be filled edge to edge to wipe out
    whatever the previous frame left behind.
    """
    # 先剪到能放得下的部分
    clipped = _clip_line(text, room)
    # 已经占掉的列数
    used = _text_width(clipped)
    # 用空格补足到整行（空格占一列，所以直接乘数量）
    return clipped + " " * max(0, room - used)


def _wrap_line(text: str, width: int) -> List[str]:
    """Wrap *text* into rows that fit *width* terminal columns.

    Wrapping is done on the **display width** rather than the character count, so
    a Chinese line (two columns per character) breaks where the terminal would.
    Latin prose breaks at the last space of the row so words stay whole, a double
    width character is never split across two rows, tabs are expanded first,
    trailing spaces are dropped, and an empty line still yields one empty row so
    blank source lines keep their place on screen.
    """
    # 制表符先统一展开成 4 个空格，宽度计算才对得上
    text = str(text).replace("\t", "    ")
    # 宽度不合理或没有内容：原样返回（空串也返回一个空行）
    if width <= 0 or not text:
        return [text]
    # 折好的每一行
    lines: List[str] = []
    # 当前正在攒的这一行（逐字符存，方便回头找空格）
    current: List[str] = []
    # 当前这行已经占了多少列
    used = 0
    # 逐字符走，按显示宽度决定什么时候换行
    for character in text:
        # 这个字符占几列
        char_width = _char_width(character)
        # 再塞进去就超宽（且本行已有内容）：先换行
        if current and used + char_width > width:
            # 英文单词优先在空格处断开，别把单词劈成两半；
            # 汉字没有空格可断，也就找不到 space_at，直接按字断。
            # 溢出的本身是空格时不必回头找：行尾就是天然断点，别把刚排满
            # 那一行的最后一个单词白白推到下一行。
            space_at = -1
            if character != " " and char_width == 1:
                for position in range(len(current) - 1, -1, -1):
                    if current[position] == " ":
                        space_at = position
                        break
            # 空格在行中：空格前半段成一行，空格后面的残词挪到下一行
            if space_at > 0:
                lines.append("".join(current[:space_at]))
                current = current[space_at + 1 :]
            else:
                # 找不到可用空格（汉字，或整行就是一个超长单词）：只能硬断
                lines.append("".join(current))
                current = []
            # 换行后重新算这一行现有的宽度
            used = sum(_char_width(item) for item in current)
        # 换行后紧跟的空格丢掉，避免下一行以空格开头
        if character == " " and not current:
            continue
        # 把字符放进当前行
        current.append(character)
        used += char_width
    # 收尾：把最后一段也加进去；整串为空时至少给一个空行
    if current or not lines:
        lines.append("".join(current))
    # 折完统一去掉行尾空格：屏幕上本来也看不见，留着只会让断言变脏
    return [line.rstrip() for line in lines]


def _draw_text(stdscr: Any, row: int, column: int, text: str, attr: int) -> None:
    """Write one line of the text area with the given attribute."""
    # 一句话：交给 _addstr（它负责裁剪与吞掉 curses 的边界错误）
    _addstr(stdscr, row, column, text, attr)


def _message_row(pager: Pager, room: int, notice: str = "") -> str:
    """The bottom row: a transient message, else the key hints.

    *room* counts terminal columns, not characters, so the row is measured the
    same way the terminal draws it.  *notice* carries the achievement notice when the
    corner box does not fit on this terminal (see :func:`_draw`); it wins over the
    hints and the message because an unlock is the more interesting thing to know.
    """
    # 成就通知在窗口里画不下：这一行顶上（比快捷键提示重要）
    if notice:
        return _pad_line("🏆 " + notice, room)
    # 有临时消息就先显示它
    message = pager.current_message()
    if message:
        # 按显示宽度裁到整行再右填充（填充用来盖掉上一帧的残留）
        return _pad_line(message, room)
    # 自动翻页开着：提示栏改报当前速度（比快捷键提示更有用）
    if pager.auto_scroll:
        return _pad_line(_AUTO_HINT.format(pager.auto_scroll_pace()), room)
    # 否则显示常驻的快捷键提示
    return _pad_line(_HINT, room)


def status_segment(token: str, pager: Pager, moment: datetime) -> str:
    """Return one status bar segment, or ``""`` for an unknown token.

    The tokens are listed in :data:`STATUS_TOKENS`; ``reader.status_bar_format``
    joins the ones it wants with ``|``.
    """
    # 依次判断是哪个片段；不认识就返回空串（上层会跳过空片段）
    if token == "time":
        return moment.strftime("%H:%M")
    if token == "book":
        return pager.title
    if token == "chapter":
        return pager.chapter_title or "无章节"
    if token == "position":
        # 对外显示行号从 1 开始
        return "行 {}/{}".format(pager.position + 1, max(1, pager.total))
    if token == "percent":
        return "{:.1f}%".format(pager.percentage)
    if token == "duration":
        return "本章 {}".format(format_duration(pager.chapter_elapsed()))
    if token == "elapsed":
        return "本次 {}".format(format_duration(pager.session_elapsed()))
    if token == "streak":
        return "连续 {} 天".format(pager.streak)
    if token == "bookmarks":
        return "书签 {}".format(len(pager.bookmarks))
    return ""


def format_status_bar(
    pager: Pager, moment: datetime, width: Optional[int] = None
) -> str:
    """Compose the first status row from ``reader.status_bar_format``.

    Segments are joined with ``·`` and an unknown token is skipped.  With a
    *width*, whole trailing segments are dropped rather than cut in half; a
    format that yields nothing at all falls back to the clock.  The width is
    measured in terminal columns, so a Chinese chapter title is charged the two
    columns per character it actually occupies.
    """
    # 按 | 拆出片段名（去空白，忽略空段）
    tokens = [
        part.strip()
        for part in str(pager.status_bar_format or DEFAULT_STATUS_FORMAT).split("|")
    ]
    # 逐个渲染，丢掉渲染出空串的（未知片段）
    pieces = [
        piece
        for piece in (
            status_segment(token, pager, moment) for token in tokens if token
        )
        if piece
    ]
    # 一个都没渲染出来（配置全写错）：退回显示时钟
    if not pieces:
        pieces = [status_segment("time", pager, moment)]
    # 不限制宽度：全部拼接返回
    if width is None:
        return " · ".join(pieces)

    # 限制宽度：整段整段地保留，不把某一小段切一半
    room = max(0, int(width))
    kept: List[str] = []
    used = 0
    for piece in pieces:
        # 已有片段时还要算上分隔符 " · " 的 3 列（半角点号占一列）
        cost = _text_width(piece) + (3 if kept else 0)
        if kept and used + cost > room:
            break
        kept.append(piece)
        used += cost
    # 一段都放不下时至少显示第一段（再按显示宽度硬裁一次）
    return _clip_line(" · ".join(kept) if kept else pieces[0], room)


def _draw_status(
    stdscr: Any,
    pager: Pager,
    moment: datetime,
    height: int,
    width: int,
    notice: str = "",
) -> None:
    """Draw the two status rows: the configured segments, then messages."""
    # 留出最后一列，避免写到右下角触发 curses 报错
    room = max(0, width - 1)
    # 屏幕太小就不画状态栏
    if room <= 0 or height < _STATUS_ROWS:
        return
    # 倒数第二行：信息栏（反白显示）。按显示宽度补齐到整行，免得留下上一帧的残影
    status = _pad_line(format_status_bar(pager, moment, room), room)
    _addstr(stdscr, height - 2, 0, status, curses.A_REVERSE)
    # 最后一行：消息/快捷键提示（暗色）；成就通知放不下时由它顶上
    _addstr(stdscr, height - 1, 0, _message_row(pager, room, notice), curses.A_DIM)


def _draw(stdscr: Any, pager: Pager, moment: datetime) -> None:
    """Repaint the text area and the two status rows."""
    # 终端当前尺寸
    height, width = stdscr.getmaxyx()
    # 正文区行数 = 总行数 - 状态栏两行
    text_rows = max(1, height - _STATUS_ROWS)
    # 正文从第 1 列写起（第 0 列留给书签标记），所以可用宽度要减掉那一列
    text_width = max(1, width - 1)
    # 把真实视口告诉 Pager：翻页要按"屏幕行"算，长段折行才不会被整段跳过
    # （每帧都刷新，所以窗口大小变了下一帧就生效）
    pager.viewport_rows = text_rows
    pager.viewport_width = text_width
    # 清屏，接着重画整帧
    stdscr.erase()
    # 上一条屏幕行属于哪个源行，用来判断"这是不是某个源行的第一屏行"
    previous_index: Optional[int] = None
    # 这一帧真正要画出来的可见行
    rows = pager.visible_rows(text_rows, text_width)
    for screen_row, (index, text) in enumerate(rows):
        # 换行就算"某源行自己的第一屏行"
        line_start = index != previous_index
        # 若整屏是从某源行中间续显示的，那第一条只是半截，别把书签误标在段落中间
        if screen_row == 0 and pager.line_offset:
            line_start = False
        # 折行后一个源行可能占多条屏幕行，书签只画在它的第一屏行上
        marked = line_start and pager.is_bookmarked(index)
        # 第 0 列放书签标记（有就实心星，没有就留空占位）
        _addstr(
            stdscr,
            screen_row,
            0,
            _BOOKMARK_MARK if marked else " ",
            curses.A_BOLD if marked else curses.A_DIM,
        )
        # 正文的显示属性：当前命中反白，其它命中加粗，普通不加
        attr = curses.A_NORMAL
        if index == pager.current_match:
            attr = curses.A_REVERSE
        elif index in pager.matches:
            attr = curses.A_BOLD
        # 第 1 列开始写正文（文本已在 visible_rows 里按宽度折好、Tab 也展开过）
        _draw_text(stdscr, screen_row, 1, text, attr)
        # 记下这条屏幕行属于哪个源行，供下一轮判断
        previous_index = index
    # 最后画状态栏两行
    # 成就通知：能画就画在正文右上角；窗口太小就交给消息行（_message_row 顶上）
    notice = pager.current_notice()
    fits = bool(notice) and _notice_layout(notice, height, width) is not None
    _draw_status(stdscr, pager, moment, height, width, notice if not fits else "")
    if fits:
        _draw_notice(stdscr, pager, height, width)
    # 提交这一帧
    stdscr.refresh()


def _notice_layout(
    text: str, height: int, width: int
) -> Optional[Tuple[int, int, int, int]]:
    """Return ``(rows, cols, top, left)`` for the achievement notice, or ``None``.

    The box sits in the **top right corner**, three rows tall (title, names, footer) and
    only as wide as the longest of the three lines.  ``None`` means the terminal is too
    small to show it without covering everything -- the message row still gets the text
    as a fallback, see :func:`_achievement_tick`.
    """
    # 太小就别画了（给状态栏和正文留活路）
    if height < 6 or width < 24:
        return None
    widest = max(_text_width(_NOTICE_TITLE), _text_width(text), _text_width(_NOTICE_FOOTER))
    cols = min(widest + _NOTICE_PADDING, width - 1)
    # 窄到放不下一行字：交给消息行
    if cols < 14:
        return None
    # 顶端贴边，右侧留最后一列（curses 写不了右下角）
    return 3, cols, 0, max(0, width - cols - 1)


def _draw_notice(stdscr: Any, pager: Pager, height: int, width: int) -> None:
    """Paint the in-screen achievement notice while it lasts (top right corner)."""
    text = pager.current_notice()
    # 没有通知：什么都不画（屏幕上就只是正文）
    if not text:
        return
    layout = _notice_layout(text, height, width)
    # 放不下：不画，消息行会顶上
    if layout is None:
        return
    rows, cols, top, left = layout
    # 整块反白（连续三行，视觉上就是一块"牌子"）
    for row in range(rows):
        _addstr(stdscr, top + row, left, " " * cols, curses.A_REVERSE)
    # 第一行标题、第二行成就名、第三行脚注，都按显示宽度裁到块内
    body = max(1, cols - 1)
    _addstr(
        stdscr, top, left, _pad_line(_clip_line(_NOTICE_TITLE, body), cols), curses.A_BOLD
    )
    _addstr(
        stdscr, top + 1, left, _pad_line(_clip_line(" " + text, body), cols), curses.A_NORMAL
    )
    _addstr(
        stdscr,
        top + 2,
        left,
        _pad_line(_clip_line(_NOTICE_FOOTER, body), cols),
        curses.A_DIM,
    )


def _prompt(stdscr: Any, label: str, initial: str = "") -> Optional[str]:
    """Read a line on the bottom row; ``None`` when cancelled with Esc.

    ``get_wch`` is used rather than ``getch`` so that Chinese keywords can be
    typed into the search and goto prompts.
    """
    # 输入缓冲区（用列表方便增删）
    buffer = list(initial)
    try:
        # 显示光标，方便用户看到输入位置
        curses.curs_set(1)
    except curses.error:
        pass
    # 阻塞等待输入（-1 表示不超时）
    stdscr.timeout(-1)
    try:
        while True:
            height, width = stdscr.getmaxyx()
            room = max(1, width - 2)
            # 在最后一行回显 "提示语 + 已输入内容"
            _addstr(
                stdscr, height - 1, 0, (label + "".join(buffer))[:room], curses.A_REVERSE
            )
            stdscr.refresh()
            try:
                # get_wch 会返回字符（str）或特殊键码（int）
                key = stdscr.get_wch()
            except curses.error:
                # 极少数情况下的瞬时错误：重试
                continue
            except KeyboardInterrupt:
                # Ctrl-C：视为取消
                return None
            # 普通字符
            if isinstance(key, str):
                # 回车：提交
                if key in ("\n", "\r"):
                    return "".join(buffer)
                # Esc：取消
                if key == "\x1b":
                    return None
                # 退格（DEL / BS）
                if key in ("\x7f", "\b"):
                    if buffer:
                        buffer.pop()
                    continue
                # 可打印字符且没超长：追加
                if key.isprintable() and len(buffer) < room:
                    buffer.append(key)
                continue
            # 特殊键：不同终端上报的回车码不一样
            if key in (curses.KEY_ENTER, 10, 13):
                return "".join(buffer)
            # 特殊键：退格
            if key in (curses.KEY_BACKSPACE, 127, 8):
                if buffer:
                    buffer.pop()
    finally:
        # 无论怎么退出都要恢复光标与超时设置
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        # 恢复主循环需要的 1 秒轮询
        stdscr.timeout(_TICK_MS)


def _confirm(
    stdscr: Any,
    title: str,
    body: Sequence[str],
    hint: str = "[y] 确认    其他键 取消",
) -> bool:
    """Show a small centred popup and return whether the user said yes.

    *hint* is the last line of the box (what ``y`` and the other keys do), so the
    caller can spell out the exact wording of the question being asked.
    """
    height, width = stdscr.getmaxyx()
    # 弹窗内每行最多的显示列数
    limit = max(12, width - 6)
    # 标题 + 正文 + 空行 + 操作提示（按显示宽度裁：一个汉字占两列）
    lines = [_clip_line(line, limit) for line in [title] + list(body)]
    lines.append("")
    lines.append(hint)
    # 边框各占 1 行/列，所以内容区再加 2
    box_height = min(len(lines) + 2, height - 2)
    # 宽度按最宽那一行的显示列数算（用字符数算的话中文会被挤掉）
    box_width = min(max(_text_width(line) for line in lines) + 4, width - 2)
    # 屏幕太小放不下就当作"取消"
    if box_height < 3 or box_width < 8:
        return False
    # 居中计算
    top = max(0, (height - box_height) // 2)
    left = max(0, (width - box_width) // 2)
    try:
        # 新建一个独立窗口当弹窗
        window = curses.newwin(box_height, box_width, top, left)
        window.erase()
        # 画边框
        window.box()
        # 逐行写内容（跳过边框那一行，从 offset=1 开始）
        for offset, line in enumerate(lines[: box_height - 2], start=1):
            _addstr(window, offset, 2, line, curses.A_NORMAL)
        window.refresh()
        # 阻塞等待一个按键
        window.timeout(-1)
        try:
            key = window.getch()
        except KeyboardInterrupt:
            key = -1
    except curses.error:
        return False
    # 关掉弹窗
    del window
    try:
        # 弹窗盖住的内容需要主窗口重画
        stdscr.touchwin()
    except curses.error:
        pass
    # 只有按 y/Y 才算确认
    return key in (ord("y"), ord("Y"))


def _first_line(text: str) -> str:
    """Return the first non-blank line of *text* (used by the tiny-screen fallback)."""
    # 逐行找第一个有内容的
    for line in str(text or "").split("\n"):
        if line.strip():
            return line.strip()
    # 全是空白：返回空串
    return ""


def _goto(stdscr: Any, pager: Pager) -> None:
    """``g``: ask for a line number, as displayed and therefore 1 based.

    The prompt starts empty even though the status row already shows the current
    line, because typing the target line is the whole point and an empty buffer
    never has to be backspaced over first.
    """
    # 提示里带上总行数，方便用户知道范围
    answer = _prompt(stdscr, "跳到行号 (1-{}): ".format(pager.total))
    # Esc 或直接回车：什么都不做
    if answer is None or not answer.strip():
        return
    try:
        # 用户输入的是"从 1 开始显示"的行号
        wanted = int(answer.strip())
    except ValueError:
        pager.say("行号需要是数字，例如 120")
        return
    # 内部行号从 0 开始，所以减 1
    pager.move_to(wanted - 1)
    pager.say("已跳到第 {} / {} 行".format(pager.position + 1, pager.total))


def _search(stdscr: Any, pager: Pager) -> None:
    """``/``: ask for a keyword, highlight the hits and jump to the first one."""
    # 弹出底部输入框要关键词
    needle = _prompt(stdscr, _SEARCH_PROMPT)
    if needle is None or not needle.strip():
        return
    needle = needle.strip()
    # 搜索并跳到第一个命中
    count = pager.search(needle)
    if count:
        pager.say("命中 {} 行，按 n 跳到下一个".format(count))
    else:
        # 没命中就把搜索状态清干净，避免残留高亮
        pager.clear_search()
        pager.say("没有找到「{}」".format(needle))


def _toc_panel_width(width: int) -> int:
    """Return how many columns the table-of-contents panel takes."""
    # 目标：屏幕宽度的 40%
    panel = int(round(width * _TOC_WIDTH_RATIO))
    # 至少给正文留 8 列：窄终端上别让浮层把正文挤没
    return max(1, min(panel, max(1, width - 8)))


def _toc_window(count: int, cursor: int, rows: int) -> Tuple[int, int]:
    """Return the ``(first, last)`` entry indices the *rows* rows can show.

    The cursor stays inside the window and the window sticks to either end
    instead of scrolling past them.
    """
    # 没有条目、或一行都放不下：空窗口
    if count <= 0 or rows <= 0:
        return 0, 0
    # 一屏就装得下全部：全都显示
    if count <= rows:
        return 0, count
    # 尽量让光标落在窗口中段，滚到两端时窗口贴住边界
    first = min(max(0, cursor - rows // 2), count - rows)
    return first, first + rows


def _toc_move_cursor(count: int, cursor: int, key: Any) -> int:
    """Return the new cursor index for *key*, clamped to the entry list."""
    # 没有条目：光标恒为 0
    if count <= 0:
        return 0
    if key in (curses.KEY_UP, "k"):
        cursor -= 1
    elif key in (curses.KEY_DOWN, "j"):
        cursor += 1
    elif key == curses.KEY_PPAGE:
        cursor -= 10
    elif key == curses.KEY_NPAGE:
        cursor += 10
    elif key == curses.KEY_HOME:
        cursor = 0
    elif key == curses.KEY_END:
        cursor = count - 1
    # 夹进合法范围，光标永远指向真实条目
    return max(0, min(cursor, count - 1))


def _draw_toc_panel(
    stdscr: Any,
    pager: Pager,
    entries: Sequence[Dict[str, Any]],
    indices: Sequence[int],
    cursor: int,
    filter_text: str,
    typing: bool,
    height: int,
    width: int,
    panel: int,
) -> None:
    """Paint the chapter list into the right hand panel."""
    # 面板最左边的列号
    left = max(0, width - panel)
    # 最后一行留出最后一列：curses 写不了右下角那个格子
    last_room = max(1, panel - 1)
    # 标题行："当前第几 / 共几条"（过滤后是过滤结果数）
    heading = "目录  {}/{}".format(cursor + 1, len(indices)) if indices else "目录  0/0"
    _addstr(stdscr, 0, left, _pad_line(heading, panel), curses.A_REVERSE)
    # 条目列表能用的行数：扣掉标题行、过滤行、提示行
    list_rows = max(1, height - 3)
    first, last = _toc_window(len(indices), cursor, list_rows)
    # 正在读的那一章（用来加粗标记）
    current = pager.current_chapter()
    for offset, position in enumerate(range(first, last)):
        entry = entries[indices[position]]
        # 百分比右对齐 + 标题；按显示列数裁剪（汉字占 2 列）
        label = "{:>5.1f}%  {}".format(
            float(entry.get("percentage") or 0.0), str(entry.get("title") or "")
        )
        attr = curses.A_NORMAL
        # 光标所在行反白
        if position == cursor:
            attr = curses.A_REVERSE
        # 其它行里"当前章节"加粗，一眼看出读到哪
        elif indices[position] == current:
            attr = curses.A_BOLD
        _addstr(stdscr, 1 + offset, left, _pad_line(label, panel), attr)
    # 过滤行：输入态反白并带光标符号，普通态暗色
    prompt = "过滤: {}{}".format(filter_text, "_" if typing else "")
    _addstr(
        stdscr,
        height - 2,
        left,
        _pad_line(prompt, panel),
        curses.A_REVERSE if typing else curses.A_DIM,
    )
    # 最后一行是快捷键提示（用 last_room 留出右下角那一格）
    _addstr(stdscr, height - 1, left, _pad_line(_TOC_HINT, last_room), curses.A_DIM)


def _draw_toc(
    stdscr: Any,
    pager: Pager,
    entries: Sequence[Dict[str, Any]],
    indices: Sequence[int],
    cursor: int,
    filter_text: str,
    typing: bool,
) -> None:
    """Repaint one frame: text dimmed on the left, chapter list on the right."""
    # 终端尺寸
    height, width = stdscr.getmaxyx()
    # 正文区行数（扣掉两行状态栏）
    text_rows = max(1, height - _STATUS_ROWS)
    # 右侧目录面板宽度
    panel = _toc_panel_width(width)
    # 左侧正文可用宽度（第 0 列是书签位，所以再减 1）
    text_width = max(1, width - panel - 1)
    # 清屏后先重画左侧正文
    stdscr.erase()
    for screen_row, (_, text) in enumerate(pager.visible_rows(text_rows, text_width)):
        # 内容不变，只是变暗（视觉上退到背景）
        _addstr(stdscr, screen_row, 1, _clip_line(text, text_width), curses.A_DIM)
    # 再画右侧目录面板
    _draw_toc_panel(
        stdscr, pager, entries, indices, cursor, filter_text, typing, height, width, panel
    )
    # 提交这一帧
    stdscr.refresh()


def _toc_overlay(stdscr: Any, pager: Pager) -> Optional[int]:
    """Show the table of contents; return the source line to jump to.

    A modal mini loop: the reading text stays visible (dimmed) on the left while
    the chapters are browsed on the right.  ``/`` turns the footer into a live
    filter box, ``Enter`` picks the highlighted chapter and ``q``/``Esc`` closes
    without moving.  ``None`` means "nothing was chosen".
    """
    entries = pager.toc
    # 没识别出章节：提示一句，别弹一个空面板
    if not entries:
        pager.say("这本书没有识别出章节，无法打开目录")
        return None
    # 打开时光标停在"正在读的那一章"上
    cursor = max(0, pager.current_chapter())
    filter_text = ""
    typing = False
    # 模态：阻塞等键；退出时在 finally 里恢复主循环的 1 秒轮询
    stdscr.timeout(-1)
    try:
        while True:
            indices = toc.filter_toc(entries, filter_text)
            # 过滤后光标可能越界：夹回来
            cursor = max(0, min(cursor, max(0, len(indices) - 1)))
            _draw_toc(stdscr, pager, entries, indices, cursor, filter_text, typing)
            try:
                # 等一个按键（模态，-1 表示一直等）
                key = stdscr.get_wch()
            except curses.error:
                # 少见的瞬时错误：重画再等
                continue
            except KeyboardInterrupt:
                # Ctrl-C：当作取消
                return None
            # ---- 过滤输入态：按键当文本编辑 ----
            if typing:
                if key in ("\n", "\r", curses.KEY_ENTER, 10, 13):
                    typing = False
                elif key == "\x1b":
                    # Esc：清空过滤内容并退出输入态
                    filter_text = ""
                    typing = False
                elif key in ("\x7f", "\b", curses.KEY_BACKSPACE, 127, 8):
                    filter_text = filter_text[:-1]
                elif isinstance(key, str) and key.isprintable():
                    filter_text += key
                continue
            # ---- 浏览态 ----
            if key in ("q", "Q", "\x1b"):
                return None
            if key == "/":
                # 进入过滤输入态（保留已有内容，方便接着改）
                typing = True
                continue
            if key in ("\n", "\r", curses.KEY_ENTER, 10, 13):
                # 确认跳转：返回该章起始行（没有可选项就当取消）
                if not indices:
                    return None
                return int(entries[indices[cursor]].get("line") or 0)
            # 其它键当作光标移动
            cursor = _toc_move_cursor(len(indices), cursor, key)
    finally:
        # 恢复主循环的轮询间隔，否则界面会卡在阻塞读上
        stdscr.timeout(_TICK_MS)


def _jump_via_toc(stdscr: Any, pager: Pager) -> None:
    """``Tab``: browse the table of contents and jump to the chapter picked."""
    # 浮层返回选中章节的起始行；取消（None）就什么都不做
    chosen = _toc_overlay(stdscr, pager)
    if chosen is None:
        return
    # 走和 g / 搜索 / 章节跳转同一套原语：回到该行行首并同步章节计时
    pager.move_to(chosen)
    # 提示跳到了哪一章（拿不到章节名就退化成行号）
    title = pager.chapter_title
    pager.say(
        "已跳到「{}」".format(title) if title else "已跳到第 {} 行".format(chosen + 1)
    )


def help_lines() -> List[str]:
    """Return the reader's help page as plain text lines.

    Kept as a function over a constant so the content can be asserted without a
    terminal (``?`` is the only way in for the user, but a test can read it directly).
    """
    # 拷贝一份，调用方改坏了也影响不到模块常量
    return list(_HELP_LINES)


def _help_layout(
    height: int, width: int, lines: Sequence[str]
) -> Optional[Tuple[int, int, int, int, int]]:
    """Return ``(rows, cols, top, left, visible)`` for the help box, or ``None``.

    The box is centred, never taller/wider than the screen, and keeps one row for the
    title and one for the footer.  ``None`` means the terminal is too small to hold a
    readable help page at all, and the caller says so instead of drawing a mess.
    """
    # 没有内容，或者窗口小到放不下标题 + 1 行内容 + 脚注
    if not lines or height < 6 or width < 20:
        return None
    # 最宽的一行决定盒子宽度（按显示列数算：汉字占 2 列）
    widest = max(_text_width(line) for line in lines)
    rows = min(len(lines) + 2, height - 2)
    cols = min(widest + 2, width - 1)
    # 太窄的盒子连一行都放不下：放弃
    if rows < 4 or cols < 12:
        return None
    visible = rows - 2
    # 居中（放不下时靠左上）
    top = max(0, (height - rows) // 2)
    left = max(0, (width - cols) // 2)
    return rows, cols, top, left, visible


def _draw_help(
    stdscr: Any, lines: Sequence[str], offset: int, height: int, width: int
) -> None:
    """Paint the help box with *offset* as its first visible line."""
    layout = _help_layout(height, width, lines)
    # 放不下就不画（调用方会先检查，这里再兜一次底）
    if layout is None:
        return
    rows, cols, top, left, visible = layout
    # 先用暗色空格把这块区域盖掉（下面的正文不再露出来）
    blank = " " * cols
    for row in range(rows):
        _addstr(stdscr, top + row, left, blank, curses.A_DIM)
    # 标题行反白
    _addstr(stdscr, top, left, _pad_line(" " + _HELP_LINES[0], cols), curses.A_REVERSE)
    # 内容逐行画（按显示宽度裁到盒子里）
    for step, line in enumerate(lines[offset : offset + visible]):
        _addstr(
            stdscr,
            top + 1 + step,
            left,
            _pad_line(_clip_line(line, cols), cols),
            curses.A_NORMAL,
        )
    # 脚注：还有内容没显示完就把剩余行数报出来
    rest = len(lines) - (offset + visible)
    hint = _HELP_FOOTER if rest <= 0 else "{}  还有 {} 行".format(_HELP_FOOTER, rest)
    _addstr(stdscr, top + rows - 1, left, _pad_line(_clip_line(hint, cols), cols), curses.A_DIM)
    stdscr.refresh()


def _help_overlay(stdscr: Any, pager: Pager) -> None:
    """``?``: the key map, in a scrollable box on top of the text.

    A modal mini loop in the same style as the table of contents overlay: block on
    keys, repaint every iteration (so a resize mid-help is picked up), and restore the
    1 second tick in ``finally``.  Opening it is also what the 帮助迷 achievement
    counts, and the report is best effort: a broken achievements file must never stop
    the help page from showing.
    """
    lines = help_lines()
    # 屏幕放不下就直接说一句，别弹一个空盒子
    height, width = stdscr.getmaxyx()
    if _help_layout(height, width, lines) is None:
        pager.say("屏幕太小，放不下帮助页")
        return
    offset = 0
    # 记一次"打开了帮助页"（帮助迷）：失败也不影响看帮助
    _fire_event(pager, "help")
    # 模态：阻塞等键；退出时在 finally 里恢复主循环的 1 秒轮询
    stdscr.timeout(-1)
    try:
        while True:
            # 每帧重读尺寸：用户可能一边看帮助一边把窗口拉大
            height, width = stdscr.getmaxyx()
            layout = _help_layout(height, width, lines)
            # 缩到放不下了：直接关掉（比画一团乱码强）
            if layout is None:
                return
            visible = layout[4]
            # 滚动位置夹进合法范围（窗口变小后原来的 offset 可能越界）
            offset = max(0, min(offset, max(0, len(lines) - visible)))
            _draw_help(stdscr, lines, offset, height, width)
            try:
                # 等一个按键（模态，-1 表示一直等）
                key = stdscr.get_wch()
            except curses.error:
                # 少见的瞬时错误：重画再等
                continue
            except KeyboardInterrupt:
                # Ctrl-C：当作关闭帮助
                return
            # 关闭键：q / Esc / 回车 / 再按一次 ?
            if key in ("q", "Q", "?", "\x1b", "\n", "\r", curses.KEY_ENTER, 10, 13):
                return
            # 往下滚
            if key in ("j", " ", curses.KEY_DOWN, curses.KEY_NPAGE):
                offset += 1
                continue
            # 往上滚
            if key in ("k", curses.KEY_UP, curses.KEY_PPAGE):
                offset -= 1
    finally:
        # 恢复主循环的轮询间隔，否则界面会卡在阻塞读上
        stdscr.timeout(_TICK_MS)

def _celebrate_achievements(
    newly: Sequence[Dict[str, Any]], ring: bool = True
) -> List[Dict[str, Any]]:
    """Print the post-curses fanfare for the achievements in *newly*.

    This runs after curses has handed the terminal back, so plain writes are
    enough.  The unlocking itself happens in
    :func:`wreader.achievements.check_achievements`; this only renders the result,
    which keeps a broken definition file from ever turning a session into a
    traceback.  *ring* mirrors the ``achievement_sound`` setting: some terminals
    beep loudly on ``'\\a'``.
    """
    # 逐条播放庆祝动画
    for achievement in newly:
        stats.celebrate(achievement, ring=ring)
    return list(newly)


def _announce_unlocks(pager: Pager, newly: Sequence[Dict[str, Any]]) -> None:
    """Flash the freshly unlocked achievements on the in-screen notice.

    Three names at most: past that the reader is told *how many* instead, because the
    point is to notice that something happened without losing the page you were on.
    """
    # 成就名（没有名字就退回 id），最多列三个
    names = [str(item.get("name") or item.get("id")) for item in newly]
    shown = names[:_NOTICE_MAX_ITEMS]
    text = "、".join(shown)
    # 更多就只报个数
    if len(names) > len(shown):
        text = "{} 等 {} 个".format(text, len(names))
    pager.announce(text)


def _fire_event(
    pager: Pager,
    event_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Send one event from inside the reader and show what it unlocked.

    Returns the newly unlocked achievements, or ``None`` when the engine could not be
    reached at all (unreadable state file, unwritable data directory) -- the caller
    uses that to decide whether to advance its own bookkeeping.  Reading must never
    depend on the achievements file being sane, so nothing here raises.
    """
    try:
        newly = achievements.check_achievements(event_type, payload)
    except (achievements.AchievementsError, library.LibraryError, stats.StatsError):
        # 成就系统坏了：静默跳过，阅读继续
        return None
    if newly:
        _announce_unlocks(pager, newly)
    return newly


def _probe_achievements(
    pager: Pager, event_type: str, payload: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Fire one event *before* the curses loop starts (env / geo) and queue its notice.

    The notice is time based and lives on the :class:`Pager`, so announcing it here is
    enough for the first frame to draw it -- there is no stdscr yet.  Failures are
    swallowed exactly like in :func:`_fire_event`.
    """
    try:
        newly = achievements.check_achievements(event_type, payload)
    except (achievements.AchievementsError, library.LibraryError, stats.StatsError):
        # 成就系统坏了：环境/地理探测就当没发生
        return []
    # 已经有值就说明这次解锁了什么：排进屏内通知
    if newly:
        _announce_unlocks(pager, newly)
    return newly


def _achievement_tick(pager: Pager, event_type: str) -> List[Dict[str, Any]]:
    """Report the reader's counters to the engine -- but only when it matters.

    A check costs a file lock and a full state rewrite, so it must not happen on every
    key press.  The reader keeps its own running totals (``Pager.metric_values``) and
    compares them with the thresholds taken from the achievement definitions; only when
    one of those lines is *just* crossed does this talk to the engine -- which is also
    exactly the moment the reader should see the notice.  Counters that never reach a
    threshold are handed over in one go when the session ends.

    Thresholds the baseline already satisfies are marked as fired up front (see
    ``open_reader``), so an achievement unlocked days ago never triggers a write here.
    """
    hits = achievements.crossed_thresholds(
        pager.metric_values(), pager.thresholds, pager.fired
    )
    # 一条线都没越过：攒着，不写盘
    if not hits:
        return []
    # 没报过的增量随事件一起送（峰值可以重复送，引擎取 max）
    deltas = pager.pending_deltas()
    payload: Dict[str, Any] = {
        "deltas": deltas,
        "maxima": pager.current_maxima(),
        "width": int(pager.terminal_width or 0),
        "height": int(pager.viewport_rows),
    }
    newly = _fire_event(pager, event_type, payload)
    # 引擎这次没接住：水位与门槛都不动，下一次接着报（一条数据都不丢）
    if newly is None:
        return []
    # 真的发出去了才推进水位，并记住这几条线已经触发过
    pager.commit_report(deltas)
    pager.fired.extend(hits)
    return newly



def _toggle_auto_scroll(pager: Pager) -> None:
    """Switch the automatic page turns on or off and say which it is now."""
    # 开着 → 关掉；关着 → 打开并报一次当前速度
    if pager.toggle_auto_scroll():
        pager.say(
            "自动翻页：{}（a 暂停，> 加速 < 减速）".format(pager.auto_scroll_pace())
        )
        return
    pager.say("自动翻页已暂停（a 继续）")


def _adjust_auto_scroll(pager: Pager, factor: float) -> None:
    """Change the automatic pace by *factor* and report the new pace."""
    # 调速本身与开关无关：没开也能先设好速度
    pager.adjust_auto_scroll_speed(factor)
    # 没开自动翻页时顺带提示一句怎么开始
    suffix = "" if pager.auto_scroll else "（按 a 开始）"
    pager.say("自动翻页速度：{}{}".format(pager.auto_scroll_pace(), suffix))


def handle_key(stdscr: Any, pager: Pager, key: Any) -> bool:
    """Act on one key press; return ``False`` when the pager should quit.

    ``n`` follows the specification and moves to the next *search* hit, so
    chapter hopping lives on ``[`` and ``]`` instead.
    """
    # q / Q / Ctrl-C：退出
    if key in ("q", "Q", 3):
        return False
    # 数一下这个键：空格连击、连续翻页、方向键怀旧都从这里记账
    pager.note_key(key)
    # 向下翻页：j、空格、回车、下方向键、PageDown
    if key in ("j", " ", "\n", "\r", curses.KEY_DOWN, curses.KEY_NPAGE):
        pager.next_page()
    # 向上翻页
    elif key in ("k", curses.KEY_UP, curses.KEY_PPAGE):
        pager.previous_page()
    # g：按行号跳转
    elif key == "g":
        _goto(stdscr, pager)
    # G：跳到全书末尾
    elif key == "G":
        pager.to_end()
    # [：上一章
    elif key == "[":
        pager.previous_chapter()
    # ]：下一章
    elif key == "]":
        pager.next_chapter()
    # Tab：呼出目录浮层，选中就跳到那一章
    elif key in _TAB_KEYS:
        _jump_via_toc(stdscr, pager)
    # /：搜索
    elif key == "/":
        _search(stdscr, pager)
    # n：跳到下一个搜索命中
    elif key == "n":
        if not pager.next_match():
            pager.say("还没有搜索结果，先按 / 搜索")
    # b：加/删书签
    elif key == "b":
        added = pager.toggle_bookmark()
        pager.say(
            "已加书签：第 {} 行".format(pager.position + 1)
            if added
            else "已删除书签：第 {} 行".format(pager.position + 1)
        )
    # a：开关自动翻页（免手翻，按行数自己往下走）
    elif key in _AUTO_TOGGLE_KEYS:
        _toggle_auto_scroll(pager)
    # > / +：自动翻页加速（间隔变小 = 翻得更快）
    elif key in _AUTO_FASTER_KEYS:
        _adjust_auto_scroll(pager, 1.0 / _AUTO_SPEED_FACTOR)
    # < / -：自动翻页减速
    elif key in _AUTO_SLOWER_KEYS:
        _adjust_auto_scroll(pager, _AUTO_SPEED_FACTOR)
    # ?：帮助页（快捷键一览；帮助迷也在这里记账）
    elif key == "?":
        _help_overlay(stdscr, pager)
    # 数完了就看看有没有刚越过门槛的成就（没越过就是纯内存判断，不写盘）
    _achievement_tick(pager, "key")
    # True 表示继续阅读
    return True


def build_session(
    started: datetime, ended: datetime, lines_read: int
) -> Dict[str, Any]:
    """Return the ``sessions[]`` entry describing one reading session."""
    # 一条会话记录：起止时间 + 读了多少行
    return {
        "start": _iso(started),
        "end": _iso(ended),
        "lines_read": int(max(0, lines_read)),
    }


def accumulate_stats(
    document: Dict[str, Any], seconds: int, day: str
) -> Dict[str, Any]:
    """Add *seconds* to the global and to the per-day reading totals."""
    # 统计段落（不存在就建）
    stats = document.setdefault("stats", {})
    # 全局累计阅读秒数
    stats["total_read_time"] = int(stats.get("total_read_time") or 0) + int(seconds)
    # 按天的桶，用于连续天数和热力图
    daily = stats.get("daily_read_time")
    if not isinstance(daily, dict):
        daily = {}
        stats["daily_read_time"] = daily
    # 把秒数累加到当天的桶里
    daily[day] = int(daily.get(day) or 0) + int(seconds)
    return stats


def _write_position(
    document: Dict[str, Any], book_id: str, pager: Pager, moment: datetime
) -> bool:
    """Store position, bookmarks and the sticky finished flag; ``False`` if gone."""
    # 按 id 找书
    book = document["books"].get(str(book_id))
    if book is None:  # the book was removed while we were reading
        # 阅读过程中书被删掉了（另一个终端里删的）
        return False
    progress = book.get("progress")
    # 进度块结构不对就重建
    if not isinstance(progress, dict):
        progress = library.empty_progress()
    # 覆盖式更新关键字段
    progress.update(
        {
            "current_line": pager.position,
            "percentage": pager.percentage,
            "last_read": _iso(moment),
            # 书签先规整成标准结构再存
            "bookmarks": library.normalise_bookmarks(pager.bookmarks),
            # Sticky: once a book has been finished, jumping back does not undo it.
            # "读完了"是粘性的：读到最后一行就置位，之后回翻也不会取消
            "finished": bool(progress.get("finished"))
            or bool(pager.total and pager.position >= pager.total - 1),
        }
    )
    book["progress"] = progress
    return True


def save_position(pager: Pager) -> bool:
    """Write just where we are, without closing the session.

    This is what ``reader.auto_save_interval`` calls every minute: pure crash
    insurance for the reading position, so it deliberately records no session and
    touches no statistics.  Returns ``False`` when the index could not be written.
    """
    try:
        # 读索引 -> 改位置 -> 写回
        document = library.load_library()
        if not _write_position(document, pager.book_id, pager, _now()):
            return False
        library.save_library(document)
    except library.LibraryError:
        # 索引写不了就当作失败（下一次自动保存再试）
        return False
    # 顺手刷新"现场"：真崩了以后恢复的是最近一次自动保存的位置，而不是开书那一刻的
    write_marker(pager)
    return True


def save_session(
    book_id: str,
    pager: Pager,
    # 本次会话总秒数
    seconds: int,
    started: datetime,
    ended: datetime,
    # 是否把本次会话写进历史统计
    record_history: bool = True,
) -> None:
    """Write position, bookmarks and, optionally, the session to the index.

    The position and the bookmarks are always stored so ``werd read`` resumes where
    you stopped.  ``record_history`` (the ``reader.store_history`` setting) also
    appends the session with its duration to the book and to the global ``stats``.
    """
    document = library.load_library()
    # 先写位置（书没了就直接返回）
    if not _write_position(document, book_id, pager, ended):
        return
    progress = document["books"][str(book_id)]["progress"]
    # 只有开了记录历史才写会话明细
    if record_history:
        sessions = progress.get("sessions")
        if not isinstance(sessions, list):
            sessions = []
        # 追加一条会话记录
        sessions.append(build_session(started, ended, pager.lines_read))
        progress["sessions"] = sessions
        # 本书累计时长
        progress["total_time_seconds"] = int(
            progress.get("total_time_seconds") or 0
        ) + int(seconds)
        # 全局与当天的统计
        accumulate_stats(document, seconds, ended.strftime("%Y-%m-%d"))
    # 统一落盘
    library.save_library(document)


def _init_colors() -> None:
    """Let curses keep the terminal's own foreground and background colours.

    Without this the default colour pair is the terminal's "normal" one, and on
    many setups that means an opaque black background: a themed (or transparent)
    terminal background never shows through the reading area.  Asking for the
    default colours maps the default pair back to whatever the terminal is
    actually configured with.
    """
    try:
        # 终端不支持颜色就什么都不用做
        if not curses.has_colors():
            return
        # 初始化颜色支持（这一步会先把默认配色设成白底黑字）
        curses.start_color()
        # 再把默认前景/背景交还给终端：主题色与透空背景都能透出来
        curses.use_default_colors()
    except curses.error:
        # 老终端不支持"默认色"：静默放弃，保持原来的行为
        pass


class _DragScroll:
    """把连续的「按住拖动」事件换算成滚动行数（触摸拖动即滚动）。

    终端只报告手指的纵向位置，所以这里按「一个字符行 = 一行正文」1:1 换算；
    方向与手机阅读一致：**手指往上滑 = 往后翻（读下一屏）**，往下滑 = 往前翻。
    """

    def __init__(self) -> None:
        #: the last reported finger row; ``None`` while nothing is held down
        # 上一次报告的手指所在行；None 表示当前没有按住
        self._last_y: Optional[int] = None

    @property
    def active(self) -> bool:
        """``True`` while a press is being dragged."""
        # 只要 last_y 还在，就说明手指按着
        return self._last_y is not None

    def press(self, y: int) -> None:
        """Start a drag at row *y*."""
        # 记下起点（本次拖动的基准行）
        self._last_y = int(y)

    def release(self) -> None:
        """End the drag."""
        # 抬手：忘掉起点
        self._last_y = None

    def move(self, y: int) -> int:
        """Move to row *y*; return how many lines to scroll (positive = read on)."""
        # 没按住就忽略：既不滚动，也不会被误当成"拖动开始"
        if self._last_y is None:
            return 0
        # 手指上滑时 y 变小 → 位移为正 → 往后翻
        delta = self._last_y - int(y)
        self._last_y = int(y)
        return delta


def _mouse_scroll_delta(pager: Pager, bstate: int, y: int, drag: _DragScroll) -> int:
    """把一次鼠标事件换算成滚动行数（``0`` = 这次事件不动正文）。

    ``bstate`` 与 ``y`` 直接来自 :func:`curses.getmouse`，但这里用参数传进来，
    好让测试不依赖真终端也能驱动这套换算。
    """
    # 滚轮优先：上滚 = 往回看，下滚 = 往后读
    if bstate & _WHEEL_UP:
        return -pager.wheel_scroll_step
    if bstate & _WHEEL_DOWN:
        return pager.wheel_scroll_step
    # 触摸拖动被关掉：顺便清掉拖动状态，别留着半截状态
    if not pager.touch_scroll:
        drag.release()
        return 0
    # 按住（触摸屏通常是 button1）：第一次只记起点，之后按纵向位移滚
    if bstate & _DRAG_PRESSED:
        if not drag.active:
            drag.press(y)
            return 0
        return drag.move(y)
    # 有些终端拖到一半就不再报按键位、只发位置报告：只要还在拖动就继续算位移
    if drag.active and (bstate & _MOUSE_MOTION):
        return drag.move(y)
    # 其余情况（抬手、点一下、纯移动）都当作结束拖动
    drag.release()
    return 0


def _enable_mouse() -> None:
    """请终端把鼠标/触摸事件报过来（滚轮与拖动都靠它）。

    不开这个，终端根本不会发 ``KEY_MOUSE`` —— 这正是 Termux 上触摸滑动
    "完全没反应"的原因。不支持鼠标的终端会抛 :class:`curses.error`，
    这里静默降级：没有鼠标功能，键盘照常用。
    """
    try:
        # 关掉 ncurses 的「点一下 / 双击 / 三击」判定窗口。
        # ⚠️ 实测（2026-09-22，真 pty 灌 SGR 序列）：默认的判定窗口会把**按下事件扣住**，
        #    等它判断完才上报；结果「按住拖动」时拖动状态来不及建立，
        #    后面来的位置报告全被当成普通移动丢掉 —— 拖动因此完全失效。
        #    设成 0 之后按下事件立即上报，拖动才跟得上手指。注意它返回的是旧值，忽略即可。
        curses.mouseinterval(0)
    except curses.error:
        # 个别终端/curses 实现没有这个函数：忽略，滚轮与键盘仍然可用
        pass
    try:
        # 全套鼠标事件 + 位置报告：位置报告是「拖动即滚动」的前提
        curses.mousemask(curses.ALL_MOUSE_EVENTS | _MOUSE_MOTION)
    except curses.error:
        # 老终端不支持鼠标：算了，不影响键盘阅读
        pass


def _disable_flow_control() -> None:
    """Turn off XON/XOFF so ``Ctrl-S`` reaches the app instead of freezing output.

    :func:`curses.wrapper` only calls :func:`curses.cbreak`, which leaves software
    flow control on: with IXON set, the terminal driver swallows ``Ctrl-S`` (XOFF)
    and the note panel's save key would never arrive.  Best effort only -- Windows
    has no :mod:`termios` and a non-tty stdin has nothing to tweak, in which case
    the call simply does nothing.  ``endwin()`` puts the shell mode back the way
    :func:`curses.initscr` found it, so nothing has to be undone by hand.
    """
    # Windows 没有 termios：直接跳过（那边只能靠别的确认方式）
    try:
        import termios
    except ImportError:  # pragma: no cover - Windows only
        return
    try:
        # 终端文件描述符（stdin 被重定向时它不是 tty，下面会失败）
        fd = sys.stdin.fileno()
        # 取出当前终端属性
        attrs = termios.tcgetattr(fd)
        # attrs[0] 是输入标志位：清掉 IXON（输出流控）与 IXOFF（输入流控）
        attrs[0] &= ~(termios.IXON | termios.IXOFF)
        # 立刻生效
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except (OSError, ValueError, termios.error):  # pragma: no cover - 终端不配合
        # 拿不到 / 改不了终端属性：静默降级，别影响阅读
        pass


def _mouse_event_delta(pager: Pager, drag: _DragScroll) -> int:
    """读一条排队的鼠标事件，返回该滚几行。"""
    try:
        # getmouse 返回 (id, x, y, z, bstate)
        _id, _x, y, _z, bstate = curses.getmouse()
    except curses.error:
        # 事件已经被别的地方消费掉：当作什么都没发生
        return 0
    # 真正的换算交给纯函数，便于单测
    return _mouse_scroll_delta(pager, int(bstate), int(y), drag)


def marker_path() -> Path:
    """Return the reading-session marker, ``<data dir>/reading_session.json``."""
    # 跟数据目录走（$WREADER_HOME 一改，现场标记也跟着走）
    return config.data_dir() / SESSION_MARKER_FILENAME


def write_marker(pager: Pager, moment: Optional[datetime] = None) -> bool:
    """Write the "a session is in progress" marker; ``False`` when it cannot be written.

    The marker is small on purpose: the book, the line, the intra-line offset and a
    one-line preview.  The *authoritative* position still lives in ``library.json``
    (written by ``save_position``/``save_session``); this file only has to survive a
    crash so the next start can ask "接不接着读？".  A torn write therefore costs the
    question, never the position -- which is why a plain write is good enough here.
    """
    # 现场内容：够恢复就行（行号是唯一坐标，offset 只是显示态）
    payload = {
        "book_id": pager.book_id,
        "title": pager.title,
        "position": int(pager.position),
        "offset": int(pager.line_offset),
        "preview": _first_line(pager.lines[pager.position]) if pager.lines else "",
        "started": _iso(moment or _now()),
        "pid": os.getpid(),
    }
    try:
        # 数据目录可能还没建（第一次阅读）
        target = marker_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError:
        # 写不了（目录只读）：放弃"防意外中断"，阅读照常
        return False
    return True


def read_marker() -> Dict[str, Any]:
    """Return the marker a previous session left behind, or ``{}``."""
    target = marker_path()
    # 没有现场：上一次是正常退出的（或者从没读过）
    if not target.is_file():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 写了一半就被 kill：当作没有现场（顶多少问一次，不会丢位置）
        return {}
    return dict(raw) if isinstance(raw, dict) else {}


def clear_marker() -> None:
    """Delete the marker: the session ended on purpose."""
    try:
        marker_path().unlink()
    except FileNotFoundError:
        pass
    except OSError:  # pragma: no cover - 目录只读之类
        # 删不掉也无所谓：下次开书顶多多问一句"要不要接着读"
        pass


def _offer_recovery(stdscr: Any, pager: Pager, marker: Dict[str, Any]) -> bool:
    """Ask whether to continue where the interrupted session stopped.

    Only asked when the marker is left over *and* it is about the book being opened --
    for any other book the question would be about somebody else's page, and the marker
    is simply overwritten.  The answer is reported to the achievements engine
    (恢复大师 / 我反悔); either way the marker is cleared by the caller, so the prompt
    shows up exactly once per interruption.
    """
    # 现场里的行号也要夹进合法范围（书可能在两次阅读之间被重建过）
    position = clamp(_as_position(marker.get("position")), pager.total)
    offset = max(0, _as_position(marker.get("offset")))
    # 提示内容：读到哪一行、什么时候、以及那一行长什么样
    body = [
        "上次读到第 {} 行 · 停在 {}".format(
            position + 1, str(marker.get("started") or "时间不详")
        ),
    ]
    preview = str(marker.get("preview") or "").strip()
    if preview:
        # 只显示一行预览（弹窗会自己按宽度裁）
        body.append(preview)
    accepted = _confirm(stdscr, "上次好像没有正常退出", body, hint=_RECOVER_HINT)
    if accepted:
        # 回到现场（offset 让长段落也从原来那条屏幕行接着显示）
        pager.move_to(position, offset)
    # 报给成就引擎：恢复成功算一次"接着读"，放弃算"我反悔"
    _fire_event(pager, "recover", {"recovered": bool(accepted)})
    return accepted


def _as_position(value: Any) -> int:
    """Coerce a marker field to a non-negative int (junk becomes 0)."""
    try:
        # 手改坏的现场文件不该让阅读器起不来
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _poll_timeout_ms(pager: Pager) -> int:
    """How long ``get_wch`` may wait before the next frame: at most one tick.

    Without automatic page turns this is exactly :data:`_TICK_MS`, so the clock and
    the status bar keep refreshing once a second.  With them on the wait is shortened
    to whatever is left before the next turn (never below :data:`_AUTO_MIN_POLL_MS`),
    which is what makes the mode advance on time instead of only on tick boundaries.
    """
    # 自动翻页关着：按老规矩，最多等一个 tick
    wait = pager.auto_scroll_wait()
    if wait is None:
        return _TICK_MS
    # 到点/过点：用最小等待，下一帧立刻翻页
    return max(_AUTO_MIN_POLL_MS, min(_TICK_MS, int(wait * 1000)))


def _run(stdscr: Any, pager: Pager) -> None:
    """curses main loop: repaint on a tick, act on keys, never block forever."""
    # 让 curses 解析方向键等特殊键序列
    stdscr.keypad(True)
    try:
        # 隐藏光标（阅读时不需要）
        curses.curs_set(0)
    except curses.error:
        pass
    # 用终端自己的配色，别把正文糊成固定的黑底
    _init_colors()
    # 请终端上报鼠标/触摸事件（滚轮与拖动都靠它；不支持的终端自动降级）
    _enable_mouse()
    # 关掉 XON/XOFF 流控，否则 Ctrl+S 会被终端吞掉（失败就静默降级）
    _disable_flow_control()
    # 触摸拖动用的状态机：记住手指上一次在哪一行
    drag = _DragScroll()
    # 上次没正常退出、而且是同一本书：先问一句要不要接着上次读
    if pager.resume_marker:
        _offer_recovery(stdscr, pager, pager.resume_marker)
        # 问过就不必再问（现场文件由 open_reader 在退出时清掉）
        pager.resume_marker = {}
    # 写上"我正在读这本书"的现场：正常退出会删掉它，崩溃时它会留下来
    write_marker(pager)
    # 先量一次终端宽度：极限尺寸的秒表从这里开始走
    pager.note_width(stdscr.getmaxyx()[1])
    # get_wch 最多等 1 秒：这样时钟和状态栏能持续刷新（自动翻页开着时会缩短）
    stdscr.timeout(_poll_timeout_ms(pager))
    # 上次自动保存的时刻
    last_save = time.monotonic()
    while True:
        # 检查是否换了章节（章节计时用）
        pager.sync()
        # 自动翻页到点就自己往后挪一屏（挪不动 = 已到书末，模式会自己关掉）
        pager.auto_scroll_tick()
        # 重画整帧
        _draw(stdscr, pager, _now())
        # 自动保存：间隔到了就把进度写盘
        if pager.auto_save_interval:
            moment = time.monotonic()
            if moment - last_save >= pager.auto_save_interval:
                last_save = moment
                save_position(pager)
        # 按"离下一次自动翻页还有多久"决定这一帧等多久，否则按一个 tick
        stdscr.timeout(_poll_timeout_ms(pager))
        try:
            # 等一个按键（或等到超时）
            key = stdscr.get_wch()
        except curses.error:
            continue  # the tick expired: repaint so the clock stays fresh
        except KeyboardInterrupt:
            # Ctrl-C：退出阅读
            return
        # 终端尺寸变化：先结算窄屏时间，再看有没有刚越过的成就门槛，然后重画
        if key == curses.KEY_RESIZE:
            pager.note_width(stdscr.getmaxyx()[1])
            _achievement_tick(pager, "resize")
            # 有人动终端：把下一次自动翻页往后推
            pager.defer_auto_scroll()
            continue
        # 鼠标 / 触摸事件：滚轮一格滚 wheel_scroll_step 行，按住拖动按位移滚
        if key == curses.KEY_MOUSE:
            delta = _mouse_event_delta(pager, drag)
            # 真的滚动了才动位置（没位移就不折腾）
            if delta:
                pager.scroll(delta)
            # 手动滚过之后重新计时，别紧接着又自动翻
            pager.defer_auto_scroll()
            continue
        # 交给按键处理器；它返回 False 表示要退出
        if not handle_key(stdscr, pager, key):
            return
        # 有按键进来：把下一次自动翻页推后一整拍，别抢在读者眼皮底下翻页
        pager.defer_auto_scroll()


def _has_terminal() -> bool:
    """Return ``True`` when both stdin and stdout are a real terminal."""
    # 输入输出都被重定向时不该启动全屏界面
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _prepare_terminal() -> None:
    """Let curses render UTF-8 (CJK) properly before it initialises."""
    try:
        # 用当前环境的 locale，才能正确渲染中文宽字符
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        # locale 设置失败也不阻断（顶多是中文显示不好看）
        pass


def _prepare_achievements(pager: Pager, document: Any) -> None:
    """Load the thresholds and the baseline the real-time checks need.

    Two reads, once per session: the numbers the conditions are written against (out of
    the achievement definitions) and where every metric currently stands.  Both are best
    effort -- with a broken definitions file the reader simply never fires a mid-session
    check, and the session is still settled when it ends.
    """
    try:
        # 门槛表来自定义文件（用户自己加的成就也算数）
        pager.thresholds = achievements.metric_thresholds()
    except stats.StatsError:
        # 定义坏了：不做实时判定（`werd achievements` 会把原因报出来）
        pager.thresholds = {}
    # 基线：开书这一刻的指标快照（引擎读不出来就是空表）
    pager.baseline = achievements.session_metrics(document=document)
    # 基线就已经达标的线直接标成"已触发"：否则第一次按键会白写一遍状态文件
    pager.fired = achievements.crossed_thresholds(pager.baseline, pager.thresholds)


def _geo_cache_is_fresh(now: Optional[datetime] = None) -> bool:
    """Whether ``geo.json`` is young enough that no lookup will be made.

    Used only to decide whether to print the "正在确认位置" hint before curses takes over
    the screen: the actual decision belongs to :func:`wreader.geo.load_location`.
    """
    try:
        cached = geo.load_cached()
    except geo.GeoError:
        return False
    moment = cached.get("fetched_at")
    # 没有时间戳（文件被手改过）：当作过期，重新查
    if not isinstance(moment, datetime):
        return False
    age = ((now or _now()) - moment).total_seconds()
    return 0 <= age < geo.CACHE_SECONDS


def _probe_geo(pager: Pager, settings: Any) -> List[Dict[str, Any]]:
    """Report where this machine is, for the geography achievements.

    Skipped entirely when ``stats.geo_lookup`` is off, and cached for an hour
    (:data:`wreader.geo.CACHE_SECONDS`), so the lookup happens at most once an hour.
    Because it can take a second or two the first time, a one line hint is printed
    *before* curses takes over the screen -- silence there would look like a hang.
    """
    # 关了地理查询：一步网络都不发（地理成就保持锁定）
    if not bool(settings.get("stats.geo_lookup", True)):
        return []
    # 真要去查了才提示（缓存还新鲜时保持安静）
    if not _geo_cache_is_fresh():
        console.print("[dim]正在确认所在位置（地理成就，一小时最多查一次）…[/dim]")
    location = geo.load_location()
    # 离线 / 接口挂了：什么都不记，阅读照常（地理成就是"锦上添花"里最花的那种）
    if not location:
        return []
    return _probe_achievements(pager, "geo_change", dict(location))


def open_reader(book_id: str) -> int:
    """Open the pager for *book_id* and return a process exit code."""
    # 读索引找书
    document = library.load_library()
    book = document["books"].get(str(book_id))
    # 没有这本书：抛出异常由 CLI 提示
    if book is None:
        raise library.LibraryError("unknown book id: {}".format(book_id))

    # 读出转换后的正文并按行切分
    lines = read_lines(str(book.get("file_path") or ""))
    # 正文是空的：没法读
    if not lines:
        raise library.LibraryError(
            "{} has no readable text ({})".format(
                book.get("title"), book.get("file_path")
            )
        )
    # 需要真实终端才能进全屏界面
    if not _has_terminal():
        raise library.LibraryError(
            "werd read needs an interactive terminal (a tty on stdin and stdout)"
        )

    # 读配置（reader 与 stats 两段分别用到）
    settings = config.load_config()
    reader_settings = settings.section("reader")
    # 书里存的上次进度
    progress = book.get("progress") or {}
    # 目录（章节表 + 百分比）：优先读缓存，缺失/过期则现建
    book_toc = toc.load_toc(str(book_id), book, settings)
    # 组装 Pager：所有配置都在这里被"翻译"成运行时参数
    pager = Pager(
        lines=lines,
        chapters=book.get("chapters") or [],
        position=int(progress.get("current_line") or 0),
        page_height=int(reader_settings.get("page_height") or 24),
        book_id=str(book_id),
        title=str(book.get("title") or "untitled"),
        author=str(book.get("author") or "unknown"),
        bookmarks=progress.get("bookmarks") or [],
        # 连续阅读天数由统计里的每日桶算出
        streak=reading_streak(
            (document.get("stats") or {}).get("daily_read_time") or {}
        ),
        page_scroll_step=float(reader_settings.get("page_scroll_step") or 1.0),
        # 翻页时上下保留的上下文行数（0 = 不重叠；用 get 的默认参数，别用 or，否则 0 会被吃成 3）
        page_overlap=int(reader_settings.get("page_overlap", DEFAULT_PAGE_OVERLAP)),
        # 滚轮/触摸一格滚几行（移动端；Pager 里还会兜底成至少 1 行）
        wheel_scroll_step=int(reader_settings.get("wheel_scroll_step") or 1),
        # 触摸拖动即滚动（移动端，默认开）
        touch_scroll=bool(reader_settings.get("touch_scroll", True)),
        status_bar_format=str(
            reader_settings.get("status_bar_format") or DEFAULT_STATUS_FORMAT
        ),
        auto_save_interval=int(reader_settings.get("auto_save_interval") or 0),
        # 自动翻页（a 键）的节拍与步长：速度在阅读中按 > / < 还能再调
        auto_scroll_interval=float(
            reader_settings.get("auto_scroll_interval") or DEFAULT_AUTO_SCROLL_INTERVAL
        ),
        auto_scroll_step=int(
            reader_settings.get("auto_scroll_step") or DEFAULT_AUTO_SCROLL_STEP
        ),
        # Tab 目录浮层用的条目（带百分比）
        toc_entries=book_toc,
    )

    # -- 成就：先备好"实时判定"要用的门槛表与基线（各读一次盘）--------------
    _prepare_achievements(pager, document)
    # 环境探测（云端书虫 / 穿越子系统 / 套娃终端 / 开发者模式）：纯读环境，不联网
    _probe_achievements(pager, "env", {"flags": env.flags()})
    # 位置探测（地理成就）：一小时最多查一次外网，关掉 stats.geo_lookup 就完全离线
    _probe_geo(pager, settings)
    # 上次留下的"现场"：同一本书才认（别的书的现场会被本次会话覆盖）
    marker = read_marker()
    if str(marker.get("book_id") or "") == str(book_id):
        pager.resume_marker = marker

    # 设置 locale 后再启动 curses
    _prepare_terminal()
    started = _now()
    try:
        # wrapper 负责 curses 的初始化/收尾，并在异常时恢复终端
        curses.wrapper(_run, pager)
    except KeyboardInterrupt:  # pragma: no cover - Ctrl-C escaped the loop
        pass
    except curses.error as exc:
        raise library.LibraryError("cannot start the pager: {}".format(exc)) from exc
    ended = _now()
    # 停掉窄屏秒表：把最后一段"极限窄"窗口里的时间也算进成就
    pager.close_width_window()

    # 本次会话时长（秒）
    seconds = max(0, int((ended - started).total_seconds()))
    # 退出时把位置、书签（以及可选的会话明细）写回索引
    save_session(
        str(book_id),
        pager,
        seconds,
        started,
        ended,
        record_history=bool(reader_settings.get("store_history", True)),
    )
    # 正常退出：删掉现场标记，下次开书就不会再问"要不要接着读"
    clear_marker()
    # 在普通终端里打印一行摘要
    console.print(
        "[dim]{} · 停在 {}/{} 行 ({:.1f}%) · 本次 {} · 书签 {} 个[/dim]".format(
            pager.title,
            pager.position + 1,
            pager.total,
            pager.percentage,
            format_duration(seconds),
            len(pager.bookmarks),
        )
    )
    # 检查并庆祝本次会话解锁的成就（按设置决定是否响铃）
    _celebrate_achievements(
        _session_achievements(pager, seconds, started, ended),
        ring=bool(settings.get("stats.achievement_sound", True)),
    )
    return 0


def _session_achievements(
    pager: Pager, seconds: int, started: datetime, ended: datetime
) -> List[Dict[str, Any]]:
    """Hand the finished session to the achievements engine; never raise.

    The payload carries the whole line ranges walked through this session, so the
    engine can count the words it has not counted before (a re-read adds nothing).
    """
    try:
        # session_end：时长 + 读过的行区间 → 事件记录 + 解锁判定
        return achievements.check_achievements(
            "session_end",
            {
                "book_id": pager.book_id,
                "seconds": int(seconds),
                "started": _iso(started),
                "ended": _iso(ended),
                # 正文交给引擎，它自己按行号区间去重
                "lines": pager.lines,
                "ranges": list(pager.read_ranges),
                # 本次会话攒下的按键/尺寸计数：没撞到门槛的那些在这里一次交账
                "deltas": pager.pending_deltas(),
                "maxima": pager.current_maxima(),
                "width": int(pager.terminal_width or 0),
                "height": int(pager.viewport_rows),
            },
        )
    except (achievements.AchievementsError, library.LibraryError, stats.StatsError) as exc:
        # 成就系统坏了也只是提示一句，绝不能影响阅读体验
        console.print("[yellow]achievements skipped: {}[/yellow]".format(exc))
        return []

"""Reader core: a curses paged reading experience.

``werd read <book_id>`` pages through the UTF-8 text that :mod:`wreader.library`
produced at import time.  The pager works in **source lines**: the stored file is
split on ``\\n`` exactly the way the importer split it, so
``progress["current_line"]``, ``progress["bookmarks"][].line`` and every
``chapters[].line_start`` are indexes into the same list.  One source line may
occupy more than one screen row (long paragraphs wrap, and the bilingual view adds
a row per translation), so pagination is measured in **screen rows**: the next
screen starts at the first row that did not fit, kept as a ``(source line, offset)``
pair.  ``line_offset`` is the offset inside that line, and it is display state only
-- never written to disk, so ``progress["current_line"]`` stays a plain line index.

Views
-----
``l`` cycles the language view.  Each view first works out whether a translation
is needed at all, so asking for the language the book is already written in is
free and works offline:

============  ========================================================
view          what is drawn
============  ========================================================
中文 ``zh``     the text in Chinese (the original when the book is Chinese)
英文 ``en``     the text in English (the original when the book is English)
双语 ``both``   the original line, then its translation on the next row
============  ========================================================

``t`` translates only what is on screen and deliberately never caches it; ``T``
translates the whole chapter and caches it in ``~/.wreader/cache/<book>/``; ``v`` looks
up a single word and offers to file it in :mod:`wreader.vocab`.  ``Tab`` opens the
table of contents overlay (see :mod:`wreader.toc`) and jumps to the chapter picked there.

Settings
--------
The ``[reader]``, ``[translator]``, ``[stats]`` and ``[vocab]`` tables of
``~/.wreader/settings.toml`` drive the front end (see :mod:`wreader.config`):
``page_scroll_step`` sets how much the page keys move (``1`` = one screen) and
``page_overlap`` how many lines of the previous screen stay visible after a page
turn, ``status_bar_format`` picks the status segments, ``auto_save_interval`` writes the
position while reading, ``auto_translate_chapter`` translates each chapter as it
is entered, ``highlight_in_reader`` underlines notebook words and
``auto_add_on_mark`` files a looked up word without asking.

Everything outside the curses front end is a plain function over plain data, so
the paging, chapter, streak and view maths are testable without a terminal.
"""

# 延迟求值类型注解
from __future__ import annotations

# 全屏终端界面（Unix 自带，Windows 需额外包）
import curses
# curses 的文本编辑控件：笔记面板的编辑区复用它现成的 Emacs 键绑定
import curses.textpad
# curses.ascii：判断可打印字符、取 NL 等控制码（自定义 validator 要用）
import curses.ascii
# 设置 locale，让 curses 正确显示中文宽字符
import locale
# 高亮生词、句子边界识别要用正则
import re
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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# 退出阅读器之后用 rich 打印一行摘要
from rich.console import Console

# 同包引用：配置、书库、统计成就、目录、翻译、生词本
from . import config, library, stats, toc, translator, vocab

# 模块公开的名字（Pager 与几个纯函数，方便单测）
__all__ = [
    "DEFAULT_PAGE_OVERLAP",
    "DEFAULT_STATUS_FORMAT",
    "Pager",
    "STATUS_TOKENS",
    "format_status_bar",
    "open_reader",
    "read_lines",
    "reading_streak",
    "save_position",
    "save_session",
    "status_segment",
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

# 三种阅读视图
MODE_ZH = "zh"
MODE_EN = "en"
MODE_BOTH = "both"
# 按 l 循环的顺序
MODE_ORDER: Tuple[str, ...] = (MODE_ZH, MODE_EN, MODE_BOTH)
# 视图的中文名，用于状态栏显示
MODE_LABELS = {MODE_ZH: "中文", MODE_EN: "英文", MODE_BOTH: "双语对照"}

# 打开一本书时的默认视图，按书的语言决定
#: The view a newly opened book starts in, keyed by the book's own language.
LANGUAGE_MODES = {"zh": MODE_ZH, "en": MODE_EN}

# 状态栏支持的片段名，在配置里用 | 连接；不认识的会被跳过而不是原样打印
#: The segments ``reader.status_bar_format`` understands, joined by ``|`` in the
#: format string.  An unknown segment is skipped rather than printed raw.
STATUS_TOKENS: Tuple[str, ...] = (
    "time",
    "book",
    "chapter",
    "position",
    "percent",
    "mode",
    "duration",
    "elapsed",
    "streak",
    "bookmarks",
    "vocab",
    "translations",
)

# 默认状态栏：时间 | 章节 | 本章时长
#: The status bar the settings file documents: clock, chapter, chapter time.
DEFAULT_STATUS_FORMAT = "time|chapter|duration"

# 翻页时默认保留的上下文行数（与 config.SCHEMA 里 reader.page_overlap 的默认值一致）
#: Lines of the previous screen kept on a page turn (``reader.page_overlap``).
DEFAULT_PAGE_OVERLAP = 3

# 在同一章里待多久后，建议去看一眼中文原文
#: Time inside one chapter before the pager suggests peeking at Chinese.
SLOW_CHAPTER_SECONDS = 30 * 60

# 两个输入提示的前缀
_SEARCH_PROMPT = "搜索: "
_WORD_PROMPT = "生词: "

# 底部常驻的快捷键提示
_HINT = (
    "q退出 j/space翻页 g跳行 [/]章节 Tab目录 /搜索 n下一个 b书签 v生词 "
    "m标记 o笔记 l语言 t翻屏 T翻章 c中文"
)

# 目录浮层占屏幕宽度的比例（靠右显示），其余留给正文
_TOC_WIDTH_RATIO = 0.4
# 目录浮层底部的快捷键提示
_TOC_HINT = "↑↓ 选择  Enter 跳转  / 过滤  q/Esc 关闭"
# 笔记面板底部的快捷键提示
_NOTE_HINT = "笔记  Tab 切换焦点  Ctrl+S 保存  Esc 关闭"
# 笔记面板展开时占屏幕高度的比例（贴在下方），其余留给正文
_NOTE_PANEL_RATIO = 0.25
#: One selection may copy at most this many characters (``y`` truncates past it).
# 一次标记最多复制多少字符，超出就截断并提示（别把整章塞进引用区）
NOTE_MAX_CHARS = 2000
# 引用区的引导符，跟 Markdown 引用一样
_NOTE_QUOTE_PREFIX = "> "
# 引用区还没有内容时显示的引导语
_NOTE_QUOTE_EMPTY = "还没有引用：在正文里按 m 标记、y 复制"
# Tab 键：get_wch 多数情况返回 "\t"，个别终端上报 KEY_TAB
_TAB_KEYS = ("\t", int(getattr(curses, "KEY_TAB", 9)))
# Esc：get_wch 一般返回 "\x1b"（字符串），个别终端上报 int 27，两种都认
_ESCAPE_KEYS = ("\x1b", 27)
# Ctrl+S：同样是"字符串 / 整数"两种上报；注意 IXON 流控会吞掉它，_run 里会先关流控
_SAVE_KEYS = ("\x13", 19)

# 翻译弹窗：显示多久、占屏幕多高、底部提示语
#: Seconds the ``t`` translation popup stays on screen.
TRANSLATION_POPUP_SECONDS = 3.0
# 面板高度占屏幕的比例（贴底显示）
_TRANSLATION_POPUP_RATIO = 0.4
# 弹窗里轮询按键的间隔（毫秒）：既能立刻响应按键，又能按时自动消失
_TRANSLATION_POPUP_TICK_MS = 100
# 弹窗最后一行的说明文字
_TRANSLATION_POPUP_HINT = "翻译（临时，不缓存）· 任意键关闭"
# 抓拉丁单词（长度至少 3）用于"查词时默认选中的词"
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]{2,}")

# 关掉生词高亮时传给渲染器的空集合（避免每次新建）
#: Passed to the renderer when ``vocab.highlight_in_reader`` is off.
_EMPTY_WORDS: Set[str] = set()


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


def find_matches(lines: Sequence[str], needle: str) -> List[int]:
    """Return the indexes of every line containing *needle*, case insensitive."""
    wanted = str(needle or "")
    # 空关键词不匹配任何行
    if not wanted:
        return []
    lowered = wanted.lower()
    # 简单子串匹配（大小写不敏感）
    return [index for index, line in enumerate(lines) if lowered in line.lower()]


def mode_language(mode: str, book_language: str) -> Optional[str]:
    """Return the language *mode* needs, or ``None`` when it shows the original.

    Asking for the language the book is already written in needs no translation
    at all, and the bilingual view translates into whichever language the book is
    *not* in.
    """
    # 双语对照：翻成"书不是的那种语言"
    if mode == MODE_BOTH:
        return "en" if book_language == "zh" else "zh-CN"
    # 中文视图：书本来就是中文就不用翻
    if mode == MODE_ZH:
        return None if book_language == "zh" else "zh-CN"
    # 英文视图：书本来就是英文就不用翻
    if mode == MODE_EN:
        return None if book_language == "en" else "en"
    # 未知视图：按无需翻译处理
    return None


def detect_book_language(lines: Sequence[str], sample_lines: int = 60) -> str:
    """Detect the book's language from its opening lines."""
    # 取开头若干行拼接后交给 translator 的探测器（够代表整本书）
    return translator.detect_language("\n".join(lines[:sample_lines]))


def pick_word(line: str) -> str:
    """Return the best default word to look up on *line*.

    The longest Latin token wins, which is what a word lookup usually wants when
    the line is English prose.
    """
    # 抓出所有拉丁词
    tokens = _WORD_RE.findall(line or "")
    # 取最长的那个当默认查询词；没有就返回空串
    return max(tokens, key=len) if tokens else ""


# 句子结束标点（中英文混用）
_SENTENCE_END = "。！？!?."
# 英文单词（含撇号和连字符）
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


def sentence_around(line: str, word: str) -> str:
    """Return the sentence of *line* that contains *word*.

    Falls back to the whole line when the word is missing or the line carries no
    sentence punctuation at all.
    """
    text = str(line or "").strip()
    # 空行直接返回空
    if not text:
        return ""
    # 统一小写做定位
    needle = str(word or "").strip().lower()
    # 没给单词：整行就是"上下文"
    if not needle:
        return text
    # 找到单词在行内的位置
    position = text.lower().find(needle)
    # 找不到：退回整行
    if position < 0:
        return text
    # 往前扫，找本句的起点（上一个句号之后）
    start = 0
    for index in range(position - 1, -1, -1):
        if text[index] in _SENTENCE_END:
            start = index + 1
            break
    # 往后扫，找本句的终点（下一个句号含在内）
    end = len(text)
    for index in range(position + len(needle), len(text)):
        if text[index] in _SENTENCE_END:
            end = index + 1
            break
    # 去空白返回；万一算出空串就退回整行
    return text[start:end].strip() or text


def split_highlight(text: str, vocab_words: Set[str]) -> List[Tuple[str, bool]]:
    """Split *text* into ``(piece, highlighted)`` runs for the notebook words."""
    # 没有文本或没有生词：整段不处理
    if not text or not vocab_words:
        return [(text, False)]
    # 结果片段：(文本, 是否需要下划线)
    pieces: List[Tuple[str, bool]] = []
    # 已处理到的位置
    position = 0
    # 逐个扫英文单词
    for match in _TOKEN_RE.finditer(text):
        # 不在生词本里：跳过（它会被当作普通片段的一部分）
        if match.group(0).lower() not in vocab_words:
            continue
        # 生词前面的普通文本
        if match.start() > position:
            pieces.append((text[position : match.start()], False))
        # 生词本身
        pieces.append((match.group(0), True))
        position = match.end()
    # 最后一个生词后面的尾巴
    if position < len(text):
        pieces.append((text[position:], False))
    # 一个都没切出来时保证至少返回一段
    return pieces or [(text, False)]


# 一本书的阅读状态机：位置、视图、搜索、书签、计时
class Pager:
    """Position, view, search state, bookmarks and stopwatches for one book."""

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
        # 初始视图
        mode: str = MODE_ZH,
        # 书本身的语言
        book_language: str = "zh",
        # 已有书签
        bookmarks: Sequence[Dict[str, Any]] = (),
        target_language: str = "zh-CN",
        source_language: str = "auto",
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
        # 进入章节时自动翻译
        auto_translate_chapter: bool = False,
        # 是否高亮生词
        highlight_vocab: bool = True,
        # 查词后是否自动入库
        auto_add_on_mark: bool = True,
        # 目录条目（章节表 + 百分比），供 Tab 浮层使用
        toc_entries: Sequence[Dict[str, Any]] = (),
    ) -> None:
        # 拷贝成列表，避免外部改动影响内部状态
        self.lines = list(lines)
        self.chapters = list(chapters)
        # 每屏至少 1 行
        self.page_height = max(1, int(page_height))
        self.book_id = book_id
        self.title = title
        self.author = author
        # 视图必须是已知的三种之一，否则退回中文视图
        self.mode = mode if mode in MODE_ORDER else MODE_ZH
        self.language = book_language
        self.target_language = target_language
        self.source_language = source_language
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
        #: translate each chapter as it is entered (``translator.auto_translate_chapter``)
        # 是否进章即自动翻译
        self.auto_translate_chapter = bool(auto_translate_chapter)
        #: underline notebook words (``vocab.highlight_in_reader``)
        # 是否在正文里给生词加下划线
        self.highlight_vocab = bool(highlight_vocab)
        #: file a looked up word without asking (``vocab.auto_add_on_mark``)
        # 查词后是否免确认直接入库
        self.auto_add_on_mark = bool(auto_add_on_mark)
        #: the table of contents: ``[{"title", "line", "percentage"}, ...]``
        # 目录条目（由 toc.load_toc 备好），Tab 浮层直接读它
        self.toc = [dict(entry) for entry in toc_entries]
        #: chapters already translated or cached on demand this session
        # 本次会话已尝试过自动翻译的章节（每章最多一次）
        self.auto_translated: Set[int] = set()
        #: lowercased notebook words, underlined while drawing
        # 生词本里的小写词集合
        self.vocab_words: Set[str] = set()
        #: translation actions this session, folded into stats when it is saved
        # 本次会话用了几次翻译，退出时并入统计
        self.translations_used = 0
        # 起始位置夹到合法范围
        self.position = clamp(position, self.total)
        #: forward lines scrolled this session: the reading work actually done
        # 本次会话向前读了多少行（只统计前进，回退不抵消）
        self.lines_read = 0
        # 书签拷贝一份（深拷贝每个字典）
        self.bookmarks = [dict(mark) for mark in bookmarks]
        # 行号 -> 译文（临时翻译与缓存翻译都放这里）
        self.translations: Dict[int, str] = {}
        # 搜索命中的行号列表
        self.matches: List[int] = []
        # 当前看到第几个命中，-1 表示还没开始
        self.match_cursor = -1
        # 每章累计耗时（秒）
        self.chapter_seconds: Dict[int, float] = {}
        # -- mark mode and the note panel (Phase 1+2: UI state only) ----------
        #: mark mode is on: the cursor turns into a reverse video block
        # 是否处于标记模式（m 进入；此模式只在一屏内选字，不翻页）
        self.mark_mode = False
        #: ``(screen row, column inside that row)`` where the selection starts
        # 选区起点：屏幕行下标 + 该行内的字符下标（进入标记时落在当前屏首行行首）
        self.mark_start: Optional[Tuple[int, int]] = None
        #: ``(screen row, column)`` the selection currently reaches
        # 选区终点；与 mark_start 一起决定高亮区间（尚未扩展时两者相同）
        self.mark_end: Optional[Tuple[int, int]] = None
        #: the text copied out of the last selection with ``y``
        # 最近一次选中并复制的文字（y 写入），面板的引用区显示它
        self.note_buffer = ""
        #: notes saved this session: ``[{"quote", "text", "created"}, ...]``
        # 本次会话已保存的笔记；Phase 1+2 只存内存，落盘留给后续阶段
        self.notes: List[Dict[str, Any]] = []
        #: the note panel is expanded (``o`` toggles it)
        # 笔记面板是否展开（o 切换）；展开期间阅读区缩到上方
        self.note_panel_open = False
        #: which half of the open panel has the keyboard: ``"quote"`` or ``"edit"``
        # 面板焦点：引用区还是编辑区（Tab 切换）
        self.note_focus = "quote"
        #: the rows ``_draw`` actually put on screen last frame
        # 上一帧真正画出的可见行 ``[(源行号, 文本), ...]``；标记模式靠它定位与取词
        self.viewport: List[Tuple[int, str]] = []
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

    def needs_translation(self) -> bool:
        """Whether the current view needs a translation at all."""
        # 视图要求的语言为 None 说明显示的就是原文
        return mode_language(self.mode, self.language) is not None

    def rows_for(self, index: int) -> List[str]:
        """The screen rows one source line occupies in the current view.

        A stored empty string means the line is already covered by a paragraph
        translation above it, so it contributes no row of its own.
        """
        # 原始行
        original = self.lines[index]
        # 不需要翻译：一行就是一屏一行
        if not self.needs_translation():
            return [original]
        # 这一行有译文（可能在 translations 里）
        if index in self.translations:
            translated = self.translations[index]
            if not translated:
                # Already covered by the paragraph translated above it.  In the
                # bilingual view the source line still belongs on screen; in a
                # translated-only view it would just be a duplicate, so it is
                # dropped.
                # 空串 = 已被上一行的整段译文覆盖
                return [original] if self.mode == MODE_BOTH else []
            # 双语：原文 + 译文两行
            if self.mode == MODE_BOTH:
                return [original, translated]
            # 纯译文视图：只显示译文
            return [translated]
        # 还没有译文：先显示原文
        return [original]

    def _row_texts(self, index: int, width: Optional[int]) -> List[str]:
        """Every screen row one source line owns, from its top downwards.

        A source line can produce several rows: the bilingual view adds the
        translation, and a long paragraph is wrapped by :func:`_wrap_line`, which
        knows a CJK character is two columns wide.  An empty list means the line
        contributes nothing -- the translated-only view drops a line whose
        paragraph was already translated above it.
        """
        # 一个源行在当前视图下可能拆成多段显示文本（双语是原文 + 译文）
        texts = self.rows_for(index)
        # 没有宽度信息（纯数据场景）：一段文本就是一屏行
        if width is None:
            return list(texts)
        # 有宽度：每段各自按显示宽度折行，再依次拼起来
        chunks: List[str] = []
        for text in texts:
            chunks.extend(_wrap_line(text, int(width)))
        return chunks

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
    def translate_screen(
        self, first: int, last: int, progress=None, target: Optional[str] = None
    ) -> int:
        """Translate every paragraph touched by ``[first, last]`` into memory.

        Paragraphs, not lines, are the unit: the back-end then sees whole sentences
        instead of a pile of fragments, and the bilingual view can pair one Chinese
        paragraph with one English paragraph.  Returns how many paragraphs landed.

        *target* overrides the language the current view would ask for, which is
        what lets ``t`` pop up a translation without switching the view first.
        """
        # 没显式指定就用当前视图该翻成的语言；None 表示这个视图不需要翻译
        resolved = mode_language(self.mode, self.language) if target is None else target
        if resolved is None:
            return 0
        # 划出与屏幕相交的段落区间
        spans = translator.paragraph_spans(self.lines, first, last)
        if not spans:
            return 0
        # 逐段翻译（只进内存，不缓存）
        english = translator.translate_paragraphs(
            translator.paragraph_texts(self.lines, spans),
            target=resolved,
            source=self.source_language,
            progress=progress,
        )
        # 把结果挂到对应行号上
        self.translations.update(translator.map_paragraphs(spans, english))
        # 返回翻译了几段
        return len(spans)

    def load_chapter(self, chapter_index: int) -> int:
        """Merge a cached chapter translation into the view.

        Returns how many source lines the cached chapter covers.
        """
        # 从磁盘上的章节缓存读出"行号 -> 译文"
        mapping = translator.load_chapter_map(self.book_id, int(chapter_index))
        if not mapping:
            return 0
        # 合并进当前译文字典
        self.translations.update(mapping)
        return len(mapping)

    def word_target(self) -> str:
        """The language a single word lookup should aim for."""
        # 当前视图要翻成什么语言；若视图就是原文则用配置的目标语言
        return mode_language(self.mode, self.language) or self.target_language

    def set_vocab_words(self, words: Iterable[str]) -> None:
        """Replace the set of notebook words that get underlined while drawing."""
        # 统一小写并存成集合，绘制时查得快
        self.vocab_words = {
            str(word).strip().lower() for word in words if str(word).strip()
        }

    # -- chapter stopwatch ------------------------------------------------
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

    def slow_chapter_hint(self) -> str:
        """The nudge shown after a long stretch inside a single chapter."""
        # 已经是中文视图：不用提醒
        if self.mode == MODE_ZH:
            return ""
        # 还没待够久：不提醒
        if self.chapter_elapsed() < SLOW_CHAPTER_SECONDS:
            return ""
        # 提醒用户切回中文看看
        return "这一章读了很久，要不要看一眼中文？按 c 切换"

    # -- transient messages ----------------------------------------------
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


def _mark_clamp(
    rows: Sequence[Tuple[int, str]], row: int, col: int
) -> Tuple[int, int]:
    """Clamp a mark cursor ``(row, col)`` into the rows actually on screen.

    *col* is a **character** index inside the row's text, not a display column, so
    a CJK character and a Latin letter both count as one step -- the reverse video
    highlight then covers the right cells because ``addstr`` knows the real width.
    """
    # 一屏都没有（空书或空屏）：光标钉在左上角
    if not rows:
        return 0, 0
    # 行夹进 [0, 可见行数 - 1]
    row = max(0, min(int(row), len(rows) - 1))
    # 列夹进这一行 [0, 字符数 - 1]（空行只有第 0 列可选）
    col = max(0, min(int(col), max(0, len(rows[row][1]) - 1)))
    return row, col


def _mark_move(
    rows: Sequence[Tuple[int, str]], row: int, col: int, key: Any
) -> Tuple[int, int]:
    """Move the mark cursor one step for *key*, clamped to what is on screen.

    Only h/j/k/l and the arrow keys move; every other key leaves the cursor where
    it is.  Page keys are deliberately absent: mark mode never scrolls, so a
    selection can only ever span the screen it started on.
    """
    # 先把起点夹合法，免得后面越界
    row, col = _mark_clamp(rows, row, col)
    # 左：h 或 ←
    if key in ("h", curses.KEY_LEFT):
        col -= 1
    # 右：l 或 →
    elif key in ("l", curses.KEY_RIGHT):
        col += 1
    # 上：k 或 ↑
    elif key in ("k", curses.KEY_UP):
        row -= 1
    # 下：j 或 ↓
    elif key in ("j", curses.KEY_DOWN):
        row += 1
    # 移完再夹一次：上下跨行时列可能落到新行长之外
    return _mark_clamp(rows, row, col)


def _mark_normalize(
    start: Tuple[int, int], end: Tuple[int, int]
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Order two mark corners into ``(top, bottom)`` reading order.

    Marking works in both directions, so every consumer normalises first: the
    highlight, the extraction and the truncation then only deal with one order.
    """
    # 先比行号，行号相同再比列号；小的那个算"左上"
    if (start[0], start[1]) <= (end[0], end[1]):
        return start, end
    return end, start


def _mark_selection(
    rows: Sequence[Tuple[int, str]],
    start: Tuple[int, int],
    end: Tuple[int, int],
    limit: int = NOTE_MAX_CHARS,
) -> Tuple[str, bool]:
    """Return ``(text, truncated)`` for the screen range *start* .. *end*.

    The rows are **screen** rows, so a wrapped paragraph arrives as several chunks.
    Chunks that belong to the same source line are glued back together and a
    newline is only inserted where the source line actually changes, which is what
    makes the copied text read like the book rather than like the terminal.
    *limit* caps the result (``0`` means no cap) and *truncated* says whether it bit.
    """
    # 没有可见行：没有可复制的内容
    if not rows:
        return "", False
    # 排成左上 -> 右下，方向无关
    (first_row, first_col), (last_row, last_col) = _mark_normalize(start, end)
    # 行号夹进真实范围，防止越界切片
    first_row = max(0, min(first_row, len(rows) - 1))
    last_row = max(0, min(last_row, len(rows) - 1))
    # 收集 (源行号, 片段)：同一源行的折行片段要接着拼，不能插换行
    pieces: List[Tuple[int, str]] = []
    for row in range(first_row, last_row + 1):
        source_line, text = rows[row]
        # 首尾同一行：只取中间那段（末列包含在内）
        if row == first_row == last_row:
            fragment = text[first_col : last_col + 1]
        # 选区的第一行：从起点列取到行尾
        elif row == first_row:
            fragment = text[first_col:]
        # 选区的最后一行：从行首取到终点列
        elif row == last_row:
            fragment = text[: last_col + 1]
        # 中间行：整行都要
        else:
            fragment = text
        # 上一段就是同一源行：直接接上（说明这是同一个段落的折行）
        if pieces and pieces[-1][0] == source_line:
            pieces[-1] = (source_line, pieces[-1][1] + fragment)
        else:
            pieces.append((source_line, fragment))
    # 源行之间用换行连接（同源行的折行片段前面已经拼好）
    text = "\n".join(fragment for _line, fragment in pieces)
    # 超长就截断，并告诉调用方"截过了"
    if limit and len(text) > limit:
        return text[:limit], True
    return text, False


def _mark_row_span(
    row: int, text: str, start: Tuple[int, int], end: Tuple[int, int]
) -> Optional[Tuple[int, int]]:
    """The ``(first, last)`` character indices to reverse on *row*, or ``None``.

    ``None`` means this screen row is not part of the selection at all, so the
    caller can fall back to the ordinary drawing path.  Indices are inclusive and
    clamped to the row, so a selection that starts on a longer line still covers
    the whole of a shorter one.
    """
    # 排好序
    (first_row, first_col), (last_row, last_col) = _mark_normalize(start, end)
    # 这一行完全在选区之外
    if row < first_row or row > last_row:
        return None
    # 单行选区：只反色这一段
    if first_row == last_row:
        return first_col, last_col
    # 选区的第一行：从起点列反色到行尾
    if row == first_row:
        return first_col, max(0, len(text) - 1)
    # 选区的最后一行：从行首反色到终点列
    if row == last_row:
        return 0, last_col
    # 中间行：整行反色
    return 0, max(0, len(text) - 1)


def _draw_text(
    stdscr: Any, row: int, column: int, text: str, attr: int, vocab_words: Set[str]
) -> None:
    """Write one line, underlining every word already in the vocabulary notebook.

    The pieces are written from a moved cursor rather than fixed columns, so the
    alignment stays right when the line also holds double width CJK characters.
    """
    # 按生词切成若干片段
    pieces = split_highlight(text, vocab_words)
    # 没有生词（一段）：整行一次写完
    if len(pieces) <= 1:
        _addstr(stdscr, row, column, text, attr)
        return
    try:
        # 把光标移动到行首，后面按片段连续写
        stdscr.move(row, column)
    except curses.error:
        return
    for piece, highlighted in pieces:
        try:
            # 生词片段加下划线属性
            stdscr.addstr(
                piece, (attr | curses.A_UNDERLINE) if highlighted else attr
            )
        except curses.error:
            # 某段写失败就放弃这一行剩下的内容
            return


def _draw_marked_row(
    stdscr: Any,
    row: int,
    column: int,
    text: str,
    attr: int,
    span: Optional[Tuple[int, int]],
    vocab_words: Set[str],
) -> None:
    """Draw one screen row, reversing the characters covered by *span*.

    The row is written as up to three pieces (before / selected / after) so only
    the marked part is reversed.  Offsets are counted in **terminal columns** with
    :func:`_text_width`, which is what keeps the pieces lined up when the selection
    starts after a run of double width CJK characters.
    """
    # 这一行不在选区里：走普通绘制
    if span is None:
        _draw_text(stdscr, row, column, text, attr, vocab_words)
        return
    # 按字符下标切三段（末列包含在选中段里）
    first, last = span
    before = text[:first]
    selected = text[first : last + 1]
    after = text[last + 1 :]
    # 前段：正常属性（生词下划线照旧）
    if before:
        _draw_text(stdscr, row, column, before, attr, vocab_words)
    # 选中段：反色。反色块本身就是那条"光标"，所以不用再去动真实光标
    selected_column = column + _text_width(before)
    if selected:
        _addstr(stdscr, row, selected_column, selected, attr | curses.A_REVERSE)
    # 后段：正常属性（从选中段之后接着写）
    if after:
        _draw_text(
            stdscr,
            row,
            selected_column + _text_width(selected),
            after,
            attr,
            vocab_words,
        )


def _note_status(pager: Pager) -> str:
    """The folded note indicator: how many notes there are and how to open the panel.

    Shown on the message row while the panel is closed, so the note count stays
    visible without spending a third status row on it.
    """
    # 折叠状态：几条笔记 + 展开键（_HINT 里也还有一遍 o笔记）
    return "📝 {}条笔记 | 按o展开".format(len(pager.notes))


def _message_row(pager: Pager, room: int) -> str:
    """The bottom row: a transient message, else hints plus the long chapter nudge.

    *room* counts terminal columns, not characters, so the row is measured the
    same way the terminal draws it.
    """
    # 有临时消息就先显示它
    message = pager.current_message()
    if message:
        # 按显示宽度裁到整行再右填充（填充用来盖掉上一帧的残留）
        return _pad_line(message, room)
    # 否则显示"快捷键提示 [+ 长时间没换章的提醒]"
    nudge = pager.slow_chapter_hint()
    if not nudge:
        # 折叠的笔记面板：把"几条笔记 + 怎么展开"并进提示行（面板展开时另画自己的提示）
        return _pad_line(_note_status(pager) + " · " + _HINT, room)
    # 空间够就两个都显示（按显示列数算：一个汉字占两列）
    if _text_width(_HINT) + _text_width(nudge) + 3 <= room:
        return _pad_line(_HINT + "   " + nudge, room)
    # 空间不够就只显示提醒（本身太长时按列裁）
    return _pad_line(nudge, room)


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
    if token == "mode":
        return MODE_LABELS.get(pager.mode, pager.mode)
    if token == "duration":
        return "本章 {}".format(format_duration(pager.chapter_elapsed()))
    if token == "elapsed":
        return "本次 {}".format(format_duration(pager.session_elapsed()))
    if token == "streak":
        return "连续 {} 天".format(pager.streak)
    if token == "bookmarks":
        return "书签 {}".format(len(pager.bookmarks))
    if token == "vocab":
        return "生词 {}".format(len(pager.vocab_words))
    if token == "translations":
        return "翻译 {}".format(pager.translations_used)
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
    stdscr: Any, pager: Pager, moment: datetime, height: int, width: int
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
    # 最后一行：消息/快捷键提示（暗色）
    _addstr(stdscr, height - 1, 0, _message_row(pager, room), curses.A_DIM)


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
    # 关掉高亮时传空集合，_draw_text 就不做生词切分了
    words = pager.vocab_words if pager.highlight_vocab else _EMPTY_WORDS
    # 清屏，接着重画整帧
    stdscr.erase()
    # 上一条屏幕行属于哪个源行，用来判断"这是不是某个源行的第一屏行"
    previous_index: Optional[int] = None
    # 这一帧真正要画出来的可见行，顺手记下来给标记模式定位光标与取词用
    rows = pager.visible_rows(text_rows, text_width)
    pager.viewport = list(rows)
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
        # 标记模式：把选中的那段反色画出来（反色块本身就是那条"光标"）
        if pager.mark_mode and pager.mark_start and pager.mark_end:
            span = _mark_row_span(screen_row, text, pager.mark_start, pager.mark_end)
            _draw_marked_row(stdscr, screen_row, 1, text, attr, span, words)
        else:
            _draw_text(stdscr, screen_row, 1, text, attr, words)
        # 记下这条屏幕行属于哪个源行，供下一轮判断
        previous_index = index
    # 最后画状态栏两行
    _draw_status(stdscr, pager, moment, height, width)
    # 提交这一帧
    stdscr.refresh()


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


def _confirm(stdscr: Any, title: str, body: Sequence[str]) -> bool:
    """Show a small centred popup and return whether the user said yes."""
    height, width = stdscr.getmaxyx()
    # 弹窗内每行最多的显示列数
    limit = max(12, width - 6)
    # 标题 + 正文 + 空行 + 操作提示（按显示宽度裁：一个汉字占两列）
    lines = [_clip_line(line, limit) for line in [title] + list(body)]
    lines.append("")
    lines.append("[y] 加入生词本    其他键 取消")
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


def _screen_range(stdscr: Any, pager: Pager) -> Tuple[int, int]:
    """The half open range of source lines currently on screen.

    The end comes from the rows that actually fit, so a wrapped paragraph counts
    for as many source lines as it takes up on the terminal rather than one.
    """
    height, width = stdscr.getmaxyx()
    # 正文区屏幕行数（减去状态栏两行）
    rows = max(1, height - _STATUS_ROWS)
    # 正文区列数（第 0 列留给书签位）
    text_width = max(1, width - 1)
    # 这一屏真实画到的源行（长段会折成多屏行）
    visible = pager.visible_rows(rows, text_width)
    # 一屏都填不满（空书 / 已在书末）：退化成空区间
    if not visible:
        return pager.position, pager.position
    # 返回 [当前位置, 最后一个已显示源行 + 1) 的半开区间
    return pager.position, min(max(index for index, _ in visible) + 1, pager.total)


def _progress_text(done: int, total: int, width: int = 16) -> str:
    """Render a compact progress bar, e.g. ``[####----]  3/8``."""
    if total <= 0:
        return ""
    # 按比例算出实心格数
    filled = int(round(width * min(max(done, 0), total) / float(total)))
    return "[{}{}]  {}/{}".format("#" * filled, "-" * (width - filled), done, total)


def _draw_progress(stdscr: Any, chapter_index: int, done: int, total: int) -> None:
    """Paint the translation progress bar on the message row."""
    height, width = stdscr.getmaxyx()
    text = "正在翻译第 {} 章  {} ".format(
        chapter_index + 1, _progress_text(done, total)
    )
    # 画在最后一行，反白显示
    _addstr(stdscr, height - 1, 0, text[: max(0, width - 1)], curses.A_REVERSE)
    stdscr.refresh()


def _wrap_text(text: str, width: int, limit: int) -> List[str]:
    """Wrap *text* to *width* columns, keeping at most *limit* lines.

    Blank lines between paragraphs are preserved, which is what makes the popup
    read like prose instead of one wall of text.  Wrapping itself goes through
    :func:`_wrap_line`, so double width CJK characters are counted correctly.
    """
    # 攒出来的屏幕行
    lines: List[str] = []
    # 空行也要保留：段落之间那一行空白正是可读性的来源
    for paragraph in str(text or "").split("\n"):
        for line in _wrap_line(paragraph, max(1, int(width))):
            # 到上限就停，超出部分不画（弹窗不做滚动）
            if len(lines) >= max(1, int(limit)):
                return lines
            lines.append(line)
    return lines


def _first_line(text: str) -> str:
    """Return the first non-blank line of *text* (used by the tiny-screen fallback)."""
    # 逐行找第一个有内容的
    for line in str(text or "").split("\n"):
        if line.strip():
            return line.strip()
    # 全是空白：返回空串
    return ""


def _screen_translation_text(pager: Pager, first: int, last: int) -> str:
    """Join the translations of the on-screen paragraphs, blank line between them.

    A paragraph's translation is stored on its **first** line while the rest of
    the paragraph maps to an empty string ("already covered by the paragraph
    above"), so dropping the empties both dedupes and restores the paragraphs.
    """
    # 收集 [first, last) 里真正带译文的那几行
    pieces = [
        str(pager.translations.get(index) or "")
        for index in range(max(0, first), min(int(last), pager.total))
    ]
    # 段落之间空一行再拼，末尾空白去掉
    return "\n\n".join(piece for piece in pieces if piece).strip()


def _translation_popup_layout(height: int, width: int) -> Optional[Tuple[int, int, int]]:
    """Return ``(top, rows, room)`` for the translation popup, or ``None``.

    The panel sticks to the bottom of the screen, keeps one row for its own hint
    and leaves at least three rows of reading text visible above it, so it never
    covers the whole page.  *room* is the usable column count -- the very last
    column is left alone because curses cannot write to the bottom right cell.
    """
    # 太矮 / 太窄就放下面板（调用方会退化成一行短消息）
    if height < 8 or width < 8:
        return None
    # 面板高度 = 屏幕的 40%，再夹一层：正文至少留 3 行
    rows = max(3, int(round(height * _TRANSLATION_POPUP_RATIO)))
    rows = min(rows, max(3, height - 3))
    # 贴着屏幕底部
    top = height - rows
    # 可用列数：留出最后一列，避开 curses 右下角限制
    room = max(1, width - 1)
    return top, rows, room


def _show_translation_popup(
    stdscr: Any, pager: Pager, text: str, seconds: float = TRANSLATION_POPUP_SECONDS
) -> None:
    """Show *text* in a panel at the bottom of the screen for a few seconds.

    Any key dismisses it early, and it disappears on its own after *seconds*, so
    the reading loop is never stuck behind it.  A screen too small for the panel
    degrades to the usual one-line message instead of drawing a squashed box.
    """
    # 终端尺寸
    height, width = stdscr.getmaxyx()
    layout = _translation_popup_layout(height, width)
    # 屏幕太小：退回一行短消息
    if layout is None:
        pager.say(_first_line(text))
        return
    # 拆出位置、高度与可用列数
    top, rows, room = layout
    try:
        # 走 _sub_window：真终端是 curses.newwin，测试换成假窗口
        window = _sub_window(stdscr, rows, width, top, 0)
    except curses.error:
        pager.say(_first_line(text))
        return
    # 先把正文那一帧画出来（主窗口先刷），面板随后叠上去（子窗口后刷）
    _draw(stdscr, pager, _now())
    # 画译文；最后一行留给提示
    lines = _wrap_text(text, room, rows - 1)
    window.erase()
    for offset, line in enumerate(lines):
        _addstr(window, offset, 0, line, curses.A_NORMAL)
    _addstr(
        window, rows - 1, 0, _pad_line(_TRANSLATION_POPUP_HINT, room), curses.A_DIM
    )
    window.refresh()
    # 展示期间改成短轮询：按键能立刻关掉，时间到也能自己消失
    stdscr.timeout(_TRANSLATION_POPUP_TICK_MS)
    deadline = time.monotonic() + max(0.0, float(seconds))
    try:
        while time.monotonic() < deadline:
            try:
                # 等一个键（超时抛 curses.error，回到 while 再看时间）
                stdscr.get_wch()
            except curses.error:
                continue
            except KeyboardInterrupt:
                # Ctrl-C：关掉面板，把"退出阅读"留给主循环
                break
            # 任意键都立刻关掉面板
            break
    finally:
        # 恢复主循环的轮询间隔
        stdscr.timeout(_TICK_MS)
        # 交回子窗口
        del window
        # 面板盖住的正文要让主窗口重画
        try:
            stdscr.touchwin()
        except curses.error:
            pass


def _translate_screen_range(pager: Pager, first: int, last: int) -> str:
    """Translate the paragraphs on screen into memory; returns a status sentence."""
    # 当前视图就是原文：没什么可翻的
    if not pager.needs_translation():
        return "当前视图就是原文，无需翻译"
    try:
        count = pager.translate_screen(first, last)
    except translator.TranslationUnavailable as exc:
        # 后端不可达
        return "翻译不可用：{}".format(exc)
    except translator.TranslationError as exc:
        # 其它翻译错误
        return "翻译失败：{}".format(exc)
    # 一段都没翻出来
    if not count:
        return "这些段落还没有译文"
    # 记一次翻译使用
    pager.translations_used += 1
    return "已翻译 {} 段（临时，不缓存）".format(count)


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


def _enter_mark(pager: Pager) -> None:
    """``m``: start marking from the top left of the screen.

    Marking is deliberately screen bound: the selection can never scroll past the
    screen it started on, which keeps the coordinates plain ``(row, col)`` pairs
    into :attr:`Pager.viewport` and the extraction a pure function over them.
    """
    # 一屏都没有可选中的文字（空书）：没法标
    if not pager.viewport:
        pager.say("这一屏没有可选中的文字")
        return
    # 进入标记模式，光标落在当前屏首行行首（反色方块就是它）
    pager.mark_mode = True
    pager.mark_start = (0, 0)
    pager.mark_end = (0, 0)
    pager.say("标记：h/j/k/l 或方向键选字 · y 复制 · Esc 取消")


def _handle_mark_key(pager: Pager, key: Any) -> None:
    """Act on one key while marking: move, copy or cancel -- never scroll."""
    # Esc：取消标记，回阅读
    if key in _ESCAPE_KEYS:
        pager.mark_mode = False
        pager.mark_start = None
        pager.mark_end = None
        pager.say("已取消标记")
        return
    # y：把选中的文字收进引用缓冲区，然后回阅读
    if key == "y":
        _copy_selection(pager)
        return
    # h/j/k/l 或方向键：移动光标扩展选区
    if key in (
        "h",
        "j",
        "k",
        "l",
        curses.KEY_LEFT,
        curses.KEY_RIGHT,
        curses.KEY_UP,
        curses.KEY_DOWN,
    ):
        # 起点还没设（理论上不会发生）：先补一个再动
        if pager.mark_end is None:
            pager.mark_end = pager.mark_start or (0, 0)
        pager.mark_end = _mark_move(pager.viewport, *pager.mark_end, key)


def _copy_selection(pager: Pager) -> None:
    """``y``: put the marked text into the quote buffer and leave mark mode."""
    # 起点或终点缺失（理论上不会发生）：直接退出标记
    if pager.mark_start is None or pager.mark_end is None:
        pager.mark_mode = False
        return
    # 提取选区文字（超过上限会自动截断）
    text, truncated = _mark_selection(
        pager.viewport, pager.mark_start, pager.mark_end
    )
    # 去掉尾部换行与空白（选到下一行行首时会带出一个换行，引用里不需要它）
    text = text.rstrip()
    # 选区里全是空白：提示一句，留在标记模式等用户换一段
    if not text:
        pager.say("选中的是空白，换一段再按 y")
        return
    # 存进引用缓冲区并退出标记模式
    pager.note_buffer = text
    pager.mark_mode = False
    pager.mark_start = None
    pager.mark_end = None
    # 明确告诉用户复制了多少字（被截断时也要说清楚）
    if truncated:
        pager.say(
            "已复制 {} 字（超过 {} 已截断）· 按 o 打开笔记面板".format(
                len(text), NOTE_MAX_CHARS
            )
        )
    else:
        pager.say("已复制 {} 字 · 按 o 打开笔记面板".format(len(text)))


def _note_panel_layout(height: int, width: int) -> Optional[Tuple[int, int, int]]:
    """Return ``(text_rows, quote_rows, edit_rows)`` for the note panel, or ``None``.

    The panel takes the bottom quarter of the screen (never fewer than four rows),
    keeps one row for its own hint, and splits what is left between the read only
    quote area and the editor.  ``None`` means the screen cannot hold a usable panel
    at all, so the caller just says so instead of drawing a mess.
    """
    # 太矮 / 太窄：连"引用 1 行 + 编辑 1 行 + 提示 1 行"都摆不下
    if height < 8 or width < 8:
        return None
    # 面板高度 = 屏幕的 25%，再夹一层：正文至少留 3 行
    panel_rows = max(4, int(round(height * _NOTE_PANEL_RATIO)))
    panel_rows = min(panel_rows, max(4, height - 3))
    # 正文区 = 总高 - 面板高度
    text_rows = height - panel_rows
    # 面板内容区：扣掉它自己那一行提示
    inner = panel_rows - 1
    # 引用区占一半（向下取整），编辑区拿剩下的（多一行，写起来舒服些）
    quote_rows = max(1, inner // 2)
    edit_rows = max(1, inner - quote_rows)
    return text_rows, quote_rows, edit_rows


def _sub_window(
    stdscr: Any, nlines: int, ncols: int, begin_y: int, begin_x: int
) -> Any:
    """Create one of the note panel's sub windows.

    ``curses.newwin`` is the real API -- a ``curses.window`` object has **no**
    ``newwin`` method (only ``derwin``), which is why this indirection exists:
    it is the module level call in production and a seam the tests can replace
    with a fake window.
    """
    # 真终端上就是 curses 的模块级 newwin
    return curses.newwin(nlines, ncols, begin_y, begin_x)


def _note_panel(stdscr: Any, pager: Pager) -> None:
    """``o``: write a note beside the text, quoting the copied selection.

    A modal mini loop in the same style as the table of contents overlay: the screen
    is repainted from the main thread, nothing is spawned and every key is read
    here.  The bottom quarter holds a read only quote area and a
    :class:`curses.textpad.Textbox`; ``Tab`` swaps the focus, ``Ctrl-S`` stores the
    note and ``Esc`` closes the panel.
    """
    # 终端尺寸
    height, width = stdscr.getmaxyx()
    # 算面板布局；屏幕太小就干脆不弹
    layout = _note_panel_layout(height, width)
    if layout is None:
        pager.say("屏幕太小，放不下笔记面板（至少 8 行 8 列）")
        return
    # 拆出三块高度
    text_rows, quote_rows, edit_rows = layout
    # 两个子窗口：上引用、下编辑（编辑区必须是真窗口，Textbox 要读写它的格子）
    # 走 _sub_window 而不是直接 curses.newwin：留一个测试能替换的接缝
    try:
        quote_win = _sub_window(stdscr, quote_rows, width, text_rows, 0)
        edit_win = _sub_window(stdscr, edit_rows, width, text_rows + quote_rows, 0)
    except curses.error:
        pager.say("屏幕太小，放不下笔记面板")
        return
    # 只借 Textbox 的"按键 -> 窗口内容"编辑动作，绝不调用它那个阻塞的 edit()
    editor = curses.textpad.Textbox(edit_win)
    # 面板展开期间，折叠提示让位给面板自己的提示
    pager.note_panel_open = True
    # 打开时焦点默认在编辑区（引用区只是只读展示）
    pager.note_focus = "edit"
    # 模态：阻塞等键；退出时在 finally 里恢复主循环的 1 秒轮询
    stdscr.timeout(-1)
    try:
        while True:
            # 重画面板这一帧
            _draw_note_panel(stdscr, pager, quote_win, edit_win, text_rows)
            try:
                # 等一个按键（模态，一直等）
                key = stdscr.get_wch()
            except curses.error:
                # 少见的瞬时错误：重画再等
                continue
            except KeyboardInterrupt:
                # Ctrl-C：关面板回阅读
                return
            # Esc：关面板回阅读
            if key in _ESCAPE_KEYS:
                return
            # Ctrl+S：把"引用 + 编辑区内容"存成一条笔记
            if key in _SAVE_KEYS:
                _save_note(pager, editor)
                continue
            # Tab：在引用区 / 编辑区之间切换焦点
            if key in _TAB_KEYS:
                pager.note_focus = "quote" if pager.note_focus == "edit" else "edit"
                continue
            # 焦点不在编辑区：只读的引用区不接受文字输入
            if pager.note_focus != "edit":
                continue
            # 交给 Textbox：退格、左右光标、回车换行都由它的键绑定负责
            code = _note_validate(key)
            if code is None:
                continue
            editor.do_command(code)
    finally:
        # 恢复主循环的轮询间隔，否则关面板后界面会卡在阻塞读上
        stdscr.timeout(_TICK_MS)
        # 面板已折叠
        pager.note_panel_open = False
        # 交回两个子窗口（与 _confirm 里 del window 同款写法）
        del quote_win, edit_win
        # 子窗口盖住的正文要主窗口重画
        try:
            stdscr.touchwin()
        except curses.error:
            pass


def _note_validate(key: Any) -> Optional[int]:
    """Turn one ``get_wch`` result into the code :meth:`Textbox.do_command` expects.

    This is the text box's *validator*: the stock widget maps ``Enter`` onto Ctrl-G,
    which ends the edit and hands the text back, whereas here ``Enter`` becomes the
    ``NL`` command so it starts a **new line** instead of submitting.  Saving is an
    explicit key (``Ctrl-S``), so no editor keystroke can close the panel by
    accident.  ``None`` means "a key the editor does not understand".
    """
    # 特殊键（方向键、Home 等）本来就是 int：直接用
    if isinstance(key, int):
        # 回车（终端可能报 KEY_ENTER / 10 / 13）：统一走 NL 分支，实现"回车换行"
        if key in (curses.KEY_ENTER, 10, 13):
            return curses.ascii.NL
        return int(key)
    # 单字符：换成码点（do_command 只认 int）
    if isinstance(key, str) and len(key) == 1:
        code = ord(key)
        # \r（13）也算回车，落进同一个 NL 分支
        if code == 13:
            return curses.ascii.NL
        return code
    # 其它情况（不该出现的组合键字符串）：忽略
    return None


def _save_note(pager: Pager, editor: Any) -> None:
    """Store the current quote plus whatever the editor holds as one note."""
    # 收集编辑区内容（Textbox 自己按行拼好，会剥掉行尾空白）
    try:
        text = str(editor.gather()).strip("\n").strip()
    except curses.error:
        text = ""
    # 既没有引用也没写正文：没什么可存的，提醒一句就好
    if not text and not pager.note_buffer:
        pager.say("先按 m 标记一段文字，或在编辑区写点什么，再按 Ctrl+S")
        return
    # 存一条笔记：引用 + 正文 + 时间戳（时间戳格式与仓库其它地方一致）
    pager.notes.append(
        {"quote": pager.note_buffer, "text": text, "created": _iso(_now())}
    )
    # 存完清空引用与编辑区，方便接着写下一条
    pager.note_buffer = ""
    _clear_editor(editor)
    pager.say("已保存（共 {} 条笔记）".format(len(pager.notes)))


def _clear_editor(editor: Any) -> None:
    """Blank the text box so the next note starts from an empty line."""
    try:
        # 清掉窗口内容并把光标放回左上角
        editor.win.erase()
        editor.win.move(0, 0)
        editor.win.refresh()
    except curses.error:
        # 窗口已失效（比如正在 resize）：忽略
        pass


def _draw_quote(window: Any, quote: str) -> None:
    """Paint the read only quote area: ``"> "`` plus the copied selection."""
    # 子窗口尺寸
    rows, cols = window.getmaxyx()
    # 没有引用时给一句引导语，别留一片空白
    text = quote if quote else _NOTE_QUOTE_EMPTY
    # 折行按显示宽度算（汉字占 2 列），并给 "> " 和最后一列各留位置
    width = max(1, cols - len(_NOTE_QUOTE_PREFIX) - 1)
    lines = _wrap_line(text, width)
    # 引用区放不下就只画前几行（Phase 1+2 不做引用区滚动）
    for offset, line in enumerate(lines[:rows]):
        _addstr(window, offset, 0, _NOTE_QUOTE_PREFIX + line, curses.A_DIM)


def _draw_note_panel(
    stdscr: Any, pager: Pager, quote_win: Any, edit_win: Any, text_rows: int
) -> None:
    """Repaint one frame of the panel: the text above, quote then editor below.

    The main window is refreshed **before** the two sub windows: ``stdscr.erase``
    touches the rows the panel covers, so painting the panel afterwards is what lets
    it win over the blank cells underneath instead of being wiped by them.
    """
    # 主窗口尺寸
    height, width = stdscr.getmaxyx()
    # 正文区可用宽度（第 0 列留给书签位）
    text_width = max(1, width - 1)
    # 先清主窗口，再画缩小后的正文
    stdscr.erase()
    for screen_row, (_, text) in enumerate(
        pager.visible_rows(max(1, text_rows), text_width)
    ):
        # 写笔记时正文不加任何高亮，专心看引用与编辑区
        _addstr(stdscr, screen_row, 1, text, curses.A_NORMAL)
    # 最后一行是面板自己的快捷键提示（留出最后一列，避开 curses 右下角限制）
    room = max(0, width - 1)
    if room > 0:
        _addstr(stdscr, height - 1, 0, _pad_line(_NOTE_HINT, room), curses.A_DIM)
    # 主窗口先刷；它那几行里被面板盖住的部分稍后由子窗口刷回来
    stdscr.refresh()
    # 引用区：只读灰字
    quote_win.erase()
    _draw_quote(quote_win, pager.note_buffer)
    quote_win.refresh()
    # 编辑区的内容由 Textbox 维护，这里只把它刷到屏幕上
    edit_win.refresh()


def _cycle_mode(stdscr: Any, pager: Pager) -> None:
    """``l``: cycle 中文 -> 英文 -> 双语对照, translating the screen as needed."""
    order = MODE_ORDER
    # 在三种视图里循环切换
    pager.mode = order[(order.index(pager.mode) + 1) % len(order)]
    # 切完立刻把屏幕上需要的段落翻出来
    first, last = _screen_range(stdscr, pager)
    pager.say(
        "视图：{} · {}".format(
            MODE_LABELS[pager.mode], _translate_screen_range(pager, first, last)
        )
    )


def _translation_ready() -> Tuple[bool, str]:
    """Whether the configured engine can be used, and why not when it cannot.

    Checked *before* a request goes out, so an unconfigured engine shows the
    actionable "run ``werd config translate``" hint instead of a provider error.
    """
    try:
        # engine_ready 会自己读设置，这里不用再传一遍
        return translator.engine_ready()
    except translator.TranslationError as exc:
        # 配置本身坏了（比如 TOML 写错）：也算"没配好"，给可操作的提示
        return False, str(exc)


def _translate_screen(stdscr: Any, pager: Pager) -> None:
    """``t``: translate what is on screen and pop the result up for a few seconds.

    The translation is still merged into ``Pager.translations`` (so switching to
    the bilingual view afterwards is instant), but the point of ``t`` is the
    popup: a quick look that does not change the view you are reading in.
    """
    # 引擎没配好：直接告诉用户跑哪条命令，别让请求先失败
    ready, reason = _translation_ready()
    if not ready:
        pager.say("未配置翻译引擎：运行 werd config translate（{}）".format(reason))
        return
    # 只处理当前一屏
    first, last = _screen_range(stdscr, pager)
    # 不管当前是哪个视图，都翻成"另一种语言"（中文书 -> 英文，英文书 -> 中文）
    target = mode_language(MODE_BOTH, pager.language)
    if target is None:
        # 理论上 MODE_BOTH 总有目标；真取不到就什么都不做
        pager.say("这些段落无需翻译")
        return
    try:
        # 显式给 target：当前视图是原文时也要能翻（比如中文书的中文视图）
        count = pager.translate_screen(first, last, target=target)
    except translator.TranslationUnavailable as exc:
        # 后端不可达
        pager.say("翻译不可用：{}".format(exc))
        return
    except translator.TranslationError as exc:
        # 其它翻译错误
        pager.say("翻译失败：{}".format(exc))
        return
    # 一段都没翻出来
    if not count:
        pager.say("这些段落还没有译文")
        return
    # 记一次翻译使用
    pager.translations_used += 1
    # 把这一屏的译文收拢成一段文字弹出来
    text = _screen_translation_text(pager, first, last)
    if not text:
        # 译文是空的（后端返回空串）：退化成一行提示，别弹一个空面板
        pager.say("已翻译 {} 段（临时，不缓存）".format(count))
        return
    _show_translation_popup(stdscr, pager, text)


def _translate_chapter(stdscr: Any, pager: Pager) -> None:
    """``T``: translate and cache the whole chapter, showing a progress bar.

    A cached chapter is loaded straight from disk, which is what makes a second
    visit free and an interrupted run resumable.
    """
    # 当前章节下标（-1 时按 0 处理）
    index = max(0, pager.current_chapter())
    try:
        settings = translator.load_settings()
        # 先看有没有缓存
        cached = translator.get_cached_translation(pager.book_id, index, settings)
    except translator.TranslationError as exc:
        pager.say("翻译不可用：{}".format(exc))
        return
    # 没缓存才真的去翻
    if cached is None:
        try:
            translator.translate_chapter(
                pager.book_id,
                index,
                # 进度回调直接把进度条画在消息行上
                progress=lambda done, total: _draw_progress(stdscr, index, done, total),
                settings=settings,
            )
        except translator.TranslationUnavailable as exc:
            pager.say("翻译不可用：{}".format(exc))
            return
        except translator.TranslationError as exc:
            pager.say("翻译失败：{}".format(exc))
            return
    # 把（刚写入的或已有的）缓存合并进视图
    covered = pager.load_chapter(index)
    if covered:
        pager.translations_used += 1
        pager.say(
            "第 {} 章已就绪（{}）· 覆盖 {} 行".format(
                index + 1, "来自缓存" if cached else "已写入缓存", covered
            )
        )
    else:
        pager.say("第 {} 章没有可用的译文".format(index + 1))


def _switch_to_chinese(stdscr: Any, pager: Pager) -> None:
    """``c``: jump straight into the Chinese view."""
    # 直接切到中文视图
    pager.mode = MODE_ZH
    first, last = _screen_range(stdscr, pager)
    pager.say("视图：中文 · {}".format(_translate_screen_range(pager, first, last)))


def _reload_vocab(pager: Pager) -> None:
    """Refresh the underline set from the notebook.

    A missing or damaged notebook must never stop you reading, so a failure only
    surfaces as a message.
    """
    try:
        # 从生词本读出全部单词，用于正文下划线
        pager.set_vocab_words(vocab.word_set())
    except vocab.VocabError as exc:
        # 生词本坏了也不该影响阅读，只提示一句
        pager.say("生词本读取失败：{}".format(exc))


def _celebrate_achievements(ring: bool = True) -> List[Dict[str, Any]]:
    """Unlock whatever the finished session earned, then show the fanfare.

    A broken definition file must never turn a reading session into a traceback,
    so anything unexpected is reported and swallowed instead.  *ring* mirrors the
    ``achievement_sound`` setting: some terminals beep loudly on ``'\\a'``.
    """
    try:
        # 根据最新统计检查有没有新解锁的成就
        newly = stats.check_achievements()
    except (stats.StatsError, library.LibraryError) as exc:
        # 成就文件坏了也只是提示，不能影响阅读体验
        console.print("[yellow]achievements skipped: {}[/yellow]".format(exc))
        return []
    # 逐条播放庆祝动画
    for achievement in newly:
        stats.celebrate(achievement, ring=ring)
    return newly


def _mark_word(stdscr: Any, pager: Pager) -> None:
    """``v``: look a word up, show its translation and offer to keep it.

    A curses pager has no mouse selection, so the word is typed into a prompt that
    is pre-filled with the longest Latin token on the current line -- usually
    exactly the word you were staring at.  The sentence around it is kept as the
    context, and the notebook is reloaded afterwards so the new word starts being
    underlined straight away.
    """
    # 当前行（书为空时给空串）
    line = pager.lines[pager.position] if pager.total else ""
    # 提示框预填"本行最长的英文单词"，用户可以直接回车确认
    word = _prompt(stdscr, _WORD_PROMPT, pick_word(line))
    if word is None or not word.strip():
        return
    word = word.strip()
    # 取包含该词的整句当上下文
    context = sentence_around(line, word)
    try:
        # 查词（单次翻译，不缓存）
        translated = translator.translate_text(
            word, target=pager.word_target(), source=pager.source_language
        )
    except translator.TranslationError as exc:
        pager.say("查词失败：{}".format(exc))
        return
    # 记一次翻译使用
    pager.translations_used += 1
    # ``vocab.auto_add_on_mark`` skips the confirmation: the word is looked up and
    # filed in one go, and the message still shows the meaning that was stored.
    # 开了自动入库就跳过确认弹窗
    auto = pager.auto_add_on_mark
    if auto or _confirm(stdscr, "生词：{}".format(word), [translated, "", context]):
        # 记进生词本（带上书名与章节名）
        vocab.add_word(
            word,
            translated,
            context=context,
            book=pager.title,
            chapter=pager.chapter_title,
        )
        # 立刻刷新下划线集合，新词马上就会高亮
        _reload_vocab(pager)
        # 自动入库时把释义也回显出来
        pager.say(
            "已加入生词本：{} = {}".format(word, translated)
            if auto
            else "已加入生词本：{}".format(word)
        )
    else:
        pager.say("已取消：{}".format(word))


def handle_key(stdscr: Any, pager: Pager, key: Any) -> bool:
    """Act on one key press; return ``False`` when the pager should quit.

    ``n`` follows the specification and moves to the next *search* hit, so
    chapter hopping lives on ``[`` and ``]`` instead.  ``m`` starts mark mode and
    ``o`` opens the note panel; while marking, every key goes to the selection, so
    the screen never moves under the cursor.
    """
    # q / Q / Ctrl-C：退出（标记模式里也放行，免得用户被困在选区里出不来）
    if key in ("q", "Q", 3):
        return False
    # 标记模式：只处理选字相关的按键，翻页一律不响应
    if pager.mark_mode:
        _handle_mark_key(pager, key)
        return True
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
    # l：循环切换语言视图
    elif key == "l":
        _cycle_mode(stdscr, pager)
    # t：翻译当前屏幕并弹窗显示几秒（临时，不缓存）
    elif key == "t":
        _translate_screen(stdscr, pager)
    # T：翻译并缓存整章
    elif key == "T":
        _translate_chapter(stdscr, pager)
    # c：直接切到中文视图
    elif key == "c":
        _switch_to_chinese(stdscr, pager)
    # v：查词并收藏
    elif key == "v":
        _mark_word(stdscr, pager)
    # m：进入标记模式，在这一屏内选一段文字
    elif key == "m":
        _enter_mark(pager)
    # o：展开 / 折叠笔记面板
    elif key == "o":
        _note_panel(stdscr, pager)
    # 每次按键后都看看要不要触发"进章自动翻译"
    _maybe_auto_translate(stdscr, pager)
    # True 表示继续阅读
    return True


def _maybe_auto_translate(stdscr: Any, pager: Pager) -> None:
    """Translate the chapter under the cursor before it is needed.

    Only active with ``translator.auto_translate_chapter``.  The work happens on
    the main thread -- exactly like pressing ``T`` -- and each chapter is
    attempted at most once per session, so a chapter already in the cache is
    simply loaded from disk.  The translation is prepared whatever the current
    view shows: the point of the setting is that switching to 英文 or 双语 is
    instant, which is why it is not gated on the view needing a translation.
    """
    # 没开这个设置就什么都不做
    if not pager.auto_translate_chapter:
        return
    # 当前章节下标
    index = max(0, pager.current_chapter())
    # 本次会话已经处理过这一章：不再重复
    if index in pager.auto_translated:
        return
    # 先记下来，避免翻译过程中再次触发
    pager.auto_translated.add(index)
    _translate_chapter(stdscr, pager)


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
        # 本次用过翻译就累加翻译次数
        if pager.translations_used:
            stats.bump_translations(document, pager.translations_used)
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
    # get_wch 最多等 1 秒：这样时钟和状态栏能持续刷新
    stdscr.timeout(_TICK_MS)
    # 上次自动保存的时刻
    last_save = time.monotonic()
    while True:
        # 检查是否换了章节（章节计时用）
        pager.sync()
        # 重画整帧
        _draw(stdscr, pager, _now())
        # 自动保存：间隔到了就把进度写盘
        if pager.auto_save_interval:
            moment = time.monotonic()
            if moment - last_save >= pager.auto_save_interval:
                last_save = moment
                save_position(pager)
        try:
            # 等一个按键（或等到超时）
            key = stdscr.get_wch()
        except curses.error:
            continue  # the tick expired: repaint so the clock stays fresh
        except KeyboardInterrupt:
            # Ctrl-C：退出阅读
            return
        # 终端尺寸变化：不处理按键，直接重画
        if key == curses.KEY_RESIZE:
            continue
        # 鼠标 / 触摸事件：滚轮一格滚 wheel_scroll_step 行，按住拖动按位移滚
        if key == curses.KEY_MOUSE:
            delta = _mouse_event_delta(pager, drag)
            # 真的滚动了才走后续流程（比如进章自动翻译）
            if delta:
                pager.scroll(delta)
                _maybe_auto_translate(stdscr, pager)
            continue
        # 交给按键处理器；它返回 False 表示要退出
        if not handle_key(stdscr, pager, key):
            return


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

    # 读配置（三个段落分别用到）
    settings = config.load_config()
    reader_settings = settings.section("reader")
    translator_settings = settings.section("translator")
    vocab_settings = settings.section("vocab")
    # 书里存的上次进度
    progress = book.get("progress") or {}
    # 自动识别书的语言，决定初始视图
    language = detect_book_language(lines)
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
        mode=LANGUAGE_MODES.get(language, MODE_ZH),
        book_language=language,
        bookmarks=progress.get("bookmarks") or [],
        target_language=str(translator_settings.get("target_language") or "zh-CN"),
        source_language=str(translator_settings.get("source_language") or "auto"),
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
        auto_translate_chapter=bool(translator_settings.get("auto_translate_chapter")),
        highlight_vocab=bool(vocab_settings.get("highlight_in_reader", True)),
        auto_add_on_mark=bool(vocab_settings.get("auto_add_on_mark", True)),
        # Tab 目录浮层用的条目（带百分比）
        toc_entries=book_toc,
    )
    # 载入生词集合，正文里会给它们加下划线
    _reload_vocab(pager)

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
    # 在普通终端里打印一行摘要
    console.print(
        "[dim]{} · 停在 {}/{} 行 ({:.1f}%) · 本次 {} · 书签 {} 个[/dim]".format(
            MODE_LABELS[pager.mode],
            pager.position + 1,
            pager.total,
            pager.percentage,
            format_duration(seconds),
            len(pager.bookmarks),
        )
    )
    # 检查并庆祝本次会话解锁的成就（按设置决定是否响铃）
    _celebrate_achievements(ring=bool(settings.get("stats.achievement_sound", True)))
    return 0

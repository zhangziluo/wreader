"""Reader core: a curses paged reading experience.

``wreader read <book_id>`` pages through the UTF-8 text that :mod:`wreader.library`
produced at import time.  The pager works in **source lines**: the stored file is
split on ``\\n`` exactly the way the importer split it, so
``progress["current_line"]``, ``progress["bookmarks"][].line`` and every
``chapters[].line_start`` are indexes into the same list.  One source line may
occupy more than one screen row (long paragraphs wrap, and the bilingual view adds
a row per translation), so a page turn is measured in **screen rows**, not source
lines: pagination fills a real screenful and then continues from the first line
that did not fit, which is what stops long paragraphs from being skipped.

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
up a single word and offers to file it in :mod:`wreader.vocab`.

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

# 同包引用：配置、书库、统计成就、翻译、生词本
from . import config, library, stats, translator, vocab

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
_HINT = "q退出 j/space翻页 g跳行 [/]章节 /搜索 n下一个 b书签 v生词 l语言 t翻屏 T翻章 c中文"
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

    def visible_rows(
        self, height: int, width: Optional[int] = None
    ) -> List[Tuple[int, str]]:
        """Return ``(source_line, text)`` for the rows that fit into *height*.

        With a *width* the text of one source line is wrapped into as many screen
        rows as it needs, so a long paragraph is never cut off at the right edge.
        Without it the text is handed over unwrapped (one source line per screen
        row) -- the historical behaviour, still handy for plain assertions.
        """
        # 最多能画多少行
        room = max(1, int(height))
        # 结果是 (源行号, 该行要显示的文字)
        rows: List[Tuple[int, str]] = []
        index = self.position
        # 从当前位置往下灌，直到填满屏幕或读到结尾
        while index < self.total and len(rows) < room:
            # 一个源行可能占多行（双语视图）
            for text in self.rows_for(index):
                if len(rows) >= room:
                    break
                # 没给宽度：不做折行，一行就是一行
                if width is None:
                    rows.append((index, text))
                    continue
                # 给了宽度：把超长的显示文本折成多个屏幕行
                for chunk in _wrap_line(text, int(width)):
                    if len(rows) >= room:
                        break
                    rows.append((index, chunk))
            index += 1
        return rows

    def _screen_rows(self, index: int, width: Optional[int]) -> int:
        """How many screen rows one source line takes in the current view.

        Wrapping is delegated to :func:`_wrap_line`, so double width CJK characters
        and latin word wrapping are counted exactly the way the screen draws them.
        """
        # 一个源行在当前视图下可能拆成多段显示文本（双语是原文 + 译文）
        texts = self.rows_for(index)
        # 没有宽度信息（纯数据场景）：一段文本就是一屏行
        if width is None:
            return len(texts)
        # 有宽度：每段各自按显示宽度折行，行数相加
        return sum(len(_wrap_line(text, int(width))) for text in texts)

    def next_position(self, screen_rows: int, width: Optional[int] = None) -> int:
        """The source line that sits at the top of the screen *screen_rows* ahead.

        Advancing by **screen rows** instead of source lines is what stops a page
        turn from skipping text: a wrapped paragraph eats several rows, so one
        screenful of rows is fewer source lines than a fixed per-page step assumed.
        """
        # 先看从当前位置起，这一屏的屏幕行到底填到哪个源行
        rows = self.visible_rows(max(1, int(screen_rows)), width)
        # 一屏都填不满（已在书末）：至少前进一行，保证按键有反应
        if not rows:
            return min(self.position + 1, self.total)
        # 屏幕上最后一个已显示源行的下一行，才是下一屏的起点
        last = max(index for index, _ in rows)
        return min(last + 1, self.total)

    def previous_position(self, screen_rows: int, width: Optional[int] = None) -> int:
        """The source line a screen of *screen_rows* rows would start on going back.

        The mirror image of :meth:`next_position`: walk upwards row by row until a
        whole screenful has been covered, and land on the line that then tops it.
        """
        # 从当前位置往上走
        index = self.position
        # 还要往上凑多少屏幕行
        remaining = max(1, int(screen_rows))
        # 逐行往上走，直到凑满一屏或到达书首
        while index > 0 and remaining > 0:
            index -= 1
            remaining -= self._screen_rows(index, width)
        return max(0, index)

    # -- movement --------------------------------------------------------
    def move_to(self, position: int) -> None:
        """Jump to *position*, counting the forward distance as lines read."""
        # 先把目标位置夹进合法范围
        target = clamp(position, self.total)
        # 只统计"向前"的位移，往回翻不抵消阅读量
        if target > self.position:
            self.lines_read += target - self.position
        self.position = target
        # 位置变了，章节计时可能需要滚动到下一章
        self._sync_chapter()

    def scroll(self, delta: int) -> None:
        """Move by *delta* lines."""
        # 相对移动：在当前位置上加减
        self.move_to(self.position + delta)

    def next_page(self) -> None:
        """Advance one page, counted in screen rows so nothing is skipped."""
        # 按屏幕行推进：折行后的长段不会被整段跳过去
        self.move_to(self.next_position(self.page_budget, self.viewport_width))

    def previous_page(self) -> None:
        """Go back one page, counted in screen rows like :meth:`next_page`."""
        # 往回也按屏幕行，和前进对称
        self.move_to(self.previous_position(self.page_budget, self.viewport_width))

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
    def translate_screen(self, first: int, last: int, progress=None) -> int:
        """Translate every paragraph touched by ``[first, last]`` into memory.

        Paragraphs, not lines, are the unit: the back-end then sees whole sentences
        instead of a pile of fragments, and the bilingual view can pair one Chinese
        paragraph with one English paragraph.  Returns how many paragraphs landed.
        """
        # 当前视图需要翻成什么语言；None 表示不需要翻译
        target = mode_language(self.mode, self.language)
        if target is None:
            return 0
        # 划出与屏幕相交的段落区间
        spans = translator.paragraph_spans(self.lines, first, last)
        if not spans:
            return 0
        # 逐段翻译（只进内存，不缓存）
        english = translator.translate_paragraphs(
            translator.paragraph_texts(self.lines, spans),
            target=target,
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
        return _pad_line(_HINT, room)
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
    # 上一条屏幕行属于哪个源行，用来判断"这是不是某个源行的第一行"
    previous_index: Optional[int] = None
    for offset, (index, text) in enumerate(pager.visible_rows(text_rows, text_width)):
        # 折行后一个源行可能占多条屏幕行，书签只画在它的第一行上
        marked = index != previous_index and pager.is_bookmarked(index)
        # 第 0 列放书签标记（有就实心星，没有就留空占位）
        _addstr(
            stdscr,
            offset,
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
        _draw_text(stdscr, offset, 1, text, attr, words)
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


def _translate_screen(stdscr: Any, pager: Pager) -> None:
    """``t``: translate what is on screen, deliberately never touching the cache."""
    # 只处理当前一屏
    first, last = _screen_range(stdscr, pager)
    pager.say(_translate_screen_range(pager, first, last))


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
    chapter hopping lives on ``[`` and ``]`` instead.
    """
    # q / Q / Ctrl-C：退出
    if key in ("q", "Q", 3):
        return False
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
    # t：翻译当前屏幕（不缓存）
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

    The position and the bookmarks are always stored so ``wreader read`` resumes where
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
            "wreader read needs an interactive terminal (a tty on stdin and stdout)"
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

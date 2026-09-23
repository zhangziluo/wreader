"""Tests for :mod:`wreader.reader` — paging maths, the pager, the status bar and keys.

The curses front end is exercised through a stub window, so no test needs a real
terminal: ``FakeStdscr`` implements exactly the slice of the API the reader
touches, and the keys that would prompt for input have ``wreader.reader._prompt``
monkeypatched.
"""

# 延迟求值类型注解
from __future__ import annotations

# 用 curses 的常量（A_REVERSE、KEY_DOWN 等）做断言
import curses
# curses.ascii：笔记面板的 validator 会把回车映射成 NL
import curses.ascii
# 注入固定日期/时间
from datetime import date, datetime
# 类型注解
from typing import Any, Dict, List, Optional, Tuple

# pytest.raises / parametrize / fixture
import pytest

# 被测模块 + 翻译与生词本
from wreader import notes, reader, translator, vocab

# 复用样例正文
from conftest import BOOK_LINES, ENGLISH_LINES


# 假的 curses 窗口：把画上去的内容记下来，供断言用
class FakeStdscr:
    """A stand-in for the curses window, recording what was drawn."""

    def __init__(self, height: int = 10, width: int = 40) -> None:
        # 尺寸可配，方便测窄屏/多页
        self.height = height
        self.width = width
        # 统计 erase/refresh 被调用次数
        self.erase_calls = 0
        self.refreshes = 0
        # 每次 addstr 的记录：(行, 列, 文本, 属性)
        self.writes: List[Tuple[int, int, str, int]] = []
        # 光标位置（供不带行/列的 addstr 使用）
        self.cursor_row = 0
        self.cursor_column = 0
        # 屏幕快照：二维字符数组，用来断言"画出来长什么样"
        self.screen: List[List[str]] = [[" "] * width for _ in range(height)]
        # 需要读键的循环（目录浮层）预置的按键队列
        self.keys: List[Any] = []
        # 子窗口（笔记面板用 stdscr.newwin 建了两个）：建过就记下来，方便断言
        self.windows: List[FakeStdscr] = []
        # 子窗口在屏幕上的起始坐标（只有 newwin 出来的才会有意义）
        self.begin: Tuple[int, int] = (0, 0)

    # -- the window API the reader uses ---------------------------------
    def getmaxyx(self) -> Tuple[int, int]:
        # curses 的尺寸接口，返回 (高, 宽)
        return self.height, self.width

    def erase(self) -> None:
        # 清屏：计数并把快照重置成空格
        self.erase_calls += 1
        self.screen = [[" "] * self.width for _ in range(self.height)]

    def refresh(self) -> None:
        # 提交这一帧：只计数
        self.refreshes += 1

    def touchwin(self) -> None:
        # 真实现里用来标记需要重画；这里什么都不用做
        return None

    def timeout(self, _milliseconds: int) -> None:
        return None

    def keypad(self, _flag: bool) -> None:
        return None

    def move(self, row: int, column: int) -> None:
        # 记录光标位置
        self.cursor_row = row
        self.cursor_column = column

    def get_wch(self) -> Any:
        # 目录浮层会一直读键；队列空了就当 Ctrl-C，保证测试不会死循环
        if not self.keys:
            raise KeyboardInterrupt
        return self.keys.pop(0)

    def addstr(self, *args: Any) -> None:
        # Copy into a list first: pyright narrows the ``*args`` tuple itself on the
        # ``len()`` check and then claims index 0 is out of range.
        # 先转成列表，避免类型检查器在 len() 之后把元组收窄
        values = list(args)
        # 三种调用形式：addstr(text) / addstr(text, attr) / addstr(row, col, text[, attr])
        if len(values) >= 3:
            row, column, text = int(values[0]), int(values[1]), values[2]
            attr = int(values[3]) if len(values) > 3 else 0
        else:
            row, column, text = self.cursor_row, self.cursor_column, values[0]
            attr = int(values[1]) if len(values) > 1 else 0
        # 记录这次写入
        self.writes.append((row, column, str(text), attr))
        # 同时把字符铺到屏幕快照上（越界的字符忽略，模拟 curses）
        for offset, character in enumerate(str(text)):
            if 0 <= row < self.height and 0 <= column + offset < self.width:
                self.screen[row][column + offset] = character

    # -- the slice of the window API the Textbox needs -------------------
    def newwin(
        self, nlines: int, ncols: int, begin_y: int, begin_x: int
    ) -> FakeStdscr:
        # 笔记面板建两个子窗口：各给一个独立的假窗口，方便断言面板画/编辑了什么
        child = FakeStdscr(height=nlines, width=ncols)
        # 记下它在屏幕上的位置（面板靠这个把子窗口摆到下半屏）
        child.begin = (begin_y, begin_x)
        # 记到父窗口上，测试从 window.windows 就能拿到
        self.windows.append(child)
        return child

    def getch(self) -> int:
        # Textbox 自己那个 edit() 循环才会用它；这里做个等价实现以防万一
        if not self.keys:
            raise KeyboardInterrupt
        key = self.keys.pop(0)
        return ord(key) if isinstance(key, str) else int(key)

    def getyx(self) -> Tuple[int, int]:
        # textpad 每个编辑动作前都会先问光标在哪
        return self.cursor_row, self.cursor_column

    def addch(self, ch: Any) -> None:
        # curses 的 addch 既收字符也收字符码；写完光标右移一格
        character = chr(ch) if isinstance(ch, int) else str(ch)
        # 在光标处落下这个字符
        if 0 <= self.cursor_row < self.height and 0 <= self.cursor_column < self.width:
            self.screen[self.cursor_row][self.cursor_column] = character
            self.writes.append((self.cursor_row, self.cursor_column, character, 0))
        # 光标右移（夹住右边界，模拟 curses）
        self.cursor_column = min(self.cursor_column + 1, max(0, self.width - 1))

    def inch(self, y: Optional[int] = None, x: Optional[int] = None) -> int:
        # 取某格的字符码：textpad 靠它找行尾、把编辑内容拼回来
        row = self.cursor_row if y is None else y
        column = self.cursor_column if x is None else x
        # 越界当空格，免得 textpad 拿到怪值
        if not (0 <= row < self.height and 0 <= column < self.width):
            return 32
        character = self.screen[row][column]
        return ord(character) if len(character) == 1 else 32

    def delch(self) -> None:
        # 删除光标处字符：整行左移一格，行尾补一个空格
        if 0 <= self.cursor_column < self.width:
            row = self.screen[self.cursor_row]
            del row[self.cursor_column]
            row.append(" ")

    def clrtoeol(self) -> None:
        # 从光标清到行尾
        row = self.screen[self.cursor_row]
        for column in range(self.cursor_column, self.width):
            row[column] = " "

    def deleteln(self) -> None:
        # 删掉当前行：下面的行整体上移，末行清空
        del self.screen[self.cursor_row]
        self.screen.append([" "] * self.width)

    def insertln(self) -> None:
        # 在当前行插入一个空行：整体下移，丢掉最后一行
        self.screen.insert(self.cursor_row, [" "] * self.width)
        del self.screen[self.height]

    # -- helpers for the assertions -------------------------------------
    def row(self, index: int) -> str:
        # 取某一行的文本（去掉右侧空白，方便比较）
        return "".join(self.screen[index]).rstrip()

    def body(self) -> str:
        # 正文区（去掉底部两行状态栏）的全部内容
        return "\n".join(
            self.row(index) for index in range(self.height - reader._STATUS_ROWS)
        )


# 每个测试一个干净的假窗口
@pytest.fixture
def window() -> FakeStdscr:
    return FakeStdscr()


# 每个测试一个干净的 Pager（由 conftest 的工厂构造）
@pytest.fixture
def pager(pager_factory):
    return pager_factory()


# 笔记面板用的假窗口：真 curses 只有模块级的 curses.newwin（window 对象没有 newwin
# 方法，只有 derwin），所以把读者里那个建窗接缝换成假窗口 —— 子窗口才会被记进 window.windows
@pytest.fixture
def panel_window(window, monkeypatch):
    def fake_newwin(stdscr, nlines: int, ncols: int, begin_y: int, begin_x: int):
        # 借父假窗口的 newwin，子窗口才会被记进父窗口的 windows 列表
        return window.newwin(nlines, ncols, begin_y, begin_x)

    monkeypatch.setattr(reader, "_sub_window", fake_newwin)
    return window


# ------------------------------------------------------------------ pure helpers
def test_clamp_keeps_a_position_inside_the_book() -> None:
    # 范围内的原样返回
    assert reader.clamp(5, 10) == 5
    # 负数夹到 0
    assert reader.clamp(-3, 10) == 0
    # 越界夹到最后一行
    assert reader.clamp(99, 10) == 9
    # 空书统一返回 0
    assert reader.clamp(5, 0) == 0


def test_chapter_lookup_helpers() -> None:
    # 两章：分别从第 0、5 行开始
    chapters = [{"title": "a", "line_start": 0}, {"title": "b", "line_start": 5}]
    # 0-4 行属于第 0 章，第 5 行起属于第 1 章
    assert reader.chapter_index_at(chapters, 0) == 0
    assert reader.chapter_index_at(chapters, 4) == 0
    assert reader.chapter_index_at(chapters, 5) == 1
    # 章节起始行；越界返回 0
    assert reader.chapter_start(chapters, 1) == 5
    assert reader.chapter_start(chapters, 9) == 0
    # 下一章的位置；后面没有章节就跳到全书最后一行
    assert reader.next_chapter_position(chapters, 0, 10) == 5
    assert reader.next_chapter_position(chapters, 5, 10) == 9  # no chapter left
    # 上一章的位置；已经在第一章就回到开头
    assert reader.previous_chapter_position(chapters, 7, 10) == 0
    assert reader.previous_chapter_position(chapters, 0, 10) == 0


def test_chapter_bounds() -> None:
    chapters = [{"title": "a", "line_start": 0}, {"title": "b", "line_start": 5}]
    # 第 0 章覆盖 0-4 行
    assert reader.chapter_bounds(chapters, 0, 10) == (0, 4)
    # 第 1 章覆盖 5-9 行
    assert reader.chapter_bounds(chapters, 6, 10) == (5, 9)
    # 没有章节信息：整本书一章
    assert reader.chapter_bounds([], 6, 10) == (0, 9)
    # 空书
    assert reader.chapter_bounds(chapters, 0, 0) == (0, 0)


def test_reading_streak_counts_today() -> None:
    today = date(2026, 1, 7)
    # 前天+昨天+今天 = 3 天
    assert reader.reading_streak(["2026-01-05", "2026-01-06"], today) == 3
    # 没有任何记录：今天也算 1 天
    assert reader.reading_streak([], today) == 1  # today always counts
    # 只有大前天：断了
    assert reader.reading_streak(["2026-01-04"], today) == 1


# 参数化：时长格式化的边界（分:秒 / 时:分:秒）
@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "00:00"),
        (59, "00:59"),
        (60, "01:00"),
        (3599, "59:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
    ],
)
def test_format_duration(seconds: int, expected: str) -> None:
    assert reader.format_duration(seconds) == expected


def test_find_matches_is_case_insensitive() -> None:
    lines = ["One two", "three", "ONE more"]
    # 小写/大写查询都命中第 0、2 行
    assert reader.find_matches(lines, "one") == [0, 2]
    assert reader.find_matches(lines, "ONE") == [0, 2]
    # 空关键词不命中任何行
    assert reader.find_matches(lines, "") == []


# 参数化：视图 + 书的语言 -> 需要翻译成什么语言（None = 显示原文）
@pytest.mark.parametrize(
    "mode, language, expected",
    [
        ("zh", "zh", None),
        ("zh", "en", "zh-CN"),
        ("en", "en", None),
        ("en", "zh", "en"),
        ("both", "zh", "en"),
        ("both", "en", "zh-CN"),
        ("weird", "zh", None),
    ],
)
def test_mode_language(mode: str, language: str, expected) -> None:
    assert reader.mode_language(mode, language) == expected


def test_detect_book_language() -> None:
    # 中文样例书判 zh，英文样例书判 en
    assert reader.detect_book_language(list(BOOK_LINES)) == "zh"
    assert reader.detect_book_language(list(ENGLISH_LINES)) == "en"


def test_pick_word_takes_the_longest_latin_token() -> None:
    # 最长的英文词就是用户最可能想查的
    assert reader.pick_word("He acknowledged it completely") == "acknowledged"
    # 没有英文词
    assert reader.pick_word("汪淼看到了") == ""
    assert reader.pick_word("") == ""


def test_sentence_around() -> None:
    line = "First one. It is acknowledged. Last one."
    # 取包含目标词的整句
    assert reader.sentence_around(line, "acknowledged") == "It is acknowledged."
    # 词不在行里：退回整行
    assert reader.sentence_around(line, "missing") == line
    # 空行
    assert reader.sentence_around("", "x") == ""


def test_char_width_counts_cjk_as_two_columns() -> None:
    # 汉字、全角标点在终端里占两列
    assert reader._char_width("中") == 2
    # 半角 ASCII 占一列
    assert reader._char_width("a") == 1


def test_clip_line_cuts_on_display_width() -> None:
    # 放得下就原样返回
    assert reader._clip_line("abc", 9) == "abc"
    # ASCII 就按列数切
    assert reader._clip_line("abcdef", 4) == "abcd"
    # 汉字占两列：宽度 5 只放得下两个（4 列），不会把第三个劈开
    assert reader._clip_line("中文测试", 5) == "中文"
    # 连一个宽字符都放不下：返回空串
    assert reader._clip_line("中", 1) == ""
    # 没有可用列数
    assert reader._clip_line("abc", 0) == ""


def test_text_width_counts_columns_not_characters() -> None:
    # 纯 ASCII：列数等于字符数
    assert reader._text_width("abc") == 3
    # 汉字一个占两列
    assert reader._text_width("中文") == 4
    # 中英混排
    assert reader._text_width("中a文") == 5
    # 空串
    assert reader._text_width("") == 0


def test_pad_line_fills_exactly_the_requested_columns() -> None:
    # 短的就补空格（一个空格一列）
    assert reader._pad_line("中", 5) == "中   "
    # 长的先按显示宽度裁，再补齐
    assert reader._pad_line("中文测试", 5) == "中文 "
    # 已经正好占满：原样返回
    assert reader._pad_line("中文", 4) == "中文"
    # 没有可用列数
    assert reader._pad_line("abc", 0) == ""


def test_wrap_line_folds_on_display_width() -> None:
    # 纯 ASCII：宽度 4 就是每 4 个字符一行
    assert reader._wrap_line("abcdef", 4) == ["abcd", "ef"]
    # 中文按显示宽度算：两个汉字正好 4 列，刚好放下
    assert reader._wrap_line("中文", 4) == ["中文"]
    # 宽度 3 装不下两个汉字（4 列），只能一个一行，绝不把汉字劈开
    assert reader._wrap_line("中文", 3) == ["中", "文"]
    # 中英混排：先放两个汉字（4 列）再换行放英文
    assert reader._wrap_line("中文ab", 4) == ["中文", "ab"]
    # 空行仍占一行，空源行才不会在屏幕上消失
    assert reader._wrap_line("", 4) == [""]
    # 制表符先展开成 4 个空格，再按宽度算
    assert reader._wrap_line("col\tone", 20) == ["col    one"]
    # 宽度不合法：不折行，原样返回
    assert reader._wrap_line("abcdef", 0) == ["abcdef"]


def test_wrap_line_keeps_latin_words_whole() -> None:
    # 英文在空格处折行，单词不会被劈成两半
    assert reader._wrap_line("hello world", 6) == ["hello", "world"]
    # 连续多个空格也一样：不会跑到下一行行首去
    assert reader._wrap_line("hello  world", 6) == ["hello", "world"]
    # 一个单词本身就比整行宽：只能硬断，没有别的办法
    assert reader._wrap_line("abcdefghij", 4) == ["abcd", "efgh", "ij"]
    # 中英混排：汉字按字断，英文单词整体带走
    assert reader._wrap_line("英文 abc", 6) == ["英文", "abc"]


def test_wrap_line_fills_a_row_exactly_before_breaking() -> None:
    # 一行正好排满时不该把最后一个单词白白推到下一行
    phrase = "It is a truth universally acknowledged,"
    assert reader._wrap_line(phrase, 39) == [phrase]
    # 再往后放一个单词就真的超宽了，这时才换行
    assert reader._wrap_line(phrase + " that", 39) == [phrase, "that"]


def test_wrap_line_never_exceeds_the_width() -> None:
    # 随便拿一段中英混排的长文本，折出来的每一行都不能超宽
    text = "汪淼看到了一串数字，he said it is a truth universally acknowledged."
    for width in (4, 7, 11, 20, 39, 79):
        # 逐行算出显示宽度
        widths = [
            sum(reader._char_width(char) for char in line)
            for line in reader._wrap_line(text, width)
        ]
        # 除了"单个宽字符比整行还宽"这种情况，都不该超过给定宽度
        assert all(size <= max(width, 2) for size in widths)
        # 也不能出现空行（那会白白浪费一屏）
        assert all(line for line in reader._wrap_line(text, width))


# ------------------------------------------------------------------------ pager
def test_pager_position_and_percentage(pager) -> None:
    # 样例书 8 行
    assert pager.total == len(BOOK_LINES)
    assert pager.position == 0
    # 第 0 行 => 1/8 = 12.5%
    assert pager.percentage == 12.5  # the first line of eight
    pager.to_end()
    # 跳到最后一行的位置就是 100%
    assert pager.position == pager.total - 1
    assert pager.percentage == 100.0


def test_page_scroll_step_controls_the_page_turn(pager_factory) -> None:
    # 用一本足够长的书，免得到书末被夹住影响断言
    lines = ["l{}".format(n) for n in range(40)]
    # 默认视口 = page_height=4 且不折行：一次翻满 4 行
    full = pager_factory(lines=lines, chapters=[], page_scroll_step=1.0)
    full.next_page()
    assert full.position == 4
    # 半屏 = 2 行；两屏 = 8 行
    half = pager_factory(lines=lines, chapters=[], page_scroll_step=0.5)
    half.next_page()
    assert half.position == 2
    double = pager_factory(lines=lines, chapters=[], page_scroll_step=2.0)
    double.next_page()
    assert double.position == 8
    # 0 会被兜成至少 1 行，保证按键一定有反应
    stalled = pager_factory(lines=lines, chapters=[], page_scroll_step=0.0)
    stalled.next_page()
    assert stalled.position == 1


def test_page_budget_counts_screen_rows(pager_factory) -> None:
    # 预算是"屏幕行"：视口 10 行、无重叠 → 10
    pager = pager_factory(page_overlap=0)
    pager.viewport_rows = 10
    assert pager.page_budget == 10
    # 重叠 3 行 → 预算 7
    pager.page_overlap = 3
    assert pager.page_budget == 7
    # 重叠比整屏还大 → 兜底 1，按键不会没反应
    pager.page_overlap = 99
    assert pager.page_budget == 1


def test_page_overlap_shortens_the_page_turn(pager_factory) -> None:
    # 每屏 4 行、重叠 3 行：翻页只前进 1 行，其余 3 行留在屏幕上当上下文
    pager = pager_factory(page_overlap=3)
    pager.next_page()
    assert pager.position == 1


def test_page_overlap_zero_keeps_the_full_page(pager_factory) -> None:
    # 关掉重叠：一次翻满整屏
    pager = pager_factory(page_overlap=0)
    pager.next_page()
    assert pager.position == 4


def test_page_overlap_with_a_half_page_step(pager_factory) -> None:
    # 半屏（2 行）减掉 3 行重叠会变负：兜底成 1 行
    pager = pager_factory(page_scroll_step=0.5, page_overlap=3)
    pager.next_page()
    assert pager.position == 1


def test_page_overlap_never_stalls_the_page_keys(pager_factory) -> None:
    # 重叠比整屏还大也只前进 1 行，按键一定有反应
    pager = pager_factory(page_overlap=10)
    pager.next_page()
    assert pager.position == 1


def test_page_overlap_defaults_to_three_lines() -> None:
    # 不传 page_overlap 时默认保留 3 行，且模块常量与之一致
    assert reader.Pager(["a", "b"]).page_overlap == 3
    assert reader.DEFAULT_PAGE_OVERLAP == 3


def test_page_overlap_is_clamped_to_zero() -> None:
    # 负数被夹到 0：绝不会因为"负重叠"反而一次跳得更多
    assert reader.Pager(["a", "b"], page_overlap=-5).page_overlap == 0


def test_page_turn_keeps_the_last_lines_of_the_previous_screen(pager_factory) -> None:
    # 每屏 6 行、重叠 3 行：翻一页后新屏幕最前面正是上一屏的最后 3 行
    lines = [str(number) for number in range(40)]
    pager = pager_factory(lines=lines, page_height=6, page_overlap=3)
    before = [index for index, _ in pager.visible_rows(6)]
    pager.next_page()
    after = [index for index, _ in pager.visible_rows(6)]
    # 顶部 3 行是衔接过来的旧文字，之后才是新内容
    assert after[:3] == before[-3:]
    assert after[3:] == [6, 7, 8]
    # 往回翻一页就精确回到原处（既有顶部重叠也有底部重叠）
    pager.previous_page()
    assert pager.position == before[0]


def test_screen_rows_counts_wrapped_and_cjk_lines(pager_factory) -> None:
    # 不给宽度：一个源行就是一条屏幕行
    pager = pager_factory(lines=["中文测试"], chapters=[])
    assert pager._screen_rows(0, None) == 1
    # 宽度 4：4 个汉字占 8 列 → 折成 2 行（用 len() 会误算成 1 行）
    assert pager._screen_rows(0, 4) == 2
    # ASCII 12 字符、宽度 5 → 3 行（按词/硬断，不丢字符）
    latin = pager_factory(lines=["abcdefghijkl"], chapters=[])
    assert latin._screen_rows(0, 5) == 3


def test_screen_rows_counts_every_row_of_the_bilingual_view(pager_factory) -> None:
    # 双语视图：一个源行是"原文 + 译文"两段，各占一屏行
    pager = pager_factory(lines=["hello"], chapters=[])
    pager.mode = "both"
    pager.translations = {0: "你好"}
    assert pager._screen_rows(0, None) == 2


def test_next_top_stops_at_the_first_row_that_does_not_fit(pager_factory) -> None:
    # 第 0 行长到占 3 屏行，后面是 1 行一条的短行；屏幕只放得下 4 行
    lines = ["x" * 15] + ["ab{}".format(n) for n in range(10)]
    pager = pager_factory(lines=lines, chapters=[])
    # 宽度 5：15 个字符折成 3 行，再加第 1 行正好 4 行 → 下一屏从第 2 行开头
    assert pager.next_top(4, 5) == (2, 0)


def test_next_top_returns_an_intra_line_offset(pager_factory) -> None:
    # 第 0 行 200 个汉字 = 400 列，宽 20 时折成 20 屏行；屏幕只放得下 5 行
    pager = pager_factory(lines=["长" * 200, "下一行"], chapters=[])
    # 一屏 5 行全落在第 0 行里，于是下一屏还是第 0 行，但要跳过前 5 条折行片段
    assert pager.next_top(5, 20) == (0, 5)
    # 再往后 10 行：20 条片段全在屏幕内，落点回到第 1 行开头
    pager.move_to(0, 5)
    assert pager.previous_top(5, 20) == (0, 0)


def test_previous_top_is_the_mirror_of_next_top(pager_factory) -> None:
    # 不折行、每屏 4 行：从第 8 行往回一屏落在第 4 行开头
    pager = pager_factory(lines=["l{}".format(n) for n in range(40)], chapters=[])
    pager.move_to(8)
    assert pager.previous_top(4, None) == (4, 0)
    # 从第 4 行往前一屏同样回到第 8 行开头
    pager.move_to(4)
    assert pager.next_top(4, None) == (8, 0)


def test_previous_top_walks_back_inside_a_wrapped_line(pager_factory) -> None:
    # 当前在第 0 行的第 5 条折行片段上：往回 3 屏行应当落在第 2 条
    pager = pager_factory(lines=["长" * 200], chapters=[])
    pager.move_to(0, 5)
    assert pager.previous_top(3, 20) == (0, 2)


def test_page_turn_resumes_inside_a_truncated_paragraph(pager_factory) -> None:
    # 长段落折成 6 屏行，屏幕只有 4 行：翻页后要停在同一行的第 4 条片段上
    pager = pager_factory(lines=["长" * 60, "末行"], chapters=[], page_overlap=0)
    pager.viewport_rows = 4
    pager.viewport_width = 20
    # 第一屏：第 0 行的前 4 条折行片段
    assert [text for _, text in pager.visible_rows(4, 20)] == reader._wrap_line(
        "长" * 60, 20
    )[:4]
    pager.next_page()
    # 接着显示第 4、5 条片段，再往下才是第 1 行 —— 中间一条都没漏
    assert (pager.position, pager.line_offset) == (0, 4)
    assert [index for index, _ in pager.visible_rows(4, 20)] == [0, 0, 1]
    pager.next_page()
    # 第 0 行、第 1 行都读完了：停在书末
    assert (pager.position, pager.line_offset) == (1, 0)


def test_page_turns_show_every_row_of_a_long_paragraph(pager_factory) -> None:
    # 验收口径：一屏装不下的长段落，必须一屏一屏全部读出来，一条都不能漏
    lines = ["长" * 200] + ["第 {} 行".format(n) for n in range(20)]
    pager = pager_factory(lines=lines, chapters=[], page_overlap=0)
    pager.viewport_rows = 12
    pager.viewport_width = 20
    seen: List[Tuple[int, str]] = []
    for _ in range(3):
        seen.extend(pager.visible_rows(12, 20))
        pager.next_page()
    # 长段落折出来的 20 条屏幕行，按原顺序一条不少地出现过
    assert [text for index, text in seen if index == 0] == reader._wrap_line("长" * 200, 20)


def test_next_page_from_a_mid_line_position_is_reversible(pager_factory) -> None:
    # 长段落 + 折行：一页页往回翻，落点（含段内偏移）应当逐页吻合
    lines = ["长" * 60] + ["第 {} 行".format(n) for n in range(40)]
    pager = pager_factory(lines=lines, chapters=[], page_overlap=0)
    pager.viewport_rows = 6
    pager.viewport_width = 10
    # 先往前翻 4 页，记下每一页的屏顶坐标
    tops: List[Tuple[int, int]] = []
    for _ in range(4):
        tops.append((pager.position, pager.line_offset))
        pager.next_page()
    # 再倒着翻回去，坐标应当逐页吻合
    for expected in reversed(tops):
        pager.previous_page()
        assert (pager.position, pager.line_offset) == expected


def test_scroll_is_measured_in_screen_rows(pager_factory) -> None:
    # 第 0 行折成 5 屏行：往后滚 2 行只走到这一行的第 2 条片段，不是跳过整行
    pager = pager_factory(lines=["长" * 50, "末行"], chapters=[], page_overlap=0)
    pager.viewport_rows = 12
    pager.viewport_width = 20
    pager.scroll(2)
    assert (pager.position, pager.line_offset) == (0, 2)
    pager.scroll(-2)
    assert (pager.position, pager.line_offset) == (0, 0)


def test_move_to_resets_the_intra_line_offset(pager_factory) -> None:
    # 直接跳行（goto / 搜索 / 章节 / 首尾）总是落在该行开头
    pager = pager_factory(lines=["长" * 60] + ["l{}".format(n) for n in range(20)], chapters=[])
    pager.move_to(0, 3)
    assert pager.line_offset == 3
    pager.move_to(2)
    assert (pager.position, pager.line_offset) == (2, 0)
    pager.move_to(0, 2)
    pager.to_start()
    assert (pager.position, pager.line_offset) == (0, 0)
    pager.move_to(0, 2)
    pager.to_end()
    assert pager.line_offset == 0


def test_a_stale_intra_line_offset_never_blanks_the_screen(pager_factory) -> None:
    # 窗口变宽会让折行片段变少，旧偏移可能越界：此时不能让整行（甚至整屏）消失
    lines = ["长" * 60] + ["第 {} 行".format(n) for n in range(10)]
    pager = pager_factory(lines=lines, chapters=[])
    pager.move_to(0, 99)
    rows = pager.visible_rows(4, 20)
    # 越界偏移被夹到这一行的最后一条，屏幕照样填满
    assert rows[0][0] == 0
    assert len(rows) == 4


def test_bookmark_mark_is_not_drawn_on_a_mid_line_resume(window, pager_factory) -> None:
    # 书签画在第 0 行；但整屏是从第 0 行中间续显示的，那条半截不该标出来
    lines = ["长" * 60, "末行"]
    pager = pager_factory(lines=lines, chapters=[], page_overlap=0)
    pager.toggle_bookmark(0)
    pager.move_to(0, 3)
    reader._draw(window, pager, MOMENT)
    # 正文区第一行的书签栏是空的（A_DIM 的占位空格），没有 ★
    assert window.row(0)[0].strip() == ""
    # 回到第 0 行开头时，书签正常显示
    pager.move_to(0)
    reader._draw(window, pager, MOMENT)
    assert window.row(0)[0] == reader._BOOKMARK_MARK


def test_long_wrapped_paragraph_is_not_skipped(pager_factory) -> None:
    # 长段落（50 个汉字 = 100 列 → 宽 20 时占 5 屏行）+ 短行
    lines = ["长" * 50] + ["第 {} 行".format(n) for n in range(80)]
    pager = pager_factory(lines=lines, chapters=[], page_height=24, page_overlap=0)
    # 模拟真实终端：正文区 12 行 × 20 列
    pager.viewport_rows = 12
    pager.viewport_width = 20
    start = pager.position
    pager.next_page()
    # 长段落占 5 行 + 第 1..7 行 = 一整屏，所以下一屏从第 8 行接上
    assert pager.position == 8
    # 一次翻页跨越的文本行数绝不会超过一屏能放下的行数
    # （旧逻辑按 page_height=24 硬跳，会一次跳过从未显示过的第 8..23 行）
    assert pager.position - start <= pager.viewport_rows


def test_page_turn_never_skips_a_source_line(pager_factory) -> None:
    # 用户场景：长段落 + 翻页 10 次，每次首页紧接上一屏末页，不重叠也不跳过
    lines = ["长" * 50] + ["第 {} 行内容".format(n) for n in range(300)]
    pager = pager_factory(lines=lines, chapters=[], page_height=24, page_overlap=0)
    pager.viewport_rows = 12
    pager.viewport_width = 20
    for _ in range(10):
        shown = [index for index, _ in pager.visible_rows(12, 20)]
        # 记下这一屏最后显示到的源行
        last_shown = max(shown)
        pager.next_page()
        # 新一屏的首页正是它的下一行：既没跳过、也没重复
        assert pager.position == last_shown + 1


def test_next_page_is_reversible_with_wrapping(pager_factory) -> None:
    # 长段落折行时，一页页往回翻应当和前进时的落点一一对应
    lines = ["长" * 60] + ["第 {} 行".format(n) for n in range(40)]
    pager = pager_factory(lines=lines, chapters=[], page_overlap=0)
    pager.viewport_rows = 6
    pager.viewport_width = 10
    # 先往前翻 4 页，记下每一页的起点
    starts = []
    for _ in range(4):
        starts.append(pager.position)
        pager.next_page()
    # 再倒着翻回去，落点应当逐页吻合
    for expected in reversed(starts):
        pager.previous_page()
        assert pager.position == expected


def test_screen_range_counts_wrapped_lines(window, pager_factory) -> None:
    # 假窗口 10×40 → 正文区 8 行 × 39 列；长段折行后覆盖的源行变少
    lines = ["x" * 120] + ["短行 {}".format(n) for n in range(20)]
    pager = pager_factory(lines=lines, chapters=[])
    first, last = reader._screen_range(window, pager)
    assert first == 0
    # 120 字符按 39 列折成 4 屏行，剩下 4 行给短行 → 画到第 4 行（半开区间末端 5）
    assert last == 5


def test_paging_and_lines_read(pager) -> None:
    pager.next_page()
    # 前进 4 行
    assert pager.position == 4
    assert pager.lines_read == 4
    pager.previous_page()
    # 回到起点，但"已读行数"不回退
    assert pager.position == 0
    assert pager.lines_read == 4  # going back does not count as reading
    pager.to_start()
    assert pager.position == 0


def test_scroll_clamps_at_the_edges(pager) -> None:
    # 往前往后越界都被夹住
    pager.scroll(-10)
    assert pager.position == 0
    pager.scroll(1000)
    assert pager.position == pager.total - 1


def test_pager_chapter_navigation(pager) -> None:
    # 开局在第 0 章
    assert pager.current_chapter() == 0
    assert pager.chapter_title == "第一章 科学边界"
    assert pager.chapter_bounds_here() == (0, 4)

    # 下一章 -> 第 5 行
    pager.next_chapter()
    assert pager.position == 5
    assert pager.current_chapter() == 1
    assert pager.chapter_title == "第二章 台球"

    # 后面没章节了：跳到全书最后一行
    pager.next_chapter()
    assert pager.position == pager.total - 1  # nothing after the last chapter
    # 上一章回到开头
    pager.previous_chapter()
    assert pager.position == 0
    # 章首跳转：从第 6 行回到本章开头（第 5 行）
    pager.move_to(6)
    pager.chapter_top()
    assert pager.position == 5


def test_visible_rows_without_translation(pager) -> None:
    # 没翻译时一行就是一屏一行
    rows = pager.visible_rows(3)
    assert rows == [
        (0, "第一章 科学边界"),
        (1, ""),
        (2, "汪淼看到了一串数字在眼前跳动。"),
    ]


def test_visible_rows_wraps_long_lines_to_the_width(pager_factory) -> None:
    # 一行 12 个 ASCII 字符，宽度 5 应该折成 3 行（5 + 5 + 2）
    pager = pager_factory(lines=["abcdefghijkl"], chapters=[])
    rows = pager.visible_rows(4, width=5)
    # 折出来的每一行都还挂在同一个源行号 0 上
    assert rows == [(0, "abcde"), (0, "fghij"), (0, "kl")]


def test_visible_rows_wraps_chinese_by_two_columns(pager_factory) -> None:
    # 4 个汉字 = 8 列，宽度 4（两个汉字）应该折成 2 行
    pager = pager_factory(lines=["中文测试"], chapters=[])
    assert pager.visible_rows(4, width=4) == [(0, "中文"), (0, "测试")]


def test_visible_rows_stops_at_the_screen_height(pager_factory) -> None:
    # 折行后屏幕只有 2 行：只返回前两块，剩下的留给下一页
    pager = pager_factory(lines=["abcdefghijkl"], chapters=[])
    assert pager.visible_rows(2, width=5) == [(0, "abcde"), (0, "fghij")]


def test_rows_for_expands_the_bilingual_view(pager) -> None:
    # 切到双语视图，并手塞两条译文
    pager.mode = "both"
    pager.translations = {0: "EN:first", 1: ""}
    # 有译文：原文 + 译文两行
    assert pager.rows_for(0) == ["第一章 科学边界", "EN:first"]
    # An empty translation means "covered by the paragraph above": the source
    # line still belongs on screen, but no second row.
    # 空译文：双语视图下仍显示原文，但不额外占一行
    assert pager.rows_for(1) == [""]
    # 没译文的行照常显示原文
    assert pager.rows_for(2) == ["汪淼看到了一串数字在眼前跳动。"]

    # 切到纯英文视图
    pager.mode = "en"
    assert pager.rows_for(0) == ["EN:first"]
    # 空译文在纯译文视图里就是"重复内容"，直接丢掉
    assert pager.rows_for(1) == []  # dropped: nothing new to draw
    assert pager.rows_for(2) == ["汪淼看到了一串数字在眼前跳动。"]


def test_needs_translation(pager) -> None:
    # 中文书 + 中文视图：不需要翻译
    assert pager.needs_translation() is False  # Chinese book, Chinese view
    pager.mode = "both"
    assert pager.needs_translation() is True
    pager.mode = "en"
    assert pager.needs_translation() is True


def test_search_and_next_match(pager) -> None:
    # "第二章" 只出现在第 5 行
    assert pager.search("第二章") == 1
    assert pager.position == 5
    assert pager.current_match == 5
    # 只有一条命中：n 会绕回同一条
    assert pager.next_match() is True  # wraps around to the same single hit
    assert pager.position == 5
    assert pager.next_match() is True
    # 清空搜索后状态归零
    pager.clear_search()
    assert pager.matches == [] and pager.current_match == -1
    assert pager.next_match() is False


def test_search_without_hits_does_not_move(pager) -> None:
    pager.move_to(3)
    # 没命中：返回 0，光标不动
    assert pager.search("找不到的词") == 0
    assert pager.position == 3


def test_bookmarks_toggle_and_sort(pager) -> None:
    # 光标在第 0 行：加书签
    assert pager.is_bookmarked(0) is False
    assert pager.toggle_bookmark() is True
    assert pager.is_bookmarked(0) is True
    assert pager.bookmarks[0]["line"] == 0
    # 自动带上创建时间
    assert pager.bookmarks[0]["created"]

    # 第 6 行再加一个，书签按行号排序
    pager.move_to(6)
    pager.toggle_bookmark()
    assert [mark["line"] for mark in pager.bookmarks] == [0, 6]

    # 回到第 0 行再按一次：删掉
    pager.move_to(0)
    assert pager.toggle_bookmark() is False
    assert [mark["line"] for mark in pager.bookmarks] == [6]


def test_set_vocab_words_normalises(pager) -> None:
    # 去空白 + 转小写 + 丢掉空串
    pager.set_vocab_words([" Ephemeral ", "", "ACKNOWLEDGED"])
    assert pager.vocab_words == {"ephemeral", "acknowledged"}


def test_say_and_current_message(pager) -> None:
    # 默认显示 5 秒
    pager.say("hello")
    assert pager.current_message() == "hello"
    # 显示 0 秒：立刻过期
    pager.say("gone", seconds=0)
    assert pager.current_message() == ""


def test_word_target(pager) -> None:
    # 中文视图查词 -> 用配置的目标语言
    assert pager.word_target() == pager.target_language  # the Chinese view
    # 英文视图 -> 查英文
    pager.mode = "en"
    assert pager.word_target() == "en"  # a Chinese book looks words up in English
    # 双语视图同理
    pager.mode = "both"
    assert pager.word_target() == "en"


def test_translate_screen_uses_the_backend(pager, backend) -> None:
    # 切到英文视图，整屏翻译（8 行里 4 个段落）
    pager.mode = "en"
    assert pager.translate_screen(0, pager.total) == 4  # four paragraphs on screen
    # 译文按"段落首行"挂上，段内其余行给空串
    assert pager.translations == {
        0: "EN:第一章 科学边界",
        2: "EN:汪淼看到了一串数字在眼前跳动。 他抬头望向窗外的夜空。",
        3: "",
        5: "EN:第二章 台球",
        7: "EN:“三体世界就在我们眼前。”丁仪说道。",
    }


def test_split_highlight_marks_notebook_words() -> None:
    # 生词被单独切出来并标记为 True
    assert reader.split_highlight("An ephemeral joy", {"ephemeral"}) == [
        ("An ", False),
        ("ephemeral", True),
        (" joy", False),
    ]
    # 没有生词集合 / 空文本：整段原样返回
    assert reader.split_highlight("plain text", set()) == [("plain text", False)]
    assert reader.split_highlight("", {"x"}) == [("", False)]


def test_translate_screen_of_the_source_view_does_nothing(pager, backend) -> None:
    # 中文书 + 中文视图：不需要翻译，也不该发请求
    assert pager.translate_screen(0, pager.total) == 0
    assert backend.calls == []


def test_slow_chapter_hint(pager, monkeypatch) -> None:
    # 中文视图从不催
    assert pager.slow_chapter_hint() == ""  # the Chinese view never nags
    pager.mode = "en"
    # 把"本章已读时长"打桩成超过阈值
    monkeypatch.setattr(
        type(pager), "chapter_elapsed", lambda self: reader.SLOW_CHAPTER_SECONDS + 1
    )
    # 于是给出提示
    assert "按 c" in pager.slow_chapter_hint()


# ------------------------------------------------------------------- status bar
# 固定一个时间点，让显示时钟的断言可预测
MOMENT = datetime(2026, 1, 7, 21, 34, 56)


def test_status_segments(pager) -> None:
    # 先备好各片段要用的状态
    pager.bookmarks = [{"line": 0, "label": "", "created": ""}]
    pager.set_vocab_words(["ephemeral", "acknowledged"])
    pager.translations_used = 3
    pager.streak = 4
    # 逐个片段检查渲染结果
    assert reader.status_segment("time", pager, MOMENT) == "21:34"
    assert reader.status_segment("book", pager, MOMENT) == "untitled"
    assert reader.status_segment("chapter", pager, MOMENT) == "第一章 科学边界"
    assert reader.status_segment("position", pager, MOMENT) == "行 1/8"
    assert reader.status_segment("percent", pager, MOMENT) == "12.5%"
    assert reader.status_segment("mode", pager, MOMENT) == "中文"
    assert reader.status_segment("duration", pager, MOMENT).startswith("本章 ")
    assert reader.status_segment("elapsed", pager, MOMENT).startswith("本次 ")
    assert reader.status_segment("streak", pager, MOMENT) == "连续 4 天"
    assert reader.status_segment("bookmarks", pager, MOMENT) == "书签 1"
    assert reader.status_segment("vocab", pager, MOMENT) == "生词 2"
    assert reader.status_segment("translations", pager, MOMENT) == "翻译 3"
    # 不认识的片段名返回空串（上层会跳过）
    assert reader.status_segment("nope", pager, MOMENT) == ""


def test_status_segment_without_chapters(pager_factory) -> None:
    # 没有章节信息时显示占位文案
    pager = pager_factory(chapters=[])
    assert reader.status_segment("chapter", pager, MOMENT) == "无章节"


def test_format_status_bar_joins_the_configured_segments(pager) -> None:
    # 按配置的片段顺序用 " · " 连接
    pager.status_bar_format = "time|book|percent"
    assert reader.format_status_bar(pager, MOMENT) == "21:34 · untitled · 12.5%"


def test_format_status_bar_skips_unknown_tokens(pager) -> None:
    # 未知片段被跳过而不是原样打印
    pager.status_bar_format = "time|nope|percent"
    assert reader.format_status_bar(pager, MOMENT) == "21:34 · 12.5%"


def test_format_status_bar_falls_back_to_the_clock(pager) -> None:
    # 配置全写错时退回显示时钟
    pager.status_bar_format = "nope|also_nope"
    assert reader.format_status_bar(pager, MOMENT) == "21:34"


def test_format_status_bar_drops_whole_segments_when_narrow(pager, monkeypatch) -> None:
    # 把"本章时长"钉成 00:00，宽度的算术才好写死
    monkeypatch.setattr(type(pager), "chapter_elapsed", lambda self: 0.0)
    pager.status_bar_format = "time|chapter|duration"
    # 按显示列数算：21:34(5) · 第一章 科学边界(15) · 本章 00:00(10)
    # 宽 10：只放得下第一段
    assert reader.format_status_bar(pager, MOMENT, width=10) == "21:34"
    # 宽 22：加上分隔符要 5 + 3 + 15 = 23 列，差一列 → 第二段整段丢掉
    assert reader.format_status_bar(pager, MOMENT, width=22) == "21:34"
    # 宽 23：正好放得下前两段，第三段整段丢掉（不切一半）
    assert reader.format_status_bar(pager, MOMENT, width=23) == "21:34 · 第一章 科学边界"
    # 宽 36：5 + 3 + 15 + 3 + 10 正好排满，三段都在
    assert (
        reader.format_status_bar(pager, MOMENT, width=36)
        == "21:34 · 第一章 科学边界 · 本章 00:00"
    )


# ---------------------------------------------------------------------- drawing
def test_draw_paints_the_book_and_the_status_rows(window, pager) -> None:
    reader._draw(window, pager, MOMENT)
    # 每帧都要清屏 + 提交一次
    assert window.erase_calls == 1
    assert window.refreshes == 1
    # 第 0 列是书签标记（空），第 1 列开始是正文
    assert window.row(0) == " 第一章 科学边界"
    assert window.row(2) == " 汪淼看到了一串数字在眼前跳动。"
    # 倒数第二行是信息栏，最后一行是快捷键提示
    assert "21:34" in window.row(window.height - 2)
    assert "q退出" in window.row(window.height - 1)


def test_draw_marks_a_bookmarked_line(window, pager) -> None:
    # 给第 0 行加书签后，行首应当出现 ★
    pager.toggle_bookmark()
    reader._draw(window, pager, MOMENT)
    assert window.row(0).startswith("★")


def test_draw_highlights_the_current_search_hit(window, pager) -> None:
    pager.search("第二章")  # jumps to line 5, so it becomes the first row on screen
    reader._draw(window, pager, MOMENT)
    # 收集"屏幕行 -> 绘制属性"
    attrs = {row: attr for row, _column, _text, attr in window.writes}
    # 当前命中那一行是反白
    assert attrs[0] & curses.A_REVERSE
    # The rows that are merely part of the book stay normal.
    # 其它行保持普通属性
    assert not attrs[1] & curses.A_REVERSE


def test_draw_expands_tabs(window, pager_factory) -> None:
    # 正文里的制表符会被展开成 4 个空格
    pager = pager_factory(lines=["col\tone"], chapters=[])
    reader._draw(window, pager, MOMENT)
    assert window.row(0) == " col    one"


def test_draw_wraps_a_long_line_onto_the_next_row(pager_factory) -> None:
    # 屏幕宽 12：正文可用 11 列（第 0 列留给书签标记）
    window = FakeStdscr(height=10, width=12)
    pager = pager_factory(lines=["abcdefghijklmnop"], chapters=[])
    reader._draw(window, pager, MOMENT)
    # 长行被折到下一行继续显示，而不是被右边界截断
    assert window.row(0) == " abcdefghijk"
    assert window.row(1) == " lmnop"


def test_draw_wraps_chinese_by_display_width(pager_factory) -> None:
    # 屏幕宽 8 -> 正文 7 列：一个汉字 2 列，所以每行放 3 个汉字（6 列）
    window = FakeStdscr(height=10, width=8)
    pager = pager_factory(lines=["中文测试"], chapters=[])
    reader._draw(window, pager, MOMENT)
    assert window.row(0) == " 中文测"
    assert window.row(1) == " 试"


def test_draw_marks_a_bookmark_only_on_the_first_wrapped_row(pager_factory) -> None:
    # 窄屏 + 长行：折行后书签标记只该出现在源行的第一条屏幕行上
    window = FakeStdscr(height=10, width=12)
    pager = pager_factory(lines=["abcdefghijklmnop"], chapters=[])
    # 光标在第 0 行，按 b 加书签
    pager.toggle_bookmark()
    reader._draw(window, pager, MOMENT)
    # 第一行行首是 ★，续行只是普通占位空格
    assert window.row(0) == "★abcdefghijk"
    assert window.row(1) == " lmnop"


def test_draw_fits_the_status_rows_on_a_narrow_screen(pager_factory) -> None:
    # 20 列窄屏 + 长中文书名 + 长中文消息
    window = FakeStdscr(height=8, width=20)
    pager = pager_factory(
        lines=["这是一个很长的中文句子，用来测试窄屏下的换行。"],
        title="三体：地球往事与黑暗森林",
    )
    pager.status_bar_format = "book|position"
    pager.say("这是一条很长的中文消息")
    reader._draw(window, pager, MOMENT)
    # 每一笔写入都不能越过右边界（真终端上越界会让整行消失）
    for row, column, text, _attr in window.writes:
        # 这一笔占了多少列
        used = sum(reader._char_width(char) for char in text)
        assert column + used <= window.width, (row, column, text)
    # 信息栏按显示列数裁：19 列放得下 9 个汉字，而不是 19 个
    assert window.row(window.height - 2) == "三体：地球往事与黑"
    # 消息行同理
    assert window.row(window.height - 1) == "这是一条很长的中文"


def test_addstr_clips_a_row_wider_than_the_window() -> None:
    # 文本比窗口窄：原样写下去
    wide = FakeStdscr(height=8, width=40)
    reader._addstr(wide, 0, 0, "中文很长的一句话", curses.A_NORMAL)
    assert [text for row, _c, text, _a in wide.writes if row == 0] == ["中文很长的一句话"]

    # 文本比窗口宽：剪到屏幕宽度再写，而不是让 curses 报错、整行消失
    narrow = FakeStdscr(height=8, width=12)
    reader._addstr(narrow, 0, 0, "中文很长的一句话", curses.A_NORMAL)
    # 12 列只放得下 6 个汉字，而且不会把第 7 个劈开
    assert [text for row, _c, text, _a in narrow.writes if row == 0] == ["中文很长的一"]


def test_addstr_clips_within_the_remaining_columns() -> None:
    # 从第 10 列开始写：只剩 2 列，刚好放一个汉字
    offset = FakeStdscr(height=8, width=12)
    reader._addstr(offset, 0, 10, "中文", curses.A_NORMAL)
    assert [text for row, _c, text, _a in offset.writes if row == 0] == ["中"]

    # 只剩 1 列时一个宽字符都放不下：干脆不写，省得 curses 报错
    tiny = FakeStdscr(height=8, width=13)
    reader._addstr(tiny, 0, 12, "中", curses.A_NORMAL)
    assert tiny.writes == []


def test_message_row_shows_the_message_then_the_hint(window, pager) -> None:
    # 有临时消息：显示消息
    pager.say("hello there")
    assert reader._message_row(pager, 40).startswith("hello there")
    # 消息过期：退回快捷键提示
    pager.say("gone", seconds=0)
    assert "q退出" in reader._message_row(pager, 40)


def test_message_row_shows_the_long_chapter_nudge(pager, monkeypatch) -> None:
    # 打桩"本章读很久了"和对应的提示语
    monkeypatch.setattr(
        type(pager), "chapter_elapsed", lambda self: reader.SLOW_CHAPTER_SECONDS + 1
    )
    monkeypatch.setattr(type(pager), "slow_chapter_hint", lambda self: "看中文?")
    # The row is padded to the requested width, so compare on the stripped text.
    # 宽 100：提示追加在快捷键后面
    assert reader._message_row(pager, 100).strip().endswith("看中文?")
    # 宽 9：放不下"快捷键 + 提示"，只显示提示本身
    assert reader._message_row(pager, 9).strip() == "看中文?"
    # 宽 5：提示本身也放不下（"看中文?" 占 7 列），按显示宽度裁成前两个汉字
    assert reader._message_row(pager, 5).strip() == "看中"


# ------------------------------------------------------------------------ keys
def test_quit_keys(window, pager) -> None:
    # q / Q / Ctrl-C 都返回 False（表示退出）
    assert reader.handle_key(window, pager, "q") is False
    assert reader.handle_key(window, pager, "Q") is False
    assert reader.handle_key(window, pager, 3) is False  # Ctrl-C


# 参数化：所有"向下翻页"的按键
@pytest.mark.parametrize(
    "key", ["j", " ", "\n", "\r", curses.KEY_DOWN, curses.KEY_NPAGE]
)
def test_page_forward_keys(window, pager, key) -> None:
    # 都能前进一页（4 行）
    assert reader.handle_key(window, pager, key) is True
    assert pager.position == 4


# 参数化：所有"向上翻页"的按键
@pytest.mark.parametrize("key", ["k", curses.KEY_UP, curses.KEY_PPAGE])
def test_page_back_keys(window, pager, key) -> None:
    pager.move_to(4)
    reader.handle_key(window, pager, key)
    assert pager.position == 0


def test_chapter_and_end_keys(window, pager) -> None:
    # ] 下一章
    reader.handle_key(window, pager, "]")
    assert pager.position == 5
    # [ 上一章
    reader.handle_key(window, pager, "[")
    assert pager.position == 0
    # G 跳到末尾
    reader.handle_key(window, pager, "G")
    assert pager.position == pager.total - 1


def test_bookmark_key_reports_both_directions(window, pager) -> None:
    # 第一次按 b：加书签并提示
    reader.handle_key(window, pager, "b")
    assert "已加书签" in pager.current_message()
    assert pager.is_bookmarked(0) is True
    # 再按一次：删除并提示
    reader.handle_key(window, pager, "b")
    assert "已删除书签" in pager.current_message()
    assert pager.is_bookmarked(0) is False


def test_next_match_without_a_search_says_so(window, pager) -> None:
    # 还没搜过就按 n：给出引导
    assert reader.handle_key(window, pager, "n") is True
    assert "先按 / 搜索" in pager.current_message()


def test_next_match_after_a_search(window, pager) -> None:
    # 搜到第 3 行，回到开头再按 n：跳到命中行
    pager.search("他抬头")
    pager.move_to(0)
    reader.handle_key(window, pager, "n")
    assert pager.position == 3


def test_view_keys(window, pager, backend) -> None:
    # l 循环切换：中文 -> 英文
    reader.handle_key(window, pager, "l")
    assert pager.mode == "en"
    assert "视图：英文" in pager.current_message()
    # 切到英文视图时顺带翻当前屏
    assert "已翻译" in pager.current_message()

    # 再按一次 -> 双语对照
    reader.handle_key(window, pager, "l")
    assert pager.mode == "both"

    # c 直接回中文视图
    reader.handle_key(window, pager, "c")
    assert pager.mode == "zh"
    assert "当前视图就是原文" in pager.current_message()


def test_translate_screen_key(panel_window, pager, backend) -> None:
    # t：翻当前屏幕并把译文弹在下方（临时，不缓存）——
    # 注意即使在中文视图里也翻（目标是"另一种语言"，中文书 -> 英文）
    reader.handle_key(panel_window, pager, "t")
    # 译文已并进视图，之后切到双语/英文视图立刻可见
    assert pager.translations[0] == "EN:第一章 科学边界"
    # 记一次翻译使用
    assert pager.translations_used == 1
    # 弹窗（第一个子窗口）里画出了这段译文
    popup = panel_window.windows[0]
    drawn = [text for _row, _column, text, _attr in popup.writes]
    assert any("EN:第一章 科学边界" in text for text in drawn)


def test_translate_screen_key_without_an_engine_says_so(monkeypatch, panel_window, pager) -> None:
    # 引擎没配好：提示去跑 werd config translate，而不是发请求
    monkeypatch.setattr(reader, "_translation_ready", lambda: (False, "baidu 缺少 APPID"))
    reader.handle_key(panel_window, pager, "t")
    assert "werd config translate" in pager.current_message()


def test_translate_chapter_key_caches_the_chapter(
    imported, pager_factory, backend
) -> None:
    # 绑定真实 book_id，让 T 能把缓存写到磁盘
    pager = pager_factory(book_id=imported["zh"])
    window = FakeStdscr()
    reader.handle_key(window, pager, "T")
    # 提示语说明是"已写入缓存"（不是来自缓存）
    assert "第 1 章已就绪（已写入缓存）" in pager.current_message()
    assert pager.translations_used == 1
    # 译文已合并进视图
    assert pager.translations[0] == "EN:第一章 科学边界"


def test_translate_chapter_key_reports_a_failure(window, pager_factory) -> None:
    # book_id 为空：翻译必然失败，提示里要有"翻译失败"
    pager = pager_factory(book_id="")
    reader.handle_key(window, pager, "T")
    assert "翻译失败" in pager.current_message()


def test_goto_key(window, pager, monkeypatch) -> None:
    # 让输入框直接返回 "3"（用户看到的是 1 起始的行号）
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "3")
    reader.handle_key(window, pager, "g")
    assert pager.position == 2
    assert "已跳到第 3 / 8 行" == pager.current_message()


def test_goto_key_rejects_a_non_number(window, pager, monkeypatch) -> None:
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "第十章")
    reader.handle_key(window, pager, "g")
    # 位置不变并给出提示
    assert pager.position == 0
    assert "行号需要是数字" in pager.current_message()


def test_goto_key_can_be_cancelled(window, pager, monkeypatch) -> None:
    # Esc 取消：返回 None
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: None)
    reader.handle_key(window, pager, "g")
    assert pager.position == 0
    assert pager.current_message() == ""


def test_search_key(window, pager, monkeypatch) -> None:
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "第二章")
    reader.handle_key(window, pager, "/")
    # 跳到命中行并提示命中数
    assert pager.position == 5
    assert "命中 1 行" in pager.current_message()


def test_search_key_without_hits(window, pager, monkeypatch) -> None:
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "zzz")
    reader.handle_key(window, pager, "/")
    # 没有命中：搜索状态干净，提示"没有找到"
    assert pager.matches == []
    assert "没有找到" in pager.current_message()


def test_mark_word_uses_the_prompt(monkeypatch, window, pager, backend) -> None:
    # 输入框返回要查的词
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "ephemeral")
    reader.handle_key(window, pager, "v")
    # 默认开启自动入库，所以消息里带上释义
    assert pager.current_message() == "已加入生词本：ephemeral = EN:ephemeral"
    assert [entry["word"] for entry in vocab.load_vocab()] == ["ephemeral"]
    assert pager.vocab_words == {"ephemeral"}  # underlined from now on


def test_mark_word_can_be_declined(monkeypatch, window, pager_factory, backend) -> None:
    # 关掉自动入库，并把确认弹窗打桩成"否"
    pager = pager_factory(auto_add_on_mark=False)
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "ephemeral")
    monkeypatch.setattr(reader, "_confirm", lambda *a, **k: False)
    reader.handle_key(window, pager, "v")
    # 取消后不写进笔记本
    assert pager.current_message() == "已取消：ephemeral"
    assert vocab.load_vocab() == []


def test_mark_word_needs_a_word(monkeypatch, window, pager) -> None:
    # 只输入空白：什么都不做
    monkeypatch.setattr(reader, "_prompt", lambda *a, **k: "   ")
    reader.handle_key(window, pager, "v")
    assert pager.current_message() == ""
    assert vocab.load_vocab() == []


def test_reload_vocab_reads_the_notebook_into_the_pager(pager) -> None:
    # 笔记本里有词，重新载入后下划线集合就有它
    vocab.add_word("acknowledged", "公认的")
    pager.set_vocab_words([])
    reader._reload_vocab(pager)
    assert pager.vocab_words == {"acknowledged"}


def test_reload_vocab_survives_a_broken_notebook(pager) -> None:
    # 笔记本文件坏了：只给提示，不抛异常
    vocab.vocab_file().parent.mkdir(parents=True, exist_ok=True)
    vocab.vocab_file().write_text("{oops", encoding="utf-8")
    reader._reload_vocab(pager)
    assert "生词本读取失败" in pager.current_message()


def test_the_stopwatches_run(pager) -> None:
    # 两个计时器都应当给出非负的秒数
    assert pager.chapter_elapsed() >= 0
    assert pager.session_elapsed() >= 0


def test_screen_range_and_progress_text(window, pager) -> None:
    # 屏幕高 10 - 状态栏 2 = 8 行正文
    assert reader._screen_range(window, pager) == (0, 8)
    # 进度条：16 格，按比例填 #
    assert reader._progress_text(0, 4) == "[----------------]  0/4"
    assert reader._progress_text(2, 4) == "[########--------]  2/4"
    # 总数 <= 0 时返回空串
    assert reader._progress_text(2, 0) == ""


def test_an_unhandled_key_is_ignored(window, pager) -> None:
    # 不认识的按键：继续运行，什么都不改
    assert reader.handle_key(window, pager, "z") is True
    assert pager.position == 0
    assert pager.current_message() == ""


# -------------------------------------------------------------------- terminal
def test_init_colors_uses_the_terminal_defaults(monkeypatch) -> None:
    # 有颜色支持时：先 start_color，再 use_default_colors（顺序不能反）
    calls: List[str] = []
    monkeypatch.setattr(reader.curses, "has_colors", lambda: True)
    monkeypatch.setattr(reader.curses, "start_color", lambda: calls.append("start"))
    monkeypatch.setattr(
        reader.curses, "use_default_colors", lambda: calls.append("default")
    )
    reader._init_colors()
    assert calls == ["start", "default"]


def test_init_colors_is_a_noop_without_color_support(monkeypatch) -> None:
    # 终端根本不支持颜色：两个调用都不该发生
    monkeypatch.setattr(reader.curses, "has_colors", lambda: False)
    calls: List[str] = []
    monkeypatch.setattr(reader.curses, "start_color", lambda: calls.append("start"))
    monkeypatch.setattr(
        reader.curses, "use_default_colors", lambda: calls.append("default")
    )
    reader._init_colors()
    assert calls == []


def test_init_colors_survives_a_terminal_without_default_colors(monkeypatch) -> None:
    # 老终端有颜色但不支持"默认色"：抛 curses.error 也不能让阅读器崩掉
    monkeypatch.setattr(reader.curses, "has_colors", lambda: True)
    monkeypatch.setattr(reader.curses, "start_color", lambda: None)

    def refuse() -> None:
        # 模拟"该终端没有 default 颜色能力"
        raise curses.error("no default colors here")

    monkeypatch.setattr(reader.curses, "use_default_colors", refuse)
    # 不抛异常就算通过
    reader._init_colors()


# ---------------------------------------------------------- recording a session
def test_build_session() -> None:
    # 负数行数会被兜成 0
    session = reader.build_session(
        datetime(2026, 1, 1, 10, 0, 0), datetime(2026, 1, 1, 10, 5, 0), -3
    )
    assert session == {
        "start": "2026-01-01T10:00:00",
        "end": "2026-01-01T10:05:00",
        "lines_read": 0,  # never negative
    }


def test_accumulate_stats() -> None:
    document: dict = {}
    # 三次累加：同一天两次、另一天一次
    reader.accumulate_stats(document, 60, "2026-01-01")
    reader.accumulate_stats(document, 30, "2026-01-01")
    reader.accumulate_stats(document, 10, "2026-01-02")
    # 全局 100 秒，按天分别 90 / 10
    assert document["stats"]["total_read_time"] == 100
    assert document["stats"]["daily_read_time"] == {"2026-01-01": 90, "2026-01-02": 10}


def test_write_position_needs_the_book(pager) -> None:
    # ``_write_position`` indexes ``document["books"]``, so the document always has
    # to be a library document; an unknown id is the "book was removed" case.
    # 书 id 不在文档里：返回 False 表示写不进去
    assert reader._write_position({"books": {}}, "nope", pager, MOMENT) is False


def test_write_position_stores_the_spot(imported, pager_factory) -> None:
    pager = pager_factory(book_id=imported["zh"])
    pager.move_to(3)
    pager.toggle_bookmark()
    # 用一份最小的书库文档来测写入
    document = {"books": {imported["zh"]: {"progress": {}}}}
    assert reader._write_position(document, imported["zh"], pager, MOMENT) is True

    progress = document["books"][imported["zh"]]["progress"]
    # 行号、时间戳、书签都被写进去了
    assert progress["current_line"] == 3
    assert progress["last_read"] == "2026-01-07T21:34:56"
    assert progress["finished"] is False
    assert [mark["line"] for mark in progress["bookmarks"]] == [3]


def test_write_position_keeps_a_finished_book_finished(imported, pager_factory) -> None:
    pager = pager_factory(book_id=imported["zh"])
    # 已经标记"读完"的书：即使光标不在末尾也保持 True
    document = {"books": {imported["zh"]: {"progress": {"finished": True}}}}
    reader._write_position(document, imported["zh"], pager, MOMENT)
    assert document["books"][imported["zh"]]["progress"]["finished"] is True

    # Reaching the last line also sets it.
    # 另一种情况：光标到达最后一行也会自动置位
    pager.to_end()
    fresh = {"books": {imported["zh"]: {"progress": {}}}}
    reader._write_position(fresh, imported["zh"], pager, MOMENT)
    assert fresh["books"][imported["zh"]]["progress"]["finished"] is True


def test_save_position_writes_the_library(imported, pager_factory) -> None:
    from wreader import library

    pager = pager_factory(book_id=imported["zh"])
    pager.move_to(2)
    # 写到磁盘并读回来验证
    assert reader.save_position(pager) is True
    book = library.get_book(imported["zh"])
    assert book is not None and book["progress"]["current_line"] == 2

    # 书不存在时返回 False（不抛异常）
    pager.book_id = "gone"
    assert reader.save_position(pager) is False


def test_save_session_records_everything(imported, pager_factory) -> None:
    from wreader import library

    pager = pager_factory(book_id=imported["zh"])
    pager.move_to(4)
    # 本次会话用过 2 次翻译
    pager.translations_used = 2
    reader.save_session(
        imported["zh"],
        pager,
        90,
        datetime(2026, 1, 1, 10, 0, 0),
        datetime(2026, 1, 1, 10, 1, 30),
    )

    book = library.get_book(imported["zh"])
    assert book is not None
    progress = book["progress"]
    # 位置、本书累计时长、会话明细都写进去了
    assert progress["current_line"] == 4
    assert progress["total_time_seconds"] == 90
    assert progress["sessions"] == [
        {"start": "2026-01-01T10:00:00", "end": "2026-01-01T10:01:30", "lines_read": 4}
    ]
    # 全局统计与当天桶、翻译次数也一起更新
    document = library.load_library()
    assert document["stats"]["total_read_time"] == 90
    assert document["stats"]["daily_read_time"] == {"2026-01-01": 90}
    assert document["stats"]["translations"] == 2


def test_save_session_can_skip_the_history(imported, pager_factory) -> None:
    from wreader import library

    pager = pager_factory(book_id=imported["zh"])
    # record_history=False：只存位置，不记会话与统计
    reader.save_session(
        imported["zh"],
        pager,
        60,
        datetime(2026, 1, 1, 10, 0, 0),
        datetime(2026, 1, 1, 10, 1, 0),
        record_history=False,
    )
    book = library.get_book(imported["zh"])
    assert book is not None
    assert book["progress"]["sessions"] == []
    assert book["progress"]["total_time_seconds"] == 0
    assert library.load_library()["stats"].get("total_read_time", 0) == 0


def test_save_session_of_a_removed_book_is_harmless(imported, pager_factory) -> None:
    # 书在阅读过程中被删掉：保存会话不该抛异常
    pager = pager_factory(book_id="gone")
    reader.save_session(
        "gone",
        pager,
        10,
        datetime(2026, 1, 1, 10, 0, 0),
        datetime(2026, 1, 1, 10, 0, 10),
    )  # must not raise


# ---------------------------------------------------------------- opening a book
def test_open_reader_rejects_an_unknown_book() -> None:
    from wreader import library

    with pytest.raises(library.LibraryError) as excinfo:
        reader.open_reader("nope")
    assert "unknown book id" in str(excinfo.value)


def test_open_reader_needs_a_terminal(imported) -> None:
    from wreader import library

    # Under pytest stdout is captured, so this is the documented non-tty path.
    # pytest 下 stdout 被捕获，因此自然会走到"非终端"分支
    with pytest.raises(library.LibraryError) as excinfo:
        reader.open_reader(imported["zh"])
    assert "needs an interactive terminal" in str(excinfo.value)


def test_open_reader_rejects_a_book_without_text(isolated_home) -> None:
    from wreader import library

    # 正文文件存在但是空的
    empty = isolated_home.novels / "empty_utf8.txt"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_text("", encoding="utf-8")
    document = library.load_library()
    document["books"]["empty"] = {"title": "Empty", "file_path": str(empty)}
    library.save_library(document)

    with pytest.raises(library.LibraryError) as excinfo:
        reader.open_reader("empty")
    assert "no readable text" in str(excinfo.value)


def test_open_reader_needs_the_file(isolated_home) -> None:
    from wreader import library

    # 索引里有记录但正文文件不存在
    document = library.load_library()
    document["books"]["gone"] = {"title": "Gone", "file_path": "/nope/missing.txt"}
    library.save_library(document)
    with pytest.raises(library.LibraryError) as excinfo:
        reader.open_reader("gone")
    assert "book text is missing" in str(excinfo.value)


# ------------------------------------------- 鼠标滚轮 / 触摸拖动（移动端翻页）
def test_drag_scroll_reads_on_when_the_finger_moves_up() -> None:
    # 手指往上滑（y 变小）= 往后翻，和手机阅读习惯一致
    drag = reader._DragScroll()
    drag.press(10)
    assert drag.move(7) == 3


def test_drag_scroll_goes_back_when_the_finger_moves_down() -> None:
    # 手指往下滑（y 变大）= 往前翻
    drag = reader._DragScroll()
    drag.press(10)
    assert drag.move(13) == -3


def test_drag_scroll_is_one_line_per_row() -> None:
    # 拖一行 = 滚一行：连续各挪一行，位移依次是 -1 / -1 / -1
    drag = reader._DragScroll()
    drag.press(0)
    assert [drag.move(step) for step in (1, 2, 3)] == [-1, -1, -1]


def test_drag_scroll_ignores_moves_without_a_press() -> None:
    # 没按住就忽略：既不滚动，也不会被误当成"拖动开始"（桌面端移动鼠标不该翻页）
    drag = reader._DragScroll()
    assert drag.move(5) == 0
    assert drag.active is False


def test_drag_scroll_forgets_the_anchor_after_a_release() -> None:
    # 抬手之后再移动，不应该接着算位移
    drag = reader._DragScroll()
    drag.press(10)
    drag.release()
    assert drag.active is False
    assert drag.move(20) == 0


def test_pager_defaults_for_mobile_scrolling(pager_factory) -> None:
    # 默认：滚轮一格 1 行、拖动即滚动开着
    pager = pager_factory()
    assert pager.wheel_scroll_step == 1
    assert pager.touch_scroll is True


def test_pager_clamps_a_zero_wheel_step(pager_factory) -> None:
    # 步长写成 0 会兜底成 1，否则滚了等于没滚
    assert pager_factory(wheel_scroll_step=0).wheel_scroll_step == 1


def test_wheel_constants_come_from_curses() -> None:
    # 滚轮位直接取 curses 的常量：拿得到就用真的
    assert reader._WHEEL_UP == int(getattr(curses, "BUTTON4_PRESSED", 0))
    assert reader._WHEEL_DOWN == int(getattr(curses, "BUTTON5_PRESSED", 0))


def test_mouse_wheel_scrolls_by_the_configured_step(monkeypatch, pager_factory) -> None:
    # 滚轮下 = 往后翻、滚轮上 = 往回翻，一格走 wheel_scroll_step 行。
    # 这里把滚轮位换成哨兵位：并非所有平台都导出 BUTTON5_PRESSED（macOS 实测就没有），
    # 用哨兵位才能在任意平台上稳定地验证"方向 + 步长"这段逻辑。
    monkeypatch.setattr(reader, "_WHEEL_UP", 1 << 28)
    monkeypatch.setattr(reader, "_WHEEL_DOWN", 1 << 29)
    pager = pager_factory(wheel_scroll_step=3)
    drag = reader._DragScroll()
    assert reader._mouse_scroll_delta(pager, reader._WHEEL_DOWN, 5, drag) == 3
    assert reader._mouse_scroll_delta(pager, reader._WHEEL_UP, 5, drag) == -3


def test_mouse_wheel_scrolls_one_line_by_default(monkeypatch, pager_factory) -> None:
    # 默认一格就是 1 行
    monkeypatch.setattr(reader, "_WHEEL_UP", 1 << 28)
    monkeypatch.setattr(reader, "_WHEEL_DOWN", 1 << 29)
    pager = pager_factory()
    drag = reader._DragScroll()
    assert reader._mouse_scroll_delta(pager, reader._WHEEL_DOWN, 0, drag) == 1
    assert reader._mouse_scroll_delta(pager, reader._WHEEL_UP, 0, drag) == -1


def test_mouse_drag_scrolls_by_the_finger_movement(pager_factory) -> None:
    # 按下那一下只记起点（不滚动），继续拖才按位移滚
    pager = pager_factory()
    drag = reader._DragScroll()
    assert reader._mouse_scroll_delta(pager, curses.BUTTON1_PRESSED, 20, drag) == 0
    # 手指从第 20 行滑到第 16 行：往上滑 4 行 → 往后翻 4 行
    assert reader._mouse_scroll_delta(pager, curses.BUTTON1_PRESSED, 16, drag) == 4


def test_mouse_drag_is_ignored_when_touch_scrolling_is_off(pager_factory) -> None:
    # 关掉 touch_scroll 后拖动不动正文，而且不会残留拖动状态
    pager = pager_factory(touch_scroll=False)
    drag = reader._DragScroll()
    assert reader._mouse_scroll_delta(pager, curses.BUTTON1_PRESSED, 20, drag) == 0
    assert drag.active is False


def test_mouse_motion_without_a_button_does_not_scroll(pager_factory) -> None:
    # 桌面端单纯移动鼠标（没有按键）不该翻页
    pager = pager_factory()
    drag = reader._DragScroll()
    assert reader._mouse_scroll_delta(pager, reader._MOUSE_MOTION, 20, drag) == 0
    assert drag.active is False


def test_mouse_release_ends_the_drag(pager_factory) -> None:
    # 抬手事件（只有 RELEASED 位）要结束拖动，免得下次移动接着算位移
    pager = pager_factory()
    drag = reader._DragScroll()
    reader._mouse_scroll_delta(pager, curses.BUTTON1_PRESSED, 20, drag)
    assert drag.active is True
    reader._mouse_scroll_delta(pager, curses.BUTTON1_RELEASED, 20, drag)
    assert drag.active is False


def test_mouse_drag_keeps_working_on_motion_reports_alone(pager_factory) -> None:
    # 有些终端拖到一半就不再报按键位、只发位置报告：只要还在拖就继续滚
    pager = pager_factory()
    drag = reader._DragScroll()
    reader._mouse_scroll_delta(pager, curses.BUTTON1_PRESSED, 20, drag)
    assert reader._mouse_scroll_delta(pager, reader._MOUSE_MOTION, 18, drag) == 2


def test_enable_mouse_asks_for_position_reports(monkeypatch) -> None:
    # 必须把「位置报告」一起请上，否则拖动根本不会产生事件
    seen: dict[str, int] = {}

    def record_mask(mask: int) -> tuple[int, int]:
        # 记下掩码；真 curses 返回的是 (availmask, oldmask) 元组
        seen["mask"] = mask
        return mask, 0

    monkeypatch.setattr(curses, "mousemask", record_mask, raising=False)
    monkeypatch.setattr(curses, "mouseinterval", lambda value: 0, raising=False)
    reader._enable_mouse()
    assert seen["mask"] & reader._MOUSE_MOTION


def test_enable_mouse_disables_the_click_window(monkeypatch) -> None:
    # 关键回归：必须把 ncurses 的「点击判定窗口」设成 0。
    # 实测（真 pty 灌 SGR 序列）默认窗口会把按下事件扣住，拖动状态建立不起来，
    # 后面的位置报告全被当成普通移动丢掉 —— 拖动会完全失效。
    seen: dict[str, int] = {}

    def record_interval(value: int) -> int:
        # 记下传入的间隔；真 curses 返回旧值
        seen["interval"] = value
        return 166

    monkeypatch.setattr(curses, "mouseinterval", record_interval, raising=False)
    monkeypatch.setattr(curses, "mousemask", lambda mask: (mask, 0), raising=False)
    reader._enable_mouse()
    assert seen["interval"] == 0


def test_enable_mouse_tolerates_a_missing_mouseinterval(monkeypatch) -> None:
    # 个别 curses 实现没有 mouseinterval：抛错也必须被吞掉，不能把阅读器弄崩
    def boom(_value: int) -> int:
        # 模拟不支持这个调用
        raise curses.error("no mouseinterval")

    monkeypatch.setattr(curses, "mouseinterval", boom, raising=False)
    monkeypatch.setattr(curses, "mousemask", lambda mask: (mask, 0), raising=False)
    reader._enable_mouse()


def test_enable_mouse_survives_a_terminal_without_mouse_support(monkeypatch) -> None:
    # 不支持鼠标的终端会抛 curses.error：必须吞掉，不能把阅读器弄崩
    def boom(*_args: object) -> None:
        # 模拟老终端：一开鼠标上报就报错
        raise curses.error("no mouse here")

    monkeypatch.setattr(curses, "mousemask", boom, raising=False)
    reader._enable_mouse()









# --------------------------------------------------------------- toc overlay
def test_toc_panel_width_reserves_room_for_the_text() -> None:
    # 100 列的 40% 就是 40 列
    assert reader._toc_panel_width(100) == 40
    # 窄屏时至少给正文留 8 列，面板退到 2 列
    assert reader._toc_panel_width(10) == 2


def test_toc_window_keeps_the_cursor_visible() -> None:
    # 一屏装得下：全部显示
    assert reader._toc_window(3, 1, 5) == (0, 3)
    # 条目多于行数：窗口跟着光标走
    assert reader._toc_window(100, 50, 10) == (45, 55)
    # 光标在末尾：窗口贴住右端，不越界
    assert reader._toc_window(100, 99, 10) == (90, 100)
    # 没有条目：空窗口
    assert reader._toc_window(0, 0, 10) == (0, 0)


def test_toc_move_cursor_clamps_at_both_ends() -> None:
    # 两端都夹住
    assert reader._toc_move_cursor(3, 0, curses.KEY_UP) == 0
    assert reader._toc_move_cursor(3, 2, curses.KEY_DOWN) == 2
    # 正常移动
    assert reader._toc_move_cursor(3, 1, curses.KEY_DOWN) == 2
    # j/k 也能移动（浮层是模态的，与翻页键不冲突）
    assert reader._toc_move_cursor(3, 0, "j") == 1
    # 空列表：光标恒为 0
    assert reader._toc_move_cursor(0, 5, curses.KEY_DOWN) == 0


# 造一份两章的目录条目（line 与 BOOK_LINES 的章节起点对齐）
def _toc_entries() -> List[Dict[str, Any]]:
    return [
        {"title": "第一章 科学边界", "line": 0, "percentage": 0.0},
        {"title": "第二章 台球", "line": 5, "percentage": 75.0},
    ]


def test_tab_opens_the_overlay_and_jumps_to_the_chapter(window, pager_factory) -> None:
    pager = pager_factory(toc_entries=_toc_entries())
    # Tab 打开浮层 -> ↓ 移到第二章 -> 回车确认
    window.keys = [curses.KEY_DOWN, "\n"]
    reader.handle_key(window, pager, "\t")
    # 跳到了第二章的起始行，提示里带着章节名
    assert pager.position == 5
    assert "第二章 台球" in pager.current_message()
    # 右侧面板确实画过（标题行里有"目录"）
    assert any("目录" in text for _, _, text, _ in window.writes)


def test_toc_overlay_can_be_cancelled(window, pager_factory) -> None:
    pager = pager_factory(toc_entries=_toc_entries())
    pager.move_to(3)
    # q 关闭浮层：位置一点都没动
    window.keys = ["q"]
    reader.handle_key(window, pager, "\t")
    assert pager.position == 3


def test_toc_overlay_filter_narrows_and_jumps(window, pager_factory) -> None:
    pager = pager_factory(toc_entries=_toc_entries())
    # / 进入过滤 -> 输入"台球" -> 回车结束输入 -> 回车确认（过滤后只剩第二章）
    window.keys = ["/", "台", "球", "\n", "\n"]
    reader.handle_key(window, pager, "\t")
    assert pager.position == 5


def test_toc_overlay_without_chapters_reports_it(window, pager_factory) -> None:
    # 没有章节表（toc_entries 默认空）：给一句提示，而不是弹一个空面板
    pager = pager_factory()
    reader.handle_key(window, pager, "\t")
    assert "没有识别出章节" in pager.current_message()


# ------------------------------------------------ mark mode (selection maths)
def test_mark_clamp_keeps_the_cursor_on_screen() -> None:
    rows = [(0, "abc"), (1, ""), (2, "中文字")]
    # 正常范围原样返回
    assert reader._mark_clamp(rows, 1, 0) == (1, 0)
    # 行越界夹回来
    assert reader._mark_clamp(rows, 99, 0) == (2, 0)
    assert reader._mark_clamp(rows, -5, 0) == (0, 0)
    # 列越界夹到该行最后一个字符（汉字也按"一个字符"算一步）
    assert reader._mark_clamp(rows, 2, 99) == (2, 2)
    # 空行只有第 0 列可选
    assert reader._mark_clamp(rows, 1, 5) == (1, 0)
    # 一屏都没有：光标钉在 (0, 0)
    assert reader._mark_clamp([], 3, 4) == (0, 0)


def test_mark_move_follows_letters_and_arrows() -> None:
    rows = [(0, "abc"), (1, "de")]
    # h / ← 往左
    assert reader._mark_move(rows, 0, 1, "h") == (0, 0)
    assert reader._mark_move(rows, 0, 1, curses.KEY_LEFT) == (0, 0)
    # l / → 往右
    assert reader._mark_move(rows, 0, 1, "l") == (0, 2)
    assert reader._mark_move(rows, 0, 1, curses.KEY_RIGHT) == (0, 2)
    # j / ↓ 往下，落到短行时列被夹住
    assert reader._mark_move(rows, 0, 2, "j") == (1, 1)
    # k / ↑ 往上
    assert reader._mark_move(rows, 1, 1, "k") == (0, 1)
    # 两端都夹住
    assert reader._mark_move(rows, 0, 0, "h") == (0, 0)
    assert reader._mark_move(rows, 1, 1, "j") == (1, 1)


def test_mark_move_ignores_paging_keys() -> None:
    rows = [(0, "abc"), (1, "def")]
    # 翻页键在标记模式里不动光标：标记模式绝不翻页
    assert reader._mark_move(rows, 0, 1, " ") == (0, 1)
    assert reader._mark_move(rows, 0, 1, curses.KEY_NPAGE) == (0, 1)


def test_mark_normalize_orders_both_directions() -> None:
    # 已经左上 -> 右下：原样
    assert reader._mark_normalize((0, 1), (2, 3)) == ((0, 1), (2, 3))
    # 反向标记：交换成同一顺序
    assert reader._mark_normalize((2, 3), (0, 1)) == ((0, 1), (2, 3))
    # 同一行：按列排
    assert reader._mark_normalize((1, 5), (1, 2)) == ((1, 2), (1, 5))


def test_mark_selection_reads_the_characters_in_the_range() -> None:
    rows = [(0, "hello world")]
    # 末列包含在内： [0, 4] 就是前五个字符
    assert reader._mark_selection(rows, (0, 0), (0, 4)) == ("hello", False)
    # 反向标记结果一样
    assert reader._mark_selection(rows, (0, 4), (0, 0)) == ("hello", False)


def test_mark_selection_glues_the_wrapped_rows_of_one_line() -> None:
    # 同一个源行被折成两条屏幕行：拼回去不该多出换行
    rows = [(0, "第一章"), (0, "正文"), (1, "第二章")]
    assert reader._mark_selection(rows, (0, 0), (2, 2)) == ("第一章正文\n第二章", False)


def test_mark_selection_truncates_at_the_limit() -> None:
    rows = [(0, "abcdef")]
    # 超限：截断并如实报告
    assert reader._mark_selection(rows, (0, 0), (0, 5), limit=3) == ("abc", True)
    # 没超限：原样
    assert reader._mark_selection(rows, (0, 0), (0, 2)) == ("abc", False)
    # limit=0 表示不限长
    assert reader._mark_selection(rows, (0, 0), (0, 5), limit=0) == ("abcdef", False)
    # 空屏：空字符串
    assert reader._mark_selection([], (0, 0), (1, 1)) == ("", False)


def test_mark_row_span_covers_only_the_selected_rows() -> None:
    # 选区之外的行没有高亮
    assert reader._mark_row_span(3, "text", (0, 0), (1, 2)) is None
    # 单行选区
    assert reader._mark_row_span(0, "abcdef", (0, 1), (0, 3)) == (1, 3)
    # 跨行：第一行反色到行尾、中间整行、最后一行从行首
    assert reader._mark_row_span(0, "abc", (0, 1), (2, 1)) == (1, 2)
    assert reader._mark_row_span(1, "def", (0, 1), (2, 1)) == (0, 2)
    assert reader._mark_row_span(2, "ghij", (0, 1), (2, 1)) == (0, 1)


# ------------------------------------------------------- mark mode (keys/UI)
def _draw_once(window, pager) -> None:
    """Paint one frame so the Pager knows which rows are on screen."""
    # 标记坐标是"屏幕行"下标，所以先得有这一帧的可见行
    reader._draw(window, pager, datetime(2026, 1, 1, 12, 0, 0))


def test_mark_key_enters_mark_mode(window, pager) -> None:
    _draw_once(window, pager)
    assert reader.handle_key(window, pager, "m") is True
    # 光标落在当前屏首行行首，起点终点重合（那个反色方块就是它）
    assert pager.mark_mode is True
    assert pager.mark_start == (0, 0)
    assert pager.mark_end == (0, 0)
    assert "标记" in pager.current_message()


def test_mark_mode_never_pages(window, pager) -> None:
    _draw_once(window, pager)
    reader.handle_key(window, pager, "m")
    start = pager.position
    # j / k 在标记模式里是移动光标，空格干脆无操作 —— 位置一动不动
    reader.handle_key(window, pager, "j")
    reader.handle_key(window, pager, "k")
    reader.handle_key(window, pager, " ")
    assert pager.position == start


def test_mark_and_copy_puts_the_text_into_the_buffer(window, pager) -> None:
    _draw_once(window, pager)
    # 进入标记后连按两下 l：向右选两个字（BOOK_LINES[0] = "第一章 科学边界"）
    reader.handle_key(window, pager, "m")
    reader.handle_key(window, pager, "l")
    reader.handle_key(window, pager, "l")
    assert pager.mark_end == (0, 2)
    # y：复制 -> 退出标记 -> 缓冲区里是选中的文字
    reader.handle_key(window, pager, "y")
    assert pager.mark_mode is False
    assert pager.note_buffer == "第一章"
    assert pager.mark_start is None and pager.mark_end is None
    assert "已复制" in pager.current_message()


def test_mark_can_be_cancelled(window, pager) -> None:
    _draw_once(window, pager)
    reader.handle_key(window, pager, "m")
    reader.handle_key(window, pager, "l")
    # Esc：清空标记状态，缓冲区不动
    reader.handle_key(window, pager, "\x1b")
    assert pager.mark_mode is False
    assert pager.mark_start is None and pager.mark_end is None
    assert pager.note_buffer == ""
    assert "已取消" in pager.current_message()


def test_mark_mode_paints_the_selection_in_reverse_video(window, pager) -> None:
    _draw_once(window, pager)
    reader.handle_key(window, pager, "m")
    reader.handle_key(window, pager, "l")
    reader.handle_key(window, pager, "l")
    # 重画一帧，看反色段画出来没有
    window.writes.clear()
    _draw_once(window, pager)
    reversed_text = [
        text for _row, _col, text, attr in window.writes if attr & curses.A_REVERSE
    ]
    assert "第一章" in reversed_text


def test_mark_without_anything_to_mark_says_so(pager) -> None:
    # 空屏（viewport 还没填）：给提示而不是进标记模式
    empty = FakeStdscr()
    reader.handle_key(empty, pager, "m")
    assert pager.mark_mode is False
    assert "没有可选中的文字" in pager.current_message()


def test_message_row_shows_the_note_status_when_folded(pager) -> None:
    # 没有临时消息也没有长时间提醒时，底部提示行带着笔记计数
    assert "0条笔记" in reader._message_row(pager, 80)
    pager.notes.append({"quote": "q", "text": "t", "created": "2026-01-01T00:00:00"})
    assert "1条笔记" in reader._message_row(pager, 80)


# ------------------------------------------------------------- note panel
def test_note_panel_layout_splits_the_bottom_quarter() -> None:
    # 40 行：面板 10 行（25%），正文 30 行，内容 9 行拆成引用 4 + 编辑 5
    assert reader._note_panel_layout(40, 80) == (30, 4, 5)
    # 屏幕太小就不弹面板
    assert reader._note_panel_layout(6, 80) is None
    assert reader._note_panel_layout(40, 5) is None
    # 矮屏也守住底线：正文至少 3 行，三块加起来正好等于"总高 - 提示行"
    layout = reader._note_panel_layout(8, 80)
    assert layout is not None
    text_rows, quote_rows, edit_rows = layout
    assert text_rows >= 3
    assert text_rows + quote_rows + edit_rows == 8 - 1


def test_note_validate_turns_enter_into_a_newline() -> None:
    # 回车（三种上报方式）都变成 NL：换行，绝不提交
    assert reader._note_validate("\n") == curses.ascii.NL
    assert reader._note_validate("\r") == curses.ascii.NL
    assert reader._note_validate(curses.KEY_ENTER) == curses.ascii.NL
    # 可打印字符换成码点
    assert reader._note_validate("a") == ord("a")
    # 方向键原样交给 Textbox
    assert reader._note_validate(curses.KEY_LEFT) == curses.KEY_LEFT
    # 多字符字符串不是单键：忽略
    assert reader._note_validate("ab") is None


def test_note_status_counts_the_saved_notes(pager) -> None:
    # 一条都没有时也显示计数与展开键
    assert "0条笔记" in reader._note_status(pager)
    assert "按o展开" in reader._note_status(pager)
    # 存一条后计数跟着涨
    pager.notes.append({"quote": "q", "text": "t", "created": "2026-01-01T00:00:00"})
    assert "1条笔记" in reader._note_status(pager)


def test_disable_flow_control_never_raises() -> None:
    # 测试环境里 stdin 不是 tty：应当静默降级，绝不抛异常
    reader._disable_flow_control()


def test_note_panel_reports_a_tiny_screen(pager_factory) -> None:
    # 6 行 40 列：装不下面板，给一句提示而不是崩
    tiny = FakeStdscr(height=6, width=40)
    pager = pager_factory()
    reader.handle_key(tiny, pager, "o")
    assert "屏幕太小" in pager.current_message()


def test_note_panel_opens_saves_and_closes(panel_window, pager) -> None:
    # 先备好一段引用（平时由 m / y 产生）
    pager.note_buffer = "第一章 科学边界"
    # 面板里：打 abc -> Tab 切到引用 -> Tab 切回编辑 -> Ctrl+S 保存 -> Esc 关闭
    panel_window.keys = ["a", "b", "c", "\t", "\t", "\x13", "\x1b"]
    reader.handle_key(panel_window, pager, "o")
    # 存下一条：引用 + 编辑区内容（形状与 notes.load_notes 一致）
    assert len(pager.notes) == 1
    assert pager.notes[0]["index"] == 1
    assert pager.notes[0]["quote"] == "第一章 科学边界"
    assert pager.notes[0]["content"] == "abc"
    assert pager.notes[0]["time"]
    # 真的落盘了：磁盘上的 markdown 与内存里那份一致
    stored = notes.load_notes(pager.book_id)
    assert stored == list(pager.notes)
    assert "第一章 科学边界" in notes.note_file(pager.book_id).read_text(encoding="utf-8")
    # 存完引用与编辑区都清空，面板已折叠
    assert pager.note_buffer == ""
    assert pager.note_panel_open is False
    # 状态栏闪现的是规格里那句话
    assert "已保存" in pager.current_message()
    # 面板确实建了两个子窗口（引用区 + 编辑区）
    assert len(panel_window.windows) == 2


def test_note_panel_paints_the_quote_in_the_first_subwindow(panel_window, pager) -> None:
    pager.note_buffer = "第一章 科学边界"
    # 只画一帧就 Esc 关掉
    panel_window.keys = ["\x1b"]
    reader.handle_key(panel_window, pager, "o")
    # 第一个子窗口就是引用区，第一行是 "> " + 选中的文字
    quote_win = panel_window.windows[0]
    quote_writes = [text for _row, _col, text, _attr in quote_win.writes]
    assert "> 第一章 科学边界" in quote_writes


def test_note_panel_quote_focus_ignores_typing(panel_window, pager) -> None:
    pager.note_buffer = "引用"
    # 默认焦点在编辑区；Tab 切到引用区后打的字不该进编辑区
    panel_window.keys = ["\t", "x", "\x13", "\x1b"]
    reader.handle_key(panel_window, pager, "o")
    assert len(pager.notes) == 1
    assert pager.notes[0]["quote"] == "引用"
    # 引用区不接受输入，所以正文是空的
    assert pager.notes[0]["content"] == ""


def test_note_panel_save_without_anything_says_so(panel_window, pager) -> None:
    # 没有引用也没写正文：Ctrl+S 只提示，不存空笔记
    panel_window.keys = ["\x13", "\x1b"]
    reader.handle_key(panel_window, pager, "o")
    assert pager.notes == []
    assert "先按 m 标记" in pager.current_message()


def test_note_panel_can_be_closed_with_ctrl_c(panel_window, pager) -> None:
    # 队列空 -> FakeStdscr.get_wch 抛 KeyboardInterrupt -> 面板当作关闭
    panel_window.keys = []
    reader.handle_key(panel_window, pager, "o")
    # 关干净了：没卡在模态循环里，也没存东西
    assert pager.note_panel_open is False
    assert pager.notes == []


# ------------------------------------------------ note panel: 落盘（Phase 3）
def test_note_panel_esc_commits_what_was_typed(panel_window, pager) -> None:
    # 没按 Ctrl+S，直接 Esc：编辑区里的内容也要变成一条笔记（失去焦点即保存）
    panel_window.keys = ["h", "i", "\x1b"]
    reader.handle_key(panel_window, pager, "o")
    stored = notes.load_notes(pager.book_id)
    assert len(stored) == 1
    assert stored[0]["content"] == "hi"


def test_note_panel_ctrl_c_keeps_the_text_as_a_draft(panel_window, pager) -> None:
    # Ctrl-C 关面板：不提交成笔记，但内容要留成草稿，下次打开还在
    panel_window.keys = ["h", "i"]
    reader.handle_key(panel_window, pager, "o")
    assert notes.load_notes(pager.book_id) == []
    assert notes.load_draft(pager.book_id)["text"] == "hi"


def test_note_panel_restores_an_ascii_draft(panel_window, pager) -> None:
    # 上次崩溃留下的草稿（纯 ASCII）：引用区与编辑区都要捞回来
    notes.save_draft(pager.book_id, "草稿里的引用", "draft body")
    panel_window.keys = ["\x1b"]
    reader.handle_key(panel_window, pager, "o")
    # 引用区（第一个子窗口）画出来的就是草稿里的引用
    quote_writes = [text for _row, _col, text, _attr in panel_window.windows[0].writes]
    assert any("草稿里的引用" in text for text in quote_writes)
    # 编辑区（第二个子窗口）里画出了草稿正文
    edit_win = panel_window.windows[1]
    written = "".join(text for _row, _col, text, _attr in edit_win.writes)
    assert "draft body" in written
    # Esc 提交后草稿消失，正式笔记里就是这份草稿（引用与正文都带过来了）
    assert notes.load_draft(pager.book_id) == {"quote": "", "text": ""}
    note = notes.load_notes(pager.book_id)[0]
    assert note["quote"] == "草稿里的引用"
    assert note["content"] == "draft body"


def test_note_panel_commits_a_chinese_draft_without_the_editor(panel_window, pager) -> None:
    """中文草稿不走编辑区，也绝不能变形。

    关键回归：``Textbox.gather()`` 用 ``curses.ascii.ascii()`` 把每个字符截成 7 位，
    所以中文一旦进过编辑区再读回来就会变成乱码（实测 ``草稿正文`` -> ``I?c\\x07``）。
    正确处理是**根本不进编辑区**：Esc 提交时直接从草稿文件原样落盘。
    """
    notes.save_draft(pager.book_id, "中文引用", "草稿正文")
    panel_window.keys = ["\x1b"]
    reader.handle_key(panel_window, pager, "o")
    # 编辑区是空的（中文没有被塞进去）
    edit_win = panel_window.windows[1]
    written = "".join(text for _row, _col, text, _attr in edit_win.writes)
    assert "草稿正文" not in written
    # 提交出来的正文一字不差，没有变成乱码
    note = notes.load_notes(pager.book_id)[0]
    assert note["quote"] == "中文引用"
    assert note["content"] == "草稿正文"
    # 草稿已经被消费掉
    assert notes.load_draft(pager.book_id) == {"quote": "", "text": ""}


def test_autosave_draft_waits_for_the_interval(pager) -> None:
    # 直接测那 30 秒的判断：没到点不写，到点才写
    editor = None  # _autosave_draft 只在到点后才读编辑区，这里用假对象
    class _Editor:
        def gather(self) -> str:
            return "写到一半"

    editor = _Editor()
    # 刚存过：时间差为 0，不该写草稿
    now = reader.time.monotonic()
    assert reader._autosave_draft(pager, editor, now) == now
    assert notes.draft_file(pager.book_id).is_file() is False
    # 时间差超过阈值：写一份草稿，并把时刻推到现在
    stale = now - reader.NOTE_AUTOSAVE_SECONDS - 1
    assert reader._autosave_draft(pager, editor, stale) > stale
    assert notes.load_draft(pager.book_id)["text"] == "写到一半"


def test_note_panel_reports_a_save_failure(panel_window, pager, monkeypatch) -> None:
    # 磁盘写不进去（目录只读等）：提示一句，而且**绝不**清空用户写的内容
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise notes.NotesError("disk is full")

    monkeypatch.setattr(reader.notes, "save_note", boom)
    pager.note_buffer = "重要引用"
    panel_window.keys = ["x", "\x13", "\x1b"]
    reader.handle_key(panel_window, pager, "o")
    assert pager.notes == []
    # 引用还在（没被清掉），用户不会白写
    assert pager.note_buffer == "重要引用"
    assert "失败" in pager.current_message()

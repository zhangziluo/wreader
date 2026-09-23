"""Event driven achievements: the state store, the events and the unlock check.

:mod:`wreader.stats` owns the *numbers* (metrics, streak, heatmap) and the
achievement **definitions**; this module owns the **unlocks**: which achievement
has fired, when, and how far the counter driven ones have got.

Why a separate file: an unlock is earned by an *event* ("I opened werd today",
"I finished a book"), not by re-deriving everything from the library document.
Some conditions cannot be expressed as a metric of the index at all (a day
counter, seconds read on weekends, words read from line ranges), so they are
recorded here as they happen.

* the definitions stay in ``wreader/data/achievements.json`` (user editable,
  conditions are plain ``metric OP number`` expressions),
* the state lives in ``<data dir>/achievements.json`` -- plain JSON, written
  under a file lock so two terminals cannot lose each other's unlocks,
* every call site only has to call :func:`check_achievements` with an event name.

Pure functions over plain data wherever possible; the only I/O is the state file
and the one time legacy import from ``library.json``.
"""

# 延迟求值类型注解，避免运行时解析
from __future__ import annotations

# 读写状态文件
import json
# os.replace 做原子替换
import os
# 读正则：数拉丁单词
import re
# 写临时文件再替换，避免写一半被读到
import tempfile
# 数汉字要判断东亚宽度
import unicodedata
# datetime：daily_open 要判断几点、是不是周末；date：节日判定
from datetime import date, datetime
# 状态文件路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

# 同包引用：数据目录、环境探测（前缀信号名）、地理（世仇组合）、书库索引（迁移用）、
# 笔记（数笔记总数）、指标与成就定义
from . import config, env, geo, library, notes, stats
# 跨进程文件锁：与 notes.py 共用同一份实现
from .lock import file_lock

# 模块对外暴露的名字
__all__ = [
    "COUNTER_METRICS",
    "EARLY_END_HOUR",
    "EARLY_START_HOUR",
    "EGG_NAMES",
    "EVENTS",
    "HOLIDAYS",
    "LUNAR_HOLIDAYS",
    "MAX_METRICS",
    "NARROW_CHAPTER_COLUMNS",
    "NARROW_COLUMNS",
    "STATE_FILENAME",
    "AchievementsError",
    "check_achievements",
    "compute_metrics",
    "count_words",
    "crossed_thresholds",
    "empty_state",
    "empty_metrics",
    "holiday_of",
    "list_achievements",
    "load_definitions",
    "load_state",
    "merge_ranges",
    "metric_thresholds",
    "save_state",
    "session_metrics",
    "state_path",
    "uncovered_words",
    "unlocked_ids",
    "weekend_seconds",
]

# 运行时状态文件名（成就定义是另一个文件，见 stats.ACHIEVEMENTS_FILE）
STATE_FILENAME = "achievements.json"

# 状态文件的版本号，将来结构变化时用来迁移
STATE_VERSION = 1

# "清晨第一眼"的时间窗口：05:00 - 07:00
EARLY_START_HOUR = 5
EARLY_END_HOUR = 7

# 事件名清单：调用方只允许用这几个名字，写错不会被静默吞掉
#: The events every call site is allowed to report, in rough lifecycle order.
EVENTS: Tuple[str, ...] = (
    "daily_open",
    "session_end",
    "progress_update",
    "geo_change",
    "book_add",
    "book_finish",
    "word_add",
    "note_add",
    # Phase 2（阅读器里的实时事件）：按键计数、终端尺寸变化、帮助页、意外中断恢复
    "key",
    "resize",
    "help",
    "recover",
    # Phase 3：环境探测、名字彩蛋、翻开成就页
    "env",
    "name_egg",
    "achievements_view",
    # check = 只做一次判定（`werd achievements` 以前用它，现在改用更具体的
    # achievements_view；这个名字保留着，因为它是公开白名单，删掉会打断老脚本）
    "check",
)

# 阅读器可以在 "key" / "resize" / "session_end" 载荷里累加的指标（增量语义）
#: Metrics the reader reports as *deltas* (they only ever grow).
COUNTER_METRICS: Tuple[str, ...] = (
    # 全程只用方向键读完的章节数（方向键怀旧）
    "arrow_chapters",
    # 按过多少次翻译键（翻译狂魔）
    "translate_hits",
    # 窄窗口（≤ NARROW_COLUMNS 列）里累计读了多少秒（极限尺寸）
    "narrow_seconds",
    # 窄窗口（≤ NARROW_CHAPTER_COLUMNS 列）里读完了几章（窄屏挑战）
    "narrow_chapters",
    # 打开过几次阅读器帮助页（帮助迷）
    "help_opens",
)

# 阅读器上报的是**峰值**的指标（取 max，不累加）
#: Metrics the reader reports as *maxima* (the longest run wins).
MAX_METRICS: Tuple[str, ...] = (
    # 最长的空格连击（手速达人）
    "space_combo",
    # 最长的一次连续翻页（翻页永动机）
    "page_streak",
)

# 「极限尺寸」判定的列数上限：终端窄到这么多列才算"极限"
#: The terminal width (columns) below which a reading session is "cramped".
NARROW_COLUMNS = 40
# 「窄屏挑战」判定的列数上限：比 NARROW_COLUMNS 宽松一档
#: The terminal width (columns) below which a chapter counts as read "narrow".
NARROW_CHAPTER_COLUMNS = 60

# 状态文件 metrics 段里按**非负整数**存的指标（手改坏的值一律夹回 0）
#: Metrics stored as non-negative ints in the state file.
_INT_METRICS: Tuple[str, ...] = (
    "early_open",
    "words_read",
    "space_combo",
    "page_streak",
    "arrow_chapters",
    "translate_hits",
    "narrow_seconds",
    "narrow_chapters",
    "help_opens",
    "crash_recovers",
    "recover_declined",
    "achievement_views",
)

# 布尔型的指标：只关心"有没有发生过"，读回来一律夹成 0/1
#: Metrics that are flags rather than counters.
_FLAG_METRICS: Tuple[str, ...] = ("early_open",)

# 状态文件 metrics 段里按**字符串列表**存的指标（读回来去重排序，坏项丢掉）
#: Metrics stored as lists of strings in the state file.
_LIST_METRICS: Tuple[str, ...] = (
    # 打开过 werd 的日期
    "days_opened",
    # 在节日里打开过的日期
    "holidays",
    # 去过的国家代码 / 大洲名 / 命中的世仇组合
    "countries",
    "continents",
    "feuds",
    # 命中过的环境信号（cloud / wsl / tmux / editable）
    "envs",
    # 触发过的彩蛋名
    "eggs",
)

# 固定日期的节日（公历 MM-DD -> 名字）：只要在这一天打开过 werd 就算"节日读者"
#: Fixed-date holidays (Gregorian ``MM-DD``) that unlock 节日读者.
HOLIDAYS: Dict[str, str] = {
    "01-01": "元旦",
    "02-14": "情人节",
    "03-08": "妇女节",
    "04-01": "愚人节",
    "05-01": "劳动节",
    "06-01": "儿童节",
    "07-01": "建党节",
    "08-01": "建军节",
    "09-10": "教师节",
    "10-01": "国庆节",
    "12-24": "平安夜",
    "12-25": "圣诞节",
    "12-31": "跨年夜",
}

# 农历节日：公历日期每年不同，所以直接列官方公布的日期（2024-2030）。
# ⚠️ 这张表刻意只到 2030：再往后得查天文台公布的历书，宁可让 2031 年之后
# 退回 HOLIDAYS 里的公历节日，也不在这里编日期。
#: Lunar festivals, whose Gregorian dates are listed explicitly for 2024-2030.
LUNAR_HOLIDAYS: Dict[str, str] = {
    "2024-02-10": "春节",
    "2025-01-29": "春节",
    "2026-02-17": "春节",
    "2027-02-06": "春节",
    "2028-01-26": "春节",
    "2029-02-13": "春节",
    "2030-02-03": "春节",
    "2024-09-17": "中秋节",
    "2025-10-06": "中秋节",
    "2026-09-25": "中秋节",
    "2027-09-15": "中秋节",
    "2028-10-03": "中秋节",
    "2029-09-22": "中秋节",
    "2030-09-12": "中秋节",
}

# 彩蛋名字清单：`werd werd` / `werd word` / `werd --werd` 都算同一个成就
#: Easter egg names the CLI may report (see ``werd werd`` / ``werd word``).
EGG_NAMES: Tuple[str, ...] = ("werd", "word")

# 周末的 weekday() 编号：周六 = 5、周日 = 6（周一为 0）
_WEEKEND_DAYS = (5, 6)

# 拉丁单词：字母开头，允许撇号与连字符（I'm / well-known 都算一个词）
_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*")


# 状态文件坏到无法使用时抛这个异常（调用方通常选择忽略）
class AchievementsError(Exception):
    """Raised when the achievements state file cannot be used."""


def state_path(path: Optional[Path] = None) -> Path:
    """Return the achievements state file, ``<data dir>/achievements.json``."""
    # 显式给路径就用它（测试用），否则跟随数据目录
    return Path(path) if path is not None else config.data_dir() / STATE_FILENAME


def empty_metrics() -> Dict[str, Any]:
    """Return a fresh ``metrics`` block with every key present and empty."""
    # 计数类指标全 0
    metrics: Dict[str, Any] = {name: 0 for name in _INT_METRICS}
    # 列表类指标全空
    for name in _LIST_METRICS:
        metrics[name] = []
    # 周末时长是按天的桶，单独一个形状
    metrics["weekend_seconds"] = {}
    return metrics


def empty_state() -> Dict[str, Any]:
    """Return a fresh state document with every section present."""
    # 结构固定，免得调用方到处写 setdefault
    return {
        "version": STATE_VERSION,
        # 已解锁记录：[{"id": ..., "name": ..., "unlocked_at": ...}, ...]
        "unlocked": [],
        # 事件计数：{"daily_open": 12, "book_add": 3}
        "counters": {},
        # 状态派生的指标：打开过的日期、清晨是否打开过、周末时长、读了多少字、
        # 以及在阅读器里实时攒下的那些（连击、翻页、窄屏、地理、环境……）
        "metrics": empty_metrics(),
        # 每本书读过的行区间与已统计字数：用来给字数统计去重
        "books": {},
        # 每条成就的进度快照（`werd achievements` 直接读它）
        "progress": {},
    }


def _as_int(value: Any, default: int = 0) -> int:
    """Coerce *value* to an int, falling back to *default*."""
    # bool 是 int 的子类，但这里不区分
    try:
        return int(value)
    except (TypeError, ValueError):
        # 手改坏的数值：按默认值处理，不让整个状态文件失效
        return default


def _string_list(value: Any) -> List[str]:
    """Return *value* as a list of strings, dropping anything odd."""
    # 不是列表（文件被改坏）就当空
    if not isinstance(value, list):
        return []
    # 只保留能安全转成字符串的项
    return [str(item) for item in value if isinstance(item, (str, int))]


def _int_map(value: Any) -> Dict[str, int]:
    """Return a ``{str: int}`` copy of *value*, tolerant of junk."""
    # 不是字典就当空
    if not isinstance(value, dict):
        return {}
    # 逐项转 int，坏值退成 0
    return {str(key): _as_int(item) for key, item in value.items()}


def _ranges(value: Any) -> List[Tuple[int, int]]:
    """Return *value* as a list of ``(start, end)`` half open line ranges."""
    # 不是列表就当没有读过
    if not isinstance(value, list):
        return []
    # 每个区间都必须是长度为 2 的数字对
    ranges: List[Tuple[int, int]] = []
    for item in value:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            start, end = _as_int(item[0]), _as_int(item[1])
            # 空区间（end <= start）没有意义，丢掉
            if end > start:
                ranges.append((start, end))
    return ranges


def _normalise_state(raw: Any) -> Dict[str, Any]:
    """Return a well formed state document built from whatever *raw* holds."""
    # 以空状态为模板，逐段吸收文件里认识的部分
    state = empty_state()
    # 顶层不是字典：完全重建（宁可丢状态也不要崩）
    if not isinstance(raw, dict):
        return state
    # 版本号
    state["version"] = _as_int(raw.get("version"), STATE_VERSION)
    # 已解锁记录：兼容字典、纯字符串、以及手写的 {"id": true} 三种写法
    entries = raw.get("unlocked")
    unlocked: List[Dict[str, Any]] = []
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and item.get("id"):
                unlocked.append(
                    {
                        "id": str(item["id"]),
                        "name": str(item.get("name") or item["id"]),
                        "unlocked_at": str(item.get("unlocked_at") or ""),
                    }
                )
            elif isinstance(item, str):
                unlocked.append({"id": item, "name": item, "unlocked_at": ""})
    elif isinstance(entries, dict):
        for key in entries:
            unlocked.append({"id": str(key), "name": str(key), "unlocked_at": ""})
    state["unlocked"] = unlocked
    # 事件计数
    state["counters"] = _int_map(raw.get("counters"))
    # 状态派生的指标：逐项按类型吸收，认不出的键直接丢掉（保持文件形状可控）
    metrics = raw.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    normalised_metrics: Dict[str, Any] = {}
    for name in _INT_METRICS:
        # 计数类：负数夹回 0（手改出 -5 时不该让进度倒退成负）
        value = max(0, _as_int(metrics.get(name)))
        # 布尔型的指标（置位就不再撤销）统一夹成 0/1
        normalised_metrics[name] = 1 if (name in _FLAG_METRICS and value) else value
    for name in _LIST_METRICS:
        # 列表类：去重并排序，方便断言与调试（日期/国家代码都是定长字符串）
        normalised_metrics[name] = sorted(set(_string_list(metrics.get(name))))
    # 周末时长的桶
    normalised_metrics["weekend_seconds"] = _int_map(metrics.get("weekend_seconds"))
    state["metrics"] = normalised_metrics
    # 每本书的已统计字数与已计入的行区间
    books = raw.get("books")
    normalised: Dict[str, Dict[str, Any]] = {}
    if isinstance(books, dict):
        for book_id, record in books.items():
            record = record if isinstance(record, dict) else {}
            normalised[str(book_id)] = {
                "words": max(0, _as_int(record.get("words"))),
                # 区间统一成 list[list[int]]：内存里的形状与写盘后的 JSON 完全一致
                "counted": [[start, end] for start, end in merge_ranges(_ranges(record.get("counted")))],
            }
    state["books"] = normalised
    # 进度快照：{"id": {"current": n, "required": m}}
    progress = raw.get("progress")
    snapshots: Dict[str, Dict[str, int]] = {}
    if isinstance(progress, dict):
        for key, value in progress.items():
            value = value if isinstance(value, dict) else {}
            snapshots[str(key)] = {
                "current": _as_int(value.get("current")),
                "required": _as_int(value.get("required")),
            }
    state["progress"] = snapshots
    return state


def unlocked_ids(state: Mapping[str, Any]) -> List[str]:
    """Return the achievement ids already unlocked in *state*."""
    # 只要 id，形状与旧 API 保持一致（调用方拿去判重）
    return [
        str(entry.get("id")) for entry in state.get("unlocked") or [] if entry.get("id")
    ]


def merge_ranges(
    ranges: Iterable[Sequence[int]],
) -> List[Tuple[int, int]]:
    """Merge overlapping or touching ``(start, end)`` line ranges.

    Ranges are half open (``start`` inclusive, ``end`` exclusive) and come back
    sorted, which is what the word counter needs to answer "have I already
    counted this line?" without holding a set of every line number.
    """
    # 先按起点排序，再线性合并
    merged: List[Tuple[int, int]] = []
    for item in sorted(
        (int(item[0]), int(item[1])) for item in ranges if len(tuple(item)) >= 2
    ):
        start, end = item
        # 空区间直接跳过
        if end <= start:
            continue
        # 与前一段重叠或相接（start <= 上一段的 end）就并成一段
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            continue
        # 否则新起一段
        merged.append((start, end))
    return merged


def _cjk_count(text: str) -> int:
    """Count the CJK characters in *text* (one character counts as one word).

    Only letters and other non-punctuation wide characters count: counting
    ``，`` or ``。`` as a word would inflate every total by the punctuation of
    the book.
    """
    # 逐个字符判断：空白与标点不算，其余东亚宽字符（汉字、假名、全角字母）都算
    return sum(
        1
        for char in text
        if unicodedata.east_asian_width(char) in ("W", "F")
        and not char.isspace()
        and unicodedata.category(char)[0] != "P"
    )


def count_words(text: str) -> int:
    """Count *text* the way the achievements count it.

    The rule from the specification is "Chinese: one character is one word,
    English: one token is one word", so punctuation, digits and whitespace do
    not contribute at all.
    """
    # 非字符串（None、数字）一律算 0
    raw = text if isinstance(text, str) else ""
    # 汉字/全角字符逐字算，拉丁单词逐个 token 算
    return _cjk_count(raw) + len(_LATIN_WORD_RE.findall(raw))


def uncovered_words(
    lines: Sequence[str],
    counted: Iterable[Sequence[int]],
    start: int,
    end: int,
) -> Tuple[int, List[Tuple[int, int]]]:
    """Words in ``lines[start:end]`` that were never counted before.

    Returns ``(words, merged_ranges)`` where *merged_ranges* is *counted* with
    ``[start, end)`` folded in.  Reading the same page twice therefore adds
    nothing the second time: that is the whole point of tracking line ranges
    instead of a running total.
    """
    # 已经统计过的区间（规整过）
    known = merge_ranges(counted)
    # 本次区间的合法化：负数夹到 0，右端不越过正文
    first = max(0, int(start))
    last = min(int(end), len(lines))
    # 空区间：没有新字
    if last <= first:
        return 0, known
    # 找出 [first, last) 里没被统计过的那些小段
    gaps: List[Tuple[int, int]] = []
    cursor = first
    for known_start, known_end in known:
        # 这一段完全在游标左边：跳过
        if known_end <= cursor:
            continue
        # 这一段完全在区间右边：后面的也不用看了
        if known_start >= last:
            break
        # 中间露出一段没统计过的
        if known_start > cursor:
            gaps.append((cursor, min(known_start, last)))
        # 游标推到这一段末尾
        cursor = max(cursor, known_end)
    # 最后还可能剩一段尾巴
    if cursor < last:
        gaps.append((cursor, last))
    # 逐段累计汉字与单词
    words = sum(count_words(line) for gap in gaps for line in lines[gap[0] : gap[1]])
    # 把本次区间并进已统计区间
    return words, merge_ranges(list(known) + [(first, last)])


def weekend_seconds(start: Any, end: Any, seconds: int) -> Tuple[str, int]:
    """Attribute a session's *seconds* to a weekend day, or to nothing.

    A session that touches Saturday or Sunday counts as weekend reading; the end
    day wins when both touch a weekend so a session spanning Saturday midnight
    is not counted twice.  Returns ``("", 0)`` for a weekday-only session.
    """
    # 秒数没有意义就不记
    total = max(0, int(seconds))
    if not total:
        return "", 0
    # 解析会话日期（坏格式就当作没有）
    first = stats.parse_timestamp(start)
    last = stats.parse_timestamp(end)
    # 优先记到结束那天（跨午夜时更符合"读到了周末"的直觉）
    if last is not None and last.weekday() in _WEEKEND_DAYS:
        return last.date().isoformat(), total
    # 再退到开始那天
    if first is not None and first.weekday() in _WEEKEND_DAYS:
        return first.date().isoformat(), total
    # 整个会话都在工作日：不算周末阅读
    return "", 0


def load_state(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read the achievements state, seeding it from ``library.json`` once.

    A missing file is normal (first run) and yields an empty state.  Broken JSON
    raises :class:`AchievementsError` so the caller can decide what to do; the
    file itself is left untouched until the next write.
    """
    target = state_path(path)
    # 文件不存在：第一次使用，看看旧版本有没有把解锁记录写在索引里
    if not target.is_file():
        return _seeded_state(target)
    try:
        # 读文件并解析
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AchievementsError(
            "{} is not usable: {}".format(STATE_FILENAME, exc)
        ) from exc
    # 结构规整（历史写法与手改坏值都在这里吸收掉）
    return _normalise_state(raw)


def _seeded_state(target: Path) -> Dict[str, Any]:
    """Return the state for a first run, adopting the pre-0.2 unlocks."""
    # 老版本的解锁记录住在 library.json 里，迁移一次就不会再读它
    try:
        document = library.load_library()
    except (library.LibraryError, OSError):
        # 索引读不到（或本来就没有）：就是干净的开始
        return empty_state()
    # 一个都没有就不用建文件
    legacy = _legacy_unlocked(document)
    state = empty_state()
    state["unlocked"] = legacy
    return state


def _legacy_unlocked(document: Any) -> List[Dict[str, Any]]:
    """Read unlocks stored the old way, inside ``library.json``."""
    # 老位置：document["achievements"]["unlocked"]，解析交给 stats（三种历史写法）
    ids = stats.unlocked_ids(document if isinstance(document, dict) else {})
    # 顺便把老记录里的名字与时间戳带过来
    state = document.get("achievements") if isinstance(document, dict) else None
    entries = state.get("unlocked") if isinstance(state, dict) else None
    stamps: Dict[str, str] = {}
    names: Dict[str, str] = {}
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and item.get("id"):
                key = str(item["id"])
                stamps[key] = str(item.get("unlocked_at") or "")
                names[key] = str(item.get("name") or key)
    return [
        {"id": key, "name": names.get(key, key), "unlocked_at": stamps.get(key, "")}
        for key in ids
    ]


def save_state(state: Dict[str, Any], path: Optional[Path] = None) -> Path:
    """Write *state* atomically and return the path it was written to."""
    target = state_path(path)
    # 目录可能还不存在（全新安装）
    target.parent.mkdir(parents=True, exist_ok=True)
    # 先写同目录的临时文件，再 os.replace：中途被读到也只会是完整的旧文件
    handle, temp_name = tempfile.mkstemp(
        prefix=STATE_FILENAME + ".", dir=str(target.parent)
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            # ensure_ascii=False 让中文成就名在文件里可读
            json.dump(state, stream, ensure_ascii=False, indent=2, sort_keys=False)
            stream.write("\n")
        # 原子替换
        os.replace(temp_name, target)
    except OSError:
        # 写失败：清掉临时文件，别在数据目录里留垃圾
        try:
            os.unlink(temp_name)
        except OSError:  # pragma: no cover - 临时文件已经不在了
            pass
        raise
    return target


# 分类的展示顺序：与 specification 里的四组 + 隐藏类一致
CATEGORY_ORDER: Tuple[str, ...] = (
    "阅读习惯",
    "操作彩蛋",
    "数据积累",
    "难度挑战",
    "隐藏",
)


def load_definitions() -> List[Dict[str, Any]]:
    """Return the achievement definitions (thin alias of :func:`stats.load_achievements`)."""
    # 定义的唯一来源是打包的 achievements.json，这里只是给调用方一个顺手的入口
    return stats.load_achievements()


def _record_daily_open(state: Dict[str, Any], moment: datetime) -> None:
    """Remember that werd was opened today, and at what hour."""
    metrics = _metrics(state)
    # 打开过的日期去重后排序（百日筑基要的是"天数"而不是"次数"）
    days = _string_list(metrics.get("days_opened"))
    day = moment.date().isoformat()
    if day not in days:
        days.append(day)
    metrics["days_opened"] = sorted(set(days))
    # 05:00-07:00 之间打开过就置位（一旦置位就不再撤销）
    if EARLY_START_HOUR <= moment.hour < EARLY_END_HOUR:
        metrics["early_open"] = 1
    # 正好撞上节日（公历或表里的农历节日）：记下这一天，"节日读者"靠它
    if holiday_of(moment):
        _add_unique(state, "holidays", [day])


def _record_session_end(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Fold one reading session's duration and words into the state."""
    # 本次会话时长（秒）
    seconds = max(0, _as_int(payload.get("seconds")))
    # 落在周六/周日的会话才计入"周末战士"
    day, weekend = weekend_seconds(payload.get("started"), payload.get("ended"), seconds)
    if day:
        buckets = _metrics(state).setdefault("weekend_seconds", {})
        buckets[day] = _as_int(buckets.get(day)) + weekend
    # 阅读器退出时也会把本次攒下的按键/尺寸计数一起送来（免得没撞到门槛就丢了）
    _record_counters(state, payload)
    # 会话里带了正文与读过的行区间：顺便结算本次的字数
    _record_progress(state, payload)


def _record_progress(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Add the words of the newly read line ranges to the totals.

    The caller hands over the whole book text plus the ranges it walked through
    this session, so the "already counted" bookkeeping stays here and re-reading
    a page never inflates the word count.
    """
    # 没有书 id 或没有区间：没什么可结算的
    book_id = str(payload.get("book_id") or "")
    lines = payload.get("lines")
    ranges = _ranges(payload.get("ranges"))
    if not book_id or not isinstance(lines, (list, tuple)) or not ranges:
        return
    # 这本书的累计记录
    books = state.setdefault("books", {})
    record = books.get(book_id)
    if not isinstance(record, dict):
        record = {"words": 0, "counted": []}
    books[book_id] = record
    # 逐段结算：只有没统计过的行才算数
    counted = _ranges(record.get("counted"))
    gained = 0
    for start, end in ranges:
        step, counted = uncovered_words(lines, counted, start, end)
        gained += step
    # 写回（用 list 存区间，保证状态文件是纯 JSON 可读的）
    record["counted"] = [[start, end] for start, end in counted]
    record["words"] = max(0, _as_int(record.get("words"))) + gained
    # 全局字数指标同步累加
    metrics = state.setdefault("metrics", empty_state()["metrics"])
    metrics["words_read"] = max(0, _as_int(metrics.get("words_read"))) + gained


def holiday_of(moment: Any) -> str:
    """Return the name of the holiday on *moment*, or ``""`` for an ordinary day.

    Accepts a :class:`datetime.date`, a :class:`datetime.datetime` or an ISO string.
    Lunar festivals (春节 / 中秋节) come from the explicit table in
    :data:`LUNAR_HOLIDAYS`; everything else is matched on the month and day, so the
    answer does not depend on which year the table was written.
    """
    # 先把输入收成一个 date（datetime 是 date 的子类，但要多一步取出日期部分）
    if isinstance(moment, datetime):
        day = moment.date()
    elif isinstance(moment, date):
        day = moment
    else:
        # 字符串：容忍 "2026-02-17" 与 "2026-02-17T10:00:00" 两种写法
        try:
            day = date.fromisoformat(str(moment or "")[:10])
        except ValueError:
            # 格式不对：当作不是节日
            return ""
    stamp = day.isoformat()
    # 农历节日查完整日期
    if stamp in LUNAR_HOLIDAYS:
        return LUNAR_HOLIDAYS[stamp]
    # 公历节日只看"月-日"
    return HOLIDAYS.get(stamp[5:], "")


def _metrics(state: Dict[str, Any]) -> Dict[str, Any]:
    """Return the metrics block of *state*, creating it if it is missing."""
    # 老状态文件（Phase 1 写的）缺新键：这里补一份完整的空块再往上写
    block = state.setdefault("metrics", empty_metrics())
    return block


def _bump(state: Dict[str, Any], name: str, step: int = 1) -> None:
    """Add *step* to one integer metric (never below zero)."""
    # 负数没意义（回退不该让成就进度倒退）
    metrics = _metrics(state)
    metrics[name] = max(0, _as_int(metrics.get(name)) + int(step))


def _record_counters(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Fold the reader's real time report into the metrics block.

    The payload carries two shapes, because the two kinds of metric behave
    differently: ``deltas`` are *added* (a counter can only grow: chapters read with
    arrow keys, ``t`` presses, seconds read in a cramped window) and ``maxima`` are
    *compared* (the longest space combo, the longest run of page turns -- reading
    another book must not reset yesterday's record).
    """
    # 增量：只认白名单里的名字，别让手写的载荷往状态文件里塞新键
    deltas = payload.get("deltas")
    if isinstance(deltas, Mapping):
        for name in COUNTER_METRICS:
            step = _as_int(deltas.get(name))
            # 0 与负数都跳过（增量语义里它们没有意义）
            if step > 0:
                _bump(state, name, step)
    # 峰值：只保留更大的那个
    peaks = payload.get("maxima")
    if isinstance(peaks, Mapping):
        metrics = _metrics(state)
        for name in MAX_METRICS:
            peak = _as_int(peaks.get(name))
            if peak > _as_int(metrics.get(name)):
                metrics[name] = peak


def _add_unique(state: Dict[str, Any], name: str, values: Iterable[Any]) -> None:
    """Merge *values* into the list metric *name*, ignoring blanks and repeats."""
    metrics = _metrics(state)
    current = _string_list(metrics.get(name))
    for value in values:
        # 空值（没有国家代码、没有名字）不算一条记录
        text = str(value or "").strip()
        if text and text not in current:
            current.append(text)
    metrics[name] = sorted(set(current))


def _record_recover(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Count one run-in with the crash recovery prompt.

    ``{"recovered": true}`` means the reader was interrupted last time **and** this
    time the position was picked up again (恢复大师); ``False`` is the reader saying
    "算了，从头读" (我反悔).
    """
    # 恢复成功与主动放弃各记一个指标，成就分别挂在两个指标上
    if bool(payload.get("recovered")):
        _bump(state, "crash_recovers")
        return
    _bump(state, "recover_declined")


def _record_geo(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Remember where this machine was seen, for the geography achievements.

    The payload is the mapping :func:`wreader.geo.load_location` returns
    (``country_code`` / ``continent`` / ``country``); an empty one is silently
    ignored, which is what "offline" looks like from here.
    """
    code = str(payload.get("country_code") or "").strip().upper()
    # 没有国家代码：可能只是接口挂了，什么都别记
    if not code:
        return
    # 国家与大洲各自去重
    _add_unique(state, "countries", [code])
    _add_unique(state, "continents", [payload.get("continent") or geo.continent_of(code)])
    # 世仇组合要两边都去过：每次新增国家时重新算一遍（命中就记下来）
    hit = geo.feud_hit(_string_list(_metrics(state).get("countries")))
    if hit:
        _add_unique(state, "feuds", [hit])


def _record_env(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Remember which environment signals were ever true (cloud / wsl / tmux / editable)."""
    # 载荷是一个名字列表（wreader.env.flags 的返回值）；只认白名单里的名字，
    # 免得别处传进来的字符串把 env_flags 这个计数撑大
    given = payload.get("flags")
    if isinstance(given, (list, tuple)):
        _add_unique(
            state, "envs", [name for name in given if name in env.SIGNAL_NAMES]
        )


def _record_egg(state: Dict[str, Any], payload: Mapping[str, Any]) -> None:
    """Remember one easter egg hit (``werd werd`` / ``werd word``)."""
    # 只认白名单里的彩蛋名，防止随便什么字符串都算一条
    name = str(payload.get("egg") or "").strip().lower()
    if name in EGG_NAMES:
        _add_unique(state, "eggs", [name])


def record_event(
    state: Dict[str, Any],
    event_type: str,
    data: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Fold one event into *state* and return it (the same dict, mutated)."""
    # 事件名必须是我们认识的那几个，写错就报出来（不要静默丢事件）
    if event_type not in EVENTS:
        raise AchievementsError("unknown event {!r}".format(event_type))
    payload: Mapping[str, Any] = data or {}
    # 触发时刻：测试可以注入固定时间
    moment = now or datetime.now()
    counters = state.setdefault("counters", {})
    # 多数事件一次算 1；book_add 按本次导入的本数算
    step = max(1, _as_int(payload.get("count"), 1)) if event_type == "book_add" else 1
    counters[event_type] = _as_int(counters.get(event_type)) + step
    # 分派到各自的累加逻辑
    if event_type == "daily_open":
        _record_daily_open(state, moment)
    elif event_type == "session_end":
        _record_session_end(state, payload)
    elif event_type == "progress_update":
        _record_progress(state, payload)
    elif event_type in ("key", "resize"):
        # 阅读器里的实时上报：增量 + 峰值两种形状
        _record_counters(state, payload)
    elif event_type == "help":
        _bump(state, "help_opens")
    elif event_type == "recover":
        _record_recover(state, payload)
    elif event_type == "geo_change":
        _record_geo(state, payload)
    elif event_type == "env":
        _record_env(state, payload)
    elif event_type == "name_egg":
        _record_egg(state, payload)
    elif event_type == "achievements_view":
        _bump(state, "achievement_views")
    # book_add / book_finish / word_add / note_add / check 只需要计数
    return state


def compute_metrics(
    document: Mapping[str, Any],
    state: Optional[Mapping[str, Any]] = None,
    vocab_size: Optional[int] = None,
) -> Dict[str, int]:
    """Return every metric the conditions may reference.

    The index derived numbers come from :func:`stats.compute_metrics`; the ones
    that only the event log knows about (days opened, words read, weekend time)
    are added on top, and the note total is counted from the notes directory, so a
    condition stays a plain expression either way.
    """
    # 书库侧指标：复用 stats 的实现，避免两套口径
    metrics = stats.compute_metrics(dict(document), vocab_size=vocab_size)
    # 状态侧指标：拿不到状态（首次运行）就按 0 算
    state = state if isinstance(state, Mapping) else {}
    log = state.get("metrics")
    log = log if isinstance(log, Mapping) else {}
    # 书库里一共有几本（藏书家 / 移动图书馆）
    metrics["library_books"] = len((document or {}).get("books") or {})
    # 累计读了多少字（万字户 … 十亿富豪）
    metrics["words_read"] = max(0, _as_int(log.get("words_read")))
    # 打开过 werd 的天数（百日筑基）
    metrics["days_opened"] = len(_string_list(log.get("days_opened")))
    # 清晨 5-7 点打开过（清晨第一眼）
    metrics["early_open"] = 1 if _as_int(log.get("early_open")) else 0
    # 周末累计阅读秒数（周末战士）
    metrics["weekend_time"] = sum(_int_map(log.get("weekend_seconds")).values())
    # 累计写了多少条笔记（笔记达人）：现数 markdown，手写在编辑器里的也算
    metrics["notes_count"] = _note_total()
    # -- Phase 2：阅读器实时攒下的那些 --------------------------------------
    # 最长的空格连击 / 最长的一次连续翻页
    metrics["space_combo"] = _as_int(log.get("space_combo"))
    metrics["page_streak"] = _as_int(log.get("page_streak"))
    # 全程只用方向键读完的章节数
    metrics["arrow_chapters"] = _as_int(log.get("arrow_chapters"))
    # 按过多少次翻译键（t / T）
    metrics["translate_hits"] = _as_int(log.get("translate_hits"))
    # 窄窗口里累计读的秒数、读完的章节数
    metrics["narrow_seconds"] = _as_int(log.get("narrow_seconds"))
    metrics["narrow_chapters"] = _as_int(log.get("narrow_chapters"))
    # 帮助页打开次数
    metrics["help_opens"] = _as_int(log.get("help_opens"))
    # 意外中断：接着读了几次、放弃恢复几次
    metrics["crash_recovers"] = _as_int(log.get("crash_recovers"))
    metrics["recover_declined"] = _as_int(log.get("recover_declined"))
    # 翻开成就页的次数（成就猎人）
    metrics["achievement_views"] = _as_int(log.get("achievement_views"))
    # -- Phase 3：地理 / 环境 / 节日 / 彩蛋 ---------------------------------
    # 节日读书的天数（节日读者）
    metrics["holiday_opens"] = len(_string_list(log.get("holidays")))
    # 去过的国家数、大洲数、世仇组合是否凑齐
    metrics["geo_countries"] = len(_string_list(log.get("countries")))
    metrics["geo_continents"] = len(_string_list(log.get("continents")))
    metrics["geo_feud"] = 1 if _string_list(log.get("feuds")) else 0
    # 触发过的彩蛋个数
    metrics["easter_eggs"] = len(_string_list(log.get("eggs")))
    # 环境信号：每个名字一个 0/1 指标（云端书虫/穿越子系统/套娃终端/开发者模式）
    flags = set(_string_list(log.get("envs")))
    for name in env.SIGNAL_NAMES:
        metrics["env_{}".format(name)] = 1 if name in flags else 0
    metrics["env_flags"] = len(flags)
    return metrics


def crossed_thresholds(
    values: Mapping[str, int],
    thresholds: Mapping[str, Sequence[int]],
    fired: Iterable[Sequence[Any]] = (),
) -> List[Tuple[str, int]]:
    """Return the ``(metric, threshold)`` pairs *values* has just reached.

    This is the arithmetic behind the reader's "should I bother the engine now?"
    question.  *values* is what the reader currently believes each metric to be
    (baseline at open + whatever happened since), *thresholds* comes from
    :func:`metric_thresholds`, and *fired* lists what this session has already
    triggered so the same line is not crossed twice.  Pure, so it is testable
    without a terminal.
    """
    # 已经报过的（指标, 门槛）不再重复触发
    seen = {(str(item[0]), int(item[1])) for item in fired}
    hits: List[Tuple[str, int]] = []
    # 排序让结果稳定（测试断言好写，消息行也稳定）
    for metric in sorted(thresholds):
        value = _as_int(values.get(metric))
        for number in thresholds[metric]:
            key = (str(metric), int(number))
            # 到达或越过门槛，且本次会话还没报过：命中
            if value >= int(number) and key not in seen:
                hits.append(key)
    return hits


def session_metrics(
    path: Optional[Path] = None,
    document: Optional[Mapping[str, Any]] = None,
) -> Dict[str, int]:
    """Return the metrics as they stand right now (the reader's baseline).

    The reader needs to know where every counter already is when it opens a book, so
    that "this key press just crossed the line" can be answered without asking the
    engine on every keystroke -- a check costs a file lock and a full state rewrite.
    Failures degrade to ``{}``: the reader then fires no mid-session checks and the
    achievements are still settled when the session ends.
    """
    try:
        # 状态 + 书库文档（调用方可以不传，那就现读索引）
        log = load_state(path)
        library_document = (
            dict(document) if document is not None else library.load_library()
        )
        return compute_metrics(library_document, log)
    except (AchievementsError, library.LibraryError, stats.StatsError):
        # 成就系统读不出来：当作"没有任何基线"，只是这一个会话没有实时通知
        return {}


def metric_thresholds(
    definitions: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Tuple[int, ...]]:
    """Return ``{metric: (required, ...)}`` for every condition in the definitions.

    Conditions that do not parse are skipped, exactly like everywhere else in the
    engine, and the numbers come back sorted and deduplicated so a user who adds two
    achievements on the same metric does not make the reader check twice.
    """
    # 定义来源：调用方可以注入（测试），默认用打包的那份
    entries = list(definitions) if definitions is not None else load_definitions()
    thresholds: Dict[str, List[int]] = {}
    for achievement in entries:
        try:
            metric, _operator, required = stats.parse_condition(
                str(achievement.get("condition") or "")
            )
        except (KeyError, TypeError, stats.StatsError):
            # 条件写坏的那一条跳过（`werd achievements` 会另外给出提示）
            continue
        thresholds.setdefault(metric, []).append(int(required))
    return {
        metric: tuple(sorted(set(numbers))) for metric, numbers in thresholds.items()
    }


def _note_total() -> int:
    """Return the total number of notes on disk, or 0 when they cannot be read.

    The count is *derived* from the notes directory every time rather than kept as
    a counter in the state file: a note deleted (or written) by hand must move the
    笔记达人 progress in the same direction, exactly like every other metric here.
    """
    try:
        return notes.total_note_count()
    except Exception:  # pragma: no cover - notes 自己已经兜过底
        # 笔记目录整个读不了：按 0 算，别让统计页与成就页一起炸掉
        return 0


def check_achievements(
    event_type: str,
    data: Optional[Mapping[str, Any]] = None,
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
    document: Optional[Mapping[str, Any]] = None,
    definitions: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Record *event_type*, unlock whatever it earned, and return the new ones.

    This is the single entry point every module calls (``daily_open`` from the
    CLI, ``session_end`` from the reader, ``book_add`` from ``werd import``, …).
    Unlocking is idempotent: an achievement that is already in the state is never
    returned twice.  The whole read-record-check-write runs under a file lock so
    two terminals cannot overwrite each other's unlocks.
    """
    # 目标状态文件
    target = state_path(path)
    with file_lock(target):
        state = _load_state_or_reset(target)
        # 先把事件本身累加进去（计数、日期、字数）
        record_event(state, event_type, data, now)
        # 书库文档：调用方可以不传（那就现读索引）
        library_document = dict(document) if document is not None else library.load_library()
        metrics = compute_metrics(library_document, state)
        # 定义：调用方可以注入（测试），默认用打包的那份
        entries = list(definitions) if definitions is not None else load_definitions()
        # 解锁时间戳
        stamp = (now or datetime.now()).isoformat(timespec="seconds")
        known = set(unlocked_ids(state))
        newly: List[Dict[str, Any]] = []
        # 顺带刷新每条成就的进度快照，给 `werd achievements` 用
        progress: Dict[str, Dict[str, int]] = {}
        for achievement in entries:
            info = stats.achievement_state(achievement, metrics)
            progress[str(achievement["id"])] = {
                "current": int(info["current"]),
                "required": int(info["required"]),
            }
            # 没达标，或者早就解锁过：跳过
            if not info["unlocked"] or str(achievement["id"]) in known:
                continue
            record = {
                "id": str(achievement["id"]),
                "name": str(achievement.get("name") or achievement["id"]),
                "unlocked_at": stamp,
            }
            state["unlocked"].append(record)
            known.add(record["id"])
            newly.append(record)
        state["progress"] = progress
        # 落盘：写不了（磁盘满 / 目录只读）也不能影响阅读
        try:
            save_state(state, target)
        except OSError:  # pragma: no cover - 磁盘异常
            pass
    return newly


def _load_state_or_reset(target: Path) -> Dict[str, Any]:
    """Read the state, quarantining an unreadable file instead of crashing."""
    try:
        return load_state(target)
    except AchievementsError:
        # 坏文件挪到 .broken：既不静默丢数据，也让下次写入有干净的目标
        try:
            os.replace(target, target.with_name(STATE_FILENAME + ".broken"))
        except OSError:  # pragma: no cover - 挪不动就原地覆盖
            pass
        return empty_state()


def list_achievements(
    document: Optional[Mapping[str, Any]] = None,
    state: Optional[Mapping[str, Any]] = None,
    path: Optional[Path] = None,
    definitions: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Return every achievement with its progress, for ``werd achievements``.

    Unlocked ones come first (the order they fired in), then the rest grouped by
    category, so the output reads as "what I got" followed by "what is next".
    """
    # 状态与书库文档：不传就现读
    log = state if state is not None else load_state(path)
    library_document = dict(document) if document is not None else library.load_library()
    metrics = compute_metrics(library_document, log)
    entries = list(definitions) if definitions is not None else load_definitions()
    # 解锁时间戳查表
    stamps: Dict[str, str] = {}
    for record in log.get("unlocked") or []:
        if record.get("id"):
            stamps[str(record["id"])] = str(record.get("unlocked_at") or "")
    rows: List[Dict[str, Any]] = []
    for achievement in entries:
        info = stats.achievement_state(achievement, metrics)
        rows.append(
            {
                "id": info["id"],
                "name": info["name"],
                "desc": info["desc"],
                "category": str(achievement.get("category") or "其他"),
                "secret": bool(achievement.get("secret")),
                "metric": info["metric"],
                "current": int(info["current"]),
                "required": int(info["required"]),
                "unlocked": bool(info["unlocked"]) or info["id"] in stamps,
                "unlocked_at": stamps.get(info["id"], ""),
            }
        )
    # 分类排序：先按 CATEGORY_ORDER，未列出的分类排在最后（保持定义顺序）
    def sort_key(row: Dict[str, Any]) -> int:
        # 认识的分类取它在常量里的下标，不认识的排到末尾
        return CATEGORY_ORDER.index(str(row["category"])) if row["category"] in CATEGORY_ORDER else len(CATEGORY_ORDER)

    rows.sort(key=sort_key)
    return rows



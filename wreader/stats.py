"""Reading statistics and the achievement system.

Two things live here:

* the **numbers** behind ``wreader stats`` -- the total, the per book totals, the daily
  buckets that today/week/month are summed from, and the week-grid heatmap; the
  same data is available as JSON through :func:`build_report`,
* the **achievements**: the definitions in ``wreader/data/achievements.json``, the
  metrics their conditions are written against, and the unlock check that runs
  when the reader closes a book.

The recording side already lives in :mod:`wreader.reader` (session start/end,
``progress.total_time_seconds``, ``stats.daily_read_time``, ``stats.translations``);
this module reads that data back and turns it into metrics.  Everything except
:func:`check_achievements` and :func:`celebrate` is a pure function over plain
data, so the metrics, the streak and the heatmap are testable without a
terminal.
"""

# 延迟求值类型注解
from __future__ import annotations

# 解析 achievements.json
import json
# 解析成就条件字符串（如 "total_time >= 3600"）
import re
# sys.stdout 和 isatty 判断是否终端
import sys
# 庆祝动画每帧之间 sleep
import time
# date 做日期运算；datetime 解析时间戳；timedelta 做天数偏移
from datetime import date, datetime, timedelta
# 允许测试传入自定义的成就文件路径
from pathlib import Path
# 类型注解：TextIO 表示"可写文本流"
from typing import Any, Dict, List, Optional, Sequence, TextIO, Tuple

# 同包引用：配置（读每日目标）、书库（读写索引）、生词本（统计生词数）
from . import config, library, vocab

# 模块公开的名字：常量 + 各项统计/成就函数
__all__ = [
    "CELEBRATION_FRAMES",
    "HEATMAP_CHARS",
    "HEATMAP_DAYS",
    "STREAK_SECONDS",
    "StatsError",
    "achievement_state",
    "book_totals",
    "build_report",
    "bump_translations",
    "celebrate",
    "check_achievements",
    "compute_metrics",
    "evaluate_condition",
    "format_hours",
    "heat_char",
    "heatmap",
    "heatmap_weeks",
    "load_achievements",
    "month_total",
    "night_overlap",
    "parse_condition",
    "progress_bar",
    "session_seconds",
    "streak_days",
    "today_total",
    "unlocked_ids",
    "week_total",
]

# 成就定义文件名，放在包的 data/ 目录里
ACHIEVEMENTS_FILE = "achievements.json"

# 一天读满 30 分钟才算"有效阅读日"，用于连续天数统计
#: A day only counts towards an achievement streak once it reaches this.
STREAK_SECONDS = 30 * 60

# "夜间阅读"统计的时间窗口：00:00 - 04:00
#: Reading between these hours feeds the ``night_time`` metric.
NIGHT_START_HOUR = 0
NIGHT_END_HOUR = 4

# 热力图默认展示最近多少天
HEATMAP_DAYS = 30

# 热力图用到的 5 个等级字符，从"没读"到"读得最多"
#: Index 0 means "nothing read"; the rest are increasing intensity.
HEATMAP_CHARS: Tuple[str, ...] = ("·", "░", "▒", "▓", "█")

# 成就条件字符串的格式：指标名 + 比较符 + 整数
_CONDITION_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*(>=|<=|==|>|<)\s*(-?\d+)\s*$"
)

# 比较符 -> 对应的比较函数，避免写一长串 if/elif
_COMPARISONS = {
    ">=": lambda value, required: value >= required,
    ">": lambda value, required: value > required,
    "<=": lambda value, required: value <= required,
    "<": lambda value, required: value < required,
    "==": lambda value, required: value == required,
}


# 成就定义文件损坏或条件写错时抛这个异常
class StatsError(Exception):
    """Raised when the achievement definitions cannot be used."""


def load_achievements(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Load the achievement definitions from ``wreader/data/achievements.json``.

    The packaged resource is preferred so an installed wheel works; *path* exists
    for the tests.  Entries without an id or a condition are skipped rather than
    breaking the whole list.
    """
    # 测试传入自定义路径时直接读那个文件
    if path is not None:
        raw = Path(path).read_text(encoding="utf-8")
    else:
        # 否则读包内资源：用 importlib.resources 保证装成 wheel 后也能找到
        from importlib import resources

        raw = (resources.files("wreader") / "data" / ACHIEVEMENTS_FILE).read_text(
            encoding="utf-8"
        )
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        # 文件格式坏了：包成 StatsError
        raise StatsError(
            "{} is not valid JSON: {}".format(ACHIEVEMENTS_FILE, exc)
        ) from exc
    # 兼容老版本 {"achievements": [...]} 的包装写法
    if isinstance(data, dict):  # tolerate the older {"achievements": [...]} wrapper
        data = data.get("achievements") or []
    if not isinstance(data, list):
        raise StatsError("{} must contain a list".format(ACHIEVEMENTS_FILE))

    # 清洗后的成就定义
    achievements: List[Dict[str, Any]] = []
    for item in data:
        # 非字典项直接跳过
        if not isinstance(item, dict):
            continue
        # 没有 id 或没有条件判断的项无法使用，跳过（不让整个列表失败）
        if not item.get("id") or not item.get("condition"):
            continue
        # 统一成四个字段，并把值都转成字符串
        achievements.append(
            {
                "id": str(item["id"]),
                "name": str(item.get("name") or item["id"]),
                "desc": str(item.get("desc") or ""),
                "condition": str(item["condition"]),
            }
        )
    return achievements


def parse_condition(condition: str) -> Tuple[str, str, int]:
    """Split ``"total_time >= 3600"`` into ``("total_time", ">=", 3600)``."""
    # 用正则把条件拆成三段
    match = _CONDITION_RE.match(str(condition or ""))
    if not match:
        # 格式不对：明确报错，方便定位是哪个成就写错了
        raise StatsError("cannot understand the condition {!r}".format(condition))
    # 指标名、比较符、目标值（转成 int）
    return match.group(1), match.group(2), int(match.group(3))


def _holds(operator: str, value: int, required: int) -> bool:
    """Apply one comparison operator."""
    # 从映射表里取对应的比较函数
    compare = _COMPARISONS.get(operator)
    if compare is None:
        raise StatsError("unknown comparison {!r}".format(operator))
    # 统一转成 bool 返回
    return bool(compare(value, required))


def evaluate_condition(condition: str, metrics: Dict[str, int]) -> bool:
    """Return whether *condition* currently holds for *metrics*."""
    # 先拆条件，再从当前指标里取值
    metric, operator, required = parse_condition(condition)
    # 指标不存在时按 0 处理
    return _holds(operator, int(metrics.get(metric, 0)), required)


def achievement_state(
    # 一条成就定义
    achievement: Dict[str, Any],
    # 当前所有指标的数值
    metrics: Dict[str, int],
) -> Dict[str, Any]:
    """Return the display state of one achievement: unlocked plus progress."""
    # 拆出它依赖哪个指标、要求多少
    metric, operator, required = parse_condition(achievement["condition"])
    # 该指标当前值
    current = int(metrics.get(metric, 0))
    # 返回给界面用的状态：进度 + 是否已达标
    return {
        "id": achievement["id"],
        "name": achievement.get("name") or achievement["id"],
        "desc": achievement.get("desc") or "",
        "metric": metric,
        "current": current,
        "required": required,
        "unlocked": _holds(operator, current, required),
    }


def parse_timestamp(text: Any) -> Optional[datetime]:
    """Parse one of wreader's ISO timestamps, or ``None`` when it is unusable."""
    try:
        # 阅读会话里存的是 ISO 字符串
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        # 空值或格式不对：返回 None，由调用方当作"无效时间"
        return None


def night_overlap(start: Any, end: Any) -> int:
    """Seconds of the session ``[start, end)`` that fall inside 00:00-04:00.

    A session spanning midnight is walked window by window, so reading from 22:00
    to 02:00 counts only the two hours after midnight that belong to the night
    window.
    """
    # 解析会话起止时间
    first = parse_timestamp(start)
    last = parse_timestamp(end)
    # 时间无效或结束不晚于开始：没有有效时长
    if first is None or last is None or last <= first:
        return 0
    # 用浮点累加，最后再取整
    total = 0.0
    # 游标从会话开始走
    cursor = first
    while cursor < last:
        # 游标当天 00:00 和 04:00 组成的"夜间窗口"
        window_start = cursor.replace(
            hour=NIGHT_START_HOUR, minute=0, second=0, microsecond=0
        )
        window_end = cursor.replace(
            hour=NIGHT_END_HOUR, minute=0, second=0, microsecond=0
        )
        # 游标已经过了 04:00（比如是前一天 22:00 开始的会话），窗口顺延到第二天
        if window_end <= cursor:
            window_start += timedelta(days=1)
            window_end += timedelta(days=1)
        # 取 [会话, 夜间窗口] 的交集
        overlap_start = max(cursor, window_start)
        overlap_end = min(last, window_end)
        # 有交集就累加这段时长
        if overlap_end > overlap_start:
            total += (overlap_end - overlap_start).total_seconds()
        # 游标跳到窗口末尾，继续看下一段（防止死循环，兜底 +1 天）
        cursor = window_end if window_end > cursor else cursor + timedelta(days=1)
    # 秒数取整返回
    return int(total)


def session_seconds(session: Dict[str, Any]) -> int:
    """Return how long one recorded session lasted."""
    # 会话记录里的 start/end
    first = parse_timestamp((session or {}).get("start"))
    last = parse_timestamp((session or {}).get("end"))
    # 时间无效或倒挂：算 0 秒
    if first is None or last is None or last <= first:
        return 0
    # 时长取整（秒）
    return int((last - first).total_seconds())


def daily_totals(daily: Any) -> Dict[str, int]:
    """Return the daily buckets with their values coerced to ints."""
    # 每天 -> 秒数
    totals: Dict[str, int] = {}
    # 不是字典（文件被改坏）就当没有数据
    if isinstance(daily, dict):
        for day, value in daily.items():
            try:
                # 日期统一转字符串，值统一转 int；空值按 0
                totals[str(day)] = int(value or 0)
            except (TypeError, ValueError):
                # 值不是数字：跳过这一天，不要让统计整体报错
                continue
    return totals


def streak_days(
    # 每日时长桶（{"2026-09-21": 1800}）
    daily: Any,
    # 一天至少读多少秒才算"达标"
    min_seconds: int = STREAK_SECONDS,
    # 以哪天为"今天"（测试可注入固定日期）
    today: Optional[date] = None,
) -> int:
    """Count consecutive qualifying days ending today or yesterday.

    Today only counts once it has reached *min_seconds*; if it has not, a run
    still alive from yesterday keeps its length instead of dropping to zero,
    which is what "7 days in a row" means to somebody who has not read *yet*
    today.
    """
    # 默认用真实今天
    today = today or date.today()
    # 把每日桶规整成 {"YYYY-MM-DD": int}
    totals = daily_totals(daily)
    # 阈值至少为 1 秒，避免传 0 导致"每天都算达标"
    threshold = max(1, int(min_seconds))

    def qualifies(day: date) -> bool:
        # 这一天是否达标
        return totals.get(day.isoformat(), 0) >= threshold

    # 从今天往前数
    cursor = today
    # 今天还没读够：从昨天起数，这样"连续 7 天"不会因为今天还没读而归零
    if not qualifies(cursor):
        cursor -= timedelta(days=1)
    # 连续天数
    streak = 0
    # 只要达标就继续往前一天
    while qualifies(cursor):
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def format_hours(seconds: float) -> str:
    """Render a duration as ``X小时Y分钟``, dropping a trailing zero.

    ``0分钟`` under a minute, ``45分钟`` under an hour, ``1小时`` on the hour and
    ``6小时35分钟`` otherwise, so a one hour target reads ``1小时``.
    """
    # 负数兜成 0，并取整
    total = max(0, int(seconds))
    # divmod 一次算出小时和余下的秒
    hours, remainder = divmod(total, 3600)
    # 余下的秒换成分钟
    minutes = remainder // 60
    # 小时和分钟都有：两个都显示
    if hours and minutes:
        return "{}小时{}分钟".format(hours, minutes)
    # 只有小时：省略 0 分钟
    if hours:
        return "{}小时".format(hours)
    # 不足一小时：只显示分钟（含 0分钟）
    return "{}分钟".format(minutes)


def period_total(daily: Any, start: date, end: date) -> int:
    """Sum the buckets between *start* and *end* inclusive."""
    # 日期是 ISO 字符串，字典序就等于时间序，所以可以直接比字符串
    return sum(
        value
        for day, value in daily_totals(daily).items()
        if start.isoformat() <= day <= end.isoformat()
    )


def today_total(daily: Any, today: Optional[date] = None) -> int:
    """Seconds read today."""
    # 默认取真实今天
    today = today or date.today()
    # 起止同一天
    return period_total(daily, today, today)


def week_total(daily: Any, today: Optional[date] = None) -> int:
    """Seconds read so far this ISO week (Monday through today)."""
    today = today or date.today()
    # weekday() 周一为 0，减掉它就回到本周一
    return period_total(daily, today - timedelta(days=today.weekday()), today)


def month_total(daily: Any, today: Optional[date] = None) -> int:
    """Seconds read so far this month."""
    today = today or date.today()
    # 把日换成 1 就是本月 1 号
    return period_total(daily, today.replace(day=1), today)


def heat_char(seconds: float) -> str:
    """Return the heatmap character for one day's *seconds*.

    The buckets are pegged to a full hour so the picture stays comparable between
    days: nothing is ``·``, then ``░`` under 20 minutes, ``▒`` under 40, ``▓``
    under an hour and ``█`` from an hour up.
    """
    # 负数兜成 0 并取整
    value = max(0, int(seconds))
    # 没读：最浅的字符
    if value <= 0:
        return HEATMAP_CHARS[0]
    # 不到 20 分钟
    if value < 20 * 60:
        return HEATMAP_CHARS[1]
    # 20-40 分钟
    if value < 40 * 60:
        return HEATMAP_CHARS[2]
    # 40-60 分钟
    if value < 60 * 60:
        return HEATMAP_CHARS[3]
    # 满一小时以上：最亮
    return HEATMAP_CHARS[4]


def heatmap(
    # 每日时长桶
    daily: Any,
    # 显示最近多少天
    days: int = HEATMAP_DAYS,
    # 以哪天为基准
    today: Optional[date] = None,
) -> List[Tuple[str, str, int]]:
    """Return ``(date, char, seconds)`` for the last *days* days, oldest first."""
    today = today or date.today()
    totals = daily_totals(daily)
    # 每格是 (日期, 等级字符, 秒数)
    cells: List[Tuple[str, str, int]] = []
    # 从最旧的一天走到今天（offset 递减）
    for offset in range(max(1, int(days)) - 1, -1, -1):
        day = today - timedelta(days=offset)
        # 这一天读了多久，没记录就是 0
        seconds = totals.get(day.isoformat(), 0)
        cells.append((day.isoformat(), heat_char(seconds), seconds))
    return cells


def heatmap_weeks(
    daily: Any,
    days: int = HEATMAP_DAYS,
    today: Optional[date] = None,
) -> List[List[Optional[Tuple[str, str, int]]]]:
    """Return the heatmap as a two dimensional grid, one row per weekday.

    Columns are whole weeks (Monday through Sunday) so a day is always in the
    same column as its weekday neighbours, the way a paper calendar reads.  Days
    outside the *days* window -- the padding at the head of the first week and
    the tail of the last one -- come back as ``None`` so the caller can leave
    them blank.
    """
    today = today or date.today()
    # 先拿到一维的每日数据
    cells = heatmap(daily, days=days, today=today)
    # 建索引：日期 -> 那一格
    by_day = {cell[0]: cell for cell in cells}
    span = max(1, int(days))
    # 窗口的第一天
    first = today - timedelta(days=span - 1)
    # Pad backwards to the Monday that opens the first week.
    # 往前对齐到第一周的那个周一，这样每列都是完整的"周"
    cursor = first - timedelta(days=first.weekday())

    # 一周一个星期地收集
    weeks: List[List[Optional[Tuple[str, str, int]]]] = []
    while cursor <= today:
        week: List[Optional[Tuple[str, str, int]]] = []
        # 这一周的 7 天（周一到周日）
        for offset in range(7):
            day = (cursor + timedelta(days=offset)).isoformat()
            # 窗口外的日期取不到，就是 None（画的时候留白）
            week.append(by_day.get(day))
        weeks.append(week)
        cursor += timedelta(days=7)

    # 转置：从"按周分行"变成"按星期几分行"（每行是星期一到星期日）
    return [[week[weekday] for week in weeks] for weekday in range(7)]


def book_totals(document: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    """Return ``(book_id, title, seconds)`` for every book that has been read."""
    # 结果行
    rows: List[Tuple[str, str, int]] = []
    # 遍历书库里的每一本
    for book_id, book in (document.get("books") or {}).items():
        if not isinstance(book, dict):
            continue
        progress = book.get("progress")
        # 进度块不是字典就当作空
        progress = progress if isinstance(progress, dict) else {}
        # 这本书累计阅读秒数
        seconds = int(progress.get("total_time_seconds") or 0)
        # 读过（>0 秒）才列出来
        if seconds:
            rows.append((str(book_id), str(book.get("title") or "untitled"), seconds))
    # 按时长从多到少排
    rows.sort(key=lambda row: row[2], reverse=True)
    return rows


def compute_metrics(
    # 书库文档（含 books 与 stats）
    document: Dict[str, Any],
    # 生词总数；不传就自己去读生词本
    vocab_size: Optional[int] = None,
) -> Dict[str, int]:
    """Return every metric the achievement conditions are written against.

    ``books_read`` counts books with at least one recorded session, ``finished``
    counts books left at the last line, ``night_time`` and ``single_session`` are
    derived from the session timestamps, and the rest come straight out of
    ``stats``.
    """
    # 防御性取值：文档结构不对也不炸
    books = document.get("books") if isinstance(document, dict) else None
    stats = document.get("stats") if isinstance(document, dict) else None
    stats = stats if isinstance(stats, dict) else {}
    # 每日时长桶（给 streak_days 用）
    daily = stats.get("daily_read_time")

    # 下面四个指标需要遍历每本书的会话记录才能算出来
    books_read = 0
    finished = 0
    night_time = 0
    longest_session = 0
    for book in (books or {}).values():
        if not isinstance(book, dict):
            continue
        progress = book.get("progress")
        progress = progress if isinstance(progress, dict) else {}
        sessions = progress.get("sessions")
        sessions = sessions if isinstance(sessions, list) else []
        # 有过阅读会话就算"读过这本书"
        if sessions:
            books_read += 1
        # 标记为读完的
        if progress.get("finished"):
            finished += 1
        # 逐条会话：累计夜间时长、记录最长一次会话
        for session in sessions:
            if not isinstance(session, dict):
                continue
            night_time += night_overlap(session.get("start"), session.get("end"))
            longest_session = max(longest_session, session_seconds(session))

    # 没传生词数就现去数（生词本坏了按 0 处理，不影响其它统计）
    if vocab_size is None:
        try:
            vocab_size = len(vocab.load_vocab())
        except vocab.VocabError:
            vocab_size = 0

    # 这就是成就条件里可以引用的全部变量
    return {
        "books_read": books_read,
        "total_time": int(stats.get("total_read_time") or 0),
        "night_time": int(night_time),
        "streak": streak_days(daily),
        "finished": finished,
        "vocab_count": int(vocab_size),
        "translations": int(stats.get("translations") or 0),
        "single_session": int(longest_session),
    }


def unlocked_ids(document: Dict[str, Any]) -> List[str]:
    """Return the achievement ids already recorded as unlocked.

    The list is normally ``[{"id": ..., "name": ..., "unlocked_at": ...}]``, but a
    bare list of ids or a hand written ``{"first_book": true}`` mapping also work.
    """
    # 取 achievements 段落
    state = document.get("achievements") if isinstance(document, dict) else None
    # 里面的 unlocked 字段
    entries = state.get("unlocked") if isinstance(state, dict) else None
    ids: List[str] = []
    # 正常格式：一个列表，元素可能是字典或纯字符串
    if isinstance(entries, list):
        for item in entries:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
            elif isinstance(item, str):
                ids.append(item)
    # 手写格式：{"first_book": true} 这种映射，键就是 id
    elif isinstance(entries, dict):
        ids.extend(str(key) for key in entries)
    return ids


def bump_translations(document: Dict[str, Any], count: int = 1) -> int:
    """Add *count* translation uses to the statistics; returns the new total."""
    # 确保 stats 段落存在
    stats = document.setdefault("stats", {})
    # 累加翻译次数
    total = int(stats.get("translations") or 0) + int(count)
    stats["translations"] = total
    return total


def check_achievements(
    # 书库文档；不传就自己读索引（并在最后写回）
    document: Optional[Dict[str, Any]] = None,
    # 成就定义；不传就读打包的 achievements.json
    achievements: Optional[Sequence[Dict[str, Any]]] = None,
    # 解锁时间戳来源（测试可注入固定时间）
    now: Optional[datetime] = None,
    # 是否把结果写回磁盘
    save: bool = True,
) -> List[Dict[str, Any]]:
    """Unlock every achievement whose condition now holds.

    Returns the newly unlocked ones in definition order so the caller can
    celebrate them, and refreshes ``achievements.progress`` on the way through.
    When *document* is omitted the index is loaded and written back; a caller
    that passes its own document can pass ``save=False`` to keep control.
    """
    # 没传文档就从磁盘读
    if document is None:
        document = library.load_library()
    # 没传定义就用打包的那份（拷贝成列表，下面只读）
    definitions = (
        list(achievements) if achievements is not None else load_achievements()
    )
    # 先算出所有指标的当前值
    metrics = compute_metrics(document)

    # 确保 achievements 段落存在且是字典
    state = document.get("achievements")
    if not isinstance(state, dict):
        state = {}
        document["achievements"] = state
    # 已解锁列表（格式不对就重建为空列表）
    entries = state.get("unlocked")
    if not isinstance(entries, list):
        entries = []
    # 已解锁 id 的集合，用来判重
    known = set(unlocked_ids(document))
    # 本次记录使用的时间戳
    stamp = (now or datetime.now()).isoformat(timespec="seconds")

    # 本次新解锁的成就，按定义顺序返回给调用方做庆祝
    newly: List[Dict[str, Any]] = []
    # 每个成就的进度快照，写回文件供 `wreader achievements` 展示
    progress: Dict[str, Dict[str, int]] = {}
    for achievement in definitions:
        # 算出这条成就的当前进度与是否达标
        info = achievement_state(achievement, metrics)
        progress[achievement["id"]] = {
            "current": info["current"],
            "required": info["required"],
        }
        # 没达标，或者之前已经解锁过：跳过
        if not info["unlocked"] or achievement["id"] in known:
            continue
        # 新解锁：记一条带时间戳的记录
        record = {
            "id": achievement["id"],
            "name": achievement["name"],
            "unlocked_at": stamp,
        }
        entries.append(record)
        known.add(achievement["id"])
        newly.append(record)

    # 把解锁列表和进度写回文档
    state["unlocked"] = entries
    state["progress"] = progress
    # 需要的话落盘
    if save:
        library.save_library(document)
    return newly


def build_report(
    # 书库文档
    document: Dict[str, Any],
    # 以哪天为"今天"
    today: Optional[date] = None,
    # 已加载的配置（读每日目标用）
    settings: Optional[config.Config] = None,
) -> Dict[str, Any]:
    """Return everything ``wreader stats`` shows as plain, JSON serialisable data.

    The rendered view is built from this very dict, so ``wreader stats --json`` and
    the pretty table can never drift apart.  Durations stay in seconds; the
    human readable strings are added alongside them as well.  *settings* is the
    loaded settings file, read for the daily goal (``stats.daily_goal_minutes``).
    """
    today = today or date.today()
    # 没传配置就现加载
    settings = settings or config.load_config()
    stats = document.get("stats") if isinstance(document, dict) else None
    stats = stats if isinstance(stats, dict) else {}
    # 每日时长桶
    daily = stats.get("daily_read_time")
    # 一次性算出所有指标
    metrics = compute_metrics(document)
    # 今天读了多久
    today_seconds = today_total(daily, today)
    # 每日目标（分钟 -> 秒），0 表示没设目标
    goal_minutes = max(0, int(settings.get("stats.daily_goal_minutes") or 0))
    goal_seconds = goal_minutes * 60
    try:
        # 成就总数用于显示 x/y
        total_achievements = len(load_achievements())
    except StatsError:
        # 定义文件坏了也不该让 stats 命令失败
        total_achievements = 0
    # 已解锁的 id 列表
    unlocked = unlocked_ids(document)

    # 这份字典既用于渲染表格，也直接作为 --json 的输出
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "total_seconds": metrics["total_time"],
        "total": format_hours(metrics["total_time"]),
        "today_seconds": today_seconds,
        "week_seconds": week_total(daily, today),
        "month_seconds": month_total(daily, today),
        "daily_goal_seconds": goal_seconds,
        # 设了目标且今天已达标
        "goal_met": bool(goal_seconds) and today_seconds >= goal_seconds,
        "streak_days": metrics["streak"],
        "streak_min_seconds": STREAK_SECONDS,
        "books_read": metrics["books_read"],
        "finished_books": metrics["finished"],
        "vocab_count": metrics["vocab_count"],
        "translations": metrics["translations"],
        "night_seconds": metrics["night_time"],
        "longest_session_seconds": metrics["single_session"],
        "achievements": {
            "unlocked": unlocked,
            "unlocked_count": len(unlocked),
            "total": total_achievements,
        },
        # 每本书的累计时长
        "books": [
            {"id": book_id, "title": title, "seconds": seconds}
            for book_id, title, seconds in book_totals(document)
        ],
        # 每日桶按日期排序后输出
        "daily": dict(sorted(daily_totals(daily).items())),
        # 一维热力图数据
        "heatmap": [
            {"date": day, "seconds": seconds, "level": char}
            for day, char, seconds in heatmap(daily, today=today)
        ],
        # 二维热力图（按星期几分行，空位是 None）
        "heatmap_grid": [
            [
                None
                if cell is None
                else {"date": cell[0], "seconds": cell[2], "level": cell[1]}
                for cell in row
            ]
            for row in heatmap_weeks(daily, today=today)
        ],
    }


def progress_bar(
    # 当前进度值
    current: int,
    # 达成需要的值
    required: int,
    # 进度条总宽度（字符数）
    width: int = 14,
) -> str:
    """Render a compact progress bar such as ``████░░░░░░░░░░``.

    The caller prints the numbers, so a time based achievement can show them as
    hours instead of raw seconds.
    """
    # 分母至少为 1，避免除以 0
    target = max(1, int(required))
    # 当前值至少为 0
    done = max(0, int(current))
    # 宽度至少为 1
    size = max(1, int(width))
    # 完成比例，最多 100%
    ratio = min(done, target) / float(target)
    # 实心方块个数（四舍五入后夹在 [0, size] 内）
    filled = max(0, min(size, int(round(size * ratio))))
    # 实心 + 空心拼成整条
    return "█" * filled + "░" * (size - filled)


# 解锁成就时播放的小烟花，从空到满共 5 帧
#: Frames of the little ASCII burst shown when an achievement unlocks.
CELEBRATION_FRAMES: Tuple[str, ...] = (
    "        ·        ",
    "      · ★ ·      ",
    "   ·  ★ ★ ★  ·   ",
    " ★  ★ ★ ★ ★  ★  ",
    "★ ★ ★ ★ ★ ★ ★ ★ ★",
)


def celebrate(
    # 刚解锁的成就（取 name/desc/id）
    achievement: Dict[str, Any],
    # 输出流；默认 sys.stdout
    stream: Optional[TextIO] = None,
    # 是否播放动画；None 表示自动判断（看是不是终端）
    animate: Optional[bool] = None,
    # 是否响铃
    ring: bool = True,
    # 每帧之间的间隔秒数
    delay: float = 0.12,
) -> str:
    """Print the unlock animation, ring the bell and return the banner line.

    This runs after curses has handed the terminal back, so plain writes are
    enough.  The animation is skipped for a non-tty (or when *animate* is False)
    so redirecting the output never fills a file with animation frames, and the
    bell can be turned off with *ring* for terminals that beep loudly.
    """
    # Bind the resolved stream to a fresh, non-optional local: reassigning a
    # variable whose declared type is ``Optional[TextIO]`` (the parameter, here)
    # does not clear the optionality for pyright, which would keep reporting the
    # writes below as optional member access.
    # 用一个明确非 None 的局部变量，避免类型检查器一直报"可能为 None"
    out: TextIO = stream if stream is not None else sys.stdout
    # 没指定就自动判断：不是终端就不放动画（避免把帧写进重定向的文件）
    if animate is None:
        animate = bool(getattr(out, "isatty", lambda: False)())
    # 成就名（都取不到就兜个默认值）
    name = str(achievement.get("name") or achievement.get("id") or "achievement")
    # 成就描述
    desc = str(achievement.get("desc") or "")
    # 横幅文字
    banner = "🏆 Achievement Unlocked: {}".format(name)
    # 有描述就接在后面
    if desc:
        banner += "  —  {}".format(desc)
    # 响铃字符（关掉就是空串）
    bell = "\a" if ring else ""
    try:
        if animate:
            # 逐帧覆盖同一行：\r 回到行首
            for frame in CELEBRATION_FRAMES:
                out.write("\r" + frame)
                out.flush()
                time.sleep(delay)
            # 用空格把最后一帧擦掉
            out.write("\r" + " " * len(CELEBRATION_FRAMES[-1]) + "\r")
        # 打印持久的那行横幅
        out.write(bell + banner + "\n")
        out.flush()
    except OSError:
        # 终端已经关掉之类的写失败：静默忽略
        pass
    return banner

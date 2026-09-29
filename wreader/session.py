"""Reading-session core: text lines, reading position and session records.

This module is the **presentation-free** half of reading.  It knows how a book's
text is split into lines, how a position and a bookmark list are written back
into ``library.json`` and how a finished session lands in the per-book and the
global totals.  It imports no terminal, no ``curses`` and no renderer, so the
curses front end (:mod:`wreader.reader`), the headless JSON-RPC sidecar
(:mod:`wreader.serve`) and the test suite can all drive reading through the very
same functions.

Line numbers stay the single coordinate system: the file written by the importer
is split on ``\\n`` exactly the way :mod:`wreader.library` split it, so
``progress["current_line"]``, ``progress["bookmarks"][].line`` and
``chapters[].line_start`` keep pointing into the same list.
"""

# 延迟求值类型注解
from __future__ import annotations

# 会话起止时间
from datetime import datetime
# 正文文件路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, List, Optional, Sequence

# 同包引用：书库（读正文、读写索引、空进度块、书签规整）
from . import library

# 模块公开的名字：会话落库的一条纯函数链
__all__ = [
    "accumulate_stats",
    "apply_position",
    "build_session",
    "iso",
    "now",
    "read_lines",
    "write_position",
    "write_session",
]


def now() -> datetime:
    """Return the current local time."""
    # 当前本地时间；单独包一层方便测试替换，也让所有落库时间戳同源
    return datetime.now()


def iso(moment: datetime) -> str:
    """Format *moment* the way the index stores timestamps."""
    # 与索引里的时间戳格式保持一致（精确到秒）
    return moment.isoformat(timespec="seconds")


def read_lines(file_path: str) -> List[str]:
    """Return the book text as lines, split exactly like the importer did."""
    # 导入时写下的 UTF-8 正文路径
    path = Path(str(file_path))
    # 文件不在了：抛出书库异常，由调用方统一提示
    if not path.is_file():
        raise library.LibraryError("book text is missing: {}".format(path))
    # 读盘可能失败（权限 / 磁盘），下面包成书库异常往上抛
    try:
        # 读出全文
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        # 读不了（权限 / 磁盘）：包成书库异常往上抛
        raise library.LibraryError("cannot read {}: {}".format(path, exc)) from exc
    # 必须与 library 用同样的方式规范化换行，行号才能对得上
    text = library.normalise_newlines(text)
    # 按 \n 切行；空文件返回空列表
    return text.split("\n") if text else []


def build_session(started: datetime, ended: datetime, lines_read: int) -> Dict[str, Any]:
    """Return the ``sessions[]`` entry describing one reading session."""
    # 一条会话记录：起止时间 + 这次读了多少行
    return {
        "start": iso(started),
        "end": iso(ended),
        "lines_read": int(max(0, lines_read)),
    }


def accumulate_stats(document: Dict[str, Any], seconds: int, day: str) -> Dict[str, Any]:
    """Add *seconds* to the global and to the per-day reading totals."""
    # 统计段落（不存在就建出来）
    stats = document.setdefault("stats", {})
    # 全局累计阅读秒数
    stats["total_read_time"] = int(stats.get("total_read_time") or 0) + int(seconds)
    # 按天的桶，连续天数与热力图都读它
    daily = stats.get("daily_read_time")
    # 结构不对（被手改坏了）就换一个空桶
    if not isinstance(daily, dict):
        # 换成空桶
        daily = {}
        # 挂回统计段落
        stats["daily_read_time"] = daily
    # 把秒数累加到当天的桶里
    daily[day] = int(daily.get(day) or 0) + int(seconds)
    # 交出（就地改过的）统计段落
    return stats


def apply_position(
    # 书库文档（就地修改）
    document: Dict[str, Any],
    # 书 id
    book_id: str,
    # 读到第几行（0 起始，唯一的坐标）
    position: int,
    # 百分比
    percentage: float,
    # 书签列表（可以混着行号与完整记录）
    bookmarks: Sequence[Any],
    # 正文总行数（用来判定“读完”）
    total: int,
    # 落库时刻
    moment: datetime,
) -> bool:
    """Store position, bookmarks and the sticky finished flag; ``False`` if gone."""
    # 按 id 找书；阅读中在另一个终端里把书删了，就写不进去
    book = document["books"].get(str(book_id))
    if book is None:  # the book was removed while we were reading
        # 书没了：明确返回 False，让调用方知道这次没落库
        return False
    # 取进度块（可能缺、也可能被手改坏）
    progress = book.get("progress")
    # 进度块结构不对就重建一份空进度
    if not isinstance(progress, dict):
        progress = library.empty_progress()
    # 覆盖式更新关键字段
    progress.update(
        {
            # 位置只存源行号，段内偏移是显示态、不落盘
            "current_line": int(position),
            "percentage": float(percentage),
            "last_read": iso(moment),
            # 书签先规整成标准结构再存
            "bookmarks": library.normalise_bookmarks(list(bookmarks)),
            # Sticky: once a book has been finished, jumping back does not undo it.
            # “读完了”是粘性的：读到最后一行就置位，之后回翻也不会取消
            "finished": bool(progress.get("finished"))
            or bool(total and position >= total - 1),
        }
    )
    # 写回索引记录
    book["progress"] = progress
    # 成功
    return True


def write_position(
    # 书 id
    book_id: str,
    # 读到第几行
    position: int,
    # 百分比
    percentage: float,
    # 书签列表
    bookmarks: Sequence[Any],
    # 正文总行数
    total: int,
    # 落库时刻，不传就取当前时间
    moment: Optional[datetime] = None,
) -> bool:
    """Load the index, store *just* where we are and save it back.

    This is what an auto-save timer calls: pure crash insurance for the reading
    position, so it deliberately records no session and touches no statistics.
    Returns ``False`` when the index could not be written.
    """
    # 读盘 / 写盘的失败都要吞成 False（下一次自动保存再试）
    try:
        # 读索引 -> 改位置 -> 写回，三步都在书库层
        document = library.load_library()
        # 书不在索引里：不写，直接报失败
        if not apply_position(
            document, book_id, position, percentage, bookmarks, total, moment or now()
        ):
            return False
        library.save_library(document)
    except library.LibraryError:
        # 索引写不了就当作失败（下一次自动保存再试）
        return False
    # 写成功
    return True


def write_session(
    # 书 id
    book_id: str,
    # 读到第几行
    position: int,
    # 百分比
    percentage: float,
    # 书签列表
    bookmarks: Sequence[Any],
    # 正文总行数
    total: int,
    # 本次会话总秒数
    seconds: int,
    # 会话开始时刻
    started: datetime,
    # 会话结束时刻
    ended: datetime,
    # 本次读了多少行
    lines_read: int,
    # 是否把本次会话写进历史统计
    record_history: bool = True,
) -> bool:
    """Write position, bookmarks and, optionally, the session to the index.

    The position and the bookmarks are always stored, so reading resumes where it
    stopped.  *record_history* (the ``reader.store_history`` setting) also appends
    the session with its duration to the book and to the global ``stats``.
    Returns ``False`` when the book is no longer in the index.
    """
    # 读索引：下面的改动都在内存里做，最后一次性落盘
    document = library.load_library()
    # 先写位置（书没了就直接返回，什么都不改）
    if not apply_position(
        document, book_id, position, percentage, bookmarks, total, ended
    ):
        return False
    # 这本书的进度块（刚写进去的，一定在）
    progress = document["books"][str(book_id)]["progress"]
    # 只有开了记录历史才写会话明细
    if record_history:
        # 已有的会话列表
        sessions = progress.get("sessions")
        # 会话列表结构不对就重建
        if not isinstance(sessions, list):
            sessions = []
        # 追加一条会话记录
        sessions.append(build_session(started, ended, lines_read))
        # 挂回进度块
        progress["sessions"] = sessions
        # 本书累计时长
        progress["total_time_seconds"] = int(
            progress.get("total_time_seconds") or 0
        ) + int(seconds)
        # 全局与当天的统计
        accumulate_stats(document, seconds, ended.strftime("%Y-%m-%d"))
    # 统一落盘
    library.save_library(document)
    # 成功
    return True

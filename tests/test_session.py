"""Tests for :mod:`wreader.session` -- the curses-free reading core.

Everything here is plain data in and plain data out: the module reads the book
text, folds a position into the index and appends a finished session to the
totals.  These tests pin the behaviour the terminal reader relies on, now that
the very same functions also serve the headless sidecar.
"""

# 延迟求值类型注解
from __future__ import annotations

# 会话起止时刻
from datetime import datetime
# 类型注解
from typing import Any, Dict

# pytest.raises
import pytest

# 被测模块 + 书库（读索引）
from wreader import library, session

# 测试里固定用的"落库时刻"
MOMENT = datetime(2026, 3, 1, 21, 30, 0)


def _book(book_id: str) -> Dict[str, Any]:
    """Return the index record of *book_id* (the tests always expect it to exist)."""
    # 取记录（get_book 的返回值是可选的）
    record = library.get_book(book_id)
    # 取不到说明测试自己的前提坏了：先失败，后面的下标才安全
    assert record is not None
    return record


def test_iso_keeps_seconds_only() -> None:
    """Timestamps are stored with second precision, without microseconds."""
    # 带微秒的时刻：写出来必须把微秒丢掉
    assert session.iso(datetime(2026, 3, 1, 21, 30, 0, 123456)) == "2026-03-01T21:30:00"


def test_read_lines_splits_like_the_importer(imported: Dict[str, Any]) -> None:
    """The text is split exactly the way the importer split it."""
    # 从索引里取中文书的正文路径
    path = _book(imported["zh"])["file_path"]
    # 读出来
    lines = session.read_lines(str(path))
    # 第一行就是第一章标题（行号是唯一坐标，切错一行整本书都会错位）
    assert lines[0] == "第一章 科学边界"
    # 与索引里记的总行数一致
    assert len(lines) == _book(imported["zh"])["total_lines"]


def test_read_lines_normalises_newlines(home: Any) -> None:
    """CRLF text is normalised, so line numbers stay comparable."""
    # 手写一份 CRLF 正文：不做规范化的话每行都会多带一个 \r
    target = home.novels / "crlf_utf8.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes("第一行\r\n第二行\r\n".encode("utf-8"))
    # 读出来是干净的两行（normalise_newlines 顺带丢掉末尾的空行）
    assert session.read_lines(str(target)) == ["第一行", "第二行"]


def test_read_lines_missing_file_raises(home: Any) -> None:
    """A missing text file is a library error, not a crash."""
    # 指向一个不存在的文件：必须抛 LibraryError 交给上层提示
    with pytest.raises(library.LibraryError):
        session.read_lines(str(home.novels / "nope_utf8.txt"))


def test_build_session_clamps_negative_lines() -> None:
    """A negative ``lines_read`` is clamped to 0 (hand written data cannot go negative)."""
    # 负数会被夹成 0，避免统计里出现负行数
    entry = session.build_session(MOMENT, MOMENT, -5)
    assert entry == {
        "start": "2026-03-01T21:30:00",
        "end": "2026-03-01T21:30:00",
        "lines_read": 0,
    }


def test_accumulate_stats_adds_global_and_daily() -> None:
    """Seconds land in both the global total and the per-day bucket."""
    # 空文档：会自动建出 stats 段落
    document: Dict[str, Any] = {}
    # 同一天两次、另一天一次
    session.accumulate_stats(document, 60, "2026-03-01")
    session.accumulate_stats(document, 30, "2026-03-01")
    session.accumulate_stats(document, 10, "2026-03-02")
    # 全局 = 100 秒
    assert document["stats"]["total_read_time"] == 100
    # 按天的桶分别累加
    assert document["stats"]["daily_read_time"] == {"2026-03-01": 90, "2026-03-02": 10}


def test_accumulate_stats_rebuilds_a_broken_bucket() -> None:
    """A hand edited ``daily_read_time`` that is not a dict gets replaced."""
    # 有人把按天的桶手改成了字符串
    document: Dict[str, Any] = {"stats": {"total_read_time": 5, "daily_read_time": "oops"}}
    session.accumulate_stats(document, 10, "2026-03-01")
    # 桶被重建，原有累计值不会丢
    assert document["stats"]["daily_read_time"] == {"2026-03-01": 10}
    assert document["stats"]["total_read_time"] == 15


def test_apply_position_stores_the_spot() -> None:
    """Position, percentage, bookmarks and the read time all land on one update."""
    # 一份最小的索引文档
    document: Dict[str, Any] = {"books": {"abc": {"progress": library.empty_progress()}}}
    # 书签用"简写形式"（纯行号）传进去，出来必须是标准记录
    assert session.apply_position(document, "abc", 3, 50.0, [2, 0], 8, MOMENT) is True
    progress = document["books"]["abc"]["progress"]
    # 位置与百分比
    assert progress["current_line"] == 3
    assert progress["percentage"] == 50.0
    # 书签被规整成 {line,label,created} 并按行号排序
    assert [mark["line"] for mark in progress["bookmarks"]] == [0, 2]
    # 最后阅读时间按秒级 ISO 存
    assert progress["last_read"] == "2026-03-01T21:30:00"


def test_apply_position_needs_the_book() -> None:
    """Writing a position for an unknown book reports failure instead of inventing one."""
    # 书不在索引里：返回 False，且不会凭空建出一条记录
    document: Dict[str, Any] = {"books": {}}
    assert session.apply_position(document, "nope", 1, 10.0, [], 4, MOMENT) is False
    assert document["books"] == {}


def test_apply_position_keeps_a_finished_book_finished() -> None:
    """The finished flag is sticky: jumping back never clears it."""
    # 先造一本"读完了"的书，位置落在最后一行
    document: Dict[str, Any] = {"books": {"abc": {"progress": library.empty_progress()}}}
    session.apply_position(document, "abc", 7, 100.0, [], 8, MOMENT)
    assert document["books"]["abc"]["progress"]["finished"] is True
    # 再回到第 1 行：finished 不能被撤销
    session.apply_position(document, "abc", 0, 0.0, [], 8, MOMENT)
    assert document["books"]["abc"]["progress"]["finished"] is True


def test_write_position_writes_the_library(imported: Dict[str, Any]) -> None:
    """``write_position`` persists to ``library.json`` and records no session."""
    # 写一个位置
    assert session.write_position(imported["zh"], 4, 44.0, [], 9) is True
    # 重新读盘：位置已经落库
    progress = _book(imported["zh"])["progress"]
    assert progress["current_line"] == 4
    # 只写位置不写会话：统计不受影响
    assert progress["sessions"] == []
    assert library.load_library()["stats"]["total_read_time"] == 0


def test_write_position_for_an_unknown_book_is_false() -> None:
    """An unknown book id is reported as a failure, not as a silent success."""
    # 不存在的书：返回 False（而不是假装写成功）
    assert session.write_position("nope", 1, 1.0, [], 10) is False


def test_write_session_records_everything(imported: Dict[str, Any]) -> None:
    """Position, session entry, per-book time and the global totals all move."""
    started = datetime(2026, 3, 1, 20, 0, 0)
    ended = datetime(2026, 3, 1, 20, 10, 0)
    # 写一场 10 分钟的会话（读了 5 行，停在最后一行）
    assert session.write_session(
        imported["zh"], 8, 100.0, [], 9, 600, started, ended, 5
    ) is True
    progress = _book(imported["zh"])["progress"]
    # 位置停在最后一行，并因此置上"读完"
    assert progress["current_line"] == 8
    assert progress["finished"] is True
    # 会话明细
    assert progress["sessions"] == [
        {"start": "2026-03-01T20:00:00", "end": "2026-03-01T20:10:00", "lines_read": 5}
    ]
    # 本书累计时长
    assert progress["total_time_seconds"] == 600
    # 全局累计 + 当天的桶
    stats = library.load_library()["stats"]
    assert stats["total_read_time"] == 600
    assert stats["daily_read_time"]["2026-03-01"] == 600


def test_write_session_can_skip_the_history(imported: Dict[str, Any]) -> None:
    """``record_history=False`` stores the position but no session and no time."""
    started = datetime(2026, 3, 1, 20, 0, 0)
    ended = datetime(2026, 3, 1, 20, 10, 0)
    # 不开记账：本次会话不进统计
    session.write_session(
        imported["zh"], 4, 50.0, [], 9, 600, started, ended, 3, record_history=False
    )
    progress = _book(imported["zh"])["progress"]
    # 位置照写
    assert progress["current_line"] == 4
    # 但没有会话、没有时长
    assert progress["sessions"] == []
    assert progress["total_time_seconds"] == 0
    assert library.load_library()["stats"]["total_read_time"] == 0


def test_write_session_of_a_removed_book_is_harmless() -> None:
    """A book deleted while reading reports failure instead of raising."""
    started = datetime(2026, 3, 1, 20, 0, 0)
    ended = datetime(2026, 3, 1, 20, 10, 0)
    # 书被另一个终端删掉了：返回 False，不抛异常
    assert session.write_session(
        "gone", 1, 10.0, [], 9, 60, started, ended, 1
    ) is False

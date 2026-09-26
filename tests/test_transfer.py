"""Tests for :mod:`wreader.transfer` — moving reading time between machines.

The real use case is "new laptop": export on the old machine, import the books and
then the bundle on the new one.  Everything here stays inside the throwaway
``$WREADER_HOME`` from ``conftest`` -- the bundle is written under ``tmp_path`` and
the "other machine" is just a second pair of data/novels directories wired up with
``monkeypatch``.
"""

# 延迟求值类型注解
from __future__ import annotations

# 解析导出的包
import json
# 路径类型注解
from pathlib import Path
# 造一个额外的阅读会话
from typing import Any, Dict

# pytest.raises / monkeypatch 的类型
import pytest

# 被测模块 + 书库（造记录）、成就（造解锁）、配置（切换"另一台机器"）
from wreader import achievements, config, library, transfer


def _switch_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    """Point this process at a second, empty pair of data/novels directories."""
    # 第二台机器：数据目录与正文目录都另起一套
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path / name / "data"))
    monkeypatch.setenv(config.ENV_NOVELS_DIR, str(tmp_path / name / "novels"))
    # 配置按路径+时间戳缓存：换了目录必须把缓存清掉，否则还在读上一台机器那份
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_PATH", None)
    monkeypatch.setattr(config, "_CACHE_STAMP", None)


def _read_history_into(document: Dict[str, Any], book_id: str) -> None:
    """Give *book_id* a 10 minute session, a position and the matching totals."""
    # 全局：累计时长 + 当天的桶
    stats = document["stats"]
    stats["total_read_time"] = int(stats.get("total_read_time") or 0) + 600
    stats["daily_read_time"]["2026-02-01"] = 600
    # 这本书：位置、累计时长、一场会话
    document["books"][book_id]["progress"].update(
        {
            "current_line": 4,
            "percentage": 50.0,
            "last_read": "2026-02-01T20:00:00",
            "total_time_seconds": 600,
            "sessions": [
                {
                    "start": "2026-02-01T19:50:00",
                    "end": "2026-02-01T20:00:00",
                    "lines_read": 4,
                }
            ],
        }
    )


def _seed_and_export(book_id: str, target: Path) -> None:
    """Read a bit of *book_id*, unlock one achievement, then export to *target*."""
    # 先攒阅读记录（直接改索引，省得模拟整个阅读器）
    document = library.load_library()
    _read_history_into(document, book_id)
    library.save_library(document)
    # 敲一次彩蛋命令等价的操作：解锁"名字彩蛋"，让状态文件里真的有东西
    achievements.check_achievements("name_egg", {"egg": "werd"})
    # 导出成包
    transfer.export_data(target)


# ------------------------------------------------------------------- exporting
def test_export_writes_a_plain_json_bundle(imported, tmp_path: Path) -> None:
    # 中文书读一段，并解锁一个成就
    target = tmp_path / "out" / "werd-data.json"
    _seed_and_export(imported["zh"], target)

    # 返回值是给人看的摘要（CLI 直接打印它）
    summary = transfer.export_data(target)
    assert summary["path"] == str(target)
    assert summary["books"] == 1
    assert summary["seconds"] == 600
    # 敲一次彩蛋可能顺带解锁别的成就，所以解锁数照状态文件数，不写死
    unlocked = [entry["id"] for entry in achievements.load_state()["unlocked"]]
    assert "name_egg" in unlocked
    assert summary["unlocked"] == len(unlocked)

    # 包本身是 UTF-8 的纯 JSON：身份 + 摘要 + 两段数据
    bundle = json.loads(target.read_text(encoding="utf-8"))
    assert bundle["kind"] == transfer.BUNDLE_KIND
    assert bundle["version"] == transfer.BUNDLE_VERSION
    assert bundle["exported_at"]
    assert bundle["summary"] == {
        "books": 1,
        "unlocked": len(unlocked),
        "total_read_time": 600,
    }
    assert bundle["reading"]["books"][imported["zh"]]["title"] == "三体"
    # 状态文件里的解锁记录原样进包
    assert [entry["id"] for entry in bundle["achievements"]["unlocked"]] == unlocked
    # 目录里只有这一个文件：临时文件已经改名成正式文件，没留下垃圾
    assert sorted(path.name for path in target.parent.iterdir()) == ["werd-data.json"]


def test_export_refuses_a_directory(tmp_path: Path) -> None:
    # 目标是目录：明确报错，而不是在里面悄悄建一个怪文件
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.export_data(tmp_path)
    assert "is a directory" in str(excinfo.value)


def test_export_reports_a_broken_state_file(tmp_path: Path) -> None:
    # 成就状态文件坏了（手改出语法错误）：给出统一的错误，而不是 traceback
    config.data_dir().mkdir(parents=True, exist_ok=True)
    achievements.state_path().write_text("{oops", encoding="utf-8")
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.export_data(tmp_path / "werd-data.json")
    assert "achievements.json" in str(excinfo.value)


# ------------------------------------------------------------------- importing
def test_a_bundle_carries_the_history_to_a_fresh_machine(
    imported, home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A 机：读 10 分钟 + 解锁名字彩蛋，然后导出一个包
    target = tmp_path / "out" / "werd-data.json"
    _seed_and_export(imported["zh"], target)
    # A 机的解锁清单（敲一次彩蛋可能顺带解锁别的成就，不写死数字）
    unlocked = [entry["id"] for entry in achievements.load_state()["unlocked"]]

    # B 机：数据目录和正文目录都是空的，先导入同样的书
    # （正文一样 → 转换后的 SHA-1 一样 → book_id 一样，两边才对得上）
    _switch_machine(monkeypatch, tmp_path, "machine-b")
    result = library.import_books(str(home.root / "books"))
    assert [book_id for book_id, _book in result.imported] == imported["ids"]
    # 新机器上还没有任何阅读记录与成就
    assert library.load_library()["stats"]["total_read_time"] == 0
    assert achievements.load_state()["unlocked"] == []

    summary = transfer.import_data(target)

    # 摘要：1 本书的记录接上了，没有跳过，搬来 600 秒
    assert summary == {
        "path": str(target),
        "books": 1,
        "skipped": 0,
        "seconds": 600,
        "unlocked": len(unlocked),
    }
    # 全局时长与每日桶都搬过来了
    document = library.load_library()
    assert document["stats"]["total_read_time"] == 600
    assert document["stats"]["daily_read_time"] == {"2026-02-01": 600}
    # 这本书的进度也接上了：位置、百分比、时长、会话
    progress = document["books"][imported["zh"]]["progress"]
    assert progress["current_line"] == 4
    assert progress["percentage"] == 50.0
    assert progress["total_time_seconds"] == 600
    assert [item["lines_read"] for item in progress["sessions"]] == [4]
    # 成就也跟过来了：和 A 机的清单一致
    assert sorted(
        entry["id"] for entry in achievements.load_state()["unlocked"]
    ) == sorted(unlocked)


def test_importing_the_same_bundle_twice_does_not_duplicate_sessions(
    imported, home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A 机导出，B 机把同一份包导入两遍
    target = tmp_path / "out" / "werd-data.json"
    _seed_and_export(imported["zh"], target)
    _switch_machine(monkeypatch, tmp_path, "machine-b")
    library.import_books(str(home.root / "books"))

    transfer.import_data(target)
    first = library.load_library()["books"][imported["zh"]]["progress"]
    transfer.import_data(target)
    second = library.load_library()["books"][imported["zh"]]["progress"]

    # 会话按内容去重：导两遍也只有一场
    assert len(first["sessions"]) == 1
    assert len(second["sessions"]) == 1
    # 时长是"增量相加"的口径，所以同一份包导两遍就会算两遍（文档里写明了）
    assert first["total_time_seconds"] == 600
    assert second["total_time_seconds"] == 1200


def test_import_counts_the_books_this_machine_does_not_have(
    imported, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A 机有一本中文书的记录；B 机一本书都没导入，没有记录可以挂
    target = tmp_path / "out" / "werd-data.json"
    _seed_and_export(imported["zh"], target)
    _switch_machine(monkeypatch, tmp_path, "machine-b")

    summary = transfer.import_data(target)

    # 跳过并计数，但全局时长照样接过来
    assert summary["books"] == 0
    assert summary["skipped"] == 1
    assert summary["seconds"] == 600
    assert library.load_library()["stats"]["total_read_time"] == 600


def test_import_rejects_files_that_are_not_bundles(tmp_path: Path) -> None:
    # 文件不存在
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.import_data(tmp_path / "nope.json")
    assert "no such data file" in str(excinfo.value)

    # 语法坏掉的 JSON
    broken = tmp_path / "broken.json"
    broken.write_text("{oops", encoding="utf-8")
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.import_data(broken)
    assert "cannot be read" in str(excinfo.value)

    # 合法 JSON 但不是 werd 的数据包：不能把它当真悄悄合并
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"books": {}}), encoding="utf-8")
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.import_data(other)
    assert "not a werd data file" in str(excinfo.value)

    # 版本比本程序新：宁可拒绝，也不猜着合并
    future = tmp_path / "future.json"
    future.write_text(
        json.dumps(
            {"kind": transfer.BUNDLE_KIND, "version": transfer.BUNDLE_VERSION + 1}
        ),
        encoding="utf-8",
    )
    with pytest.raises(transfer.TransferError) as excinfo:
        transfer.import_data(future)
    assert "another version" in str(excinfo.value)


def test_import_tolerates_a_bundle_without_payloads(tmp_path: Path) -> None:
    # 手改过的包：两段数据都被删掉了，合并应当当成空数据而不是崩掉
    target = tmp_path / "out" / "werd-data.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps({"kind": transfer.BUNDLE_KIND, "version": transfer.BUNDLE_VERSION}),
        encoding="utf-8",
    )

    summary = transfer.import_data(target)

    assert summary["books"] == 0
    assert summary["skipped"] == 0
    assert summary["seconds"] == 0
    assert summary["unlocked"] == 0

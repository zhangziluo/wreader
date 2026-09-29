"""Tests for :mod:`wreader.serve` -- the headless JSON-RPC sidecar.

The sidecar is what a GUI talks to: one JSON request per line in, one JSON
response per line out.  These tests drive :func:`wreader.serve.handle_request`
directly (no pipes needed) and only use the real stdin/stdout loop once, plus a
fresh interpreter to prove the module really stays free of ``curses`` and
``rich``.
"""

# 延迟求值类型注解
from __future__ import annotations

# 临时环境变量与子进程调用
import os
import subprocess
# 给 stdin/stdout 循环喂数据
import io
import sys
# 仓库根路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, List

# 被测模块 + 内核（直接读索引断言落库结果）
from wreader import config, library, serve


def _raw(method: str, **params: Any) -> Dict[str, Any]:
    """Send one request and return the whole response dict."""
    # id 固定用 1：这里只关心 result / error
    return serve.handle_request({"id": 1, "method": method, "params": params})


def _result(method: str, **params: Any) -> Dict[str, Any]:
    """Send one request that is expected to succeed and return its result."""
    # 用对象方法取出响应；有 error 就直接让测试炸出来（消息里带上原因）
    response = _raw(method, **params)
    assert "error" not in response, response.get("error")
    return dict(response["result"])


def _ids(method: str, **params: Any) -> List[str]:
    """Return the ``id`` of every book row a listing method produced."""
    # 所有书单方法都回 {"books": [...]}，这里只取 id 方便断言
    return [row["id"] for row in _result(method, **params)["books"]]


def _book(book_id: str) -> Dict[str, Any]:
    """Return the index record of *book_id* (the tests always expect it to exist)."""
    # 取记录（get_book 的返回值是可选的）
    record = library.get_book(book_id)
    # 取不到说明测试自己的前提坏了：先失败，后面的下标才安全
    assert record is not None
    return record


def test_ping_reports_a_pong_and_the_version() -> None:
    """``ping`` is the liveness probe the shell uses while starting the core."""
    # 回 pong + 版本号
    result = _result("ping")
    assert result["pong"] is True
    assert result["version"] == serve.__version__


def test_paths_describes_the_data_directory(home: Any) -> None:
    """``paths`` tells the shell where the plain text data lives."""
    # 四个路径都要报出来，且都指向临时家目录
    result = _result("paths")
    assert result["data_dir"] == str(home.data)
    assert result["novels_dir"] == str(home.novels)
    assert result["library_file"] == str(config.library_file())


def test_unknown_method_is_an_error_response() -> None:
    """A typo in the shell's call must not take the core down."""
    # 不认识的方法：回一条 error，而不是抛异常
    response = _raw("no_such_method")
    assert response["error"]["type"] == "ServeError"
    assert "no_such_method" in response["error"]["message"]


def test_a_bad_method_field_is_an_error_response() -> None:
    """A request without a string ``method`` is rejected, not crashed on."""
    # 缺 method / method 不是字符串：都是 error 响应
    assert "error" in serve.handle_request({"id": 2})
    assert "error" in serve.handle_request({"id": 3, "method": 7})


def test_a_non_object_request_is_an_error_response() -> None:
    """A bare JSON scalar is answered with an error, since it has no id either."""
    # 直接发一个字符串：连 id 都没有，id 回 null
    response = serve.handle_request("hello")
    assert response["id"] is None
    assert response["error"]["type"] == "ServeError"


def test_bad_params_type_is_an_error_response(imported: Dict[str, Any]) -> None:
    """A parameter of the wrong type becomes an error, not a traceback."""
    # count 传了字符串：转 int 会失败，要被包成 error（书 id 是真的，好让错误来自参数）
    response = _raw("text", book_id=imported["zh"], count="many")
    assert response["error"]["type"] == "ServeError"
    assert "bad params" in response["error"]["message"]


def test_serve_answers_one_line_per_request(imported: Dict[str, Any]) -> None:
    """The stdin/stdout loop: blank lines are skipped, everything else is answered."""
    # 三行有效请求 + 一行坏 JSON + 一行空行
    stream = io.StringIO(
        '{"id": 1, "method": "ping"}\n'
        "\n"
        "not json\n"
        '{"id": 3, "method": "list"}\n'
    )
    output = io.StringIO()
    # 跑完整个循环
    assert serve.serve(stream, output) == 0
    lines = [line for line in output.getvalue().splitlines() if line]
    # 空行不回东西，所以是 3 条响应
    assert len(lines) == 3
    # 第二行是坏 JSON 的报错（id 为 null，因为连 id 都解不出来）
    assert '"id": null' in lines[1]
    assert "bad JSON" in lines[1]


def test_importing_the_sidecar_never_pulls_in_the_front_end(tmp_path: Path) -> None:
    """The sidecar stays headless: no curses, no rich, no CLI.

    Run in a fresh interpreter on purpose -- this test process has already
    imported ``wreader.reader`` for the terminal tests, so ``sys.modules`` here
    would prove nothing.
    """
    # 仓库根：子进程要在那里把 wreader 导进来
    root = Path(__file__).resolve().parents[1]
    # 只报告"不该出现却出现了"的那几个模块
    script = (
        "import sys\n"
        "import wreader.serve\n"
        "print(','.join(sorted(\n"
        "    name for name in ('wreader.reader', 'wreader.cli', 'rich', 'curses')\n"
        "    if name in sys.modules\n"
        ")))\n"
    )
    # 数据目录也指到临时目录，子进程绝不碰真实数据
    environment = dict(os.environ)
    environment[config.ENV_HOME] = str(tmp_path / "data")
    finished = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    # 一个都不该被带进来
    assert finished.stdout.strip() == ""


def test_list_search_and_recent_agree_on_the_rows(imported: Dict[str, Any]) -> None:
    """Every listing method publishes the same flat row shape."""
    # 全量书单：两本
    every = _result("list")["books"]
    assert {row["id"] for row in every} == {imported["zh"], imported["en"]}
    # 行里带标题、总行数与进度字段（GUI 直接渲染，不必自己翻 progress）
    row = next(item for item in every if item["id"] == imported["zh"])
    assert row["title"] == "三体"
    assert row["author"] == "刘慈欣"
    assert row["total_lines"] > 0
    assert row["current_line"] == 0
    assert row["finished"] is False
    # 搜索与列表用的是同一套行
    assert _ids("search", keyword="三体") == [imported["zh"]]
    # 空关键词 = 全量
    assert len(_result("search", keyword="")["books"]) == 2


def test_recent_is_empty_before_anything_is_read(imported: Dict[str, Any]) -> None:
    """Nothing has been read yet, so ``recent`` has nothing to offer."""
    # 没读过任何书：最近在读是空的（而不是报错）
    assert _result("recent")["books"] == []


def test_get_book_returns_null_for_an_unknown_id() -> None:
    """An unknown id is ``null``, so the shell can show its own message."""
    # 空 id 与不存在的 id 都回 null
    assert _result("get_book", book_id="")["book"] is None
    assert _result("get_book", book_id="nope")["book"] is None


def test_text_slices_the_book_in_source_lines(imported: Dict[str, Any]) -> None:
    """``text`` hands back source lines -- the very indexes the index stores."""
    # 取前两行
    chunk = _result("text", book_id=imported["zh"], start=0, count=2)
    assert chunk["lines"] == ["第一章 科学边界", ""]
    assert chunk["start"] == 0
    # 总行数与索引里记的一致（行号是唯一坐标）
    assert chunk["total_lines"] == _book(imported["zh"])["total_lines"]
    # 从第 2 行开始取三行
    later = _result("text", book_id=imported["zh"], start=2, count=3)
    assert later["lines"][0] == "汪淼看到了一串数字在眼前跳动。"
    # 起点超出总行数：回空列表，不报错
    assert _result("text", book_id=imported["zh"], start=9999)["lines"] == []


def test_text_clamps_count_and_start(imported: Dict[str, Any]) -> None:
    """A silly ``count`` is clamped, so one call cannot pull in a whole book."""
    # 负数起点夹到 0
    assert _result("text", book_id=imported["zh"], start=-5)["start"] == 0
    # 超大的 count 被夹到上限
    huge = _result("text", book_id=imported["zh"], count=999999)
    assert huge["count"] == serve._MAX_TEXT_COUNT
    # count 为 0（等于没传）时给默认的一屏多一点
    assert _result("text", book_id=imported["zh"], count=0)["count"] == serve._DEFAULT_TEXT_COUNT


def test_text_on_a_missing_file_is_an_error(imported: Dict[str, Any]) -> None:
    """A book whose text file disappeared is a ``LibraryError`` over the wire."""
    # 手删正文文件（模拟"索引里还有、磁盘上没了"）
    Path(str(_book(imported["zh"])["file_path"])).unlink()
    # 取正文：不是崩溃，而是一条可读的 error 响应
    response = _raw("text", book_id=imported["zh"])
    assert response["error"]["type"] == "LibraryError"


def test_toc_returns_the_chapters(imported: Dict[str, Any]) -> None:
    """``toc`` returns the chapter table, with line numbers in source lines."""
    # 中文书有两个章节标题
    entries = _result("toc", book_id=imported["zh"])["entries"]
    assert [entry["title"] for entry in entries] == ["第一章 科学边界", "第二章 台球"]
    # 章节起始行是源行号（第一章在 0）
    assert entries[0]["line"] == 0


def test_position_saves_without_recording_a_session(imported: Dict[str, Any]) -> None:
    """``position`` is the auto-save seam: position only, no statistics."""
    # 写位置
    saved = _result("position", book_id=imported["zh"], position=4, percentage=44.0)
    assert saved["saved"] is True
    # 落库了
    assert _book(imported["zh"])["progress"]["current_line"] == 4
    # 但没记会话，也没动统计
    assert _book(imported["zh"])["progress"]["sessions"] == []
    assert _result("stats")["total_seconds"] == 0


def test_session_records_time_and_reports_unlocks(imported: Dict[str, Any]) -> None:
    """``session`` writes the position and the duration, then asks the engine."""
    # 一场 10 分钟的会话，停在最后一行
    result = _result(
        "session",
        book_id=imported["zh"],
        position=8,
        percentage=100.0,
        seconds=600,
        lines_read=5,
        started="2026-03-01T20:00:00",
        ended="2026-03-01T20:10:00",
    )
    # 落库成功
    assert result["saved"] is True
    # unlocked 是这一场新解锁的成就（只断言形状合理，别把定义表抄进测试）
    assert isinstance(result["unlocked"], list)
    for record in result["unlocked"]:
        assert set(record) >= {"id", "name", "unlocked_at"}
    progress = _book(imported["zh"])["progress"]
    # 位置、会话明细、本书时长
    assert progress["current_line"] == 8
    assert progress["sessions"] == [
        {"start": "2026-03-01T20:00:00", "end": "2026-03-01T20:10:00", "lines_read": 5}
    ]
    assert progress["total_time_seconds"] == 600
    # 停在最后一行：置上粘性的 finished
    assert progress["finished"] is True
    # 统计报告里的累计时长同步了
    assert _result("stats")["total_seconds"] == 600


def test_session_with_ranges_counts_words_once(imported: Dict[str, Any]) -> None:
    """Line ``ranges`` let the engine count words, and re-reading adds nothing."""
    # 第一场：读过 0-4 行
    first = _result(
        "session",
        book_id=imported["zh"],
        position=4,
        percentage=50.0,
        seconds=120,
        lines_read=4,
        ranges=[[0, 4]],
        started="2026-03-01T20:00:00",
        ended="2026-03-01T20:02:00",
    )
    assert first["saved"] is True
    # 第二场：把同一段再读一遍
    second = _result(
        "session",
        book_id=imported["zh"],
        position=4,
        percentage=50.0,
        seconds=60,
        lines_read=0,
        ranges=[[0, 4]],
        started="2026-03-01T21:00:00",
        ended="2026-03-01T21:01:00",
    )
    assert second["saved"] is True
    # 时长照加（120 + 60），重复的区间不会重复解锁
    assert _result("stats")["total_seconds"] == 180
    # 会话明细里是两条（时长才是"读了几次"的判据）
    assert len(_book(imported["zh"])["progress"]["sessions"]) == 2


def test_session_can_skip_the_history(imported: Dict[str, Any]) -> None:
    """``record_history=False`` stores the position but adds no reading time."""
    # 不开记账
    _result(
        "session",
        book_id=imported["zh"],
        position=4,
        percentage=50.0,
        seconds=600,
        lines_read=3,
        record_history=False,
    )
    # 位置在，时长不在
    assert _book(imported["zh"])["progress"]["current_line"] == 4
    assert _result("stats")["total_seconds"] == 0


def test_session_fills_in_a_missing_start(imported: Dict[str, Any]) -> None:
    """A missing ``started`` is derived from ``ended`` and ``seconds``."""
    # 只给结束时刻与时长：sessions[] 里的 start 必须是 ended 往前推 600 秒
    _result(
        "session",
        book_id=imported["zh"],
        position=1,
        percentage=10.0,
        seconds=600,
        lines_read=1,
        ended="2026-03-01T20:10:00",
    )
    entry = _book(imported["zh"])["progress"]["sessions"][0]
    assert entry["start"] == "2026-03-01T20:00:00"
    assert entry["end"] == "2026-03-01T20:10:00"


def test_event_records_a_daily_open(imported: Dict[str, Any]) -> None:
    """``event`` is the generic seam onto the achievements engine."""
    # 记一条 daily_open：不报错，且回一个列表
    assert isinstance(_result("event", event_type="daily_open")["unlocked"], list)


def test_event_rejects_an_unknown_name() -> None:
    """A misspelt event is an ``AchievementsError``, never a silent no-op."""
    # 事件名不在白名单里：必须报错，不能静默吞掉
    response = _raw("event", event_type="not_an_event")
    assert response["error"]["type"] == "AchievementsError"


def test_stats_report_comes_back_in_seconds(imported: Dict[str, Any]) -> None:
    """``stats`` returns the same report ``werd stats --json`` prints."""
    # 先记一场 5 分钟的会话
    _result(
        "session",
        book_id=imported["zh"],
        position=2,
        percentage=20.0,
        seconds=300,
        lines_read=2,
        started="2026-03-01T20:00:00",
        ended="2026-03-01T20:05:00",
    )
    report = _result("stats")
    # 时长与派生值都是秒
    assert report["total_seconds"] == 300
    # "今天"就是报告生成那天（报告里两个字段同源）
    assert report["today"] == str(report["generated_at"])[:10]
    # 每本书的累计时长也在报告里
    assert {row["id"] for row in report["books"]} == {imported["zh"]}
    # 成就段落用的是 achievements.json 里的权威解锁列表
    assert report["achievements"]["total"] > 0


def test_achievements_list_carries_the_progress(imported: Dict[str, Any]) -> None:
    """``achievements`` returns every definition with its current progress."""
    rows = _result("achievements")["achievements"]
    # 定义表非空，且每行都有 GUI 要用的字段
    assert rows
    for row in rows:
        assert set(row) >= {
            "id",
            "name",
            "desc",
            "category",
            "current",
            "required",
            "unlocked",
        }


def test_config_get_returns_dotted_paths() -> None:
    """``config_get`` publishes the settings as ``section.key`` paths."""
    result = _result("config_get")
    values = result["values"]
    # 没改过设置时，报回来的就是出厂默认值（按定义表对拍，别把默认值抄死）
    assert values["reader.page_height"] == config.default_for("reader.page_height")
    assert "reader.store_history" in values
    # 同时告诉客户端有哪些合法的键（GUI 的设置页据此渲染）
    assert "reader.page_height" in result["paths"]


def test_config_set_coerces_and_writes() -> None:
    """``config_set`` coerces the value, writes the file and returns the value."""
    # 传字符串 "6"：会被转成整数再落盘
    changed = _result("config_set", path="reader.page_height", value="6")
    assert changed["value"] == 6
    assert changed["path"] == "reader.page_height"
    # 重新读出来：已经落盘
    assert _result("config_get")["values"]["reader.page_height"] == 6


def test_config_set_rejects_a_bad_value() -> None:
    """A wrong type is a ``ConfigError``, so a bad setting never reaches the file."""
    # 整数键传了 "lots"：类型校验失败
    bad = _raw("config_set", path="reader.page_height", value="lots")
    assert bad["error"]["type"] == "ConfigError"
    # 键名拼错：同样报错（CLI 会给拼写建议，这里至少不能静默通过）
    typo = _raw("config_set", path="reader.page_hight", value=3)
    assert typo["error"]["type"] == "ConfigError"


def test_config_set_requires_a_path_and_a_value() -> None:
    """Both a path and a value are required, so nothing is silently unset."""
    # 缺 path
    assert "error" in _raw("config_set", value=3)
    # 缺 value（不能默默把设置清成 None）
    assert "error" in _raw("config_set", path="reader.page_height")


def test_import_scans_a_folder(home: Any) -> None:
    """``import`` converts and indexes new files, and skips what is already there."""
    # 目录里放一本书
    home.write_book("刘慈欣-三体.txt")
    first = _result("import", path=str(home.root / "books"))
    # 扫到并入库一本
    assert first["scanned"] == 1
    assert len(first["imported"]) == 1
    assert first["imported"][0]["title"] == "三体"
    assert first["failed"] == []
    # 再导一次：同一份内容被识别成重复（book_id 是正文 SHA-1）
    second = _result("import", path=str(home.root / "books"))
    assert second["imported"] == []
    assert second["duplicates"] == ["刘慈欣-三体.txt"]


def test_import_requires_a_path() -> None:
    """A missing path is an error, not a silent no-op."""
    # 没给路径：报错
    assert _raw("import")["error"]["type"] == "ServeError"


def test_prune_drops_books_whose_text_is_gone(imported: Dict[str, Any]) -> None:
    """``prune`` reconciles the index with what is actually on disk."""
    # 手删中文书的正文文件
    Path(str(_book(imported["zh"])["file_path"])).unlink()
    # 对账：只摘掉那一本
    result = _result("prune")
    assert result["removed"] == 1
    assert result["books"] == [{"id": imported["zh"], "title": "三体"}]
    # 索引里也没了
    assert _result("get_book", book_id=imported["zh"])["book"] is None


def test_clear_keeps_the_reading_time(imported: Dict[str, Any]) -> None:
    """``clear`` forgets *which books* you have, never how long you read them."""
    # 先记 10 分钟，让统计有痕迹
    _result(
        "session",
        book_id=imported["zh"],
        position=4,
        percentage=50.0,
        seconds=600,
        lines_read=4,
    )
    # 清空书库
    cleared = _result("clear")
    assert cleared["removed"] == 2
    # 书没了
    assert _result("list")["books"] == []
    # 但累计时长与成就都还在
    assert _result("stats")["total_seconds"] == 600
    assert _result("achievements")["achievements"]


def _switch_machine(monkeypatch: Any, tmp_path: Path, name: str) -> None:
    """Point this process at a second, empty pair of data/novels directories."""
    # 第二台机器：数据目录与正文目录都另起一套
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path / name / "data"))
    monkeypatch.setenv(config.ENV_NOVELS_DIR, str(tmp_path / name / "novels"))
    # 配置按路径 + 时间戳缓存：换了目录必须清掉，否则还在读上一台机器那份
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_PATH", None)
    monkeypatch.setattr(config, "_CACHE_STAMP", None)


def test_export_and_import_data_move_the_reading_record(
    imported: Dict[str, Any], tmp_path: Path, monkeypatch: Any
) -> None:
    """The bundle written by ``export`` is exactly what ``import_data`` merges."""
    # 先读 10 分钟，包里才有东西可搬
    _result(
        "session",
        book_id=imported["zh"],
        position=4,
        percentage=50.0,
        seconds=600,
        lines_read=4,
        started="2026-03-01T20:00:00",
        ended="2026-03-01T20:10:00",
    )
    bundle = tmp_path / "werd-data.json"
    exported = _result("export", path=str(bundle))
    # 摘要报了搬几本书、多少秒，以及写到哪儿
    assert exported["path"] == str(bundle)
    assert exported["books"] == 1
    assert exported["seconds"] == 600
    assert bundle.is_file()
    # 换到"另一台机器"：书还没导入，所以那本书的记录会被跳过
    _switch_machine(monkeypatch, tmp_path, "second")
    merged = _result("import_data", path=str(bundle))
    assert merged["books"] == 0
    assert merged["skipped"] == 1
    # 全局时长是照搬的：这一趟不算白跑
    assert _result("stats")["total_seconds"] == 600


def test_export_and_import_data_require_a_path() -> None:
    """Both data methods refuse to run without a path."""
    # 没有 path：export 与 import_data 都回 error，而不是写到奇怪的地方
    assert _raw("export")["error"]["type"] == "ServeError"
    assert _raw("import_data")["error"]["type"] == "ServeError"

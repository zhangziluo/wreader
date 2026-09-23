"""Tests for :mod:`wreader.stats` — metrics, the heatmap and the achievements."""

# 延迟求值类型注解
from __future__ import annotations

# 用 StringIO 当假输出流测庆祝动画
import io
# 构造测试用成就文件
import json
# 注入固定日期/时间，保证统计结果可预测
from datetime import date, datetime

# pytest.raises / parametrize
import pytest

# 被测模块 + 配置与书库
from wreader import config, library, stats


# ------------------------------------------------------------------ definitions
def test_load_achievements_reads_the_packaged_file() -> None:
    # 读打包的那份成就定义
    definitions = stats.load_achievements()
    # 当前随包发布 48 条（Phase 1 的 28 条 + 笔记联动的"笔记达人" + Phase 2/3 的 19 条）
    assert len(definitions) == 48
    for achievement in definitions:
        # 三要素都要非空
        assert achievement["id"]
        assert achievement["name"]
        assert achievement["condition"]
        # 分类必须有值（CLI 靠它分组），secret 必须是布尔
        assert achievement["category"]
        assert isinstance(achievement["secret"], bool)
        # 且结构统一
        assert set(achievement) == {
            "id",
            "name",
            "desc",
            "condition",
            "category",
            "secret",
        }
    # id 不能重复
    ids = [achievement["id"] for achievement in definitions]
    assert len(set(ids)) == len(ids)


def test_load_achievements_accepts_an_explicit_path(tmp_path) -> None:
    # 显式给路径时读该文件，并兼容老的 {"achievements": [...]} 包装
    target = tmp_path / "a.json"
    target.write_text(
        json.dumps({"achievements": [{"id": "x", "condition": "streak >= 2"}]}),
        encoding="utf-8",
    )
    # 缺 name 时用 id 兜底，desc 补空串，category/secret 补默认值
    assert stats.load_achievements(target) == [
        {
            "id": "x",
            "name": "x",
            "desc": "",
            "condition": "streak >= 2",
            "category": stats.DEFAULT_CATEGORY,
            "secret": False,
        }
    ]


def test_load_achievements_skips_unusable_entries(tmp_path) -> None:
    # 三种坏数据：纯字符串、没有 id、没有条件
    target = tmp_path / "a.json"
    target.write_text(
        json.dumps(["junk", {"name": "no id"}, {"id": "no-condition"}]),
        encoding="utf-8",
    )
    # 全部被跳过，返回空列表（而不是报错）
    assert stats.load_achievements(target) == []


def test_load_achievements_rejects_broken_json(tmp_path) -> None:
    target = tmp_path / "a.json"
    target.write_text("{oops", encoding="utf-8")
    with pytest.raises(stats.StatsError) as excinfo:
        stats.load_achievements(target)
    assert "not valid JSON" in str(excinfo.value)


def test_load_achievements_rejects_a_non_list(tmp_path) -> None:
    # 合法 JSON 但顶层不是列表
    target = tmp_path / "a.json"
    target.write_text('"a string"', encoding="utf-8")
    with pytest.raises(stats.StatsError) as excinfo:
        stats.load_achievements(target)
    assert "must contain a list" in str(excinfo.value)


# ------------------------------------------------------------------- conditions
def test_parse_condition() -> None:
    # 条件字符串被拆成 (指标, 运算符, 目标值)
    assert stats.parse_condition("total_time >= 3600") == ("total_time", ">=", 3600)
    assert stats.parse_condition("finished == 1") == ("finished", "==", 1)
    # 不合语法时明确报错
    with pytest.raises(stats.StatsError) as excinfo:
        stats.parse_condition("total time is big")
    assert "cannot understand the condition" in str(excinfo.value)


# 参数化：五种运算符的边界情况
@pytest.mark.parametrize(
    "condition, current, expected",
    [
        ("streak >= 3", 3, True),
        ("streak >= 3", 2, False),
        ("streak > 3", 4, True),
        ("streak > 3", 3, False),
        ("streak <= 3", 3, True),
        ("streak < 3", 2, True),
        ("streak == 3", 3, True),
        ("streak == 3", 4, False),
    ],
)
def test_evaluate_condition(condition: str, current: int, expected: bool) -> None:
    # 直接对给定指标值求值
    assert stats.evaluate_condition(condition, {"streak": current}) is expected


def test_evaluate_condition_defaults_an_unknown_metric_to_zero() -> None:
    # 指标缺失按 0 处理
    assert stats.evaluate_condition("nope >= 1", {}) is False
    assert stats.evaluate_condition("nope <= 0", {}) is True


def test_achievement_state_reports_progress() -> None:
    # 只读了 3600 秒，要求 7200 秒：应当"未达标"
    info = stats.achievement_state(
        {"id": "x", "name": "X", "desc": "d", "condition": "total_time >= 7200"},
        {"total_time": 3600},
    )
    # 返回给界面用的完整状态
    assert info == {
        "id": "x",
        "name": "X",
        "desc": "d",
        "metric": "total_time",
        "current": 3600,
        "required": 7200,
        "unlocked": False,
    }


# --------------------------------------------------------------------- time maths
def test_night_overlap_counts_only_the_night_window() -> None:
    # 22:00 -> 次日 02:00 只有后两小时落在 00:00-04:00 窗口内
    assert stats.night_overlap("2026-01-01T22:00:00", "2026-01-02T02:00:00") == 7200
    # 完全落在窗口内
    assert stats.night_overlap("2026-01-01T01:00:00", "2026-01-01T02:00:00") == 3600
    # 白天：不计入
    assert stats.night_overlap("2026-01-01T10:00:00", "2026-01-01T11:00:00") == 0
    assert stats.night_overlap("2026-01-01T23:00:00", "2026-01-01T23:30:00") == 0
    # 03:30 to 04:30 only overlaps the last half hour of the window.
    assert stats.night_overlap("2026-01-01T03:30:00", "2026-01-01T04:30:00") == 1800


# 参数化：几种坏时间戳
@pytest.mark.parametrize(
    "start, end",
    [(None, "2026-01-01T01:00:00"), ("nonsense", "2026-01-01T01:00:00"), ("x", "y")],
)
def test_night_overlap_tolerates_bad_timestamps(start, end) -> None:
    # 解析不了就当没有夜间时长
    assert stats.night_overlap(start, end) == 0


def test_night_overlap_needs_a_forward_range() -> None:
    # 结束早于开始、或零长度：都是 0
    assert stats.night_overlap("2026-01-01T02:00:00", "2026-01-01T01:00:00") == 0
    assert stats.night_overlap("2026-01-01T01:00:00", "2026-01-01T01:00:00") == 0


def test_session_seconds() -> None:
    # 12 分 30 秒 = 750 秒
    session = {"start": "2026-01-01T10:00:00", "end": "2026-01-01T10:12:30"}
    assert stats.session_seconds(session) == 750
    # 缺字段或时间非法
    assert stats.session_seconds({}) == 0
    assert stats.session_seconds({"start": "x", "end": "y"}) == 0


def test_daily_totals_coerces_and_skips_garbage() -> None:
    # 数字、数字字符串、None 都能转；"abc" 被丢掉
    assert stats.daily_totals(
        {"2026-01-01": 3600, "2026-01-02": "60", "2026-01-03": None, "2026-01-04": "abc"}
    ) == {"2026-01-01": 3600, "2026-01-02": 60, "2026-01-03": 0}
    # 根本不是字典
    assert stats.daily_totals("nope") == {}


# 参数化：时长格式化的各种边界
@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "0分钟"),
        (59, "0分钟"),
        (60, "1分钟"),
        (2700, "45分钟"),
        (3600, "1小时"),
        (23700, "6小时35分钟"),
    ],
)
def test_format_hours(seconds: int, expected: str) -> None:
    assert stats.format_hours(seconds) == expected


# ---------------------------------------------------------------- period totals
DAILY = {
    "2026-01-04": 100,
    "2026-01-05": 200,
    "2026-01-06": 300,
    "2026-01-07": 400,
    "2026-01-08": 500,
}


def test_today_week_and_month_totals() -> None:
    today = date(2026, 1, 7)  # a Wednesday, so the week starts on the 5th
    # 今日 = 当天那一桶
    assert stats.today_total(DAILY, today) == 400
    # 本周 = 周一(5 日) 到今天
    assert stats.week_total(DAILY, today) == 900
    # 本月 = 1 号到今天
    assert stats.month_total(DAILY, today) == 1000
    # 任意区间求和
    assert stats.period_total(DAILY, date(2026, 1, 1), date(2026, 1, 31)) == 1500


def test_period_totals_of_an_empty_document() -> None:
    # 空字典与 None 都返回 0，不该报错
    assert stats.today_total({}, date(2026, 1, 7)) == 0
    assert stats.week_total(None, date(2026, 1, 7)) == 0


# ---------------------------------------------------------------------- streaks
# 参数化：各种"连续天数"场景（基准日为 2026-01-07）
@pytest.mark.parametrize(
    "daily, expected",
    [
        ({"2026-01-05": 1800, "2026-01-06": 1800, "2026-01-07": 1800}, 3),
        # Today has not been read yet: a run alive from yesterday keeps its length.
        ({"2026-01-05": 1800, "2026-01-06": 1800}, 2),
        ({"2026-01-06": 1800}, 1),
        ({"2026-01-04": 1800}, 0),
        ({"2026-01-06": 60, "2026-01-07": 1800}, 1),
        ({}, 0),
    ],
)
def test_streak_days(daily, expected: int) -> None:
    assert stats.streak_days(daily, today=date(2026, 1, 7)) == expected


def test_streak_days_honours_a_custom_threshold() -> None:
    # 只读了 60 秒：阈值 60 算 1 天，阈值 120 就算 0 天
    daily = {"2026-01-07": 60}
    assert stats.streak_days(daily, min_seconds=60, today=date(2026, 1, 7)) == 1
    assert stats.streak_days(daily, min_seconds=120, today=date(2026, 1, 7)) == 0


# ---------------------------------------------------------------------- heatmap
# 参数化：5 个等级字符的分界点
@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0, "·"),
        (1, "░"),
        (1199, "░"),
        (1200, "▒"),
        (2399, "▒"),
        (2400, "▓"),
        (3599, "▓"),
        (3600, "█"),
        (99999, "█"),
    ],
)
def test_heat_char_boundaries(seconds: int, expected: str) -> None:
    assert stats.heat_char(seconds) == expected


def test_heatmap_is_oldest_first_and_fixed_length() -> None:
    # 取最近 3 天
    cells = stats.heatmap(DAILY, days=3, today=date(2026, 1, 7))
    # 最旧在前
    assert [cell[0] for cell in cells] == ["2026-01-05", "2026-01-06", "2026-01-07"]
    # 秒数与字符也对得上
    assert [cell[2] for cell in cells] == [200, 300, 400]
    assert [cell[1] for cell in cells] == ["░", "░", "░"]
    # 即使没有任何数据也补齐固定长度
    assert len(stats.heatmap({}, days=30, today=date(2026, 1, 7))) == 30


def test_heatmap_weeks_is_a_monday_first_grid() -> None:
    # 二维网格：7 行（周一..周日）
    grid = stats.heatmap_weeks(DAILY, days=3, today=date(2026, 1, 7))
    assert len(grid) == 7
    assert all(len(row) == 1 for row in grid)
    # 第一行是周一，对应 1 月 5 日
    assert grid[0][0] is not None and grid[0][0][0] == "2026-01-05"  # Monday
    assert grid[1][0] is not None and grid[1][0][0] == "2026-01-06"
    assert grid[2][0] is not None and grid[2][0][0] == "2026-01-07"  # Wednesday
    # 周四到周日都在窗口外，用 None 占位
    assert grid[3] == [None]  # outside the window: left blank


def test_heatmap_weeks_pads_to_whole_weeks() -> None:
    # 取 10 天：会横跨两周，所以每行两列
    grid = stats.heatmap_weeks(DAILY, days=10, today=date(2026, 1, 7))
    assert all(len(row) == 2 for row in grid)
    # 第一列是上一周的周一（12 月 29 日），第二列是本周一
    assert grid[0][0] is not None and grid[0][0][0] == "2025-12-29"
    assert grid[0][1] is not None and grid[0][1][0] == "2026-01-05"
    # 周三那一行的最后一列是今天
    assert grid[2][-1] is not None and grid[2][-1][0] == "2026-01-07"


# --------------------------------------------------------------- book and metric
def test_book_totals_sorted_by_time() -> None:
    # 五本书：正常的两本、没读过的一本、缺字段的一本、进度结构坏的一本
    document = {
        "books": {
            "a": {"title": "Short", "progress": {"total_time_seconds": 60}},
            "b": {"title": "Long", "progress": {"total_time_seconds": 600}},
            "c": {"title": "Untouched", "progress": {"total_time_seconds": 0}},
            "d": {"progress": {}},
            "e": {"title": "Broken", "progress": "nonsense"},
        }
    }
    # 只保留读过的，且按时长降序
    assert stats.book_totals(document) == [("b", "Long", 600), ("a", "Short", 60)]


def test_compute_metrics(achievements_document, monkeypatch) -> None:
    # 直接给定生词数，避免依赖真实的笔记本
    metrics = stats.compute_metrics(achievements_document, vocab_size=7)
    assert metrics["books_read"] == 2  # both books have a session
    assert metrics["finished"] == 1
    assert metrics["total_time"] == 7800
    assert metrics["night_time"] == 7200  # 22:00 -> 02:00
    # 跨午夜那场会话总长 4 小时
    assert metrics["single_session"] == 14400
    assert metrics["translations"] == 3
    assert metrics["vocab_count"] == 7
    # 指标集合固定，成就条件只能引用这些
    assert set(metrics) == {
        "books_read",
        "total_time",
        "night_time",
        "streak",
        "finished",
        "vocab_count",
        "translations",
        "single_session",
    }


def test_compute_metrics_tolerates_a_damaged_session_list(
    achievements_document,
) -> None:
    # 把 bbb 的 sessions 换成字符串（坏数据）
    achievements_document["books"]["bbb"]["progress"]["sessions"] = "broken"
    metrics = stats.compute_metrics(achievements_document, vocab_size=0)
    assert metrics["books_read"] == 1  # only the intact book counts
    # 好书的夜间时长照常统计
    assert metrics["night_time"] == 7200


def test_unlocked_ids_accepts_every_historical_shape() -> None:
    # 正常格式：字典与纯字符串混排，没有 id 的被跳过
    assert stats.unlocked_ids(
        {"achievements": {"unlocked": [{"id": "a"}, {"name": "skip"}, "b"]}}
    ) == ["a", "b"]
    # 手写格式：{"id": true}
    assert stats.unlocked_ids({"achievements": {"unlocked": {"c": True}}}) == ["c"]
    # 空列表与完全没有 achievements 段落
    assert stats.unlocked_ids({"achievements": {"unlocked": []}}) == []
    assert stats.unlocked_ids({}) == []


def test_bump_translations() -> None:
    # 空文档里累加：默认 +1
    document = {}
    assert stats.bump_translations(document) == 1
    # 再加 5 次
    assert stats.bump_translations(document, 5) == 6
    # 结果确实写进了文档
    assert document["stats"]["translations"] == 6


# --------------------------------------------------------------- celebration bits
# 参数化：进度条的取整与越界处理
@pytest.mark.parametrize(
    "current, required, width, expected",
    [
        (0, 100, 4, "░░░░"),
        (50, 100, 4, "██░░"),
        (100, 100, 4, "████"),
        (150, 100, 4, "████"),
        (100, 100, 14, "█" * 14),
        (1, 0, 2, "██"),  # a zero target counts as reached
    ],
)
def test_progress_bar(current: int, required: int, width: int, expected: str) -> None:
    assert stats.progress_bar(current, required, width) == expected


def test_celebrate_prints_a_banner() -> None:
    # 假输出流；关掉动画和响铃，只验证那行横幅
    stream = io.StringIO()
    banner = stats.celebrate(
        {"id": "x", "name": "测试成就", "desc": "描述"},
        stream=stream,
        animate=False,
        ring=False,
    )
    assert banner == "🏆 Achievement Unlocked: 测试成就  —  描述"
    # 流里恰好写入了这行 + 换行
    assert stream.getvalue() == banner + "\n"


def test_celebrate_animates_and_rings() -> None:
    # animate=True + delay=0：不打乱测试节奏但会写动画帧
    stream = io.StringIO()
    stats.celebrate({"id": "x", "name": "N"}, stream=stream, animate=True, delay=0.0)
    written = stream.getvalue()
    # 有响铃字符和星号帧
    assert "\a" in written and "★" in written
    # 最后一帧也写了
    assert stats.CELEBRATION_FRAMES[-1] in written


def test_celebrate_survives_a_closed_stream() -> None:
    # 造一个写入必抛 OSError 的流，模拟终端已关闭
    class Boom(io.StringIO):
        def write(self, text):  # type: ignore[override]
            raise OSError("closed")

    # 不该抛异常，仍然返回横幅
    assert stats.celebrate({"id": "x"}, stream=Boom(), animate=True, delay=0.0).startswith("🏆")


def test_celebrate_uses_the_id_without_a_name() -> None:
    # 没有 name 时用 id 兜底
    stream = io.StringIO()
    assert stats.celebrate(
        {"id": "first_book"}, stream=stream, animate=False, ring=False
    ) == "🏆 Achievement Unlocked: first_book"


# -------------------------------------------------------------- the stats report
def test_build_report_is_complete_and_json_serialisable(achievements_document) -> None:
    # 固定"今天"为 1 月 2 日，把统计结果钉死
    report = stats.build_report(
        achievements_document, today=date(2026, 1, 2), settings=config.load_config()
    )
    assert report["today"] == "2026-01-02"
    assert report["total_seconds"] == 7800
    # 7800 秒 = 2 小时 10 分钟
    assert report["total"] == "2小时10分钟"
    assert report["today_seconds"] == 3000
    assert report["week_seconds"] == 6600
    assert report["month_seconds"] == 6600
    # 默认每日目标 60 分钟
    assert report["daily_goal_seconds"] == 3600
    assert report["goal_met"] is False  # 3000 seconds against a one hour goal
    assert report["books_read"] == 2
    assert report["finished_books"] == 1
    assert report["translations"] == 3
    assert report["night_seconds"] == 7200
    assert report["longest_session_seconds"] == 14400
    assert report["streak_min_seconds"] == stats.STREAK_SECONDS
    assert report["achievements"]["total"] == 48
    # 每本书的累计时长（按降序）
    assert report["books"] == [
        {"id": "aaa", "title": "Read a lot", "seconds": 7200},
        {"id": "bbb", "title": "Started", "seconds": 600},
    ]
    # 每日桶与热力图
    assert report["daily"] == {"2026-01-01": 3600, "2026-01-02": 3000}
    assert len(report["heatmap"]) == stats.HEATMAP_DAYS
    assert set(report["heatmap"][0]) == {"date", "seconds", "level"}
    assert len(report["heatmap_grid"]) == 7
    # 整份报告必须能 JSON 序列化（这是 --json 的前提）
    assert json.loads(json.dumps(report))["total_seconds"] == 7800


def test_build_report_reports_an_unreached_goal(achievements_document) -> None:
    # 目标 120 分钟，今天只读了 3000 秒：没达标
    config.set("stats.daily_goal_minutes", 120)
    report = stats.build_report(
        achievements_document, today=date(2026, 1, 2), settings=config.load_config()
    )
    assert report["daily_goal_seconds"] == 7200
    assert report["goal_met"] is False


def test_build_report_reports_a_reached_goal(achievements_document) -> None:
    # 目标 30 分钟（1800 秒），今天 3000 秒：达标
    config.set("stats.daily_goal_minutes", 30)
    report = stats.build_report(
        achievements_document, today=date(2026, 1, 2), settings=config.load_config()
    )
    assert report["daily_goal_seconds"] == 1800
    assert report["goal_met"] is True


def test_build_report_without_a_goal(achievements_document) -> None:
    # 目标设 0 表示不设目标
    config.set("stats.daily_goal_minutes", 0)
    report = stats.build_report(
        achievements_document, today=date(2026, 1, 2), settings=config.load_config()
    )
    assert report["daily_goal_seconds"] == 0
    # 没设目标就不算"达标"
    assert report["goal_met"] is False


def test_build_report_of_an_empty_library(isolated_home) -> None:
    # 全新环境：所有数字为 0/空，但结构必须完整
    report = stats.build_report(
        library.load_library(), today=date(2026, 1, 2), settings=config.load_config()
    )
    assert report["total_seconds"] == 0
    assert report["books"] == []
    assert report["achievements"] == {"unlocked": [], "unlocked_count": 0, "total": 48}
    # 带生成时间
    assert report["generated_at"]




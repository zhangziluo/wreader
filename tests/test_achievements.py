"""Tests for :mod:`wreader.achievements` — the event log and the unlock check.

Everything here stays offline and terminal free: the state file lives in the
throwaway ``$WREADER_HOME`` from ``conftest`` and the definitions are injected.
"""

# 延迟求值类型注解
from __future__ import annotations

# 构造状态文件内容
import json
# 注入固定时间，让日期相关断言可预测
from datetime import datetime
# 类型注解：fixture 的返回类型写在属性里
from typing import Any, Dict, List

# pytest.raises / parametrize
import pytest

# 被测模块 + 书库（造旧数据用）与 stats（定义加载）
from wreader import achievements, library, stats


# ------------------------------------------------------------------ word counting
def test_count_words_counts_cjk_characters_and_latin_tokens() -> None:
    # 中文：一个字算一个；英文：一个 token 算一个
    assert achievements.count_words("你好世界") == 4
    assert achievements.count_words("hello world") == 2
    # 混排：两种口径相加
    assert achievements.count_words("你好 world") == 3


def test_count_words_ignores_punctuation_digits_and_spaces() -> None:
    # 标点、数字、空白都不计入（规格只认汉字与英文单词）
    assert achievements.count_words("你好，world! 123") == 3
    assert achievements.count_words("   ") == 0


def test_count_words_tolerates_non_text() -> None:
    # 非字符串（None / 数字）按 0 处理，不要抛异常
    assert achievements.count_words(None) == 0  # type: ignore[arg-type]
    assert achievements.count_words(123) == 0  # type: ignore[arg-type]


# ------------------------------------------------------------------ line ranges
def test_merge_ranges_sorts_merges_and_drops_empties() -> None:
    # 重叠、(5,9) 与 (3,4) 都要并进 (0,9)；(12,20) 独立；(9,9) 是空区间被丢掉
    assert achievements.merge_ranges([(0, 5), (5, 9), (12, 20), (3, 4), (9, 9)]) == [
        (0, 9),
        (12, 20),
    ]


def test_uncovered_words_counts_a_range_once() -> None:
    lines = ["你好世界", "hello there friend"]
    # 第一次读：4 个汉字 + 3 个单词
    words, counted = achievements.uncovered_words(lines, [], 0, 2)
    assert words == 7
    # 区间被记下来了（半开区间 [0, 2)）
    assert counted == [(0, 2)]


def test_uncovered_words_counts_nothing_on_a_reread() -> None:
    lines = ["你好世界", "hello there friend"]
    # 同一段再读一次：一个新字都不加（这就是"按行号去重"）
    words, counted = achievements.uncovered_words(lines, [(0, 2)], 0, 2)
    assert words == 0
    assert counted == [(0, 2)]


def test_uncovered_words_counts_only_the_new_part_of_an_overlap() -> None:
    lines = ["你好世界", "hello there friend"]
    # 只统计过第 0 行，第二轮读 0..2：只该算第 1 行的 3 个单词
    words, counted = achievements.uncovered_words(lines, [(0, 1)], 0, 2)
    assert words == 3
    assert counted == [(0, 2)]


def test_uncovered_words_clamps_to_the_text() -> None:
    lines = ["你好"]
    # 右端越界（读到第 99 行）不该 IndexError，也不该算进不存在的字
    words, counted = achievements.uncovered_words(lines, [], -5, 99)
    assert words == 2
    assert counted == [(0, 1)]


# ------------------------------------------------------------------ weekend rule
@pytest.mark.parametrize(
    "start, end, seconds, expected_day, expected_seconds",
    [
        # 周六 10:00-12:00：整段都算周末
        ("2026-09-26T10:00:00", "2026-09-26T12:00:00", 7200, "2026-09-26", 7200),
        # 周五 22:00 跨到周六 01:00：记在结束那天（周六）
        ("2026-09-25T22:00:00", "2026-09-26T01:00:00", 10800, "2026-09-26", 10800),
        # 周日整天
        ("2026-09-27T09:00:00", "2026-09-27T10:00:00", 3600, "2026-09-27", 3600),
        # 周三：不算周末
        ("2026-09-23T10:00:00", "2026-09-23T11:00:00", 3600, "", 0),
        # 时间戳坏掉：不记
        ("", "", 3600, "", 0),
        # 时长为 0：不记
        ("2026-09-26T10:00:00", "2026-09-26T12:00:00", 0, "", 0),
    ],
)
def test_weekend_seconds_attributes_the_session(
    start: str, end: str, seconds: int, expected_day: str, expected_seconds: int
) -> None:
    # 返回 (记到哪一天, 多少秒)；工作日只回空串
    assert achievements.weekend_seconds(start, end, seconds) == (
        expected_day,
        expected_seconds,
    )


# ------------------------------------------------------------------ state file
def test_empty_state_has_every_section() -> None:
    state = achievements.empty_state()
    # 结构固定：调用方不必到处 setdefault
    assert state["version"] == achievements.STATE_VERSION
    assert state["unlocked"] == []
    assert state["counters"] == {}
    assert state["metrics"]["days_opened"] == []
    assert state["metrics"]["words_read"] == 0
    assert state["books"] == {}


def test_save_and_load_state_round_trip(isolated_home) -> None:
    # 造一份内容齐全的状态
    state = achievements.empty_state()
    state["unlocked"] = [
        {"id": "x", "name": "X", "unlocked_at": "2026-01-01T00:00:00"}
    ]
    state["counters"]["daily_open"] = 3
    state["metrics"]["days_opened"] = ["2026-01-01"]
    state["books"]["b1"] = {"words": 42, "counted": [[0, 3]]}
    # 落盘：默认写进数据目录
    path = achievements.save_state(state)
    assert path == achievements.state_path()
    # 文件是纯文本 JSON，用户能手改、能备份
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["unlocked"][0]["name"] == "X"
    # 读回来逐项一致
    back = achievements.load_state()
    assert achievements.unlocked_ids(back) == ["x"]
    assert back["counters"]["daily_open"] == 3
    assert back["metrics"]["days_opened"] == ["2026-01-01"]
    assert back["books"]["b1"] == {"words": 42, "counted": [[0, 3]]}


def test_load_state_is_empty_on_a_fresh_install(isolated_home) -> None:
    # 全新环境：状态文件还不存在，读出来是空状态（而不是报错）
    assert achievements.state_path().is_file() is False
    state = achievements.load_state()
    assert state["unlocked"] == []
    # 只读不写：不碰盘上不存在的文件
    assert achievements.state_path().is_file() is False


def test_load_state_rejects_broken_json(isolated_home) -> None:
    target = achievements.state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{oops", encoding="utf-8")
    # 坏文件明确报错，由调用方决定怎么办
    with pytest.raises(achievements.AchievementsError) as excinfo:
        achievements.load_state()
    assert achievements.STATE_FILENAME in str(excinfo.value)


def test_load_state_normalises_hand_edited_values(isolated_home) -> None:
    target = achievements.state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                # 老的"映射式"解锁写法
                "unlocked": {"legacy": True},
                # 计数写成字符串、还有无法转换的坏值
                "counters": {"daily_open": "7", "bad": "x"},
                "metrics": {
                    # 重复日期、混进数字、负数、字符串秒数
                    "days_opened": ["2026-01-02", "2026-01-02", 5],
                    "early_open": "1",
                    "weekend_seconds": {"2026-01-03": "60"},
                    "words_read": -3,
                },
                # 倒挂的区间、非区间的垃圾
                "books": {"b": {"words": "10", "counted": [[5, 3], [0, 2], "junk"]}},
            }
        ),
        encoding="utf-8",
    )
    state = achievements.load_state()
    # 解锁 id 从映射的键来
    assert achievements.unlocked_ids(state) == ["legacy"]
    # 计数转 int，坏值退成 0
    assert state["counters"] == {"daily_open": 7, "bad": 0}
    # 日期去重排序
    assert state["metrics"]["days_opened"] == ["2026-01-02", "5"]
    assert state["metrics"]["early_open"] == 1
    # 负数夹回 0
    assert state["metrics"]["words_read"] == 0
    # 倒挂区间被丢掉，只留有效的
    assert state["books"]["b"] == {"words": 10, "counted": [[0, 2]]}


def test_load_state_seeds_once_from_the_legacy_library_block(isolated_home) -> None:
    # 老版本把解锁记录写在 library.json 里
    document = library.load_library()
    document["achievements"] = {
        "unlocked": [
            {"id": "old", "name": "老成就", "unlocked_at": "2026-01-01T00:00:00"}
        ],
        "progress": {},
    }
    library.save_library(document)
    assert achievements.state_path().is_file() is False
    # 第一次读：迁移过来（名字与时间戳都保留）
    seeded = achievements.load_state()
    assert achievements.unlocked_ids(seeded) == ["old"]
    assert seeded["unlocked"][0]["name"] == "老成就"
    # 迁移只做一次：写盘后再把索引清空，也不该影响已迁移的记录
    achievements.save_state(seeded)
    document["achievements"]["unlocked"] = []
    library.save_library(document)
    assert achievements.unlocked_ids(achievements.load_state()) == ["old"]


# ------------------------------------------------------------------ events
def test_record_event_tracks_days_and_the_early_hour() -> None:
    state = achievements.empty_state()
    # 同一天打开两次：算两次"打开"，但只算一天
    achievements.record_event(state, "daily_open", {}, now=datetime(2026, 9, 23, 6, 30))
    achievements.record_event(state, "daily_open", {}, now=datetime(2026, 9, 23, 20, 0))
    assert state["counters"]["daily_open"] == 2
    assert state["metrics"]["days_opened"] == ["2026-09-23"]
    # 06:30 落在 05:00-07:00，置位
    assert state["metrics"]["early_open"] == 1


def test_record_event_leaves_the_early_flag_alone_after_seven() -> None:
    state = achievements.empty_state()
    # 08:00 打开：不算"清晨第一眼"，但日期照记
    achievements.record_event(state, "daily_open", {}, now=datetime(2026, 9, 23, 8, 0))
    assert state["metrics"]["early_open"] == 0
    assert state["metrics"]["days_opened"] == ["2026-09-23"]


def test_record_event_rejects_an_unknown_name() -> None:
    # 事件名写错要立刻报出来，不能静默丢掉
    with pytest.raises(achievements.AchievementsError):
        achievements.record_event(achievements.empty_state(), "nope")


def test_record_event_folds_the_session_into_the_weekend_bucket() -> None:
    state = achievements.empty_state()
    achievements.record_event(
        state,
        "session_end",
        {
            "seconds": 1800,
            "started": "2026-09-26T10:00:00",
            "ended": "2026-09-26T10:30:00",
        },
    )
    # 周六的时长进当天的桶
    assert state["metrics"]["weekend_seconds"] == {"2026-09-26": 1800}
    assert state["counters"]["session_end"] == 1


def test_record_event_counts_imported_books() -> None:
    state = achievements.empty_state()
    # book_add 按本次导入的本数累加（不是每次加 1）
    achievements.record_event(state, "book_add", {"count": 3})
    achievements.record_event(state, "book_add", {})
    assert state["counters"]["book_add"] == 4


def test_record_event_counts_words_only_once_per_range() -> None:
    state = achievements.empty_state()
    payload = {"book_id": "b", "lines": ["你好世界"], "ranges": [(0, 1)]}
    # 同一段读两遍：字数只算一次（按行号区间去重）
    achievements.record_event(state, "progress_update", payload)
    achievements.record_event(state, "progress_update", payload)
    assert state["metrics"]["words_read"] == 4
    assert state["books"]["b"] == {"words": 4, "counted": [[0, 1]]}


# ------------------------------------------------------------------ check_achievements
# 一份测试专用的定义表：三条覆盖两个分类，其中一条是隐藏成就
@pytest.fixture
def achievement_defs() -> "list[dict[str, Any]]":
    """A tiny definition list with categories, so tests never touch the shipped file."""
    return [
        {
            "id": "early",
            "name": "清晨第一眼",
            "desc": "在 05:00-07:00 期间首次打开",
            "condition": "early_open >= 1",
            "category": "阅读习惯",
            "secret": False,
        },
        {
            "id": "weekend",
            "name": "周末战士",
            "desc": "周六或周日累计阅读 3 小时",
            "condition": "weekend_time >= 10800",
            "category": "阅读习惯",
            "secret": False,
        },
        {
            "id": "shelf",
            "name": "书库初成",
            "desc": "书库里添加第 1 本书",
            "condition": "library_books >= 1",
            "category": "数据积累",
            "secret": True,
        },
    ]


# 一份最小的书库文档：一本书、没有会话、没有解锁记录
def make_document() -> "dict[str, Any]":
    """Return a minimal library document with a single book in it."""
    return {
        "books": {"b1": {"title": "B", "progress": {"sessions": []}}},
        "stats": {"daily_read_time": {}},
        "achievements": {"unlocked": [], "progress": {}},
    }


def test_check_achievements_unlocks_and_persists(isolated_home, achievement_defs) -> None:
    # 清晨打开一次：early（清晨）与 shelf（书库非空）都该解锁，顺序同定义顺序
    newly = achievements.check_achievements(
        "daily_open",
        {},
        definitions=achievement_defs,
        document=make_document(),
        now=datetime(2026, 9, 23, 6, 0),
    )
    assert [entry["id"] for entry in newly] == ["early", "shelf"]
    # 每条都带解锁时间戳
    assert all(entry["unlocked_at"] == "2026-09-23T06:00:00" for entry in newly)
    # 状态文件被创建，解锁记录写在里面
    assert achievements.state_path().is_file()
    saved = achievements.load_state()
    assert achievements.unlocked_ids(saved) == ["early", "shelf"]
    # 计数与日期也记下来了
    assert saved["counters"]["daily_open"] == 1
    assert saved["metrics"]["days_opened"] == ["2026-09-23"]
    # 顺带刷新了进度快照
    assert saved["progress"]["weekend"] == {"current": 0, "required": 10800}


def test_check_achievements_leaves_unreached_ones_locked(isolated_home, achievement_defs) -> None:
    # 深夜打开、书库为空：只看书库那条能不能达标
    document = make_document()
    document["books"] = {}
    newly = achievements.check_achievements(
        "daily_open", {}, definitions=achievement_defs, document=document,
        now=datetime(2026, 9, 23, 23, 0),
    )
    assert newly == []


def test_check_achievements_is_idempotent(isolated_home, achievement_defs) -> None:
    payload = {"seconds": 10800, "started": "2026-09-26T10:00:00", "ended": "2026-09-26T13:00:00"}
    # 第一次：周末战士（周六累计 3 小时）
    first = achievements.check_achievements(
        "session_end", payload, definitions=achievement_defs, document=make_document(),
        now=datetime(2026, 9, 26, 13, 0),
    )
    assert "weekend" in [entry["id"] for entry in first]
    # 第二次同样的会话：不再重复"解锁"
    second = achievements.check_achievements(
        "session_end", payload, definitions=achievement_defs, document=make_document(),
        now=datetime(2026, 9, 26, 13, 5),
    )
    assert second == []
    # 但事件本身照样累加（计数是计数，解锁是解锁）
    saved = achievements.load_state()
    assert saved["counters"]["session_end"] == 2
    assert saved["metrics"]["weekend_seconds"] == {"2026-09-26": 21600}


def test_check_achievements_rejects_an_unknown_event() -> None:
    # 事件名不在 EVENTS 里：立刻报错，不写任何状态
    with pytest.raises(achievements.AchievementsError):
        achievements.check_achievements("nope")


def test_check_achievements_counts_words_once_per_session(isolated_home) -> None:
    # 一条按字数解锁的定义
    definitions = [
        {
            "id": "words",
            "name": "万字户",
            "desc": "累计阅读 1 万字",
            "condition": "words_read >= 8",
            "category": "数据积累",
        }
    ]
    payload = {
        "book_id": "b1",
        "seconds": 60,
        "started": "2026-09-23T10:00:00",
        "ended": "2026-09-23T10:01:00",
        "lines": ["你好世界", "hello world"],
        "ranges": [(0, 2)],
    }
    # 第一次会话：6 个字 → 未达标
    assert (
        achievements.check_achievements(
            "session_end", payload, definitions=definitions, document=make_document()
        )
        == []
    )
    # 第二次会话读同一段：一个字都不加，仍未达标（去重生效）
    assert (
        achievements.check_achievements(
            "session_end", payload, definitions=definitions, document=make_document()
        )
        == []
    )
    # 第三次读新的一段：凑满 8 个字 → 解锁
    extended = dict(payload, ranges=[(0, 3)], lines=["你好世界", "hello world", "新的文字"])
    newly = achievements.check_achievements(
        "session_end", extended, definitions=definitions, document=make_document(),
        now=datetime(2026, 9, 23, 11, 0),
    )
    assert [entry["id"] for entry in newly] == ["words"]
    assert achievements.load_state()["metrics"]["words_read"] == 10


# ------------------------------------------------------------------ definitions
def test_packaged_conditions_only_use_metrics_that_exist() -> None:
    # 条件里写了 compute_metrics 不产出的指标，那条成就就永远解锁不了 —— 这里拦下来
    metrics = achievements.compute_metrics(make_document(), achievements.empty_state())
    for achievement in stats.load_achievements():
        metric, _, _ = stats.parse_condition(achievement["condition"])
        assert metric in metrics, "{} 用了未知指标 {}".format(
            achievement["id"], metric
        )


# ------------------------------------------------------------------ listing
def test_list_achievements_reports_category_progress_and_secret(
    isolated_home, achievement_defs
) -> None:
    rows = achievements.list_achievements(make_document(), definitions=achievement_defs)
    # 排序按 CATEGORY_ORDER：阅读习惯 在 数据积累 之前，同类保持定义顺序
    assert [row["id"] for row in rows] == ["early", "weekend", "shelf"]
    # 每条都带指标名、当前值与目标值（CLI 画进度条要用）
    assert rows[0]["metric"] == "early_open"
    assert rows[0]["current"] == 0
    assert rows[0]["required"] == 1
    assert rows[0]["unlocked"] is False
    # secret 原样透传（隐藏成就的文案由 CLI 决定怎么遮）
    assert rows[2]["secret"] is True
    # 书库非空：这条已经达标（虽然还没被"解锁"事件触发过）
    assert rows[2]["current"] == 1 and rows[2]["required"] == 1


def test_list_achievements_marks_unlocked_with_its_stamp(
    isolated_home, achievement_defs
) -> None:
    # 先触发一次解锁
    achievements.check_achievements(
        "daily_open",
        {},
        definitions=achievement_defs,
        document=make_document(),
        now=datetime(2026, 9, 23, 6, 0),
    )
    rows = achievements.list_achievements(make_document(), definitions=achievement_defs)
    early = next(row for row in rows if row["id"] == "early")
    assert early["unlocked"] is True
    assert early["unlocked_at"] == "2026-09-23T06:00:00"


def test_list_achievements_uses_a_fallback_category(isolated_home) -> None:
    # 定义里没有 category：退回 stats.DEFAULT_CATEGORY，而不是崩
    rows = achievements.list_achievements(
        make_document(),
        definitions=[
            {"id": "x", "name": "X", "desc": "", "condition": "library_books >= 1"}
        ],
    )
    assert rows[0]["category"] == stats.DEFAULT_CATEGORY

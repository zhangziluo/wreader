"""Tests for :mod:`wreader.cli` — argument parsing, dispatch and exit codes.

Every command runs against the throwaway ``$WREADER_HOME`` from ``conftest``, so
nothing here touches the network or the real ``~/.wreader``.
"""

# 延迟求值类型注解
from __future__ import annotations

# 手工构造 Namespace 来测 argparse 覆盖不到的路径
import argparse
# 验证 stats --json 的输出
import json
# 摘掉成就解锁横幅（节日等日期相关的副作用）
import re
# 给 save_session 传固定时间
from datetime import datetime
# 路径断言
from pathlib import Path

# pytest.raises
import pytest

# 被测模块 + 断言时要用到的配置/书库/成就引擎/数据搬运
from wreader import achievements, cli, config, library, transfer

# 复用 conftest 里的样例正文
from conftest import BOOK_LINES


# 成就解锁横幅（cli._report_unlocked 打的 "🏆 已解锁 …"）与命令输出无关：
# 节日（如中秋节）等条件一到就会冒出来，所以断言精确 stdout 前先摘掉这一行
_BANNER = re.compile(r"^\s*🏆 已解锁.*$", re.MULTILINE)


def _stdout(capsys) -> str:
    """Return stdout with the achievement banner removed."""
    # 先读走捕获，再删掉横幅那一行；返回的仍是原始文本（没有做去空白）
    return _BANNER.sub("", capsys.readouterr().out)


# ----------------------------------------------------------------- the parser
def test_build_parser_knows_every_command() -> None:
    parser = cli.build_parser()
    # 每个已知子命令都要能解析出来
    for command in (
        "import",
        "list",
        "search",
        "read",
        "continue",
        "stats",
        "achievements",
        "config",
        "toc",
        "prune",
        "clear",
        "data",
        "werd",
        "word",
    ):
        # 有位置参数的子命令要补上占位参数
        args = parser.parse_args([command] + _required_argument(command))
        # 解析结果里的 command 字段应当与输入一致
        assert args.command == command


def _required_argument(command: str) -> list:
    # 各子命令必需的位置参数；没有的返回空列表
    return {
        "import": ["/tmp"],
        "search": ["x"],
        "read": ["id"],
        "toc": ["id"],
        # data 还要带二级子命令与文件路径
        "data": ["export", "bundle.json"],
    }.get(command, [])


def test_data_requires_a_subcommand() -> None:
    # `werd data` 后面必须跟 export / import，否则由 argparse 报用法错误
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["data"])
    assert excinfo.value.code == 2


def test_version_flag_exits_cleanly(capsys) -> None:
    # --version 会抛 SystemExit(0) 并打印版本号
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--version"])
    assert excinfo.value.code == 0
    assert "0.1.0" in capsys.readouterr().out


def test_a_command_is_required(capsys) -> None:
    # 不带子命令时 argparse 以退出码 2 结束
    with pytest.raises(SystemExit) as excinfo:
        cli.main([])
    assert excinfo.value.code == 2


# ------------------------------------------------------------------- plumbing
def test_empty_library_lists_nothing(capsys) -> None:
    # 空书库：返回 0，并提示怎么导入
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "the library is empty" in out
    assert "library.json" in out


def test_import_then_list_then_search(capsys, home) -> None:
    # 先放一本书
    home.write_book("刘慈欣-三体.txt", BOOK_LINES)
    # 导入应当成功，并报告数量与书名
    assert cli.main(["import", str(home.root / "books")]) == 0
    out = capsys.readouterr().out
    assert "imported 1 book(s)" in out
    assert "三体" in out

    # list 里能看到这本书
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "三体" in out and "library (1 book(s))" in out

    # search 按书名能命中
    assert cli.main(["search", "三体"]) == 0
    assert "1 match(es) for '三体'" in capsys.readouterr().out


def test_import_reports_duplicates(capsys, home) -> None:
    home.write_book("三体.txt", BOOK_LINES)
    # 第一次导入
    cli.main(["import", str(home.root / "books")])
    # 清掉第一次的输出，避免干扰断言
    capsys.readouterr()
    # 第二次导入同一目录：应当被识别为重复
    assert cli.main(["import", str(home.root / "books")]) == 0
    assert "skipped 1 duplicate(s)" in capsys.readouterr().out


def test_import_of_a_missing_path_fails(capsys, tmp_path: Path) -> None:
    # 路径不存在：退出码 1，错误写到 stderr，stdout 干净
    assert cli.main(["import", str(tmp_path / "nope")]) == 1
    captured = capsys.readouterr()
    assert "error: path does not exist" in captured.err
    # 只看命令自己的输出（成就横幅可能因日期触发，不算数）
    assert _BANNER.sub("", captured.out).strip() == ""


def test_import_of_a_folder_without_books_fails(capsys, tmp_path: Path) -> None:
    # 目录存在但没有书籍文件：同样算失败
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["import", str(empty)]) == 1
    assert "no .txt/.epub file found" in capsys.readouterr().out


def test_search_without_a_match_exits_one(capsys) -> None:
    # 搜不到时退出码为 1（方便脚本判断）
    assert cli.main(["search", "zzz"]) == 1
    assert "no book matches" in capsys.readouterr().out


def test_stats_and_json(capsys) -> None:
    # 人类可读输出里应当有总时长和热力图图例
    assert cli.main(["stats"]) == 0
    out = capsys.readouterr().out
    assert "总阅读时长" in out and "强度：" in out

    # --json 输出的是同一份数据
    assert cli.main(["stats", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    # 还没有阅读记录
    assert report["total_seconds"] == 0
    # 热力图按星期几分行，固定 7 行
    assert "heatmap_grid" in report and len(report["heatmap_grid"]) == 7


def test_stats_hides_the_heatmap_when_configured(capsys) -> None:
    # 关掉热力图后只提示一行
    config.set("stats.show_heatmap", False)
    assert cli.main(["stats"]) == 0
    assert "热力图已隐藏" in capsys.readouterr().out


def test_achievements_lists_progress(capsys, monkeypatch) -> None:
    # 固定启动时刻：测试若恰好在 05:00-07:00 跑会顺手解锁"清晨第一眼"，
    # 而 1 月 1 日、春节这类日子会解锁"节日读者" —— 所以这里挑一个平平无奇的
    # 中午（2026-01-15 周四，不是任何节日）
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 1, 15, 12, 0, 0))
    # 全新环境下应当一个都没解锁
    assert cli.main(["achievements"]) == 0
    out = capsys.readouterr().out
    assert "已解锁 0/48" in out
    # 并列出未解锁项的名字
    assert "开卷有益" in out


def test_achievements_marks_one_as_done(capsys, imported, monkeypatch) -> None:
    # 延迟导入 reader，避免非 curses 平台上的导入错误
    from wreader import achievements, reader

    # 同样固定启动时刻（同样避开清晨窗口与节日，见上一个测试的说明）
    monkeypatch.setattr(cli, "_now", lambda: datetime(2026, 1, 15, 12, 0, 0))
    # 造一个 Pager 并直接保存一次 60 秒的会话
    pager = reader.Pager(list(BOOK_LINES), book_id=imported["zh"], page_height=4)
    reader.save_session(
        imported["zh"],
        pager,
        60,
        datetime(2026, 1, 1, 10, 0, 0),
        datetime(2026, 1, 1, 10, 1, 0),
    )
    # 模拟"退出阅读"：把会话交给成就引擎（正文与读过的行区间一起带上）
    achievements.check_achievements(
        "session_end",
        {
            "book_id": imported["zh"],
            "seconds": 60,
            "started": "2026-01-01T10:00:00",
            "ended": "2026-01-01T10:01:00",
            "lines": list(BOOK_LINES),
            "ranges": [(0, len(BOOK_LINES))],
        },
    )
    # 清掉可能产生的输出
    capsys.readouterr()
    # 读过一本书（开卷有益）+ 书库非空（书库初成），应当解锁 2 个
    assert cli.main(["achievements"]) == 0
    out = capsys.readouterr().out
    assert "已解锁 2/48" in out
    assert "开卷有益" in out
    assert "书库初成" in out


# --------------------------------------------------------------------- config
def _flat(text: str) -> str:
    """Drop all whitespace: rich soft wraps long lines at the console width."""
    # rich 会按终端宽度软换行，导致字符串里混入换行/空格；直接全删掉再比较
    return "".join(text.split())


def test_config_shows_the_file_path(capsys, isolated_home) -> None:
    # --path 只打印设置文件路径
    assert cli.main(["config", "--path"]) == 0
    assert _flat(_stdout(capsys)) == str(isolated_home.data / "settings.toml")


def test_config_prints_every_setting(capsys) -> None:
    # 不带参数时打印整张设置表
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    # 表格里能看到两个代表性的键
    assert "reader.page_height" in out
    assert "stats.geo_lookup" in out
    # 末尾提示了文件路径
    assert _flat(str(config.settings_path())) in _flat(out)


def test_config_reads_one_setting(capsys) -> None:
    # 只给 key：读取该设置
    assert cli.main(["config", "reader.page_height"]) == 0
    assert _stdout(capsys).strip() == "reader.page_height = 24"


# 向导的所有提问都走 cli._prompt_line，这里用一串预置答案替换它
def test_config_writes_one_setting(capsys, isolated_home) -> None:
    # 给 key + value：写入并保存
    assert cli.main(["config", "reader.page_height", "30"]) == 0
    assert "reader.page_height = 30 (saved)" in capsys.readouterr().out
    # 重新读盘确认真的写进去了
    assert config.reload().get("reader.page_height") == 30
    assert "page_height = 30" in (isolated_home.data / "settings.toml").read_text("utf-8")


def test_config_accepts_a_legacy_key(capsys) -> None:
    # 老版本的扁平键名 page_height 也能用，回显时显示规范路径
    assert cli.main(["config", "page_height", "28"]) == 0
    assert "reader.page_height = 28" in capsys.readouterr().out


def test_config_rejects_a_typo(capsys) -> None:
    # 拼错键名：退出码 1，并在 stderr 给出建议
    assert cli.main(["config", "reader.pag_height", "30"]) == 1
    err = capsys.readouterr().err
    assert "unknown setting 'reader.pag_height'" in err
    assert "did you mean 'reader.page_height'?" in err


def test_config_rejects_a_bad_value(capsys) -> None:
    # 值类型不对：同样报错
    assert cli.main(["config", "reader.page_height", "abc"]) == 1
    assert "expects an integer" in capsys.readouterr().err


def test_config_reset(capsys) -> None:
    # 先改一项，再 --reset
    config.set("reader.page_height", 40)
    assert cli.main(["config", "--reset"]) == 0
    assert "settings reset to defaults" in capsys.readouterr().out
    # 值回到默认的 24
    assert config.reload().get("reader.page_height") == 24


def test_config_warns_about_unknown_and_invalid_keys(capsys, isolated_home) -> None:
    # 手写一份既有未知键、又有类型错误值的配置
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        '[reader]\npage_height = "abc"\nnotes = "mine"\n', encoding="utf-8"
    )
    # 命令本身仍然成功，只是给两条警告
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    assert "unknown setting 'reader.notes' is ignored" in out
    assert "expects an integer" in out


def test_config_value_without_a_key_is_refused(capsys) -> None:
    # argparse cannot produce this shape, so build the namespace by hand.
    # argparse 造不出"有 value 没 key"的形状，直接手搓 Namespace
    args = argparse.Namespace(path=False, reset=False, key=None, value="30")
    assert cli.cmd_config(args) == 1
    assert "a value needs a key" in capsys.readouterr().err


# ------------------------------------------------------------ read and continue
def test_read_rejects_an_unknown_book(capsys) -> None:
    # 书 id 不存在：退出码 1
    assert cli.main(["read", "nope"]) == 1
    assert "unknown book id" in capsys.readouterr().err


def test_read_needs_a_terminal(capsys, imported) -> None:
    # 测试环境 stdin/stdout 不是 tty，所以应当提示需要交互终端
    assert cli.main(["read", imported["zh"]]) == 1
    assert "needs an interactive terminal" in capsys.readouterr().err


def test_continue_on_an_empty_library(capsys) -> None:
    # 一本都没读过：给出提示，退出码仍是 0（与空书库的 list 一致）
    assert cli.main(["continue"]) == 0
    assert "还没有阅读记录" in capsys.readouterr().out


def test_continue_lists_the_recently_read_books(capsys, imported) -> None:
    # 中文书标一个更近的阅读时间，它应当排在表格第一行
    document = library.load_library()
    document["books"][imported["zh"]]["progress"]["last_read"] = "2026-02-02T20:00:00"
    document["books"][imported["en"]]["progress"]["last_read"] = "2026-02-01T20:00:00"
    library.save_library(document)

    assert cli.main(["continue"]) == 0
    out = capsys.readouterr().out
    # 两本书的 id 都打出来了，且最近读的那本在前
    assert imported["zh"] in out and imported["en"] in out
    assert out.index(imported["zh"]) < out.index(imported["en"])


# ------------------------------------------------------------- name easter egg
@pytest.mark.parametrize("argv", [["werd"], ["word"], ["--werd"]])
def test_the_name_egg_prints_and_unlocks_the_achievement(capsys, argv) -> None:
    # 三种写法（werd werd / werd word / werd --werd）都通往同一个玩笑
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert "werd" in out
    # 解锁了就报一行（名字彩蛋是唯一能靠一条命令解锁的成就）
    assert "名字彩蛋" in out
    # 状态文件里记下了这一次彩蛋
    assert achievements.load_state()["metrics"]["eggs"] == [argv[-1].lstrip("-")]


def test_the_egg_commands_are_listed_in_the_help(capsys) -> None:
    # 彩蛋也得在 --help 里露个脸，不然没人会发现
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["--help"])
    assert excinfo.value.code == 0
    assert "werd" in capsys.readouterr().out


# ------------------------------------------------------- the achievements page
def test_achievements_counts_the_views(capsys) -> None:
    # 每翻一次成就页就记一次（成就猎人要的是"超过 10 次"）
    for _ in range(3):
        assert cli.main(["achievements"]) == 0
    capsys.readouterr()
    assert achievements.load_state()["metrics"]["achievement_views"] == 3


def test_eleven_views_unlock_the_achievement_hunter(capsys) -> None:
    # 第 11 次翻开时越过了 "> 10" 这条线
    for _ in range(11):
        assert cli.main(["achievements"]) == 0
    out = capsys.readouterr().out
    assert "成就猎人" in out
    assert achievements.load_state()["metrics"]["achievement_views"] == 11



# ------------------------------------- clearing, pruning and moving a library
def _seed_history(book_id: str, seconds: int = 900) -> None:
    """Give *book_id* a position, one session and matching global totals."""
    # 直接改索引：这是"读过一段"最省事的模拟方式（不经过 curses 前端）
    document = library.load_library()
    document["stats"]["total_read_time"] = seconds
    document["stats"]["daily_read_time"] = {"2026-02-01": seconds}
    document["books"][book_id]["progress"].update(
        {
            "current_line": 3,
            "total_time_seconds": seconds,
            "last_read": "2026-02-01T20:00:00",
            "sessions": [
                {
                    "start": "2026-02-01T19:45:00",
                    "end": "2026-02-01T20:00:00",
                    "lines_read": 3,
                }
            ],
        }
    )
    library.save_library(document)


def test_clear_empties_the_library_but_keeps_the_reading_time(capsys, imported) -> None:
    # 先攒一段时长，好验证"清空书目"不会顺手抹掉阅读成绩
    _seed_history(imported["zh"])
    # 清空前记下正文路径，一会儿要确认它没被删
    book = library.get_book(imported["zh"])
    assert book is not None
    path = Path(str(book["file_path"]))

    assert cli.main(["clear"]) == 0

    out = _stdout(capsys)
    # 报告里说清掉了几本、正文文件一并删了、成绩保住了
    assert "已清空书库：2 本书及其正文文件已删除" in out
    assert "阅读时长与成就已保留" in out
    # 索引空了，但累计时长照旧
    assert library.list_books() == []
    assert library.load_library()["stats"]["total_read_time"] == 900
    # 转换后的正文文件也跟着删了（原始电子书不归 werd 管）
    assert not path.is_file()


def test_clear_on_an_empty_library_says_so(capsys) -> None:
    # 空书库：明确说一句"本来就是空的"，退出码仍是 0
    assert cli.main(["clear"]) == 0
    assert "书库本来就是空的" in _stdout(capsys)


def test_prune_reports_the_books_whose_files_are_gone(capsys, imported) -> None:
    # 手动删掉中文书的正文，再跑 werd prune
    book = library.get_book(imported["zh"])
    assert book is not None
    Path(str(book["file_path"])).unlink()

    assert cli.main(["prune"]) == 0

    out = _stdout(capsys)
    # 输出里点名了被清理的那本书
    assert "已清理 1 个失效书目" in out
    assert imported["zh"] in out
    # 记录真的没了；另一本不受影响
    assert library.get_book(imported["zh"]) is None
    assert library.get_book(imported["en"]) is not None


def test_prune_with_nothing_to_do(capsys, imported) -> None:
    # 没失效书目：只说一句，退出码 0
    assert cli.main(["prune"]) == 0
    assert "没有失效书目" in _stdout(capsys)


def test_every_command_cleans_up_the_dead_records(capsys, imported) -> None:
    # 模拟用户在 novels 文件夹里手删正文：索引里会留下一条死记录
    book = library.get_book(imported["zh"])
    assert book is not None
    Path(str(book["file_path"])).unlink()

    # 随便跑哪条命令都会先对账一次，并给一行提示
    assert cli.main(["list"]) == 0

    out = _stdout(capsys)
    assert "已清理 1 个失效书目" in out
    # 这条命令自己的输出里也就只剩一本书了
    assert "library (1 book(s))" in out
    assert library.get_book(imported["zh"]) is None


def test_auto_prune_stays_quiet_when_nothing_is_missing(capsys, imported) -> None:
    # 没有失效书目就不该多嘴，否则每条命令都白白多一行噪音
    assert cli.main(["list"]) == 0
    assert "已清理" not in _stdout(capsys)


# ---------------------------------------------------- `werd data export|import`
def test_data_export_reports_what_went_into_the_bundle(capsys, imported, tmp_path) -> None:
    # 给中文书攒一小时（格式化后正好是 "1小时"）
    _seed_history(imported["zh"], seconds=3600)
    # 故意用还没建的子目录：导出应当自己建出来
    target = tmp_path / "nested" / "bundle.json"

    assert cli.main(["data", "export", str(target)]) == 0

    out = _stdout(capsys)
    # 摘要一行：几本书、几个成就、写到哪儿
    # （跑命令时 cli 会顺手评估一次成就，所以个数照状态文件数，不写死）
    unlocked = achievements.load_state()["unlocked"]
    assert "已导出 1 本书的阅读记录与 {} 个成就".format(len(unlocked)) in out
    # 累计时长与 `werd stats` 同一个口径（路径会被 rich 折行，改用文件本身验证）
    assert "累计时长 1小时" in out
    assert target.is_file()


def test_data_export_reports_a_directory_target(capsys, imported, tmp_path) -> None:
    # 目标是目录：一条 error 行 + 退出码 1，而不是 Python 回溯
    assert cli.main(["data", "export", str(tmp_path)]) == 1
    assert "is a directory" in capsys.readouterr().err


def test_data_import_merges_the_bundle_into_this_machine(
    capsys, imported, tmp_path
) -> None:
    # 本机攒一小时，导出成包
    _seed_history(imported["zh"], seconds=3600)
    target = tmp_path / "bundle.json"
    assert cli.main(["data", "export", str(target)]) == 0
    capsys.readouterr()

    # 再把包导回同一台机器：书 id 对得上，所以没有跳过的
    assert cli.main(["data", "import", str(target)]) == 0

    out = _stdout(capsys)
    assert "已合并 1 本书的阅读记录" in out
    assert "被跳过" not in out
    # 时长是增量相加的口径：导自己的包等于把这一小时再记一遍
    assert library.load_library()["stats"]["total_read_time"] == 7200


def test_data_import_hints_about_the_books_it_could_not_attach(
    capsys, tmp_path
) -> None:
    # 手写一个包：里面的 book_id 是本机没有的（来自另一台电脑）
    bundle = {
        "kind": transfer.BUNDLE_KIND,
        "version": transfer.BUNDLE_VERSION,
        "reading": {
            "total_read_time": 60,
            "daily_read_time": {},
            "books": {"nowhere": {"total_time_seconds": 60}},
        },
        "achievements": {},
    }
    target = tmp_path / "bundle.json"
    target.write_text(json.dumps(bundle), encoding="utf-8")

    assert cli.main(["data", "import", str(target)]) == 0

    out = _stdout(capsys)
    # 没有记录可以挂：计数为 0 并提示补一步，但全局时长照样接过来
    assert "已合并 0 本书的阅读记录" in out
    assert "1 本本机还没有的书被跳过" in out
    assert library.load_library()["stats"]["total_read_time"] == 60


def test_data_import_reports_a_missing_file(capsys, tmp_path) -> None:
    # 路径打错：error 行 + 退出码 1
    assert cli.main(["data", "import", str(tmp_path / "nope.json")]) == 1
    assert "no such data file" in capsys.readouterr().err

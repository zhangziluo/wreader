"""Tests for :mod:`wreader.cli` — argument parsing, dispatch and exit codes.

Every command runs against the throwaway ``$WREADER_HOME`` from ``conftest``, and the
translation commands run against the recording back-end, so nothing here touches
the network or the real ``~/.wreader``.
"""

# 延迟求值类型注解
from __future__ import annotations

# 手工构造 Namespace 来测 argparse 覆盖不到的路径
import argparse
# 验证 stats --json 的输出
import json
# 给 save_session 传固定时间
from datetime import datetime
# 路径断言
from pathlib import Path
# 类型注解（向导答案队列）
from typing import List

# pytest.raises
import pytest

# 被测模块 + 断言时要用到的配置/书库/翻译/生词本/笔记
from wreader import achievements, cli, config, library, notes, translator, vocab

# 复用 conftest 里的样例正文
from conftest import BOOK_LINES


# ----------------------------------------------------------------- the parser
def test_build_parser_knows_every_command() -> None:
    parser = cli.build_parser()
    # 十个已知子命令都要能解析出来
    for command in (
        "import",
        "list",
        "search",
        "read",
        "continue",
        "translate",
        "vocab",
        "stats",
        "achievements",
        "config",
        "toc",
        "notes",
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
        "translate": ["id"],
        "toc": ["id"],
        # notes 的 book_id 是可选的，所以不需要占位参数
    }.get(command, [])


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


def test_vocab_flags_parse() -> None:
    parser = cli.build_parser()
    # --page/--per-page 会被转成 int，--export 取值 anki
    args = parser.parse_args(["vocab", "--page", "3", "--per-page", "5", "--export", "anki"])
    assert (args.page, args.per_page, args.export) == (3, 5, "anki")
    # 三个布尔/字符串开关都能解析
    args = parser.parse_args(["vocab", "--review", "--search", "x", "--remove", "y"])
    assert args.review and args.search == "x" and args.remove == "y"


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
    assert captured.out == ""


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


def test_notes_without_any_notes_says_how_to_start(capsys) -> None:
    # 还一条笔记都没有：给引导语，退出码仍是 0
    assert cli.main(["notes"]) == 0
    assert "还没有笔记" in capsys.readouterr().out


def test_notes_lists_every_book_newest_first(capsys) -> None:
    # 两本书各写一条（book2 更晚），列表里都要出现
    notes.save_note("book1", "三体", "引用一", "想法一", now=datetime(2026, 1, 1, 10, 0))
    notes.save_note("book2", "活着", "引用二", "想法二", now=datetime(2026, 1, 2, 10, 0))
    assert cli.main(["notes"]) == 0
    out = capsys.readouterr().out
    assert "三体" in out and "活着" in out
    assert "book1" in out and "book2" in out
    # 表格里带条数
    assert "1" in out


def test_notes_pages_a_single_book(capsys) -> None:
    # 三条笔记：非交互（pytest 的 capsys）时不等按键，一次全打出来
    for index in range(3):
        notes.save_note(
            "book1", "三体", "引用{}".format(index), "想法{}".format(index), now=datetime(2026, 1, 1, 10, index)
        )
    assert cli.main(["notes", "book1"]) == 0
    out = capsys.readouterr().out
    # 每条之前一条 --- 分隔线，序号与时间都在
    assert out.count("---") == 3
    assert "#1" in out and "#2" in out and "#3" in out
    assert "想法2" in out


def test_notes_paging_stops_on_q(capsys, monkeypatch) -> None:
    for index in range(3):
        notes.save_note("book1", "三体", "引用{}".format(index), "想法{}".format(index))
    # 假装在真终端里（两个 isatty 都真），而且第一个按键就是 q
    monkeypatch.setattr(cli, "_paging_is_interactive", lambda: True)
    monkeypatch.setattr(cli, "_read_one_key", lambda: "q")
    assert cli.main(["notes", "book1"]) == 0
    out = capsys.readouterr().out
    # 看到第一条就退出了，后面的没打
    assert "#1" in out
    assert "#3" not in out


def test_notes_paging_needs_a_terminal_on_both_ends(monkeypatch) -> None:
    class _Tty:
        """任意一端是终端。"""

        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    # 输入是终端、输出被重定向（| less / CI 日志）：没人按键，不能等
    monkeypatch.setattr(cli.sys, "stdin", _Tty(True))
    monkeypatch.setattr(cli.sys, "stdout", _Tty(False))
    assert cli._paging_is_interactive() is False
    # 两端都是终端：才等按键
    monkeypatch.setattr(cli.sys, "stdout", _Tty(True))
    assert cli._paging_is_interactive() is True


def test_notes_export_writes_the_markdown(capsys, monkeypatch, tmp_path) -> None:
    notes.save_note("book1", "三体", "引用", "想法")
    # 把导出目录指到 tmp：绝不能往真实 ~/books 写
    monkeypatch.setattr(cli, "DEFAULT_NOTES_EXPORT_DIR", str(tmp_path))
    assert cli.main(["notes", "book1", "--export"]) == 0
    out = capsys.readouterr().out
    assert "已导出到" in out
    target = tmp_path / "notes_book1.md"
    assert target.is_file()
    assert "引用" in target.read_text(encoding="utf-8")


def test_notes_export_needs_a_book_id(capsys) -> None:
    # 不给 id 的导出没有意义：报错并给出正确用法
    assert cli.main(["notes", "--export"]) == 1
    assert "needs a book id" in capsys.readouterr().err


def test_notes_for_an_unknown_book_is_harmless(capsys) -> None:
    assert cli.main(["notes", "nope"]) == 0
    assert "还没有笔记" in capsys.readouterr().out


def test_vocab_listing_search_and_removal(capsys, notebook: Path) -> None:
    # 默认列出笔记本
    assert cli.main(["vocab"]) == 0
    assert "ephemeral" in capsys.readouterr().out

    # 每页 1 条时应当提示有两页
    assert cli.main(["vocab", "--page", "1", "--per-page", "1"]) == 0
    assert "page 1/2" in capsys.readouterr().out

    # 按释义也能搜到
    assert cli.main(["vocab", "--search", "公认"]) == 0
    assert "acknowledged" in capsys.readouterr().out

    # 搜不到返回 1
    assert cli.main(["vocab", "--search", "zzz"]) == 1
    assert "nothing in the notebook matches" in capsys.readouterr().out

    # 删除成功
    assert cli.main(["vocab", "--remove", "ephemeral"]) == 0
    assert "removed" in capsys.readouterr().out
    # 再删同一个词：失败并提示"不在笔记本里"
    assert cli.main(["vocab", "--remove", "ephemeral"]) == 1
    assert "not in the notebook" in capsys.readouterr().err


def test_vocab_of_an_empty_notebook(capsys) -> None:
    # 空笔记本：返回 0 并提示怎么标记生词
    assert cli.main(["vocab"]) == 0
    assert "the vocabulary notebook is empty" in capsys.readouterr().out


def test_vocab_export_writes_raw_tabs(capsys, notebook: Path) -> None:
    # 导出必须是"裸制表符"，不能被 rich 渲染掉
    assert cli.main(["vocab", "--export", "anki"]) == 0
    captured = capsys.readouterr()
    rows = captured.out.strip("\n").split("\n")
    # 两个词两行
    assert len(rows) == 2
    # 每行恰好两个制表符（三列）
    assert all(row.count("\t") == 2 for row in rows)
    # 统计信息写在 stderr，不污染导出的数据
    assert "exported 2 word(s)" in captured.err


def test_vocab_review_degrades_without_a_terminal(capsys, notebook: Path) -> None:
    # 非交互环境下 review 退化成"直接列出全部"
    assert cli.main(["vocab", "--review"]) == 0
    out = capsys.readouterr().out
    assert "not a terminal" in out
    assert "ephemeral" in out and "短暂的" in out


# --------------------------------------------------------------------- config
def _flat(text: str) -> str:
    """Drop all whitespace: rich soft wraps long lines at the console width."""
    # rich 会按终端宽度软换行，导致字符串里混入换行/空格；直接全删掉再比较
    return "".join(text.split())


def test_config_shows_the_file_path(capsys, isolated_home) -> None:
    # --path 只打印设置文件路径
    assert cli.main(["config", "--path"]) == 0
    assert _flat(capsys.readouterr().out) == str(isolated_home.data / "settings.toml")


def test_config_prints_every_setting(capsys) -> None:
    # 不带参数时打印整张设置表
    assert cli.main(["config"]) == 0
    out = capsys.readouterr().out
    # 表格里能看到两个代表性的键
    assert "reader.page_height" in out
    assert "translator.backend" in out
    # 末尾提示了文件路径
    assert _flat(str(config.settings_path())) in _flat(out)


def test_config_reads_one_setting(capsys) -> None:
    # 只给 key：读取该设置
    assert cli.main(["config", "reader.page_height"]) == 0
    assert capsys.readouterr().out.strip() == "reader.page_height = 24"


def test_config_translate_wizard_saves_the_engine_and_keys(monkeypatch, capsys) -> None:
    """`werd config translate` 走一遍向导：选引擎 -> 填密钥 -> 落盘。"""
    # 序号 2 = 百度（菜单按 translate.engine_names() 的顺序）
    _answer_with(monkeypatch, ["2", "my-appid", "my-secret"])
    assert cli.main(["config", "translate"]) == 0
    out = capsys.readouterr().out
    # 菜单里列出所有引擎，且当前引擎被标记
    assert "选择翻译引擎" in out
    assert "百度翻译" in out
    # 两个密钥都写进了 [translate]
    settings = config.reload()
    assert settings.get("translate.engine") == "baidu"
    assert settings.get("translate.baidu_appid") == "my-appid"
    assert settings.get("translate.baidu_secret") == "my-secret"
    # 结算时自查一遍并给出"已就绪"
    assert "引擎已就绪" in out


def test_config_translate_wizard_can_be_cancelled(monkeypatch, capsys) -> None:
    # 输入不认识的名字 = 取消：退出码 1，设置一点没动
    _answer_with(monkeypatch, ["nonsense"])
    assert cli.main(["config", "translate"]) == 1
    assert "已取消" in capsys.readouterr().out
    assert config.reload().get("translate.engine") == ""


def test_config_translate_wizard_accepts_an_engine_name(monkeypatch) -> None:
    # 不记序号也可以：直接打引擎名。
    # deepseek 会问三个键（key / model / url），后两个留空即保留默认
    _answer_with(monkeypatch, ["deepseek", "sk-123", "", ""])
    assert cli.main(["config", "translate"]) == 0
    settings = config.reload()
    assert settings.get("translate.engine") == "deepseek"
    assert settings.get("translate.deepseek_api_key") == "sk-123"


def test_config_translate_wizard_keeps_existing_secrets(monkeypatch) -> None:
    # 先配好百度
    _answer_with(monkeypatch, ["baidu", "a1", "s1"])
    assert cli.main(["config", "translate"]) == 0
    # 再跑一次，密钥两问都直接回车：必须保留原值（提示语承诺了"留空保留"）
    _answer_with(monkeypatch, ["", "", ""])
    assert cli.main(["config", "translate"]) == 0
    settings = config.reload()
    assert settings.get("translate.baidu_appid") == "a1"
    assert settings.get("translate.baidu_secret") == "s1"


def test_config_translate_refuses_a_value_argument(capsys) -> None:
    # 向导是交互式的，后面不该再跟一个 value
    assert cli.main(["config", "translate", "baidu"]) == 1
    assert "交互式" in capsys.readouterr().err


def test_config_translate_dotted_path_still_works(capsys) -> None:
    # 非交互的写法不受影响：werd config translate.engine deepseek
    assert cli.main(["config", "translate.engine", "deepseek"]) == 0
    assert "translate.engine = deepseek" in capsys.readouterr().out
    assert config.reload().get("translate.engine") == "deepseek"


# 向导的所有提问都走 cli._prompt_line，这里用一串预置答案替换它
def _answer_with(monkeypatch: pytest.MonkeyPatch, answers: List[str]) -> None:
    """Feed canned answers to the ``werd config translate`` wizard."""
    queue = list(answers)

    def fake_prompt(prompt: str, default: str = "") -> str:
        # 队列空了说明向导多问了一次：直接失败，别用默认值把问题藏起来
        if not queue:
            raise AssertionError("the wizard asked more questions than expected")
        answer = queue.pop(0).strip()
        # 复刻真实 _prompt_line 的语义：空输入 = 用默认值
        return answer or default

    monkeypatch.setattr(cli, "_prompt_line", fake_prompt)


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


# ------------------------------------------------------------ read and translate
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


def test_translate_rejects_an_unknown_book(capsys) -> None:
    # 翻译不存在的书同样报错
    assert cli.main(["translate", "nope"]) == 1
    assert "unknown book id" in capsys.readouterr().err


def test_translate_runs_a_whole_book(capsys, imported, backend) -> None:
    # 用假后端把整本书翻一遍
    assert cli.main(["translate", imported["zh"]]) == 0
    captured = capsys.readouterr()
    # 开头有摘要行
    assert "translating" in captured.out
    # 两章都翻成功
    assert "translated 2, skipped 0 (already cached), 0 failed" in captured.out
    # 提示了缓存目录
    assert "cache:" in captured.out
    # Two chapters were translated, so the "used the translator" achievement fires.
    # 翻了两章，触发了"用过翻译"成就，输出里有奖杯
    assert "🏆" in captured.out

    # 再翻一次：全部走缓存
    assert cli.main(["translate", imported["zh"]]) == 0
    assert "translated 0, skipped 2" in capsys.readouterr().out


def test_translate_reports_a_failed_chapter(capsys, imported, backend, home) -> None:
    # 手工塞一条"正文文件不存在"的书，制造单章失败
    document = library.load_library()
    document["books"]["blank"] = {
        "title": "Blank",
        "file_path": str(home.novels / "missing.txt"),
        "chapters": [{"title": "c", "line_start": 0}],
    }
    library.save_library(document)

    # 单章失败时整条命令返回 1，并列出失败章节
    assert cli.main(["translate", "blank"]) == 1
    captured = capsys.readouterr()
    assert "translated 0, skipped 0 (already cached), 1 failed" in captured.out
    assert "chapter 1:" in captured.err


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



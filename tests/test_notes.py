"""Tests for :mod:`wreader.notes` — the markdown store and its index.

Everything runs against the throwaway ``$WREADER_HOME`` from ``conftest``, so the
real ``~/.wreader/notes`` is never touched.  The store is plain files, so most
assertions read the file back the way a user would.
"""

# 延迟求值类型注解
from __future__ import annotations

# 起子进程做并发写入测试
import subprocess
# sys.executable：用同一个解释器起子进程
import sys
# 注入固定时间，让"序号 + 时间戳"可预测
from datetime import datetime
# 类型注解：给假的成就检查函数用
from typing import Any, Dict, List, Optional

# pytest.raises / fixture
import pytest

# 被测模块；成就引擎用来验证"笔记达人"真的解锁了
from wreader import achievements, notes


# 固定时间，让"序号 + 时间戳"可预测
MOMENT = datetime(2026, 9, 23, 15, 10, 0)


# --------------------------------------------------------------------- paths
def test_note_file_lives_under_the_data_directory(isolated_home) -> None:
    # 路径跟随数据目录：$WREADER_HOME/notes/<book_id>.md
    assert notes.notes_dir() == isolated_home.data / "notes"
    assert notes.note_file("abc123") == isolated_home.data / "notes" / "abc123.md"
    assert notes.index_file() == isolated_home.data / "notes" / "index.json"


def test_note_file_name_is_sanitised(isolated_home) -> None:
    # 手改过的怪 id 不能把路径带跑偏
    assert notes.note_file("a/b").name == "a_b.md"
    assert notes.note_file("").name == "unknown.md"


# --------------------------------------------------------------------- writing
def test_save_note_creates_the_file_with_a_header(isolated_home) -> None:
    note = notes.save_note("book1", "三体", "汪淼看到了一串数字。", "很震撼。", now=MOMENT)
    # 返回值就是这一条的结构化形式
    assert note == {
        "index": 1,
        "time": "2026-09-23 15:10",
        "quote": "汪淼看到了一串数字。",
        "content": "很震撼。",
    }
    # 文件真的落盘了，而且是给人看的 markdown
    path = notes.note_file("book1")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# 三体\n")
    assert "书籍ID: book1" in text
    assert "创建时间: 2026-09-23T15:10:00" in text
    assert "## 笔记 #1 — 2026-09-23 15:10" in text
    assert "汪淼看到了一串数字。" in text
    assert "我的想法：" in text
    assert "很震撼。" in text


def test_save_note_appends_without_overwriting(isolated_home) -> None:
    # 连写三条：序号 1/2/3，前面的内容一个都不能丢
    for index, body in enumerate(["第一条", "第二条", "第三条"], start=1):
        note = notes.save_note("book1", "书", "引用{}".format(index), body, now=MOMENT)
        assert note is not None
        assert note["index"] == index
    text = notes.note_file("book1").read_text(encoding="utf-8")
    # 三个标题都在，且顺序正确
    assert text.count("## 笔记 #") == 3
    assert text.index("第一条") < text.index("第二条") < text.index("第三条")
    # 文件头只写了一次
    assert text.count("# 书") == 1
    # 读回来也是三条
    assert [entry["index"] for entry in notes.load_notes("book1")] == [1, 2, 3]


def test_save_note_skips_an_empty_note(isolated_home) -> None:
    # 引用与正文都空：按规格"跳过不写"，也不该创建文件
    assert notes.save_note("book1", "书", "", "   \n ", now=MOMENT) is None
    assert notes.note_file("book1").is_file() is False
    assert notes.load_notes("book1") == []


def test_save_note_truncates_a_long_quote(isolated_home) -> None:
    # 超过 500 字的引用要截断并加省略号
    note = notes.save_note("book1", "书", "甲" * 600, "短评", now=MOMENT)
    assert note is not None
    assert len(note["quote"]) == notes.QUOTE_LIMIT + 3
    assert note["quote"].endswith("...")


def test_save_note_keeps_a_quote_only_note(isolated_home) -> None:
    # 只有引用、没写想法：也是一条合法笔记
    note = notes.save_note("book1", "书", "只摘抄不评论", "", now=MOMENT)
    assert note is not None
    assert note["content"] == ""
    loaded = notes.load_notes("book1")
    assert loaded[0]["quote"] == "只摘抄不评论"
    assert loaded[0]["content"] == ""


def test_save_note_works_before_the_directory_exists(isolated_home) -> None:
    # 第一次用笔记功能时 notes/ 还不存在，必须自动创建
    assert notes.notes_dir().is_dir() is False
    notes.save_note("book1", "书", "引用", "想法", now=MOMENT)
    assert notes.notes_dir().is_dir() is True


def test_save_note_survives_a_hand_edited_file_without_a_trailing_newline(
    isolated_home,
) -> None:
    # 用户手改过、末尾没有换行：追加时不能把两条粘在一起
    path = notes.note_file("book1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 书\n\n## 笔记 #1 — 2026-01-01 00:00\n\n手写的\n我的想法：\n\n无", encoding="utf-8")
    notes.save_note("book1", "书", "引用", "机器写的", now=MOMENT)
    loaded = notes.load_notes("book1")
    assert [entry["index"] for entry in loaded] == [1, 2]
    assert loaded[1]["quote"] == "引用"


# ---------------------------------------------------------------------- loading
def test_load_notes_returns_empty_for_an_unknown_book(isolated_home) -> None:
    # 没写过笔记不是错误
    assert notes.load_notes("nope") == []
    assert notes.note_count("nope") == 0


def test_load_notes_reads_multiline_content(isolated_home) -> None:
    notes.save_note("book1", "书", "第一行\n第二行", "想法一\n想法二", now=MOMENT)
    loaded = notes.load_notes("book1")
    assert loaded[0]["quote"] == "第一行\n第二行"
    assert loaded[0]["content"] == "想法一\n想法二"


def test_parse_notes_tolerates_a_hand_written_file() -> None:
    # 手写文件：没有"我的想法"分界行、还带一条 --- 分隔线
    text = (
        "# 书\n\n书籍ID: x\n\n"
        "## 笔记 #1 — 2026-01-01 00:00\n\n只有引用没有分界行\n---\n\n"
        "## 笔记 #2 — 2026-01-02 00:00\n\n引用\n我的想法：\n\n想法\n"
    )
    parsed = notes.parse_notes(text)
    assert [entry["index"] for entry in parsed] == [1, 2]
    # 第一条整段都当引用，分隔线被吃掉
    assert parsed[0]["quote"] == "只有引用没有分界行"
    assert parsed[0]["content"] == ""
    assert parsed[1]["quote"] == "引用"
    assert parsed[1]["content"] == "想法"


def test_load_notes_reports_an_unreadable_file(isolated_home) -> None:
    # 不是合法 UTF-8（比如被别的编码写过）：给出明确错误，而不是抛裸 UnicodeDecodeError
    target = notes.note_file("book1")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xfe\x00\x00bad")
    with pytest.raises(notes.NotesError) as excinfo:
        notes.load_notes("book1")
    assert "cannot read" in str(excinfo.value)


# ------------------------------------------------------------------------ index
def test_save_note_updates_the_index(isolated_home) -> None:
    # 写完一条，index.json 立刻能反映出来
    notes.save_note("book1", "三体", "引用", "这本书值得一读，节奏很紧。", now=MOMENT)
    entries = notes.list_all_notes()
    assert list(entries) == ["book1"]
    entry = entries["book1"]
    assert entry["title"] == "三体"
    assert entry["count"] == 1
    # 预览是"最后一条笔记前 50 字"
    assert entry["preview"] == "这本书值得一读，节奏很紧。"
    assert entry["last_modified"]
    # index.json 本身也是纯文本 JSON
    raw = notes.index_file().read_text(encoding="utf-8")
    assert '"title": "三体"' in raw


def test_index_preview_falls_back_to_the_quote(isolated_home) -> None:
    # 只摘抄不评论：预览用引用
    notes.save_note("book1", "书", "只有引用", "", now=MOMENT)
    assert notes.list_all_notes()["book1"]["preview"] == "只有引用"


def test_index_preview_is_a_single_line(isolated_home) -> None:
    # 正文里有换行时预览要压成一行
    notes.save_note("book1", "书", "", "第一行\n第二行", now=MOMENT)
    assert notes.list_all_notes()["book1"]["preview"] == "第一行 第二行"


def test_index_is_rebuilt_when_it_disappears(isolated_home) -> None:
    # index.json 是派生缓存：删掉它，列表页照样能自愈
    notes.save_note("book1", "三体", "引用", "想法", now=MOMENT)
    notes.index_file().unlink()
    entries = notes.list_all_notes()
    assert entries["book1"]["count"] == 1
    # 顺手把索引写回来了
    assert notes.index_file().is_file()


def test_index_rebuild_ignores_drafts(isolated_home) -> None:
    # 草稿不是笔记，不该出现在列表里
    notes.save_note("book1", "书", "引用", "想法", now=MOMENT)
    notes.save_draft("book1", "未提交的引用", "未提交的想法")
    entries = notes.list_all_notes()
    assert entries["book1"]["count"] == 1
    assert "未提交的" not in notes.index_file().read_text(encoding="utf-8")


def test_update_index_derives_the_count_from_the_file(isolated_home) -> None:
    # 三条笔记，手删掉两条之后 count 必须跟着变小（不是盲目 +1）
    for index in range(3):
        notes.save_note(
            "book1", "书", "引用{}".format(index), "想法{}".format(index), now=MOMENT
        )
    path = notes.note_file("book1")
    text = path.read_text(encoding="utf-8")
    path.write_text(text[: text.index("## 笔记 #2")], encoding="utf-8")
    entry = notes.update_index("book1")
    assert entry["count"] == 1
    assert notes.list_all_notes()["book1"]["count"] == 1


def test_update_index_keeps_the_stored_title(isolated_home) -> None:
    # 不传书名时沿用索引里已有的（避免手改标题后被覆盖掉）
    notes.save_note("book1", "三体", "引用", "想法", now=MOMENT)
    entry = notes.update_index("book1", preview="新的预览")
    assert entry["title"] == "三体"
    assert entry["preview"] == "新的预览"


def test_list_all_notes_covers_every_book(isolated_home) -> None:
    notes.save_note("book1", "第一本", "引用", "想法", now=MOMENT)
    notes.save_note("book2", "第二本", "引用", "想法", now=MOMENT)
    notes.save_note("book2", "第二本", "引用二", "想法二", now=MOMENT)
    entries = notes.list_all_notes()
    assert sorted(entries) == ["book1", "book2"]
    assert entries["book1"]["count"] == 1
    assert entries["book2"]["count"] == 2


# ----------------------------------------------------------------------- export
def test_export_notes_copies_the_markdown(isolated_home, tmp_path) -> None:
    notes.save_note("book1", "三体", "引用", "想法", now=MOMENT)
    target = tmp_path / "out" / "notes.md"
    written = notes.export_notes("book1", target)
    assert written == target
    # 内容与源文件一致
    source = notes.note_file("book1").read_text(encoding="utf-8")
    assert written.read_text(encoding="utf-8") == source


def test_export_notes_into_a_directory_uses_the_default_name(
    isolated_home, tmp_path
) -> None:
    notes.save_note("book1", "书", "引用", "想法", now=MOMENT)
    written = notes.export_notes("book1", tmp_path)
    assert written == tmp_path / "notes_book1.md"
    assert written.is_file()


def test_export_notes_rejects_a_book_without_notes(isolated_home, tmp_path) -> None:
    # 没有笔记就明确报错，而不是导出一个空文件
    with pytest.raises(notes.NotesError) as excinfo:
        notes.export_notes("nope", tmp_path / "x.md")
    assert "no notes yet" in str(excinfo.value)


# ----------------------------------------------------------------------- drafts
def test_draft_round_trip(isolated_home) -> None:
    # 草稿是"还没提交的编辑区内容"，写完能原样读回来
    notes.save_draft("book1", "选中的引用", "写到一半的想法")
    assert notes.load_draft("book1") == {"quote": "选中的引用", "text": "写到一半的想法"}
    # 草稿与正式笔记分开存放
    assert notes.draft_file("book1").is_file()
    assert notes.note_file("book1").is_file() is False


def test_empty_draft_removes_the_file(isolated_home) -> None:
    # 清空编辑区后再自动保存：草稿要消失，不能留一份空草稿
    notes.save_draft("book1", "引用", "想法")
    assert notes.save_draft("book1", "", "  ") is None
    assert notes.draft_file("book1").is_file() is False
    assert notes.load_draft("book1") == {"quote": "", "text": ""}


def test_load_draft_tolerates_a_broken_file(isolated_home) -> None:
    # 草稿坏了不能挡住面板打开
    path = notes.draft_file("book1")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe\x00bad")
    assert notes.load_draft("book1") == {"quote": "", "text": ""}


def test_clear_draft_is_harmless_when_missing(isolated_home) -> None:
    notes.clear_draft("book1")
    assert notes.draft_file("book1").is_file() is False


# ------------------------------------------------------------------- UTF-8 / 并发
def test_chinese_content_and_file_name_survive(isolated_home) -> None:
    # 中文书名、中文正文、中文标点：一律 UTF-8，读回来不能变形
    notes.save_note(
        "book1", "诡秘之主（校对版）", "“我们头顶的星空，藏着秘密。”", "好句子", now=MOMENT
    )
    text = notes.note_file("book1").read_text(encoding="utf-8")
    assert "诡秘之主（校对版）" in text
    assert "“我们头顶的星空，藏着秘密。”" in text
    assert notes.load_notes("book1")[0]["content"] == "好句子"


def test_concurrent_writes_do_not_lose_notes(isolated_home) -> None:
    """三个进程同时往同一本书写笔记：文件锁保证一条都不丢。

    这正是"在 Mac 上写完、另一台机器上接着写"那条要求的核心：串行化靠
    ``notes/index.json.lock``（POSIX ``flock``）。
    """
    # 子进程继承 WREADER_HOME（conftest 已设好），所以落在同一个数据目录
    script = (
        "import sys\n"
        "from wreader import notes\n"
        "notes.save_note('book1', '书', '引用' + sys.argv[1], '想法' + sys.argv[1])\n"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", script, str(position)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for position in range(3)
    ]
    # 等三个进程跑完（超时保护，避免 CI 卡死）
    for process in processes:
        process.communicate(timeout=120)
    assert [process.returncode for process in processes] == [0, 0, 0]
    # 三条都在、序号连续不重复，内容也没串
    stored = notes.load_notes("book1")
    assert [entry["index"] for entry in stored] == [1, 2, 3]
    assert sorted(entry["content"] for entry in stored) == ["想法0", "想法1", "想法2"]

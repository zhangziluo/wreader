"""Tests for :mod:`wreader.vocab` — the notebook file and its operations."""

# 延迟求值类型注解
from __future__ import annotations

# 直接构造 JSON 文件来测各种异常输入
import json
# 类型注解里用到 Path
from pathlib import Path

# pytest.raises / parametrize
import pytest

# 被测模块
from wreader import vocab


def test_vocab_file_lives_in_the_data_directory(isolated_home) -> None:
    # 笔记本固定放在数据目录下的 vocab.json
    assert vocab.vocab_file() == isolated_home.data / "vocab.json"


def test_missing_notebook_is_empty(isolated_home) -> None:
    # 第一次使用（文件还不存在）时应当被当作空笔记本
    assert vocab.load_vocab() == []
    assert vocab.list_words() == []
    assert vocab.word_set() == set()


def test_normalise_entry_fills_every_field() -> None:
    # 只给两个字段，规整后应当补齐全部 FIELDS 并去掉首尾空白
    entry = vocab.normalise_entry({"word": "  ephemeral ", "translation": "短暂的"})
    assert entry is not None
    # 字段名集合应当与 FIELDS 完全一致
    assert set(entry) == set(vocab.FIELDS)
    assert entry["word"] == "ephemeral"
    assert entry["translation"] == "短暂的"
    # 没给的字段补空串
    assert entry["context"] == ""
    assert entry["book"] == ""
    assert entry["date_added"] == ""


def test_normalise_entry_understands_the_legacy_field_names() -> None:
    # 旧字段名 book_title / created 应当被折叠成 book / date_added
    entry = vocab.normalise_entry(
        {"word": "w", "book_title": "Old Title", "created": "2020-01-01T00:00:00"}
    )
    assert entry is not None
    assert entry["book"] == "Old Title"
    assert entry["date_added"] == "2020-01-01T00:00:00"


# 参数化：把各种"没有单词"的输入都试一遍
@pytest.mark.parametrize("item", [{"word": "  "}, {"translation": "x"}, "nope", 5, None])
def test_normalise_entry_rejects_anything_without_a_word(item) -> None:
    # 没有有效单词的记录一律返回 None
    assert vocab.normalise_entry(item) is None


def test_load_vocab_reads_the_legacy_wrapper(isolated_home) -> None:
    # 手写一份老格式的 {"words": [...]} 文件
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    vocab.vocab_file().write_text(
        json.dumps({"words": [{"word": "w", "translation": "t"}]}), encoding="utf-8"
    )
    # 加载时应当能把里面的列表取出来
    entries = vocab.load_vocab()
    assert len(entries) == 1
    assert entries[0]["word"] == "w"


def test_load_vocab_rejects_broken_json(isolated_home) -> None:
    # 写一个语法错误的 JSON
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    vocab.vocab_file().write_text("{not json", encoding="utf-8")
    # 应当抛出 VocabError，且消息说明是 JSON 的问题
    with pytest.raises(vocab.VocabError) as excinfo:
        vocab.load_vocab()
    assert "not valid JSON" in str(excinfo.value)


def test_load_vocab_rejects_a_non_list_payload(isolated_home) -> None:
    # 合法 JSON 但顶层不是列表
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    vocab.vocab_file().write_text('"just a string"', encoding="utf-8")
    # 应当提示"必须包含一个列表"
    with pytest.raises(vocab.VocabError) as excinfo:
        vocab.load_vocab()
    assert "must contain a list" in str(excinfo.value)


def test_save_vocab_round_trips(isolated_home) -> None:
    # 一条完整记录
    words = [
        {
            "word": "w",
            "translation": "t",
            "context": "c",
            "book": "b",
            "chapter": "ch",
            "date_added": "2026-01-01T00:00:00",
        }
    ]
    vocab.save_vocab(words)
    # 文件里的内容应当与传入的一模一样
    stored = json.loads(vocab.vocab_file().read_text(encoding="utf-8"))
    assert stored == words
    # 再读回来也应当一模一样
    assert vocab.load_vocab() == words


def test_add_word_records_every_field(isolated_home) -> None:
    # 五个字段都给上，验证都落到了记录里
    entry = vocab.add_word(
        "  Ephemeral ", "短暂的", context="An ephemeral joy.", book="B", chapter="C1"
    )
    # 首尾空白被去掉，但大小写保留
    assert entry["word"] == "Ephemeral"
    assert entry["translation"] == "短暂的"
    assert entry["context"] == "An ephemeral joy."
    assert entry["book"] == "B"
    assert entry["chapter"] == "C1"
    # 时间戳自动生成
    assert entry["date_added"]
    # 磁盘上的内容与返回的对象一致
    assert vocab.load_vocab() == [entry]


def test_add_word_refreshes_instead_of_duplicating(isolated_home) -> None:
    # 先加一个词
    vocab.add_word("ephemeral", "短暂的", context="first", book="B")
    # 用不同大小写再查一次（模拟换个上下文重新查词）
    again = vocab.add_word("EPHEMERAL", "转瞬即逝的")
    # 笔记本里还是一条记录
    assert len(vocab.load_vocab()) == 1
    # 释义被刷新成新的
    assert again["translation"] == "转瞬即逝的"
    # 空的 context/book 不会覆盖已有的值
    assert again["context"] == "first"  # not overwritten by an empty argument
    assert again["book"] == "B"


def test_add_word_overwrites_the_fields_it_is_given(isolated_home) -> None:
    # 先建一条带旧值的记录
    vocab.add_word("w", "one", context="old", book="Old", chapter="Old")
    # 只更新释义、上下文、章节，不传 book
    updated = vocab.add_word("w", "two", context="new", chapter="New")
    assert updated["translation"] == "two"
    assert updated["context"] == "new"
    # 没传的字段保持旧值
    assert updated["book"] == "Old"
    assert updated["chapter"] == "New"


# 空串、纯空白、None 都应当被拒绝
@pytest.mark.parametrize("word", ["", "   ", None])
def test_add_word_needs_a_word(isolated_home, word) -> None:
    with pytest.raises(vocab.VocabError) as excinfo:
        vocab.add_word(word, "x")
    # 错误信息里要说明缺了单词
    assert "word is required" in str(excinfo.value)


def test_find_word_is_case_insensitive(isolated_home) -> None:
    added = vocab.add_word("Ephemeral", "短暂的")
    # 大小写不同、带空白都应当查到同一条
    assert vocab.find_word("ephemeral") == added
    assert vocab.find_word("  EPHEMERAL ") == added
    # 查不到与空查询都返回 None
    assert vocab.find_word("missing") is None
    assert vocab.find_word("") is None


def test_remove_word(isolated_home) -> None:
    # 先放两条
    vocab.add_word("ephemeral", "短暂的")
    vocab.add_word("acknowledged", "公认的")
    # 大写也能删掉
    removed = vocab.remove_word("EPHEMERAL")
    assert removed is not None and removed["word"] == "ephemeral"
    # 剩下的只有另一条
    assert [entry["word"] for entry in vocab.load_vocab()] == ["acknowledged"]
    # 再删一次（已不存在）与空词都返回 None
    assert vocab.remove_word("ephemeral") is None
    assert vocab.remove_word("") is None


def test_list_words_is_newest_first(isolated_home, monkeypatch) -> None:
    # 固定时间戳序列，保证排序结果可预测
    stamps = iter(["2026-01-01T00:00:00", "2026-01-02T00:00:00", "2026-01-03T00:00:00"])
    monkeypatch.setattr(vocab, "_now", lambda: next(stamps))
    # 依次加入三个词
    for word in ("first", "second", "third"):
        vocab.add_word(word, "x")
    # 默认：最新的在最前
    assert [entry["word"] for entry in vocab.list_words()] == ["third", "second", "first"]
    # newest_first=False：最旧的在前
    assert [entry["word"] for entry in vocab.list_words(newest_first=False)] == [
        "first",
        "second",
        "third",
    ]


def test_search_words_finds_words_meanings_and_context(notebook: Path) -> None:
    # 关键词会同时匹配单词、释义、例句三处
    assert [entry["word"] for entry in vocab.search_words("EPHEM")] == ["ephemeral"]
    assert [entry["word"] for entry in vocab.search_words("公认")] == ["acknowledged"]
    assert [entry["word"] for entry in vocab.search_words("a truth")] == ["acknowledged"]
    # 搜不到与空关键词都返回空列表
    assert vocab.search_words("nothing here") == []
    assert vocab.search_words("") == []


def test_word_set_is_lowercased(notebook: Path) -> None:
    # 阅读器高亮时用小写集合比对
    assert vocab.word_set() == {"ephemeral", "acknowledged"}


def test_export_anki_is_tab_separated(notebook: Path) -> None:
    text = vocab.export_anki()
    # 末尾必须有换行
    assert text.endswith("\n")
    # 按行、按制表符切开
    rows = [row.split("\t") for row in text.strip("\n").split("\n")]
    # 两个词两行
    assert len(rows) == 2
    # 每行都是 word/translation/context 三列
    assert all(len(row) == 3 for row in rows)
    assert {row[0] for row in rows} == {"ephemeral", "acknowledged"}


def test_export_anki_collapses_tabs_and_newlines(isolated_home) -> None:
    # 释义里带换行、上下文里带制表符
    vocab.add_word("w", "line one\nline two", context="a\tb")
    text = vocab.export_anki()
    # 二者都会被压成空格，保证 Anki 每行只有 3 列
    assert text == "w\tline one line two\ta b\n"


def test_export_anki_of_an_empty_notebook_is_empty(isolated_home) -> None:
    # 空笔记本导出空串（不返回一个孤零零的换行）
    assert vocab.export_anki() == ""


def test_review_order_is_reproducible_with_a_seed(isolated_home) -> None:
    # 加 8 个词，保证洗牌结果有足够多可能
    for index in range(8):
        vocab.add_word("word{}".format(index), "t")
    # 同一个 seed 两次洗牌结果必须一致
    one = vocab.review_order(seed=7)
    two = vocab.review_order(seed=7)
    assert [entry["word"] for entry in one] == [entry["word"] for entry in two]
    # 洗牌不增不减，集合相同
    assert sorted(entry["word"] for entry in one) == sorted(
        entry["word"] for entry in vocab.load_vocab()
    )


def test_paginate_clamps_and_counts() -> None:
    # 5 条数据、每页 2 条 -> 3 页
    items = [{"word": str(index)} for index in range(5)]
    # 第 1 页
    page_items, pages, current = vocab.paginate(items, page=1, per_page=2)
    assert [item["word"] for item in page_items] == ["0", "1"]
    assert (pages, current) == (3, 1)

    # 页码越界：夹到最后一页
    page_items, pages, current = vocab.paginate(items, page=99, per_page=2)
    assert [item["word"] for item in page_items] == ["4"]
    assert (pages, current) == (3, 3)

    # 页码 0：夹到第 1 页
    page_items, pages, current = vocab.paginate(items, page=0, per_page=2)
    assert [item["word"] for item in page_items] == ["0", "1"]
    assert (pages, current) == (3, 1)


def test_paginate_treats_a_zero_page_size_as_one() -> None:
    # per_page=0 会被当成 1，避免除零/死循环
    page_items, pages, current = vocab.paginate([{"word": "a"}, {"word": "b"}], per_page=0)
    assert len(page_items) == 1
    assert (pages, current) == (2, 1)


def test_paginate_of_nothing_still_reports_one_page() -> None:
    # 空列表也报"第 1 页 / 共 1 页"
    assert vocab.paginate([]) == ([], 1, 1)


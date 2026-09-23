"""Tests for :mod:`wreader.toc` — chapter extraction, epub nav and the cache.

Nothing here touches the network or the real data directory: the autouse
``isolated_home`` fixture points every path at a ``tmp_path``, and each epub is a
tiny zip built inside the test.
"""

# 延迟求值类型注解
from __future__ import annotations

# 缓存是 JSON，测试要读写它
import json
# 手动推后 mtime，模拟"正文变了"
import os
# 造 epub（它就是个 zip）
import zipfile
# 路径
from pathlib import Path
# 类型注解
from typing import Dict, List

# pytest
import pytest

# 被测模块 + 配置/书库
from wreader import config, library, toc

# 复用样例正文
from conftest import BOOK_LINES


# 造一本"多章"的书：每章三行（标题 + 空行 + 正文）
def _many_chapters(count: int = 320) -> List[str]:
    """Return *count* chapters, three lines each."""
    lines: List[str] = []
    for index in range(1, count + 1):
        lines.append("第{}章 江湖{}".format(index, index))
        lines.append("")
        lines.append("这是第{}章的正文。".format(index))
    return lines


# 造一个最小 epub；manifest / spine 直接给字符串，方便各测试拼不同的结构
def _epub(
    path: Path,
    documents: Dict[str, str],
    manifest: str,
    spine: str,
) -> Path:
    """Write a tiny epub whose OPF is given verbatim."""
    with zipfile.ZipFile(str(path), "w") as archive:
        # container.xml 指向 opf
        archive.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        # opf：manifest + spine 由调用方拼
        archive.writestr(
            "OEBPS/content.opf",
            "<package><manifest>{}</manifest><spine>{}</spine></package>".format(
                manifest, spine
            ),
        )
        # 各文档正文
        for name, markup in documents.items():
            archive.writestr("OEBPS/{}".format(name), markup)
    return path


# 一个"两章 + 一个 EPUB3 nav"的 epub，nav 标题故意与正文标题不同
def _nav_epub(tmp_path: Path) -> Path:
    """Build an epub whose nav titles differ from the body headings."""
    nav = (
        "<html><body><nav><ol>"
        '<li><a href="ch1.xhtml">第一节 开端</a></li>'
        '<li><a href="ch2.xhtml#top">第二节 终局</a></li>'
        "</ol></nav></body></html>"
    )
    return _epub(
        tmp_path / "nav.epub",
        documents={
            "ch1.xhtml": "<html><body><p>第一章</p><p>正文一</p></body></html>",
            "ch2.xhtml": "<html><body><p>第二章</p><p>正文二</p></body></html>",
            "nav.xhtml": nav,
        },
        manifest=(
            '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml"'
            ' properties="nav"/>'
        ),
        spine='<itemref idref="c1"/><itemref idref="c2"/>',
    )


# ------------------------------------------------------------------- build_toc
def test_build_toc_returns_lines_and_percentages() -> None:
    # 8 行、两个标题：第 0 行 12.5%、第 3 行 50.0%
    lines = list(BOOK_LINES)
    entries = toc.build_toc(lines)
    assert [entry["title"] for entry in entries] == ["第一章 科学边界", "第二章 台球"]
    assert [entry["line"] for entry in entries] == [0, 5]
    # 百分比与 library 的口径一致（最后一行才是 100%）
    assert entries[0]["percentage"] == library.position_percentage(0, len(lines))
    assert entries[1]["percentage"] == library.position_percentage(5, len(lines))


def test_build_toc_finds_every_chapter_of_a_long_book() -> None:
    # 320 章、960 行：应当一章不漏，行号是 0,3,6,...
    lines = _many_chapters(320)
    entries = toc.build_toc(lines)
    assert len(entries) == 320
    assert [entry["line"] for entry in entries] == [index * 3 for index in range(320)]
    assert entries[0]["title"] == "第1章 江湖1"
    assert entries[-1]["title"] == "第320章 江湖320"


def test_build_toc_honours_custom_patterns() -> None:
    lines = ["### 楔子", "正文", "### 尾声"]
    # 内置规则不认识 ###，加上自定义正则就能识别
    assert toc.build_toc(lines) == []
    entries = toc.build_toc(lines, extra=r"^### ")
    assert [entry["title"] for entry in entries] == ["### 楔子", "### 尾声"]


def test_compile_patterns_skips_broken_regexes() -> None:
    # 坏正则被丢掉，好的保留；换行也能当分隔符
    compiled = toc.compile_patterns("[bad |^ok|^fine\n")
    assert [pattern.pattern for pattern in compiled] == ["^ok", "^fine"]


def test_extra_patterns_reads_the_setting() -> None:
    # 默认是空串
    assert toc.extra_patterns() == ""
    # 写进 settings.toml 就能读到
    config.set("toc.patterns", "^第.+回")
    assert toc.extra_patterns() == "^第.+回"


# ------------------------------------------------------------------ filter_toc
def test_filter_toc_matches_titles_case_insensitively() -> None:
    entries = [
        {"title": "第一章 起点", "line": 0, "percentage": 0.0},
        {"title": "Chapter 2 台球", "line": 5, "percentage": 50.0},
    ]
    # 中文子串
    assert toc.filter_toc(entries, "台球") == [1]
    # 英文大小写无关
    assert toc.filter_toc(entries, "chapter") == [1]
    # 没有命中
    assert toc.filter_toc(entries, "找不到") == []


def test_filter_toc_with_a_blank_needle_keeps_everything() -> None:
    entries = [{"title": "一", "line": 0}, {"title": "二", "line": 1}]
    assert toc.filter_toc(entries, "") == [0, 1]
    assert toc.filter_toc(entries, "   ") == [0, 1]


# ------------------------------------------------------------------- epub nav
def test_parse_nav_reads_an_epub3_nav_document(tmp_path: Path) -> None:
    target = _nav_epub(tmp_path)
    with zipfile.ZipFile(str(target)) as archive:
        entries = toc.parse_nav(archive)
    # 标题取 nav 里的文字，href 解析成 zip 内路径（#top 被丢掉）
    assert entries == [
        ("第一节 开端", "OEBPS/ch1.xhtml"),
        ("第二节 终局", "OEBPS/ch2.xhtml"),
    ]


def test_parse_nav_reads_an_epub2_ncx(tmp_path: Path) -> None:
    ncx = (
        "<ncx><navMap>"
        "<navPoint><navLabel><text>卷一</text></navLabel>"
        '<content src="ch1.xhtml"/></navPoint>'
        "<navPoint><navLabel><text>卷二</text></navLabel>"
        '<content src="ch2.xhtml"/></navPoint>'
        "</navMap></ncx>"
    )
    target = _epub(
        tmp_path / "ncx.epub",
        documents={
            "ch1.xhtml": "<html><body><p>a</p></body></html>",
            "ch2.xhtml": "<html><body><p>b</p></body></html>",
            "toc.ncx": ncx,
        },
        manifest=(
            '<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        ),
        spine='<itemref idref="c1"/><itemref idref="c2"/>',
    )
    with zipfile.ZipFile(str(target)) as archive:
        entries = toc.parse_nav(archive)
    assert entries == [("卷一", "OEBPS/ch1.xhtml"), ("卷二", "OEBPS/ch2.xhtml")]


def test_parse_nav_without_navigation_is_empty(tmp_path: Path) -> None:
    # 没有 nav / ncx 的 epub：返回空列表，绝不报错
    target = _epub(
        tmp_path / "plain.epub",
        documents={"ch1.xhtml": "<html><body><p>a</p></body></html>"},
        manifest='<item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>',
        spine='<itemref idref="c1"/>',
    )
    with zipfile.ZipFile(str(target)) as archive:
        assert toc.parse_nav(archive) == []


def test_build_toc_from_epub_uses_the_nav_titles_and_lines(tmp_path: Path) -> None:
    target = _nav_epub(tmp_path)
    # 用内置提取器的输出，保证行号布局与 spine 完全一致
    lines = library.extract_epub_builtin(target).split("\n")
    entries = toc.build_toc_from_epub(target, lines)
    # 标题来自 nav（不是正文里的"第X章"），行号来自 spine 布局
    assert [entry["title"] for entry in entries] == ["第一节 开端", "第二节 终局"]
    assert [entry["line"] for entry in entries] == [0, 2]


def test_build_toc_from_epub_falls_back_when_the_layout_differs(tmp_path: Path) -> None:
    target = _nav_epub(tmp_path)
    # 行数与 spine 布局对不上（外部转换器的情况）：nav 的行号不可信
    lines = ["第一章", "正文一", "第二章", "正文二", "多出来的一行"]
    entries = toc.build_toc_from_epub(target, lines)
    # 退回正则：标题变成正文里识别出来的
    assert [entry["title"] for entry in entries] == ["第一章", "第二章"]
    assert [entry["line"] for entry in entries] == [0, 2]


# ----------------------------------------------------------------------- cache
def test_toc_cache_lives_in_the_cache_directory(imported) -> None:
    book_id = imported["zh"]
    # 缓存放在 <data>/cache/<book_id>_toc.json
    path = toc.toc_cache_path(book_id)
    assert path.name == "{}_toc.json".format(book_id)
    assert path.parent == config.cache_dir()


def test_load_toc_writes_then_reuses_the_cache(imported) -> None:
    book_id = imported["zh"]
    book = library.get_book(book_id)
    assert book is not None
    first = toc.load_toc(book_id, book)
    assert len(first) == 2
    # 缓存文件真的写出来了，而且带着失效判据（正文 mtime）
    cache = toc.toc_cache_path(book_id)
    assert cache.is_file()
    payload = json.loads(cache.read_text(encoding="utf-8"))
    assert payload["mtime"] == toc.source_mtime(book)
    # 再读一次走缓存，结果一致
    assert toc.load_toc(book_id, book) == first


def test_load_toc_prefers_a_fresh_cache_until_rebuild(imported) -> None:
    book_id = imported["zh"]
    book = library.get_book(book_id)
    assert book is not None
    toc.load_toc(book_id, book)
    # 把缓存里的条目换成假的，但 mtime 戳仍对得上
    cache = toc.toc_cache_path(book_id)
    payload = json.loads(cache.read_text(encoding="utf-8"))
    payload["entries"] = [{"title": "假章节", "line": 1, "percentage": 1.0}]
    cache.write_text(json.dumps(payload), encoding="utf-8")
    # 正常读：命中缓存（假的也认）——这正是"省一次全文扫描"的代价
    assert toc.load_toc(book_id, book)[0]["title"] == "假章节"
    # rebuild=True：忽略缓存，从正文重新解析
    rebuilt = toc.load_toc(book_id, book, rebuild=True)
    assert [entry["title"] for entry in rebuilt] == ["第一章 科学边界", "第二章 台球"]


def test_load_toc_rebuilds_when_the_text_changes(imported) -> None:
    book_id = imported["zh"]
    book = library.get_book(book_id)
    assert book is not None
    assert len(toc.load_toc(book_id, book)) == 2
    # 改写正文：追加一章，并把 mtime 明确推后（免得文件系统时间精度不够）
    path = Path(str(book["file_path"]))
    path.write_text("\n".join(list(BOOK_LINES) + ["第三章 新的风暴"]), encoding="utf-8")
    stamp = os.stat(path).st_mtime + 60
    os.utime(path, (stamp, stamp))
    # 缓存过期 -> 重建，新章节被认出来
    entries = toc.load_toc(book_id, book)
    assert len(entries) == 3
    assert entries[-1]["title"] == "第三章 新的风暴"


def test_load_toc_rebuilds_over_a_broken_cache(imported) -> None:
    book_id = imported["zh"]
    book = library.get_book(book_id)
    assert book is not None
    cache = toc.toc_cache_path(book_id)
    cache.parent.mkdir(parents=True, exist_ok=True)
    # 缓存是坏 JSON：当成没有，重建就好，绝不抛异常
    cache.write_text("{ not json", encoding="utf-8")
    assert len(toc.load_toc(book_id, book)) == 2


def test_load_toc_of_a_missing_text_is_empty(tmp_path: Path) -> None:
    # 正文文件不在了：返回空列表，不抛异常
    book = {"file_path": str(tmp_path / "gone.txt")}
    assert toc.load_toc("deadbeef", book) == []

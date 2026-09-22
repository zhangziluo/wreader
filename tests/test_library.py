"""Tests for :mod:`wreader.library` — importing, indexing and searching books."""

# 延迟求值类型注解
from __future__ import annotations

# 构造各种 BOM 测试编码探测
import codecs
# 验证 book_id 就是正文的 SHA-1 前缀
import hashlib
# 构造/解析 library.json
import json
# 造 epub 测试文件
import zipfile
# 路径断言
from pathlib import Path

# pytest.raises / parametrize
import pytest

# 被测模块 + 配置
from wreader import config, library

# 复用样例正文
from conftest import BOOK_LINES, ENGLISH_LINES


# --------------------------------------------------------------- text helpers
# 参数化：各种换行/分段字符都要归一成 \n，末尾空行要去掉
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("a\r\nb", "a\nb"),
        ("a\rb", "a\nb"),
        ("a\u2028b", "a\nb"),
        ("a\u2029b", "a\nb"),
        ("a\x0bb", "a\nb"),
        ("a\x0cb", "a\nb"),
        ("a\x85b", "a\nb"),
        ("a\n\n\n", "a"),
        ("", ""),
    ],
)
def test_normalise_newlines(raw: str, expected: str) -> None:
    assert library.normalise_newlines(raw) == expected


def test_count_words_counts_cjk_characters_and_latin_tokens() -> None:
    # 2 个汉字 + 1 个英文词
    assert library.count_words("你好 world") == 3
    # It's 算一个词（撇号在单词内部）
    assert library.count_words("It's a truth") == 3
    assert library.count_words("") == 0


# 参数化：中文习惯的万字/亿字单位
@pytest.mark.parametrize(
    "count, expected",
    [
        (0, "0"),
        (9999, "9999"),
        (10000, "1.0万"),
        (123456, "12.3万"),
        (100_000_000, "1.0亿"),
    ],
)
def test_human_words(count: int, expected: str) -> None:
    assert library.human_words(count) == expected


def test_position_percentage_counts_the_last_line_as_done() -> None:
    # 第 0 行就是 1%（因为公式是 (行+1)/总数）
    assert library.position_percentage(0, 100) == 1.0
    assert library.position_percentage(49, 100) == 50.0
    # 最后一行恰好 100%
    assert library.position_percentage(99, 100) == 100.0
    # 越界也夹在 100%
    assert library.position_percentage(200, 100) == 100.0
    # 总行数为 0
    assert library.position_percentage(0, 0) == 0.0


def test_progress_percent_prefers_the_stored_value() -> None:
    # 记录里已经存了百分比：直接用
    book = {"total_lines": 100, "progress": {"current_line": 50, "percentage": 12.5}}
    assert library.progress_percent(book) == 12.5
    # 没存：用当前行号现算
    book = {"total_lines": 100, "progress": {"current_line": 50}}
    assert library.progress_percent(book) == 51.0
    # 什么都没有
    assert library.progress_percent({}) == 0.0


# ------------------------------------------------------------------ file names
# 参数化：几种常见的文件名命名方式
@pytest.mark.parametrize(
    "stem, expected",
    [
        ("刘慈欣-三体", ("三体", "刘慈欣")),
        ("刘慈欣 - 三体", ("三体", "刘慈欣")),
        ("[刘慈欣] 三体", ("三体", "刘慈欣")),
        ("《三体》", ("三体", "unknown")),
        ("三体", ("三体", "unknown")),
        ("Spider-Man", ("Spider-Man", "unknown")),
        # No CJK on the left and no spaces around the dash: not an author/title split.
        (
            "Jane Austen-Pride and Prejudice",
            ("Jane Austen-Pride and Prejudice", "unknown"),
        ),
    ],
)
def test_parse_filename(stem: str, expected) -> None:
    assert library.parse_filename(stem) == expected


# 下载站（"zxcs" 合集包）到处在用的命名方式：
#: The naming that download collections (the "zxcs" packs) use everywhere:
#: ``《书名》（校对版全本）作者：某人``.  These are real file names from a user's
#: Downloads folder, kept verbatim so the parsing stays honest.
# 参数化：真实文件名，验证尾注与"作者："标记都能被正确剥掉
@pytest.mark.parametrize(
    "stem, expected",
    [
        ("《从1983开始》（校对版全本）作者：睡觉会变白", ("从1983开始", "睡觉会变白")),
        ("《大奉打更人》（校对版全本）作者：卖报小郎君", ("大奉打更人", "卖报小郎君")),
        ("《凡人修仙传》（校对版全本+番外）作者：忘语", ("凡人修仙传", "忘语")),
        ("《诡秘之主》（精校版全本）作者：爱潜水的乌贼", ("诡秘之主", "爱潜水的乌贼")),
        ("《你好，1983》（校对版全本）作者：隐为者", ("你好，1983", "隐为者")),
        # A half width colon and no space at all.
        # 半角冒号、完全没有空格
        ("书名(校对版)作者:X", ("书名", "X")),
        # The annotation may sit behind the author name instead.
        # 尾注也可能挂在作者名后面
        ("《书名》作者：某人（校对版）", ("书名", "某人")),
        # A dash right before the marker is swallowed with it.
        # "作者："前面的连接符会被一起吃掉
        ("书名-作者：某人", ("书名", "某人")),
        # No author marker at all: the annotation is still removed.
        # 没有"作者："标记时，尾注照样删掉
        ("《三体》（修订版）", ("三体", "unknown")),
        ("三体（全本）", ("三体", "unknown")),
        ("Spider-Man (annotated)", ("Spider-Man", "unknown")),
        ("书名（上）", ("书名", "unknown")),
        # The existing shapes keep working, annotations included.
        # 原有命名方式配合尾注也仍然可用
        ("[刘慈欣] 三体（校对版全本）", ("三体", "刘慈欣")),
        ("刘慈欣-三体（校对版全本）", ("三体", "刘慈欣")),
        # Only a *trailing* group is an annotation: this title keeps its brackets.
        # 只有结尾的括号组算尾注，书名中间括号保留
        ("书名（中）下册", ("书名（中）下册", "unknown")),
        # Nothing but the marker: better a raw title than an empty one.
        # 整串只有"作者："标记：宁可保留原文，也不要空标题
        ("作者：某人", ("作者：某人", "unknown")),
    ],
)
def test_parse_filename_cleans_annotations_and_author_markers(stem: str, expected) -> None:
    assert library.parse_filename(stem) == expected


def test_strip_annotations() -> None:
    # 单层尾注
    assert library.strip_annotations("书名（校对版全本）") == "书名"
    # 多层尾注：循环删直到没有
    assert library.strip_annotations("书名(校对版)(番外)") == "书名"
    # 括号内容里带 + 号
    assert library.strip_annotations("书名（校对版全本+番外）") == "书名"
    # 括号在中间：不是尾注，保留
    assert library.strip_annotations("书名（中）下册") == "书名（中）下册"
    # 整串都是尾注
    assert library.strip_annotations("（全本）") == ""
    assert library.strip_annotations("书名") == "书名"
    assert library.strip_annotations("") == ""


def test_split_author_marker() -> None:
    # 返回 (作者标记之前的部分, 作者名)
    assert library.split_author_marker("《书名》（校对版）作者：某人") == (
        "《书名》（校对版）",
        "某人",
    )
    # 前面的连接符会被去掉
    assert library.split_author_marker("书名 - 作者：某人") == ("书名", "某人")
    # 整串就是标记
    assert library.split_author_marker("作者：某人") == ("", "某人")
    # 没有标记：原样返回，作者为空
    assert library.split_author_marker("没有标记") == ("没有标记", "")


def test_safe_filename_strips_illegal_characters() -> None:
    # 非法字符换成下划线
    assert library.safe_filename("a/b:c*d?") == "a_b_c_d_"
    # 首尾的点和空格被去掉
    assert library.safe_filename("  ..hidden..  ") == "hidden"
    assert library.safe_filename("///") == "___"
    # 全被清空时给个兜底名
    assert library.safe_filename("") == "untitled"


def test_unique_path_adds_a_counter(tmp_path: Path) -> None:
    # 第一次直接用原名
    first = library.unique_path(tmp_path, "book_utf8", ".txt")
    assert first.name == "book_utf8.txt"
    # 占用之后再要，就会加 (2)
    first.write_text("x", encoding="utf-8")
    assert library.unique_path(tmp_path, "book_utf8", ".txt").name == "book_utf8(2).txt"


# ------------------------------------------------------------------ encodings
def test_detect_and_decode_utf8_bom(tmp_path: Path) -> None:
    # UTF-8 BOM 开头
    target = tmp_path / "bom.txt"
    target.write_bytes(codecs.BOM_UTF8 + "你好".encode("utf-8"))
    assert library.detect_and_decode(target) == ("你好", "UTF-8 (BOM)")


def test_detect_and_decode_utf16(tmp_path: Path) -> None:
    # UTF-16 LE BOM 开头
    target = tmp_path / "u16.txt"
    target.write_bytes(codecs.BOM_UTF16_LE + "你好".encode("utf-16-le"))
    assert library.detect_and_decode(target) == ("你好", "UTF-16")


# 参数化：UTF-32 的两种字节序，以及一个非 BMP 字符（emoji）
@pytest.mark.parametrize(
    "bom, codec, text",
    [
        (codecs.BOM_UTF32_LE, "utf-32-le", "你好世界"),
        (codecs.BOM_UTF32_BE, "utf-32-be", "你好世界"),
        # A non-BMP character is what used to blow up: the UTF-32 BOM opens with
        # the UTF-16 BOM bytes, so reading it as UTF-16 hit an illegal surrogate.
        (codecs.BOM_UTF32_LE, "utf-32-le", "你好😀世界"),
        (codecs.BOM_UTF32_BE, "utf-32-be", "你好😀世界"),
    ],
)
def test_detect_and_decode_utf32(bom: bytes, codec: str, text: str, tmp_path: Path) -> None:
    target = tmp_path / "u32.txt"
    # 写入 BOM + 用对应字节序编码的正文
    target.write_bytes(bom + text.encode(codec))
    # 必须识别成 UTF-32，而不是被 UTF-16 抢先匹配
    assert library.detect_and_decode(target) == (text, "UTF-32")


# 参数化：BOM 声明了编码但内容已经损坏的情况
@pytest.mark.parametrize(
    "raw, expected",
    [
        # A lone high surrogate: illegal UTF-16, used to escape as a traceback.
        # 孤立的代理项：非法 UTF-16（过去会直接抛异常）
        (codecs.BOM_UTF16_LE + b"\x00\xd8", "UTF-16 (replaced)"),
        (codecs.BOM_UTF16_BE + b"\xd8\x00", "UTF-16 (replaced)"),
        # An odd byte count leaves a half code unit at the end.
        # 字节数为奇数：末尾剩下半个码元
        (codecs.BOM_UTF16_LE + b"abc", "UTF-16 (replaced)"),
        # The same damage inside the wider family.
        # UTF-32 家族里的同类损坏
        (codecs.BOM_UTF32_LE + b"\x00\xd8\x00\x00", "UTF-32 (replaced)"),
        (codecs.BOM_UTF8 + b"\xff\xff", "UTF-8 (replaced)"),
    ],
)
def test_a_bom_family_that_cannot_be_decoded_degrades(
    raw: bytes, expected: str, tmp_path: Path
) -> None:
    target = tmp_path / "damaged.txt"
    target.write_bytes(raw)
    # 关键点：解不了也不能抛异常
    text, encoding = library.detect_and_decode(target)  # must not raise
    # 编码名标注为 (replaced)，正文里有替换字符
    assert encoding == expected
    assert "\ufffd" in text


def test_detect_and_decode_gb18030(tmp_path: Path) -> None:
    # 一份 GB18030 编码的中文文本（没有 BOM，只能靠 chardet 猜）
    target = tmp_path / "gb.txt"
    target.write_bytes("第一章 科学边界".encode("gb18030"))
    text, encoding = library.detect_and_decode(target)
    # 内容必须正确还原
    assert text == "第一章 科学边界"
    # 编码名不做硬性要求（chardet 可能报 gb2312/gb18030 等）
    assert encoding


def test_detect_and_decode_falls_back_to_replacement(monkeypatch, tmp_path: Path) -> None:
    # Force the "chardet had no idea" path: the bytes are invalid in UTF-8 and
    # in GB18030, so only the replacement fallback can decode them.
    # 让 chardet 彻底猜不出来，逼出最后一层兜底
    monkeypatch.setattr(library.chardet, "detect", lambda raw: {})
    target = tmp_path / "junk.txt"
    target.write_bytes(b"\xff\xff\xff")
    text, encoding = library.detect_and_decode(target)
    # 用替换字符兜住，导入流程不会中断
    assert encoding == "utf-8 (replaced)"
    assert "\ufffd" in text


# ---------------------------------------------------------------- candidates
def test_collect_candidates_walks_a_directory(tmp_path: Path) -> None:
    # 一个子目录 + 一个 .txt + 一个 .epub + 一个 .md + 一个 macOS 影子文件
    (tmp_path / "sub").mkdir()
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "sub" / "a.epub").write_bytes(b"x")
    (tmp_path / "notes.md").write_text("x", encoding="utf-8")
    (tmp_path / "._fork.txt").write_text("x", encoding="utf-8")
    # 只收 .txt/.epub，且跳过以 . 开头的隐藏文件；顺序按路径小写排序
    assert [path.name for path in library.collect_candidates(str(tmp_path))] == [
        "b.txt",
        "a.epub",
    ]


def test_collect_candidates_accepts_one_file(tmp_path: Path) -> None:
    # 直接给单个文件也支持
    target = tmp_path / "book.txt"
    target.write_text("x", encoding="utf-8")
    assert library.collect_candidates(str(target)) == [target]


def test_collect_candidates_rejects_other_types(tmp_path: Path) -> None:
    # 不支持的后缀要报错
    target = tmp_path / "book.mobi"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(library.LibraryError) as excinfo:
        library.collect_candidates(str(target))
    assert "unsupported file type" in str(excinfo.value)


def test_collect_candidates_rejects_a_missing_path(tmp_path: Path) -> None:
    with pytest.raises(library.LibraryError) as excinfo:
        library.collect_candidates(str(tmp_path / "nope"))
    assert "path does not exist" in str(excinfo.value)


# ------------------------------------------------------------------ chapters
# 参数化：各种应当被识别为章节标题的行
@pytest.mark.parametrize(
    "line",
    [
        "第一章 科学边界",
        "第 12 章",
        "第三回",
        "卷二",
        "序章",
        "楔子",
        "尾声",
        "番外 其一",
        "大结局",
        "Chapter 12",
        "CHAPTER ONE",
        "Prologue",
    ],
)
def test_is_chapter_heading_accepts_headings(line: str) -> None:
    assert library.is_chapter_heading(line)


# 参数化：看起来像但其实是正文（或空行/超长行）
@pytest.mark.parametrize(
    "line",
    [
        "",
        "    ",
        "汪淼看到了一串数字在眼前跳动。",
        "第一章 科学边界。",  # prose that merely mentions a chapter
        "chapterbook",
        "x" * 61,
    ],
)
def test_is_chapter_heading_rejects_prose(line: str) -> None:
    assert not library.is_chapter_heading(line)


def test_parse_chapters_returns_line_starts() -> None:
    # 样例书的两章分别从第 0、5 行开始
    assert library.parse_chapters(list(BOOK_LINES)) == [
        {"title": "第一章 科学边界", "line_start": 0},
        {"title": "第二章 台球", "line_start": 5},
    ]


# ----------------------------------------------------------------------- epub
def test_html_to_text_flattens_blocks() -> None:
    # script/style 整段去掉；块级标签变换行；实体还原
    markup = (
        "<html><head><style>p{}</style><script>var x;</script></head>"
        "<body><h1>Title</h1><p>Hello<br/>world</p><p>A &amp; B</p></body></html>"
    )
    assert library.html_to_text(markup) == "Title\nHello\nworld\nA & B"


def test_epub_content_files_follows_the_spine(make_epub) -> None:
    # spine 顺序是 c2 -> c1，所以返回顺序也应当是 second 在前
    target = make_epub(spine=["c2", "c1"])
    with zipfile.ZipFile(str(target)) as archive:
        assert library._epub_content_files(archive) == [
            "OEBPS/second.xhtml",
            "OEBPS/first.xhtml",
        ]


def test_epub_content_files_falls_back_without_a_container(make_epub) -> None:
    # 没有 container.xml：退回按文件名排序
    target = make_epub(with_container=False)
    with zipfile.ZipFile(str(target)) as archive:
        assert library._epub_content_files(archive) == [
            "OEBPS/first.xhtml",
            "OEBPS/second.xhtml",
        ]


def test_epub_content_files_tolerates_broken_manifest_entries(make_epub) -> None:
    # manifest/spine 里有悬空引用：跳过它们，正常的仍然按顺序返回
    target = make_epub(dangling=True)
    with zipfile.ZipFile(str(target)) as archive:
        assert library._epub_content_files(archive) == [
            "OEBPS/first.xhtml",
            "OEBPS/second.xhtml",
        ]


def test_extract_epub_builtin_reads_the_body(make_epub) -> None:
    # 内置提取器能把两章正文读出来
    text = library.extract_epub_builtin(make_epub())
    assert "第一章" in text and "第二章" in text


def test_extract_epub_builtin_rejects_a_non_epub(tmp_path: Path) -> None:
    # 根本不是 zip 文件
    target = tmp_path / "broken.epub"
    target.write_bytes(b"not a zip")
    with pytest.raises(library.LibraryError) as excinfo:
        library.extract_epub_builtin(target)
    assert "not a readable epub" in str(excinfo.value)


def test_extract_epub_prefers_an_external_tool(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "book.epub"
    target.write_bytes(b"x")
    destination = tmp_path / "out.txt"

    # 假的外部工具：写出内容并报告自己的名字
    def fake_tool(source: Path, out: Path):
        out.write_text("from calibre\n", encoding="utf-8")
        return "ebook-convert"

    monkeypatch.setattr(library, "_run_external_epub_tool", fake_tool)
    # 外部工具成功时就用它，返回工具名
    assert library.extract_epub(target, destination) == "ebook-convert"
    assert destination.read_text(encoding="utf-8") == "from calibre\n"


def test_extract_epub_falls_back_to_the_builtin(monkeypatch, make_epub, tmp_path: Path) -> None:
    # 外部工具都不可用
    monkeypatch.setattr(library, "_run_external_epub_tool", lambda *a: None)
    destination = tmp_path / "out.txt"
    # 返回 "builtin" 表示走了内置提取器
    assert library.extract_epub(make_epub(), destination) == "builtin"
    assert "第一章" in destination.read_text(encoding="utf-8")


def test_normalise_bookmarks_accepts_ints_and_records() -> None:
    # 混着纯数字、完整记录和垃圾数据
    marks = library.normalise_bookmarks(
        [40, {"line": 12, "label": "here", "created": "t"}, "junk", {"label": "no line"}]
    )
    # 垃圾被丢掉，结果按行号升序，纯数字被补成完整结构
    assert marks == [
        {"line": 12, "label": "here", "created": "t"},
        {"line": 40, "label": "", "created": ""},
    ]
    # 不是列表时返回空列表
    assert library.normalise_bookmarks(None) == []


# ------------------------------------------------------------------- importing
def test_import_books_stores_utf8_text_and_a_record(isolated_home) -> None:
    # 放一本"作者-书名"命名的书并导入
    isolated_home.write_book("刘慈欣-三体.txt", BOOK_LINES)
    result = library.import_books(str(isolated_home.root / "books"))

    # 扫描 1 个文件，无重复无失败
    assert result.scanned == 1
    assert result.duplicates == [] and result.failed == []
    book_id, book = result.imported[0]
    # id 是 12 位十六进制
    assert len(book_id) == 12
    # 书名与作者由文件名解析而来
    assert book["title"] == "三体"
    assert book["author"] == "刘慈欣"
    # 行数与字数统计正确
    assert book["total_lines"] == len(BOOK_LINES)
    assert book["total_words"] == library.count_words("\n".join(BOOK_LINES))
    # 识别出两个章节
    assert [chapter["title"] for chapter in book["chapters"]] == [
        "第一章 科学边界",
        "第二章 台球",
    ]
    # 导入日期已填、进度为初始值、标签为空
    assert book["import_date"]
    assert book["progress"]["current_line"] == 0
    assert book["tags"] == []

    # 转换后的正文落在 novels 目录，文件名用清洗后的书名
    stored = Path(book["file_path"])
    assert stored.parent == isolated_home.novels
    assert stored.name == "三体_utf8.txt"
    # 内容与源文本一致（末尾补一个换行）
    assert stored.read_text(encoding="utf-8") == "\n".join(BOOK_LINES) + "\n"


def test_import_books_is_deduplicated_by_content(isolated_home) -> None:
    isolated_home.write_book("三体.txt", BOOK_LINES)
    # 第一次导入成功
    first = library.import_books(str(isolated_home.root / "books"))
    # 第二次同一批文件都被判为重复
    second = library.import_books(str(isolated_home.root / "books"))

    assert len(first.imported) == 1
    assert second.imported == []
    assert len(second.duplicates) == 1
    # 书库里仍然只有一本
    assert len(library.list_books()) == 1


def test_import_books_gives_the_same_id_to_the_same_text(isolated_home) -> None:
    isolated_home.write_book("one.txt", BOOK_LINES)
    book_id = library.import_books(str(isolated_home.root / "books")).imported[0][0]
    # The id is the first 12 hex digits of the SHA-1 of the converted text, which
    # is what makes importing the very same book twice a no-op.
    # 独立算一遍 SHA-1 前 12 位，验证 book_id 的生成规则
    expected = hashlib.sha1("\n".join(BOOK_LINES).encode("utf-8")).hexdigest()[:12]
    assert book_id == expected


def test_import_books_reports_empty_and_unreadable_files(isolated_home) -> None:
    # 一个只有空行的、一个 0 字节的、一个正常的
    source = isolated_home.root / "books"
    source.mkdir(parents=True)
    (source / "blank.txt").write_text("\n\n", encoding="utf-8")
    (source / "empty.txt").write_bytes(b"")
    isolated_home.write_book("good.txt", BOOK_LINES)

    result = library.import_books(str(source))
    # 只有正常的那本成功，另两个记失败但不中断
    assert len(result.imported) == 1
    assert len(result.failed) == 2
    assert result.scanned == 3


def test_import_books_does_not_abort_on_a_damaged_utf16_file(isolated_home) -> None:
    """A lone surrogate used to escape as a traceback and kill the whole run."""
    source = isolated_home.root / "books"
    source.mkdir(parents=True)
    # BOM 说是 UTF-16，但内容是孤立的代理项（坏数据）
    (source / "damaged.txt").write_bytes(codecs.BOM_UTF16_LE + b"\x00\xd8")
    isolated_home.write_book("good.txt", BOOK_LINES)

    result = library.import_books(str(source))
    assert result.scanned == 2
    assert len(result.imported) == 2  # the damaged one imports with replacement
    # 坏文件也被用替换字符导入，没有失败项
    assert result.failed == []
    assert any(book["encoding"] == "UTF-16 (replaced)" for _, book in result.imported)


def test_import_books_records_a_unicode_error_instead_of_aborting(
    isolated_home, monkeypatch
) -> None:
    source = isolated_home.root / "books"
    source.mkdir(parents=True)
    (source / "broken.txt").write_text("x", encoding="utf-8")
    isolated_home.write_book("good.txt", BOOK_LINES)

    # 保存真实实现，再包装成"遇到 broken.txt 就抛 UnicodeDecodeError"
    real = library.load_source_text

    def flaky(path: Path):
        if path.name == "broken.txt":
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
        return real(path)

    monkeypatch.setattr(library, "load_source_text", flaky)
    result = library.import_books(str(source))
    # 关键：Unicode 错误只是让这一个文件失败，运行不中断
    assert result.scanned == 2
    assert len(result.imported) == 1
    assert len(result.failed) == 1
    assert result.failed[0][0].name == "broken.txt"


def test_import_books_reads_a_utf32_book(isolated_home) -> None:
    source = isolated_home.root / "books"
    source.mkdir(parents=True)
    body = "第一章 科学边界\n\n汪淼看到了一串数字在眼前跳动。"
    # 用 UTF-32 LE + BOM 写一本中文书
    (source / "刘慈欣-三体.txt").write_bytes(
        codecs.BOM_UTF32_LE + ("{}\n".format(body)).encode("utf-32-le")
    )

    result = library.import_books(str(source))
    assert len(result.imported) == 1
    _, book = result.imported[0]
    # 编码被正确识别，书名照常解析，正文原样转换
    assert book["encoding"] == "UTF-32"
    assert book["title"] == "三体"
    assert Path(book["file_path"]).read_text(encoding="utf-8") == "{}\n".format(body)


def test_import_books_accepts_a_single_file(isolated_home) -> None:
    # import 也支持直接给一个文件路径
    target = isolated_home.write_book("三体.txt", BOOK_LINES)
    result = library.import_books(str(target))
    assert len(result.imported) == 1


def test_import_books_reads_an_epub(monkeypatch, isolated_home, make_epub) -> None:
    # 强制走内置提取器，保证不依赖外部工具
    monkeypatch.setattr(library, "_run_external_epub_tool", lambda *a: None)
    source = isolated_home.root / "books"
    source.mkdir(parents=True)
    make_epub().replace(source / "刘慈欣-A Small Epub.epub")

    result = library.import_books(str(source))
    assert len(result.imported) == 1
    book_id, book = result.imported[0]
    # 书名/作者来自文件名；编码固定成 UTF-8（内置提取器的约定）
    assert book["title"] == "A Small Epub"
    assert book["author"] == "刘慈欣"
    assert book["encoding"] == "UTF-8"
    # epub 里的两个 XHTML 成了两章
    assert [chapter["title"] for chapter in book["chapters"]] == ["第一章", "第二章"]


def test_import_books_keeps_an_ascii_title_whole(isolated_home) -> None:
    # "Spider-Man" must not be read as author "Spider" + title "Man".
    isolated_home.write_book("Spider-Man.txt", BOOK_LINES)
    result = library.import_books(str(isolated_home.root / "books"))
    assert result.imported[0][1]["title"] == "Spider-Man"
    assert result.imported[0][1]["author"] == "unknown"


def test_import_books_cleans_a_collection_style_filename(isolated_home) -> None:
    # 下载站风格的超长文件名
    isolated_home.write_book(
        "《从1983开始》（校对版全本）作者：睡觉会变白.txt", BOOK_LINES
    )
    result = library.import_books(str(isolated_home.root / "books"))
    _, book = result.imported[0]
    # 书名与作者都被正确拆出来
    assert (book["title"], book["author"]) == ("从1983开始", "睡觉会变白")
    # The cleaned title is what names the stored UTF-8 text as well.
    # 存盘文件名也用清洗后的书名
    assert Path(book["file_path"]).name == "从1983开始_utf8.txt"


# ------------------------------------------------------------------ the index
def test_empty_library_shape(isolated_home) -> None:
    # 全新环境下的索引结构：三个段落
    document = library.load_library()
    assert document == {
        "books": {},
        "stats": {"total_books": 0, "total_read_time": 0, "daily_read_time": {}},
        "achievements": {"unlocked": [], "progress": {}},
    }


def test_save_library_keeps_total_books_honest(imported) -> None:
    document = library.load_library()
    # 故意把计数器改错
    document["stats"]["total_books"] = 99
    library.save_library(document)
    # 写盘时会按实际书目数重算成 2
    assert json.loads(config.library_file().read_text(encoding="utf-8"))["stats"][
        "total_books"
    ] == 2


def test_load_library_fills_in_missing_fields(isolated_home) -> None:
    # 手写一份"字段缺失 + 数字写成字符串 + 混进垃圾"的索引
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    config.library_file().write_text(
        json.dumps(
            {
                "books": {
                    "x": {
                        "title": "T",
                        "total_lines": "5",
                        "tags": "a, b",
                        "chapters": [{"title": "c", "line_start": "3"}, "junk"],
                        "progress": {"current_line": "2", "sessions": "broken"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    book = library.get_book("x")
    assert book is not None
    # 缺失字段补默认值
    assert book["author"] == "unknown"
    assert book["encoding"] == "utf-8"
    # 字符串形式的数字被转成 int
    assert book["total_lines"] == 5
    # 逗号分隔的标签字符串被拆成列表
    assert book["tags"] == ["a", "b"]
    # 章节列表里的垃圾项被丢掉
    assert book["chapters"] == [{"title": "c", "line_start": 3}]
    # ``progress`` is kept exactly as stored (only ``finished`` is coerced and
    # ``bookmarks`` are cleaned up), but every consumer funnels the values through
    # ``int(...)`` or an ``isinstance(..., list)`` guard, so a hand edited string
    # still yields a sane percentage instead of raising.  See the stats tests for
    # the guard around a damaged ``sessions`` value.
    # 进度块里的字符串原样保留，但消费方都会做 int()/isinstance 防护
    assert book["progress"]["current_line"] == "2"
    assert book["progress"]["sessions"] == "broken"
    # 所以百分比照样算得出来
    assert library.progress_percent(book) == 60.0


def test_load_library_rejects_broken_json(isolated_home) -> None:
    # 索引文件语法坏了
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    config.library_file().write_text("{oops", encoding="utf-8")
    with pytest.raises(library.LibraryError) as excinfo:
        library.load_library()
    assert "not valid JSON" in str(excinfo.value)


def test_load_library_requires_the_books_mapping(isolated_home) -> None:
    # 合法 JSON 但缺少 books 段落
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    config.library_file().write_text('{"stats": {}}', encoding="utf-8")
    with pytest.raises(library.LibraryError) as excinfo:
        library.load_library()
    assert "missing the 'books' mapping" in str(excinfo.value)


def test_list_books_is_ordered_by_title(imported) -> None:
    # 列表顺序就是标题（忽略大小写）升序
    titles = [book["title"] for _, book in library.list_books()]
    assert titles == sorted(titles, key=str.lower)


def test_get_book_and_remove_book(imported) -> None:
    book_id = imported["zh"]
    # 按 id 能查到
    book = library.get_book(book_id)
    assert book is not None and book["title"] == "三体"
    # 不存在的 id 返回 None
    assert library.get_book("nope") is None

    # 删除会同时删掉正文文件
    stored = Path(book["file_path"])
    assert stored.is_file()
    removed = library.remove_book(book_id)
    assert removed is not None and removed["title"] == "三体"
    assert not stored.exists()
    # 再查/再删都没有了
    assert library.get_book(book_id) is None
    assert library.remove_book(book_id) is None


# -------------------------------------------------------------------- searching
def searchable() -> dict:
    """A tiny in-memory library, so the scoring rules are easy to see."""
    # 三本书的小书库，专门用来观察打分规则
    return {
        "books": {
            "1": {"title": "Harry Potter", "author": "J. K. Rowling", "tags": ["fantasy"]},
            "2": {"title": "The Hobbit", "author": "Tolkien", "tags": ["fantasy", "classic"]},
            "3": {"title": "三体", "author": "刘慈欣", "tags": []},
        }
    }


def test_search_without_a_keyword_lists_every_book() -> None:
    # 空关键词：按标题列出全部
    rows = library.search_books("", searchable())
    assert [book_id for book_id, _ in rows] == ["1", "2", "3"]


def test_search_matches_the_title_case_insensitively() -> None:
    # 大写也能命中；中文直接子串匹配
    assert [book_id for book_id, _ in library.search_books("HARRY", searchable())] == ["1"]
    assert [book_id for book_id, _ in library.search_books("三体", searchable())] == ["3"]


def test_search_falls_back_to_a_subsequence_match() -> None:
    # h-p-t-r 作为子序列出现在 "Harry Potter" 里
    assert [book_id for book_id, _ in library.search_books("hptr", searchable())] == ["1"]


def test_search_matches_the_author() -> None:
    assert [book_id for book_id, _ in library.search_books("tolkien", searchable())] == ["2"]


def test_search_restricted_to_tags() -> None:
    # 以 # 开头：只在标签里搜
    assert [book_id for book_id, _ in library.search_books("#fantasy", searchable())] == ["1", "2"]
    assert [book_id for book_id, _ in library.search_books("#classic", searchable())] == ["2"]
    # 只给一个 # ：什么都不返回
    assert library.search_books("#", searchable()) == []


def test_search_returns_nothing_for_an_unknown_keyword() -> None:
    assert library.search_books("zzzzz", searchable()) == []


def test_a_title_match_outranks_an_author_match() -> None:
    # 两本书都含 "Tolkien"，一本在标题、一本在作者
    document = {
        "books": {
            "author": {"title": "Other", "author": "Tolkien"},
            "title": {"title": "Tolkien", "author": "Someone"},
        }
    }
    # 标题权重更高，所以标题命中的排前面
    assert [book_id for book_id, _ in library.search_books("tolkien", document)] == [
        "title",
        "author",
    ]


def test_a_prefix_match_outranks_a_contained_one() -> None:
    # 一本以关键词开头，一本在中间出现
    document = {
        "books": {
            "late": {"title": "The Hobbit", "author": ""},
            "early": {"title": "Hobbit", "author": ""},
        }
    }
    # 前缀命中得分更高
    assert [book_id for book_id, _ in library.search_books("hobbit", document)] == [
        "early",
        "late",
    ]


def test_search_uses_the_stored_library_by_default(imported) -> None:
    # 不传 document 时读磁盘上的索引
    results = library.search_books("三体")
    assert [book_id for book_id, _ in results] == [imported["zh"]]






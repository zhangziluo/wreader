"""Book library management.

The index lives at ``~/.wreader/library.json`` (see :mod:`wreader.config`) and has three
top level sections::

    {
      "books":        {"<book_id>": { ...one record per book... }},
      "stats":        {"total_books": 0, "total_read_time": 0,
                       "daily_read_time": {}},
      "achievements": {"unlocked": [], "progress": {}}
    }

One book record looks like::

    {
      "title": "三体", "author": "刘慈欣",
      "file_path": "/home/you/novels/三体_utf8.txt",
      "encoding": "GB2312", "total_lines": 812, "total_words": 208400,
      "chapters": [{"title": "第一章 科学边界", "line_start": 0}],
      "progress": {"current_line": 0, "percentage": 0.0, "last_read": null,
                   "total_time_seconds": 0, "sessions": []},
      "tags": [], "import_date": "2026-09-21"
    }

Importing always stores the text as UTF-8 in the novels directory
(``<title>_utf8.txt``) so the reader never deals with encodings again.
``book_id`` is the SHA-1 of the converted text, which makes importing the same
book twice a no-op.  ``total_lines`` and every ``line_start`` are indexes into
``text.split("\\n")`` of that stored file.
"""

# 延迟求值类型注解
from __future__ import annotations

# chardet：猜文本文件编码（BOM 认不出来时的主力）
import chardet
# 各种 BOM 常量的来源
import codecs
# 用 SHA-1 给书生成稳定 id，重复导入同一本书会得到同一个 id
import hashlib
# html.unescape 把 epub 里的 &amp; 之类实体还原
import html
# 读写 library.json
import json
# os.replace 做原子写入
import os
# epub 内部是 zip，里面的路径用 posix 风格，要靠它拼路径
import posixpath
# 正则在章节识别、文件名解析、HTML 清理里到处都用
import re
# shutil.which 找外部转换工具
import shutil
# 调用 ebook-convert / epub2txt 这类外部程序
import subprocess
# 解 epub 时用临时目录放中间产物
import tempfile
# epub 本质是 zip，用标准库直接读
import zipfile
# dataclass 定义导入结果；field 用来给字段设默认工厂
from dataclasses import dataclass, field
# 记录导入日期（YYYY-MM-DD）
from datetime import datetime
# 路径处理
from pathlib import Path
# 类型注解
from typing import Any, Dict, List, Optional, Sequence, Tuple
# 解析 epub 的 container.xml / opf（都是 XML）
from xml.etree import ElementTree

# 同包引用 config，拿数据目录和 novels 目录
from . import config

# 支持导入的书籍后缀
SUPPORTED_EXTENSIONS: Tuple[str, ...] = (".txt", ".epub")

# 外部 epub 转换工具，按这个顺序尝试；都没装才用内置提取器
#: External epub converters, tried in this order before the built-in extractor.
EPUB_TOOLS: Tuple[str, ...] = ("ebook-convert", "epub2txt")

# book_id 取 SHA-1 的前 12 位，够用又短
_ID_LENGTH = 12
# 超过这个长度的行不可能被当作章节标题（避免把长句误判成标题）
_MAX_CHAPTER_TITLE_LENGTH = 60


# 书库读、写、转换出错时统一抛这个异常
class LibraryError(Exception):
    """Raised when the library cannot be read, written or converted."""


def empty_progress() -> Dict[str, Any]:
    """Return a fresh, unread progress block."""
    # 每本书都从这份"零进度"结构开始
    return {
        # 读到第几行（0 起始）
        "current_line": 0,
        # 百分比 0-100
        "percentage": 0.0,
        # 上次阅读时间，没读过就是 None
        "last_read": None,
        # 累计阅读秒数
        "total_time_seconds": 0,
        # 每次阅读会话的记录
        "sessions": [],
        # 书签列表
        "bookmarks": [],
        # 是否标记为"已读完"
        "finished": False,
    }


def normalise_bookmarks(raw: Any) -> List[Dict[str, Any]]:
    """Return a clean, line ordered ``bookmarks`` list.

    Plain integers are accepted as well as full records, so a hand written
    ``"bookmarks": [12, 40]`` still works.
    """
    # 规整后的书签
    marks: List[Dict[str, Any]] = []
    # 不是列表（None、字典等）就当作没有书签
    if isinstance(raw, list):
        for item in raw:
            # 完整记录形式：字典且带 line 字段
            if isinstance(item, dict) and item.get("line") is not None:
                # max(0, ...) 防止手改文件写出负数行号
                marks.append(
                    {
                        "line": max(0, int(item.get("line") or 0)),
                        "label": str(item.get("label") or ""),
                        "created": str(item.get("created") or ""),
                    }
                )
            # 简写形式：直接写一个行号
            elif isinstance(item, int):
                marks.append({"line": max(0, item), "label": "", "created": ""})
    # 按行号升序排，保证书签列表稳定有序
    marks.sort(key=lambda mark: mark["line"])
    return marks


def empty_library() -> Dict[str, Any]:
    """Return a library document that contains no books yet."""
    # 顶层三个段落：书、统计、成就
    return {
        "books": {},
        "stats": {"total_books": 0, "total_read_time": 0, "daily_read_time": {}},
        "achievements": {"unlocked": [], "progress": {}},
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write *payload* to *path* atomically."""
    # 目录不存在就先建出来
    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写同目录的临时文件
    temporary = path.with_name(path.name + ".tmp")
    # UTF-8 打开，ensure_ascii=False 让中文原样写、indent=2 方便人看
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        # 结尾补一个换行
        handle.write("\n")
    # 原子改名成正式文件
    os.replace(str(temporary), str(path))


def _today() -> str:
    # 今天的日期字符串，形如 2026-09-21
    return datetime.now().strftime("%Y-%m-%d")


def _normalise_book(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return *record* with every documented field present."""
    # 先用一份"带默认值的干净记录"打底，缺字段就自动补上
    book: Dict[str, Any] = {
        "title": str(record.get("title") or "untitled"),
        "author": str(record.get("author") or "unknown"),
        "file_path": str(record.get("file_path") or ""),
        "encoding": str(record.get("encoding") or "utf-8"),
        "total_lines": int(record.get("total_lines") or 0),
        "total_words": int(record.get("total_words") or 0),
        "chapters": [],
        "progress": empty_progress(),
        "tags": [],
        "import_date": str(record.get("import_date") or ""),
    }
    # 章节列表：只保留形状正确的项
    chapters = record.get("chapters") or []
    if isinstance(chapters, list):
        for chapter in chapters:
            if isinstance(chapter, dict):
                book["chapters"].append(
                    {
                        "title": str(chapter.get("title") or ""),
                        "line_start": int(chapter.get("line_start") or 0),
                    }
                )
    # 进度：以 empty_progress 为模板，只吸收文件里出现过的键
    progress = record.get("progress")
    if isinstance(progress, dict):
        known = empty_progress()
        # 这样多出来的野字段会被丢掉，缺失的字段保持默认值
        book["progress"].update(
            {key: progress[key] for key in known if key in progress}
        )
    # 书签单独规整（支持简写的纯行号）
    book["progress"]["bookmarks"] = normalise_bookmarks(
        book["progress"].get("bookmarks")
    )
    # finished 强制成 bool，避免文件里写成字符串
    book["progress"]["finished"] = bool(book["progress"].get("finished"))
    # 标签：允许写成逗号分隔的字符串，统一成去空白的列表
    tags = record.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    book["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
    return book


def load_library() -> Dict[str, Any]:
    """Load the whole library document, filling in anything missing."""
    # 索引文件位置：~/.wreader/library.json
    path = config.library_file()
    # 第一次运行还没有索引：返回空书库
    if not path.exists():
        return empty_library()
    try:
        # UTF-8 读进来并解析成 Python 对象
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except json.JSONDecodeError as exc:
        # 索引文件被写坏了：明确报错，不静默丢掉用户数据
        raise LibraryError("{} is not valid JSON: {}".format(path, exc)) from exc
    except OSError as exc:
        raise LibraryError("cannot read {}: {}".format(path, exc)) from exc
    # 顶层必须是对象
    if not isinstance(raw, dict):
        raise LibraryError("{} must contain a JSON object".format(path))

    # 以空书库为模板，把文件里的内容一项项填进去
    document = empty_library()
    books = raw.get("books")
    # 连 books 都没有说明文件结构不对
    if not isinstance(books, dict):
        raise LibraryError("{} is missing the 'books' mapping".format(path))
    # 每条书记录都过一遍 _normalise_book，补齐字段、过滤脏数据
    for book_id, record in books.items():
        if isinstance(record, dict):
            document["books"][str(book_id)] = _normalise_book(record)

    # 统计段落整体并入（里面可能有 total_read_time、daily_read_time 等）
    stats = raw.get("stats")
    if isinstance(stats, dict):
        document["stats"].update(stats)
        # daily_read_time 必须是字典，否则统计代码会崩
        if not isinstance(document["stats"].get("daily_read_time"), dict):
            document["stats"]["daily_read_time"] = {}
    # 成就段落整体并入
    achievements = raw.get("achievements")
    if isinstance(achievements, dict):
        document["achievements"].update(achievements)
    # A missing or stale counter is always recomputed on the way out.
    # 书数直接按实际记录数重算，避免计数器过期
    document["stats"]["total_books"] = len(document["books"])
    return document


def save_library(document: Dict[str, Any]) -> Path:
    """Write *document* to the index, keeping ``stats.total_books`` honest."""
    # 依次确保各段落存在（用 setdefault 只在缺失时才写入）
    document.setdefault("books", {})
    stats = document.setdefault("stats", {})
    stats.setdefault("total_read_time", 0)
    stats.setdefault("daily_read_time", {})
    stats.setdefault("translations", 0)
    # 写盘前刷新书目总数
    stats["total_books"] = len(document["books"])
    document.setdefault("achievements", {"unlocked": [], "progress": {}})
    # 目标文件路径
    path = config.library_file()
    # 原子写入
    _write_json(path, document)
    return path


def _title_key(item: Tuple[str, Dict[str, Any]]) -> Tuple[str, str]:
    """Sort key giving a stable, case insensitive title order."""
    # 解构出 (book_id, record)
    book_id, book = item
    # 先按标题小写排，标题相同时用 id 保证顺序稳定
    return str(book.get("title", "")).lower(), book_id


def get_book(book_id: str) -> Optional[Dict[str, Any]]:
    """Return the record for *book_id*, or ``None`` when it is unknown."""
    # 查不到返回 None，由调用方决定怎么提示
    return load_library()["books"].get(str(book_id))


def list_books() -> List[Tuple[str, Dict[str, Any]]]:
    """Return ``(book_id, record)`` pairs ordered by title."""
    # 按标题排序后的 (id, 记录) 列表
    return sorted(load_library()["books"].items(), key=_title_key)


def recent_books(limit: int = 3) -> List[Tuple[str, Dict[str, Any]]]:
    """Return the *limit* most recently read ``(book_id, record)`` pairs.

    Only books carrying a ``progress.last_read`` timestamp are listed, and the
    newest reading time comes first -- the shortlist behind ``werd continue``.
    """
    # 收集读过的书，形如 (last_read 时间戳, book_id, 记录)
    read: List[Tuple[str, str, Dict[str, Any]]] = []
    for book_id, book in load_library()["books"].items():
        # load_library 保证 progress 是 dict；这里再兜一层，防止手改的索引里有怪值
        progress = book.get("progress") or {}
        # last_read 是定长 ISO 字符串（YYYY-MM-DDTHH:MM:SS）；空或缺省 = 从没读过
        stamp = str(progress.get("last_read") or "")
        # 只有真正读过的书才进候选名单
        if stamp:
            read.append((stamp, str(book_id), book))
    # 时间戳是定长格式，字典序就是时间序，倒序排即"最近读的排最前"
    read.sort(key=lambda entry: entry[0], reverse=True)
    # 只取前 limit 本（负数/0 就返回空），并把排序用的时间戳从结果里丢掉
    return [(book_id, book) for _stamp, book_id, book in read[: max(0, int(limit))]]


def position_percentage(position: int, total_lines: int) -> float:
    """Return the progress of *position* as a percentage (0-100).

    The rule is ``(position + 1) / total_lines``, so the first line is a hair
    above zero and the **last line is exactly 100%**: reaching the end of a book
    reads as "finished" instead of "one line short".
    """
    # 总行数不合法就当 0%
    if total_lines <= 0:
        return 0.0
    # +1 是关键：读到最后一行时恰好 100%，不会显示 99.9%
    fraction = (max(0, int(position)) + 1) / float(total_lines)
    # 夹到 100 以内并保留一位小数
    return round(min(fraction * 100.0, 100.0), 1)


def progress_percent(book: Dict[str, Any]) -> float:
    """Return the reading progress of *book* as a percentage (0-100)."""
    # 取进度块（没有就当作空）
    progress = book.get("progress") or {}
    # 优先用记录里已存好的百分比（阅读器退出时算好写进去的）
    stored = progress.get("percentage")
    if stored:
        return round(float(stored), 1)
    # 没有存过的百分比，就用当前行号现算
    total = int(book.get("total_lines") or 0)
    current = int(progress.get("current_line") or 0)
    if total > 0 and current > 0:
        return position_percentage(current, total)
    # 既没存也没读过：0%
    return 0.0


def human_words(count: int) -> str:
    """Render a word count the way Chinese readers expect (``5.7万``)."""
    value = int(count)
    # 上亿就用"亿"
    if value >= 100000000:
        return "{:.1f}亿".format(value / 100000000.0)
    # 上万就用"万"
    if value >= 10000:
        return "{:.1f}万".format(value / 10000.0)
    # 否则直接显示数字
    return str(value)


def remove_book(book_id: str) -> Optional[Dict[str, Any]]:
    """Drop *book_id* from the index and delete its converted text file."""
    # 读出整个索引
    document = load_library()
    # pop 会同时"取出并删除"；不存在时返回 None
    book = document["books"].pop(str(book_id), None)
    if book is None:
        return None
    # 先把索引写回（索引是权威数据源）
    save_library(document)
    # 再删掉转换后的正文文件
    target = Path(str(book.get("file_path") or ""))
    # 空路径（""）的 name 也是空，跳过以免误删
    if target.name:
        try:
            target.unlink()
        except OSError:
            pass  # the index is authoritative, a missing file is not fatal
    return book


# 各种"换行/分段"字符：Windows CRLF、老 Mac CR、Unicode 行分隔符、垂直制表等
_LINE_BREAKS = re.compile(r"\r\n|\r|\u2028|\u2029|\x0b|\x0c|\x85")
# CJK 字符范围：日文假名 + 汉字扩展区 + 基本汉字 + 兼容汉字
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 拉丁单词：字母数字串，允许中间的 ' 或 -（don't、well-known 算一个词）
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019-][A-Za-z0-9]+)*")


def normalise_newlines(text: str) -> str:
    """Collapse every line separator to ``\\n`` and drop trailing blank lines."""
    # 所有换行变体统一成 \n，并去掉末尾多余的空行
    return _LINE_BREAKS.sub("\n", text or "").rstrip("\n")


# 认识的 BOM（字节序标记）：字节、对应解码器、正常情况下的编码名、解码失败时的编码名
# 顺序很重要：UTF-32 LE 的 BOM 是以 UTF-16 LE 的 BOM 开头的，宽的必须先试
#: Recognised byte order marks with the codec that consumes them and the label
#: reported to the caller.  Order matters: a UTF-32 LE BOM *starts with* the
#: UTF-16 LE BOM bytes, so the wider encoding has to be tested first.
_BOM_CODECS: Tuple[Tuple[bytes, str, str, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig", "UTF-8 (BOM)", "UTF-8 (replaced)"),
    (codecs.BOM_UTF32_LE, "utf-32", "UTF-32", "UTF-32 (replaced)"),
    (codecs.BOM_UTF32_BE, "utf-32", "UTF-32", "UTF-32 (replaced)"),
    (codecs.BOM_UTF16_LE, "utf-16", "UTF-16", "UTF-16 (replaced)"),
    (codecs.BOM_UTF16_BE, "utf-16", "UTF-16", "UTF-16 (replaced)"),
)


def detect_and_decode(path: Path) -> Tuple[str, str]:
    """Read *path* and return ``(text, encoding)``.

    The encoding comes from a BOM when there is one, otherwise from
    :mod:`chardet`.  A wrong guess falls back to UTF-8 and then GB18030, and as
    a last resort the bytes are decoded with replacement so that a damaged file
    still imports instead of aborting the whole run.

    A BOM only states what the file *intends* to be, so it is never trusted
    blindly: a UTF-32 document opens with the UTF-16 BOM bytes, and a partly
    damaged UTF-16 file can carry an illegal surrogate.  The wider encoding is
    therefore tested first, and a BOM family that fails to decode falls back to
    replacement characters instead of raising.
    """
    try:
        # 一次性读入全部字节（章节文件通常几 MB，可以接受）
        raw = path.read_bytes()
    except OSError as exc:
        raise LibraryError("cannot read {}: {}".format(path, exc)) from exc

    # 第一优先：看文件开头的 BOM
    for bom, codec, label, replaced in _BOM_CODECS:
        # 不是这个 BOM 就试下一个
        if not raw.startswith(bom):
            continue
        try:
            # 按 BOM 声明的编码解码
            return raw.decode(codec), label
        except UnicodeDecodeError:
            # BOM 说了谎（文件后半段坏了）：用替换字符兜住，至少能读进来
            return raw.decode(codec, errors="replace"), replaced

    # 第二优先：让 chardet 猜
    guess = chardet.detect(raw) or {}
    # 候选顺序：chardet 的结果 -> utf-8 -> gb18030（中文小说最常见的两种）
    candidates: List[Optional[str]] = [guess.get("encoding"), "utf-8", "gb18030"]
    for candidate in candidates:
        # chardet 有时返回 None
        if not candidate:
            continue
        try:
            return raw.decode(candidate), candidate
        # 编码名不认识或解不了，就换下一个候选
        except (LookupError, UnicodeDecodeError):
            continue
    # 最后兜底：用 utf-8 + 替换字符，保证导入流程不会因为一个坏文件整体中断
    return raw.decode("utf-8", errors="replace"), "utf-8 (replaced)"


def count_words(text: str) -> int:
    """Count words: every CJK character once, Latin text by whitespace token."""
    # 中文按"字"算，英文按"词"算，两者相加
    return len(_CJK_RE.findall(text)) + len(_LATIN_WORD_RE.findall(text))


# 章节标题的识别规则：第一章 / 卷三 / Chapter 12，以及序章、楔子、番外这类固定词
#: Chapter headings: ``第一章`` / ``卷三`` / ``Chapter 12`` plus the usual specials.
CHAPTER_PATTERN = re.compile(
    r"^(?:"
    r"第\s*[0-9０-９一二三四五六七八九十百千万零两〇]+\s*[章回节卷集部篇]"
    r"|卷\s*[0-9０-９一二三四五六七八九十百千万零两〇]*"
    r"|序章|序言|序|楔子|引子|前言|后记|尾声|终章|番外|大结局"
    r"|(?:chapter|volume|part|book|prologue|epilogue|appendix)\b"
    r")",
    re.IGNORECASE,
)


def is_chapter_heading(line: str) -> bool:
    """Return ``True`` when *line* looks like a chapter heading."""
    # 去掉首尾空白
    stripped = line.strip()
    # 空行太长的一定不是标题（标题一般很短）
    if not stripped or len(stripped) > _MAX_CHAPTER_TITLE_LENGTH:
        return False
    # 带句号的说明是正文（正文常有"第一章里……"这种句子）
    if "。" in stripped:  # prose often starts with 第一章, a heading never has 。
        return False
    # 用上面的正则匹配行首
    return bool(CHAPTER_PATTERN.match(stripped))


def parse_chapters(lines: Sequence[str]) -> List[Dict[str, Any]]:
    """Return ``[{"title": ..., "line_start": ...}, ...]`` in reading order."""
    # 逐行扫，是标题就记下"标题文本 + 行号"，行号是 chapters 跳转的依据
    return [
        {"title": line.strip(), "line_start": index}
        for index, line in enumerate(lines)
        if is_chapter_heading(line)
    ]


# 文件名里的分隔符：半角连字符、各种 Unicode 破折号、全角减号
_FILENAME_SEPARATOR = re.compile(r"\s*[-\u2010-\u2015\uff0d]\s*")
# [作者] 书名 这种写法
_BRACKETED_AUTHOR = re.compile(r"^\[(?P<author>[^\]]+)\]\s*(?P<title>.+)$")
# 文件名里不允许出现的字符（含控制字符），后面替换成下划线

_ILLEGAL_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# 下载站常挂在真标题后面的尾注，如 （校对版全本）/(annotated)
# 只删"结尾处"的括号组，所以正文本来带括号的书名不会被误伤
#: Trailing ``（校对版全本）`` / ``(annotated)`` style groups that download sites
#: append after the real title.  Only *trailing* groups are dropped, so a title
#: that legitimately carries brackets stays intact.
_TRAILING_ANNOTATION = re.compile(r"\s*[（(][^（）()]*[）)]\s*$")

# 文件名结尾的 "作者：某人"，冒号可能是全角或半角
#: ``作者：某人`` at the end of a file name; the colon may be full width or ASCII.
_AUTHOR_MARKER = re.compile(r"[\s_\-|]*作者\s*[:：]\s*(?P<author>.+?)\s*$")


def strip_annotations(name: str) -> str:
    """Drop trailing ``（校对版全本）`` style annotations from *name*.

    ``《三体》（修订版）`` becomes ``《三体》`` and ``书名(a)(b)`` becomes ``书名``.
    A group that is not at the end of the text is left alone, so ``书名（中）下册``
    keeps its brackets.
    """
    # 先去掉首尾空白
    cleaned = str(name or "").strip()
    # 循环删除：像 书名(a)(b) 需要删两次才能删干净
    while True:
        trimmed = _TRAILING_ANNOTATION.sub("", cleaned).strip()
        # 这一轮没变化，说明已经没有尾注了
        if trimmed == cleaned:
            return cleaned
        cleaned = trimmed


def split_author_marker(name: str) -> Tuple[str, str]:
    """Split ``《书名》（校对版全本）作者：某人`` into the rest and ``某人``.

    Returns ``(name, "")`` when the file name carries no ``作者：`` marker.  An
    annotation trailing the author name itself is dropped as well, so
    ``作者：某人（校对版）`` yields an author of ``某人``.
    """
    text = str(name or "")
    # 找结尾的 "作者：xxx"
    match = _AUTHOR_MARKER.search(text)
    # 没有这个标记：原样返回，作者留空
    if match is None:
        return text, ""
    # 作者名去掉尾注和书名号
    author = strip_annotations(match.group("author")).strip("《》").strip()
    # 标记之前的部分就是书名，顺手去掉结尾的分隔符
    rest = text[: match.start()].strip().rstrip("_|-").strip()
    return rest, author


def _clean_title(text: str) -> str:
    """Drop the trailing annotations and the ``《》`` wrapper from a title."""
    # 去尾注 + 去掉两端的书名号
    return strip_annotations(text).strip("《》").strip()


def _looks_like_author_title(name: str, separator: "re.Match") -> bool:
    """Decide whether *separator* really splits a ``作者-书名`` file name.

    ``Spider-Man`` has to stay one title, so the split is only trusted when the
    separator is spaced out or the left hand side carries CJK text.
    """
    # 匹配到的分隔符长度大于 1，说明连同空格一起匹配了（" - "），肯定是在分隔
    if len(separator.group(0)) > 1:  # the pattern swallowed whitespace
        return True
    # 否则只有分隔符左边含中文时才认为是 "作者-书名"（英文的 Spider-Man 必须保住）
    return bool(_CJK_RE.search(name[: separator.start()]))


def parse_filename(stem: str) -> Tuple[str, str]:
    """Extract ``(title, author)`` from a file name.

    The documented shapes are ``作者-书名`` and plain ``书名``; ``[作者] 书名`` and
    ``《书名》（校对版全本）作者：某人`` are accepted as well because downloaded
    collections use them constantly.  Trailing ``（…）`` / ``(...)`` annotations
    are always dropped, so they never reach the library.
    """
    # 去掉首尾空白后的原始文件名（不含扩展名）
    name = stem.strip()

    # 优先试 [作者] 书名 这种最明确的写法
    bracketed = _BRACKETED_AUTHOR.match(name)
    if bracketed:
        title = _clean_title(bracketed.group("title"))
        author = strip_annotations(bracketed.group("author")).strip()
        # 两边都非空才采信这个解析结果
        if title and author:
            return title, author

    # 再试结尾带 "作者：xxx" 的写法
    remaining, marked_author = split_author_marker(name)
    if marked_author and remaining:
        title = _clean_title(remaining)
        if title:
            return title, marked_author
        # The name was nothing but an annotation: a raw title beats an empty one.
        # 剩下部分只是个括号注释：标题宁可保留原文，也不要空
        return remaining.strip("《》").strip(), marked_author

    # 再试 "作者-书名"（用连字符分隔）
    separator = _FILENAME_SEPARATOR.search(name)
    if separator is not None and _looks_like_author_title(name, separator):
        author = strip_annotations(name[: separator.start()]).strip()
        title = _clean_title(name[separator.end() :])
        if author and title:
            return title, author

    # 都不匹配：整个文件名当书名，作者标记为 unknown
    plain = _clean_title(name)
    return plain or name, "unknown"


def safe_filename(title: str) -> str:
    """Turn *title* into something usable as a file name."""
    # 非法字符换成下划线，并去掉收尾的空格和点（点结尾在 Windows 上会被吞）
    cleaned = _ILLEGAL_FILENAME.sub("_", title).strip().strip(".")
    # 全被清空了就兜个名字
    return cleaned or "untitled"


def unique_path(directory: Path, base: str, suffix: str) -> Path:
    """Return a free path inside *directory* for ``base + suffix``."""
    # 先直接试 base+suffix
    candidate = directory / (base + suffix)
    # 重名就从 2 开始编号，如 书名_utf8(2).txt
    counter = 2
    while candidate.exists():
        candidate = directory / "{}({}){}".format(base, counter, suffix)
        counter += 1
    return candidate


def collect_candidates(path: str) -> List[Path]:
    """Return the ``.txt`` / ``.epub`` files found at *path*.

    *path* may be a single book file or a directory that is searched
    recursively.  Hidden files (macOS ``._book.txt`` forks, ``.DS_Store``) are
    skipped.
    """
    # 展开 ~ 得到真实路径
    target = Path(path).expanduser()
    # 路径不存在：直接报错，比静默导入 0 本更好排错
    if not target.exists():
        raise LibraryError("path does not exist: {}".format(target))
    # 情况一：给的是单个文件
    if target.is_file():
        # 后缀必须是 .txt/.epub
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise LibraryError(
                "unsupported file type: {} (expected .txt or .epub)".format(target.name)
            )
        return [target]
    # 既不是文件也不是目录（比如设备文件）也不支持
    if not target.is_dir():
        raise LibraryError("not a file or directory: {}".format(target))
    # 情况二：给的是目录，递归找出所有支持的书籍文件
    candidates = [
        item
        for item in target.rglob("*")
        if item.is_file()
        # 后缀匹配（大小写不敏感）
        and item.suffix.lower() in SUPPORTED_EXTENSIONS
        # 跳过隐藏文件：macOS 的 ._xxx 影子文件和 .DS_Store
        and not item.name.startswith(".")
    ]
    # 按路径小写排序，保证每次导入的顺序一致
    return sorted(candidates, key=lambda item: str(item).lower())


def _run_external_epub_tool(source: Path, destination: Path) -> Optional[str]:
    """Run the external converters in order; return the tool that produced text."""
    # 按 EPUB_TOOLS 的顺序逐个尝试
    for tool in EPUB_TOOLS:
        # which 返回可执行文件的绝对路径，没装就是 None
        executable = shutil.which(tool)
        if not executable:
            continue
        try:
            # 跑 <工具> <源文件> <目标文件>，最多等 15 分钟
            completed = subprocess.run(
                [executable, str(source), str(destination)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=900,
            )
        except (OSError, subprocess.SubprocessError):
            # 工具跑不起来（权限、超时等）：换下一个
            continue
        # 最理想：工具自己把文件写出来了
        if destination.exists() and destination.stat().st_size > 0:
            return tool
        # epub2txt prints to stdout in some builds instead of writing a file.
        # 某些版本的 epub2txt 把结果打到 stdout：那就自己写文件
        if completed.returncode == 0 and completed.stdout:
            text = completed.stdout.decode("utf-8", errors="replace")
            if text.strip():
                destination.write_text(text, encoding="utf-8")
                return tool
    # 所有外部工具都没成功
    return None


def _local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix from an XML tag."""
    # ElementTree 把带命名空间的标签写成 "{ns}tag"，这里只要后面的 tag 并转小写
    return tag.rsplit("}", 1)[-1].lower()


def _epub_content_files(archive: zipfile.ZipFile) -> List[str]:
    """Return the content documents of *archive*, in spine order when possible."""
    # zip 里所有文件的路径
    names = set(archive.namelist())
    # 兜底方案：把所有 html/xhtml 按文件名排序
    documents = sorted(
        name for name in names if name.lower().endswith((".xhtml", ".html", ".htm"))
    )

    # 尝试按 epub 规范找到"阅读顺序"：先读 META-INF/container.xml 找 opf 位置
    package_path = None
    container = "META-INF/container.xml"
    if container in names:
        try:
            container_root = ElementTree.fromstring(archive.read(container))
        except ElementTree.ParseError:
            # container.xml 坏了就退回文件名排序
            container_root = None
        if container_root is not None:
            # 遍历 XML 节点，找 <rootfile full-path="...">
            for node in container_root.iter():
                if _local_name(node.tag) == "rootfile" and node.get("full-path"):
                    package_path = node.get("full-path")
                    break
    # 没有 opf（或它不在包里）：直接用兜底顺序
    if not package_path or package_path not in names:
        return documents

    try:
        # 解析 opf 文件
        package = ElementTree.fromstring(archive.read(package_path))
    except ElementTree.ParseError:
        return documents

    # manifest：id -> href，描述"这个 id 对应哪个文件"
    manifest: Dict[str, str] = {}
    for node in package.iter():
        item_id = node.get("id")
        href = node.get("href")
        if _local_name(node.tag) == "item" and item_id and href:
            manifest[item_id] = href

    # opf 所在目录，spine 里的 href 是相对它的
    base = posixpath.dirname(package_path)
    # spine 里的 <itemref idref="..."> 决定真正的阅读顺序
    order = []
    for node in package.iter():
        if _local_name(node.tag) != "itemref":
            continue
        # 通过 idref 反查 href
        itemref = node.get("idref")
        href = manifest.get(itemref) if itemref else None
        if not href:
            continue
        # 把相对路径规范化成 zip 内的绝对路径
        resolved = posixpath.normpath(posixpath.join(base, href)) if base else href
        # 只收真实存在的文件
        if resolved in names:
            order.append(resolved)
    # spine 解析失败（空列表）时退回文件名排序
    return order or documents


# <script>/<style> 整段连同内容一起删掉（不删的话 JS/CSS 会混进正文）
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
# <br> 变体统一换成换行
_LINE_BREAK_TAG = re.compile(r"(?i)<br\s*/?>")
# 这些块级标签的结束标签也要换成换行，保证段落感
_BLOCK_END = re.compile(
    r"(?i)</(?:p|div|h[1-6]|li|tr|section|article|blockquote|title)\s*>"
)
# 剩下的标签一律删掉
_ANY_TAG = re.compile(r"<[^>]*>")


def html_to_text(markup: str) -> str:
    """Strip *markup* down to plain text, one block per line."""
    # 第一步：去掉脚本和样式
    text = _SCRIPT_STYLE.sub("", markup)
    # 第二步：<br> 换成换行
    text = _LINE_BREAK_TAG.sub("\n", text)
    # 第三步：块级标签结束也换成换行
    text = _BLOCK_END.sub("\n", text)
    # 第四步：删掉其余标签
    text = _ANY_TAG.sub("", text)
    # 第五步：把 &amp;、&nbsp; 之类的实体还原成字符
    text = html.unescape(text)
    # 最后逐行去空白、丢掉空行，用换行重新拼起来
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def extract_epub_builtin(source: Path) -> str:
    """Extract the text of *source* using only the standard library."""
    try:
        # epub 就是 zip，直接打开
        archive = zipfile.ZipFile(str(source))
    except (OSError, zipfile.BadZipFile) as exc:
        # 不是合法 zip：报错并说明原因
        raise LibraryError(
            "{} is not a readable epub: {}".format(source.name, exc)
        ) from exc
    # with 保证 zip 句柄被关闭
    with archive:
        # 每个 XHTML 文档提取出的纯文本
        chunks = []
        for name in _epub_content_files(archive):
            try:
                # 按 epub 规范正文是 UTF-8；解不了就用替换字符兜住
                markup = archive.read(name).decode("utf-8", errors="replace")
            except KeyError:
                # 上面列出的文件实际读不到（少见）：跳过
                continue
            text = html_to_text(markup)
            # 非空才保留
            if text:
                chunks.append(text)
    # 各章之间用换行连接
    return "\n".join(chunks)


def extract_epub(source: Path, destination: Path) -> str:
    """Write the body of *source* into *destination*; return the method used.

    ``ebook-convert`` and ``epub2txt`` win when they are installed because they
    honour the book's own structure; otherwise a small built-in extractor reads
    the epub as what it is, a zip of XHTML documents.
    """
    # 目标目录先建好
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 先试外部工具（效果通常更好）
    tool = _run_external_epub_tool(source, destination)
    if tool:
        # 返回用的是哪个工具，会记进书的 encoding 字段
        return tool
    # 外部工具都不在：用内置提取器
    destination.write_text(extract_epub_builtin(source), encoding="utf-8")
    return "builtin"


def load_source_text(path: Path) -> Tuple[str, str]:
    """Return ``(text, source_encoding)`` for a ``.txt`` or ``.epub`` file."""
    # txt 直接按编码探测读
    if path.suffix.lower() != ".epub":
        return detect_and_decode(path)
    # epub 要先解出正文再探测编码
    with tempfile.TemporaryDirectory() as scratch:
        # 临时目录里放解出来的 txt，用完自动清理
        extracted = Path(scratch) / "extracted.txt"
        method = extract_epub(path, extracted)
        text, encoding = detect_and_decode(extracted)
        if method == "builtin":
            encoding = "UTF-8"  # XHTML inside an epub is UTF-8 by specification
        return text, encoding


# 一次导入的结果汇总
@dataclass
class ImportResult:
    """Outcome of :func:`import_books`."""

    # 成功导入的 (book_id, 记录)
    imported: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    # 因为内容重复而跳过的文件
    duplicates: List[Path] = field(default_factory=list)
    # 失败的文件及原因
    failed: List[Tuple[Path, str]] = field(default_factory=list)

    @property
    def scanned(self) -> int:
        """Number of candidate files that were looked at."""
        # 扫描到的候选文件总数 = 成功 + 重复 + 失败
        return len(self.imported) + len(self.duplicates) + len(self.failed)


def write_utf8_text(text: str, title: str, directory: Path) -> Path:
    """Write *text* as UTF-8 to ``<directory>/<title>_utf8.txt``.

    The name is made file system safe and de-duplicated with a ``(2)`` suffix, so
    two different books sharing a title never overwrite each other.
    """
    # 目标目录（默认 ~/novels）不存在就建
    directory.mkdir(parents=True, exist_ok=True)
    # 文件名 = 安全的标题 + "_utf8"，重名会自动加 (2)/(3)
    destination = unique_path(directory, safe_filename(title) + "_utf8", ".txt")
    # 写入正文，末尾补一个换行
    destination.write_text(text + "\n", encoding="utf-8")
    return destination


def build_record(
    # 书名
    title: str,
    # 作者
    author: str,
    # 转成 UTF-8 后的正文路径
    file_path: Path,
    # 原文件的编码（或 epub 用的提取方式）
    encoding: str,
    # 正文全文
    text: str,
) -> Dict[str, Any]:
    """Assemble the index record for one imported book."""
    # 按换行切行：行号是阅读进度和章节跳转的基本单位
    lines = text.split("\n")
    # 组装索引记录，顺序与文件里的字段顺序一致
    return {
        "title": title,
        "author": author,
        "file_path": str(file_path),
        "encoding": encoding,
        "total_lines": len(lines),
        "total_words": count_words(text),
        "chapters": parse_chapters(lines),
        "progress": empty_progress(),
        "tags": [],
        "import_date": _today(),
    }


def import_books(path: str) -> ImportResult:
    """Scan *path*, convert every new book to UTF-8 and index it."""
    # 先找出所有候选书籍文件
    candidates = collect_candidates(path)
    # 读出现有索引，新书会直接加进这个字典
    document = load_library()
    books = document["books"]
    # 结果汇总
    result = ImportResult()

    # 逐个文件处理；单个失败不影响其它文件
    for candidate in candidates:
        try:
            # 读出正文和原编码（epub 会先解压）
            text, encoding = load_source_text(candidate)
        except (LibraryError, OSError, UnicodeError) as exc:
            # ``UnicodeError`` is not a ``LibraryError``: without it a single
            # undecodable file would abort the whole run instead of being
            # reported as failed (see ``detect_and_decode`` for the decoding).
            result.failed.append((candidate, str(exc)))
            continue
        # 换行统一成 \n
        text = normalise_newlines(text)
        # 全文只有空白（比如空文件）：算失败
        if not text.strip():
            result.failed.append((candidate, "no text content"))
            continue

        # 用正文的 SHA-1 当 id：内容一样就是同一本书
        book_id = hashlib.sha1(text.encode("utf-8")).hexdigest()[:_ID_LENGTH]
        # 已经在库里：记成重复，不重复导入
        if book_id in books:
            result.duplicates.append(candidate)
            continue

        # 从文件名解析书名和作者
        title, author = parse_filename(candidate.stem)
        try:
            # 把正文以 UTF-8 写进 novels 目录
            destination = write_utf8_text(text, title, config.novels_dir())
        except OSError as exc:
            # 磁盘写不了（满/权限）：记失败继续下一个
            result.failed.append((candidate, str(exc)))
            continue

        # 组装索引记录
        record = build_record(title, author, destination, encoding, text)
        books[book_id] = record
        result.imported.append((book_id, record))

    # 只要有新书入库，就把索引写回磁盘
    if result.imported:
        save_library(document)
    return result


def _is_subsequence(needle: str, haystack: str) -> bool:
    """Return ``True`` when *needle* appears in *haystack* in order."""
    # 把 haystack 变成迭代器：in 会顺序消耗，天然就是"子序列"判断
    iterator = iter(haystack)
    # 每个字符都要能在迭代器里按顺序找到，才算子序列
    return all(character in iterator for character in needle)


def _score_text(haystack: str, needle: str) -> int:
    """Score how well *needle* matches *haystack*; ``0`` means no match."""
    # 空字符串不参与匹配
    if not haystack:
        return 0
    # 统一小写做大小写不敏感匹配
    text = haystack.lower()
    # 完全相同：最高分
    if text == needle:
        return 100
    # 以关键词开头：次高
    if text.startswith(needle):
        return 80
    # 关键词出现在中间：分数随位置递减（越靠前越相关）
    position = text.find(needle)
    if position >= 0:
        return 60 - min(position, 30)
    # 只能按"子序列"匹配（hptr -> Harry Potter）：给个低分
    if _is_subsequence(needle, text):
        return 20
    # 完全匹配不上
    return 0


def _book_score(book: Dict[str, Any], needle: str, tags_only: bool) -> int:
    """Score a whole record, weighing the title highest."""
    tags = book.get("tags") or []
    # 只搜标签的模式（关键词以 # 开头）
    if tags_only:
        # 没有任何标签时默认 0
        return max((_score_text(str(tag), needle) for tag in tags), default=0)
    # 标题权重乘 2，因为按标题搜是最常见的诉求
    scores = [
        _score_text(str(book.get("title") or ""), needle) * 2,
        _score_text(str(book.get("author") or ""), needle),
    ]
    # 再把每个标签的得分也加进来
    scores.extend(_score_text(str(tag), needle) for tag in tags)
    # 取最高分作为这本书的得分
    return max(scores)


def search_books(
    # 搜索关键词
    keyword: str,
    # 传入书库文档可直接搜（不传就读磁盘）
    document: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """Fuzzy search by title, author or tag, best matches first.

    Matching is case insensitive and falls back to a subsequence match, so
    ``werd search hptr`` finds "Harry Potter".  A leading ``#`` restricts the
    search to tags (``werd search '#fantasy'``).  An empty keyword returns every
    book in title order; a keyword of just ``#`` returns nothing.
    """
    # 取书库里的 books 字典
    books = (document or load_library())["books"]
    # 先按标题排好，结果稳定
    rows = sorted(books.items(), key=_title_key)
    # 关键词去掉首尾空白
    needle = (keyword or "").strip()
    # 空关键词：按标题列出全部
    if not needle:
        return rows

    # 以 # 开头表示"只在标签里搜"
    tags_only = needle.startswith("#")
    if tags_only:
        needle = needle[1:].strip()
    # 只输入一个 # ：什么都不返回
    if not needle:
        return []
    # 统一小写
    needle = needle.lower()

    # 收集 (得分, 排序键, id, 记录)
    scored = []
    for book_id, book in rows:
        score = _book_score(book, needle, tags_only)
        # 得分 0 表示不匹配，直接丢掉
        if score:
            scored.append((score, _title_key((book_id, book)), book_id, book))
    # 先按得分降序（-item[0]），同分再按标题升序
    scored.sort(key=lambda item: (-item[0], item[1]))
    # 只对外返回 (id, 记录)
    return [(book_id, book) for _, _, book_id, book in scored]

"""Table of contents: chapter extraction, epub nav parsing and a rebuildable cache.

A book already knows its chapters: :func:`wreader.library.parse_chapters` stores
``chapters[].line_start`` at import time.  This module builds the richer,
user-facing *table of contents* the ``Tab`` overlay and ``werd toc`` show:

* every entry carries its **line** -- the very coordinate the pager jumps with --
  and a **percentage**, so the reader can see how far into the book each chapter
  starts,
* ``toc.patterns`` in ``settings.toml`` can add custom chapter regexes on top of
  the built-in rules,
* for epubs the ``nav``/``toc`` documents are read for their real titles,
* the result is cached at ``~/.wreader/cache/<book_id>_toc.json`` and rebuilt
  whenever the converted text changes (its mtime is the invalidation stamp).

Everything here is plain functions over plain data; the only I/O is the JSON
cache file, and every read is written so a missing or broken cache simply means
"rebuild it".
"""

# 延迟求值类型注解
from __future__ import annotations

# 缓存文件是 JSON
import json
# 自定义章节正则
import re
# epub 是 zip；nav/toc 是 XML
import zipfile
# zip 内的相对路径要按 POSIX 规则归一化
import posixpath
# 路径运算
from pathlib import Path
# 类型注解
from typing import Any, Dict, List, Optional, Sequence, Tuple
# 解析 nav.xhtml / toc.ncx
from xml.etree import ElementTree

# 同包引用：缓存目录（config）与章节判定 / 百分比（library）
from . import config, library

# 对外暴露的接口
__all__ = [
    "TOC_CACHE_SUFFIX",
    "build_toc",
    "build_toc_from_epub",
    "extra_patterns",
    "filter_toc",
    "load_toc",
    "parse_nav",
    "save_toc",
    "source_mtime",
    "toc_cache_path",
]

#: Suffix of the cache file: ``<cache>/<book_id>_toc.json``.
# 缓存文件名后缀；data 目录下 cache/<book_id>_toc.json
TOC_CACHE_SUFFIX = "_toc.json"


def toc_cache_path(book_id: str, settings: Optional[config.Config] = None) -> Path:
    """Return the path of one book's table-of-contents cache."""
    # 缓存根目录下按 "<book_id>_toc.json" 命名；与 translator 的 <book_id>/ 子目录不冲突
    return config.cache_dir(settings) / "{}{}".format(book_id, TOC_CACHE_SUFFIX)


def extra_patterns(settings: Optional[config.Config] = None) -> str:
    """Return the raw ``toc.patterns`` string from the settings."""
    # 没传设置就现加载一份
    settings = settings or config.load_config()
    # 读配置里的字面值（空串 = 没有自定义规则）
    return str(settings.get("toc.patterns") or "")


def compile_patterns(extra: str) -> List[re.Pattern[str]]:
    """Compile the user's extra chapter regexes.

    Several regexes may be written on one line separated by ``|`` or on several
    lines.  A regex that does not compile is dropped rather than raising: a typo
    in ``settings.toml`` must not make the reader unusable.
    """
    # 空配置：没有任何额外规则
    if not extra:
        return []
    # 竖线或换行都能当分隔符，方便在 TOML 里写一行或写多行
    pieces = re.split(r"[|\n]", str(extra))
    compiled: List[re.Pattern[str]] = []
    for piece in pieces:
        pattern = piece.strip()
        # 空段（比如结尾多写了个 |）跳过
        if not pattern:
            continue
        try:
            # 与内置规则一致：只匹配行首
            compiled.append(re.compile(pattern))
        except re.error:
            # 写错的正则直接忽略
            continue
    return compiled


def _is_heading(line: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Return ``True`` when *line* is a chapter heading under any rule."""
    # 内置规则（第X章 / Chapter N / 卷…）先判
    if library.is_chapter_heading(line):
        return True
    # 再看用户自定义正则：同样匹配去空白后的行首
    stripped = line.strip()
    return any(pattern.match(stripped) for pattern in patterns)


def build_toc(lines: Sequence[str], extra: str = "") -> List[Dict[str, Any]]:
    """Return ``[{"title", "line", "percentage"}, ...]`` in reading order."""
    # 自定义正则只编译一次，别在循环里重复编
    patterns = compile_patterns(extra)
    # 全书行数：用来把章节起点换算成百分比
    total = len(lines)
    # 逐行扫，命中就是一条目录项
    return [
        {
            "title": line.strip(),
            "line": index,
            # 复用 library 的百分比算法，让目录与状态栏进度一定一致
            "percentage": library.position_percentage(index, total),
        }
        for index, line in enumerate(lines)
        if _is_heading(line, patterns)
    ]


def filter_toc(entries: Sequence[Dict[str, Any]], needle: str) -> List[int]:
    """Return the indices of the entries whose title contains *needle*.

    Used by the overlay's ``/`` box: filtering is plain, case-insensitive
    substring matching (Chinese titles are unaffected).
    """
    # 空关键词 = 不过滤，直接给回全部下标
    text = str(needle or "").strip().lower()
    if not text:
        return list(range(len(entries)))
    # 逐条比对标题
    return [
        index
        for index, entry in enumerate(entries)
        if text in str(entry.get("title") or "").lower()
    ]


# -- epub navigation --------------------------------------------------------
def _resolve_href(nav_dir: str, href: str) -> str:
    """Resolve one nav href to a zip name (dropping any ``#fragment``)."""
    # 只看文件部分：锚点对行号没有意义
    clean = str(href or "").split("#", 1)[0].strip()
    if not clean:
        return ""
    # nav 文档里的链接是相对 nav 所在目录的
    return posixpath.normpath(posixpath.join(nav_dir, clean)) if nav_dir else clean


def _parse_nav_xhtml(markup: bytes, nav_dir: str) -> List[Tuple[str, str]]:
    """Read an EPUB3 nav document: ``<nav><ol><li><a href>title</a>``."""
    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError:
        return []
    # 逐个 <nav> 试：通常只有"目录"那个有链接
    for nav in root.iter():
        if library._local_name(nav.tag) != "nav":
            continue
        entries: List[Tuple[str, str]] = []
        for node in nav.iter():
            if library._local_name(node.tag) != "a":
                continue
            href = node.get("href") or ""
            # 标题要把嵌套标签之间的文字也取出来
            title = " ".join("".join(node.itertext()).split())
            resolved = _resolve_href(nav_dir, href)
            if title and resolved:
                entries.append((title, resolved))
        # 这个 nav 有内容就采用；否则继续找下一个
        if entries:
            return entries
    return []


def _parse_nav_ncx(markup: bytes, nav_dir: str) -> List[Tuple[str, str]]:
    """Read an EPUB2 ncx: ``<navPoint><navLabel><text>`` + ``<content src>``."""
    try:
        root = ElementTree.fromstring(markup)
    except ElementTree.ParseError:
        return []
    entries: List[Tuple[str, str]] = []
    for point in root.iter():
        if library._local_name(point.tag) != "navpoint":
            continue
        title = ""
        source = ""
        # 只看直接子节点：嵌套的 navPoint 会在自己那一轮被处理，避免重复
        for node in list(point):
            tag = library._local_name(node.tag)
            if tag == "navlabel" and not title:
                for text_node in node.iter():
                    if library._local_name(text_node.tag) == "text":
                        title = " ".join("".join(text_node.itertext()).split())
                        break
            elif tag == "content" and not source:
                source = node.get("src") or ""
        resolved = _resolve_href(nav_dir, source)
        if title and resolved:
            entries.append((title, resolved))
    return entries


def parse_nav(archive: zipfile.ZipFile) -> List[Tuple[str, str]]:
    """Return ``[(title, zip name), ...]`` from an epub's nav or ncx document.

    EPUB3 keeps its navigation in an XHTML document (``properties="nav"``), EPUB2
    in an ncx referenced from ``<spine toc="...">``.  Both are tried; an empty
    list means "no usable navigation", never an error.
    """
    # opf 决定 manifest/spine，也是 href 的解析基准
    package_path = library._epub_package_path(archive)
    if not package_path:
        return []
    try:
        package = ElementTree.fromstring(archive.read(package_path))
    except (ElementTree.ParseError, KeyError):
        return []
    # manifest：id -> href
    manifest: Dict[str, str] = {}
    nav_href = ""
    ncx_href = ""
    toc_id = ""
    for node in package.iter():
        tag = library._local_name(node.tag)
        if tag == "item":
            item_id = node.get("id")
            href = node.get("href")
            if item_id and href:
                manifest[item_id] = href
            # EPUB3：properties 里带 nav 的那个 item 就是导航文档
            if href and "nav" in (node.get("properties") or "").split():
                nav_href = href
            # EPUB2：ncx 按 media-type 认
            if href and (node.get("media-type") or "") == "application/x-dtbncx+xml":
                ncx_href = href
        elif tag == "spine":
            toc_id = node.get("toc") or ""
    # spine 上的 toc 属性指向 ncx（比 media-type 更可靠）
    if toc_id and toc_id in manifest:
        ncx_href = manifest[toc_id]
    # 先试 EPUB3 的 nav，再试 EPUB2 的 ncx
    for href, parser in ((nav_href, _parse_nav_xhtml), (ncx_href, _parse_nav_ncx)):
        if not href:
            continue
        # 解析出目标文档在 zip 里的真实路径
        document = _resolve_href(posixpath.dirname(package_path), href)
        if document not in archive.namelist():
            continue
        entries = parser(archive.read(document), posixpath.dirname(document))
        if entries:
            return entries
    return []


def _spine_layout(archive: zipfile.ZipFile) -> Tuple[Dict[str, int], int]:
    """Return ``(zip name -> first line, total lines)`` of the built-in layout.

    This mirrors exactly how :func:`library.extract_epub_builtin` concatenates
    the spine documents, so the numbers only line up with text produced by that
    built-in extractor -- an external converter lays the body out its own way.
    """
    # 文件名 -> 它在拼接正文里的起始行
    offsets: Dict[str, int] = {}
    line = 0
    for name, text in library.epub_spine_texts(archive):
        offsets[name] = line
        # 各文档之间用 \n 连接，所以下一个文档正好从 line + 本档行数 开始
        line += len(text.split("\n"))
    return offsets, line


def build_toc_from_epub(
    epub_path: Path, lines: Sequence[str], extra: str = ""
) -> List[Dict[str, Any]]:
    """Build a nav aware table of contents for an epub.

    The book's own ``nav``/``toc`` titles are preferred and mapped onto line
    numbers through the spine layout.  Whenever the nav is missing or the layout
    does not match the converted text (an external converter was used), this
    falls back to the plain regex scan of :func:`build_toc`.
    """
    # 兜底结果先算好，任何一步对不上就用它
    fallback = build_toc(lines, extra)
    try:
        archive = zipfile.ZipFile(str(epub_path))
    except (OSError, zipfile.BadZipFile):
        return fallback
    with archive:
        nav = parse_nav(archive)
        offsets, expected = _spine_layout(archive)
    # nav 没解析出来、或 spine 里没有文档：直接用正则结果
    if not nav or not offsets:
        return fallback
    # 正文不是内置提取器拼出来的（行数与 spine 布局对不上）：nav 的行号不可信
    if expected != len(lines):
        return fallback
    total = len(lines)
    entries: List[Dict[str, Any]] = []
    previous = -1
    for title, name in nav:
        line = offsets.get(name)
        # 指向的文档不在 spine 里，或行号倒挂：这一条不可信，整体退回正则
        if line is None or line < previous:
            return fallback
        entries.append(
            {
                "title": title,
                "line": line,
                "percentage": library.position_percentage(line, total),
            }
        )
        previous = line
    # nav 一条都没落下来：也用兜底
    return entries or fallback


# -- cache ------------------------------------------------------------------
def source_mtime(book: Dict[str, Any]) -> Optional[float]:
    """Return the modified time of the converted text behind *book*."""
    # 转换后的 UTF-8 正文路径记在索引里
    path = Path(str(book.get("file_path") or ""))
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _read_cache(book_id: str, settings: config.Config) -> Optional[Dict[str, Any]]:
    """Return the raw cache document, or ``None`` when it is missing or broken."""
    # 缓存文件就在 <cache>/<book_id>_toc.json
    path = toc_cache_path(book_id, settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 缓存坏了不是大事：当成没有，重建就是
        return None
    return raw if isinstance(raw, dict) else None


def _normalise_entries(raw: Any) -> List[Dict[str, Any]]:
    """Keep only well shaped ``{title, line, percentage}`` entries."""
    entries: List[Dict[str, Any]] = []
    # 不是列表（None、字典…）就当作空的
    if not isinstance(raw, list):
        return entries
    for item in raw:
        # 形状不对（不是字典）就丢掉
        if not isinstance(item, dict):
            continue
        # 明确成 Dict[str, Any]，类型检查器才知道取出来的是 Any
        record: Dict[str, Any] = item
        # 缺 line 的条目直接丢掉（0 是合法行号，不能当"缺失"）
        raw_line = record.get("line")
        if raw_line is None:
            continue
        try:
            # 行号必须是能转成整数的东西
            line = max(0, int(raw_line))
        except (TypeError, ValueError):
            continue
        try:
            # 百分比缺了就补 0
            percentage = float(record.get("percentage") or 0.0)
        except (TypeError, ValueError):
            percentage = 0.0
        entries.append(
            {
                "title": str(record.get("title") or ""),
                "line": line,
                "percentage": round(percentage, 1),
            }
        )
    return entries


def save_toc(
    book_id: str,
    entries: Sequence[Dict[str, Any]],
    mtime: Optional[float],
    source: Optional[Path] = None,
    settings: Optional[config.Config] = None,
) -> Path:
    """Write the cache file and return its path."""
    # 没传设置就现读一份（为了拿到缓存目录）
    settings = settings or config.load_config()
    path = toc_cache_path(book_id, settings)
    # 父目录可能还不存在（第一次运行时 cache/ 还没建）
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "book_id": str(book_id),
        # 失效判据：转换后正文的 mtime
        "mtime": mtime,
        # 源 epub 路径：留着以后 --rebuild 还能再读一次 nav
        "source": str(source) if source else "",
        "entries": [dict(entry) for entry in entries],
    }
    # 纯文本 JSON，用户随时能看、能删
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _read_lines(book: Dict[str, Any]) -> List[str]:
    """Return the converted text of *book*, split like the importer did."""
    # 与 reader.read_lines 用同一套规则，行号才对得上（这里不能 import reader：它有 curses）
    path = Path(str(book.get("file_path") or ""))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    # 必须先规范化换行
    text = library.normalise_newlines(text)
    # 空文件返回空列表
    return text.split("\n") if text else []


def load_toc(
    book_id: str,
    book: Dict[str, Any],
    settings: Optional[config.Config] = None,
    rebuild: bool = False,
) -> List[Dict[str, Any]]:
    """Return the table of contents of *book*, rebuilding it when needed.

    The cache is reused while the converted text is unchanged; ``rebuild=True``
    ignores it on purpose.  A missing or unreadable book text yields an empty
    list rather than an error.
    """
    # 没传设置就现读一份（缓存目录 + 自定义正则都要用）
    settings = settings or config.load_config()
    # 不强制重建时才看缓存
    cached = None if rebuild else _read_cache(book_id, settings)
    # 转换后正文的 mtime 是缓存是否过期的唯一判据
    mtime = source_mtime(book)
    # 缓存还有效：直接用，省一次全文扫描
    if cached is not None and mtime is not None and cached.get("mtime") == mtime:
        return _normalise_entries(cached.get("entries"))
    # 过期或缺失：读正文重建
    lines = _read_lines(book)
    if not lines:
        return []
    # 若当初记下了源 epub 且它还在，就再走一次 nav（行号才准）
    source = str((cached or {}).get("source") or "")
    entries = None
    if source and Path(source).is_file():
        entries = build_toc_from_epub(Path(source), lines, extra_patterns(settings))
    # 没有源 epub（或它已不在）：退化成纯正则
    if entries is None:
        entries = build_toc(lines, extra_patterns(settings))
    # 能拿到 mtime 才值得写缓存（拿不到说明正文本身有问题）
    if mtime is not None:
        save_toc(
            book_id,
            entries,
            mtime,
            source=Path(source) if source else None,
            settings=settings,
        )
    return entries




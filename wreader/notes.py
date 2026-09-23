"""Notes: one markdown file per book, plus an index for the list view.

The storage is deliberately boring plain text, because the project's hard rule is
that the user can always open the data with an editor:

* ``<data dir>/notes/<book_id>.md`` -- the notes themselves, one ``## 笔记 #N``
  section per note.  Markdown is *the* source of truth: :func:`load_notes` parses
  it back, so a note written by hand in an editor shows up like any other.
* ``<data dir>/notes/index.json`` -- a **derived cache** for the list view
  (title, count, last modified, preview).  It is regenerated from the markdown
  whenever it is missing or a note is saved, so it can never drift.

Everything here is plain data in and plain data out; the only side effects are
the note files and the index.  Writes take the shared file lock
(:mod:`wreader.lock`) so two terminals -- or two sessions on a machine you ssh
into -- cannot lose each other's notes.
"""

# 延迟求值类型注解
from __future__ import annotations

# 读写 index.json
import json
# os.replace 做原子替换
import os
# 解析 markdown 里的笔记小节
import re
# 导出时复制文件
import shutil
# 先写临时文件再替换，避免写一半被读到
import tempfile
# 时间戳与文件名里的时间
from datetime import datetime
# 路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, List, Optional

# 同包引用：数据目录 + 共用的文件锁
from . import config
from .lock import file_lock

# 模块对外暴露的名字
__all__ = [
    "DRAFT_SUFFIX",
    "INDEX_FILENAME",
    "NOTES_DIRNAME",
    "PREVIEW_LIMIT",
    "QUOTE_LIMIT",
    "NotesError",
    "clear_draft",
    "draft_file",
    "export_notes",
    "index_file",
    "list_all_notes",
    "load_draft",
    "load_notes",
    "note_count",
    "note_file",
    "notes_dir",
    "save_draft",
    "save_note",
    "update_index",
]

# 笔记目录名（放在数据目录下面，与 settings.toml / library.json 平级）
NOTES_DIRNAME = "notes"
# 列表页用的索引文件名
INDEX_FILENAME = "index.json"
# 未保存草稿的后缀（用于崩溃/断电后的恢复）
DRAFT_SUFFIX = ".draft.md"
# 引用原文最多写多少字，超出截断
QUOTE_LIMIT = 500
# index.json 里预览文字的截取长度
PREVIEW_LIMIT = 50

# 小节标题：``## 笔记 #3 — 2026-09-23 15:10``
_SECTION_RE = re.compile(r"^##\s*笔记\s*#(\d+)\s*[—–-]\s*(.*?)\s*$")
# 引用与正文的分界行
_MY_TEXT = "我的想法："
# 文件头的元数据行
_HEADER_ID = "书籍ID:"
_HEADER_CREATED = "创建时间:"
# 导出时的默认文件名模板
EXPORT_TEMPLATE = "notes_{}.md"
# 草稿文件的标题行（一眼能看出这不是正式笔记）
_DRAFT_TITLE = "未保存的草稿"


# 笔记读写失败（目录不可写、导出源不存在等）时抛这个异常
class NotesError(Exception):
    """Raised when the notes directory or a note file cannot be used."""


def notes_dir() -> Path:
    """Return the directory holding every note (``<data dir>/notes``)."""
    # 跟随数据目录，所以 $WREADER_HOME 一改，笔记也跟着走
    return config.data_dir() / NOTES_DIRNAME


def _slug(book_id: Any) -> str:
    """Return *book_id* as something safe to use as a file name."""
    # 书 id 本来是十六进制摘要；手改过的怪字符统一换成下划线
    return re.sub(r"[^A-Za-z0-9._-]", "_", str(book_id or "")) or "unknown"


def note_file(book_id: Any) -> Path:
    """Return the markdown file holding *book_id*'s notes."""
    return notes_dir() / "{}.md".format(_slug(book_id))


def draft_file(book_id: Any) -> Path:
    """Return the crash-recovery draft file for *book_id*."""
    return notes_dir() / "{}{}".format(_slug(book_id), DRAFT_SUFFIX)


def index_file() -> Path:
    """Return the derived index file used by ``werd notes``."""
    return notes_dir() / INDEX_FILENAME


def _strip_edges(lines: List[str]) -> List[str]:
    """Drop blank lines and stray ``---`` rules from both ends of *lines*."""
    # 先去掉首尾空行
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    # 再吃掉紧贴首尾的分隔线（用户手写的，或从别处粘来的）
    if start < end and lines[start].strip() == "---":
        start += 1
    if end > start and lines[end - 1].strip() == "---":
        end -= 1
    return lines[start:end]


def _split_body(body: List[str]) -> "tuple[str, str]":
    """Split one section body into ``(quote, content)`` using the ``我的想法：`` line."""
    lines = _strip_edges(body)
    for position, line in enumerate(lines):
        stripped = line.strip()
        # 分界行找到：上面的全是引用，下面的全是正文
        if stripped.startswith(_MY_TEXT):
            quote = "\n".join(lines[:position]).strip()
            # "我的想法：xxx" 挤在同一行时，那一小段也算正文
            inline = stripped[len(_MY_TEXT) :].strip()
            rest = "\n".join(lines[position + 1 :]).strip()
            content = "\n".join(part for part in (inline, rest) if part).strip()
            return quote, content
    # 没有分界行：整段都是引用（用户手写的文件可能就是这样）
    return "\n".join(lines).strip(), ""


def _make_note(index: int, moment: str, body: List[str]) -> Dict[str, Any]:
    """Build one note dict from its parsed pieces."""
    quote, content = _split_body(body)
    return {"index": index, "time": moment, "quote": quote, "content": content}


def parse_notes(text: str) -> List[Dict[str, Any]]:
    """Parse the markdown of one book into a list of notes.

    Sections are delimited by the ``## 笔记 #N`` headings, so a stray ``---``
    inside a note (or a hand-written paragraph) cannot confuse the parser.
    Anything before the first heading -- the file header -- is ignored.
    """
    notes: List[Dict[str, Any]] = []
    # 当前小节：``(序号, 时间)``；None 表示还没遇到第一个标题
    current: "Optional[tuple[int, str]]" = None
    body: List[str] = []
    for line in str(text or "").split("\n"):
        # 命中小节标题：先收掉上一条
        match = _SECTION_RE.match(line)
        if match:
            if current is not None:
                notes.append(_make_note(current[0], current[1], body))
            current = (int(match.group(1)), match.group(2))
            body = []
            continue
        # 标题之后的内容才算某条笔记的正文
        if current is not None:
            body.append(line)
    # 最后一条还没收尾
    if current is not None:
        notes.append(_make_note(current[0], current[1], body))
    return notes


def load_notes(book_id: Any) -> List[Dict[str, Any]]:
    """Return every note stored for *book_id* (empty list when there are none)."""
    path = note_file(book_id)
    # 还没写过笔记：这是正常情况，不是错误
    if not path.is_file():
        return []
    try:
        # 笔记一律 UTF-8（中文路径与中文内容都靠它）
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise NotesError("cannot read {}: {}".format(path, exc)) from exc
    return parse_notes(text)


def note_count(book_id: Any) -> int:
    """Return how many notes *book_id* has on disk."""
    # 以 markdown 文件为准（index.json 只是缓存）
    return len(load_notes(book_id))


def _clip_quote(text: Any) -> str:
    """Return *text* trimmed and clipped to :data:`QUOTE_LIMIT` characters."""
    quote = str(text or "").strip()
    # 超长引用截断并加省略号（规格：最多 500 字）
    if len(quote) > QUOTE_LIMIT:
        return quote[:QUOTE_LIMIT] + "..."
    return quote


def _header(book_id: Any, book_title: Any, moment: datetime) -> str:
    """Return the file header written when a book's note file is created."""
    title = str(book_title or "").strip() or str(book_id)
    return (
        "# {}\n\n{} {}\n{} {}\n\n".format(
            title,
            _HEADER_ID,
            book_id,
            _HEADER_CREATED,
            moment.isoformat(timespec="seconds"),
        )
    )


def _section(index: int, moment: datetime, quote: str, content: str) -> str:
    """Return the markdown block for one note."""
    # 时间用"年月日 时分"，比 ISO 更适合人读；-- 只是排版
    stamp = moment.strftime("%Y-%m-%d %H:%M")
    # 没有引用时就不写那一段（只留"我的想法"）
    quote_block = "{}\n\n".format(quote) if quote else ""
    return "## 笔记 #{:d} — {}\n\n{}{}\n{}\n\n".format(
        index, stamp, quote_block, _MY_TEXT, content
    )


def _write_text(path: Path, text: str) -> Path:
    """Write *text* to *path* atomically, creating the directory if needed."""
    # 目录不存在就先建（第一次用笔记功能时就是这种情况）
    path.parent.mkdir(parents=True, exist_ok=True)
    # 同目录的临时文件 + os.replace：读到一半也不会有半截内容
    handle, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        # 原子替换（同一文件系统内是原子的）
        os.replace(temp_name, path)
    except OSError:
        # 写失败就清掉临时文件，别在笔记目录里留垃圾
        try:
            os.unlink(temp_name)
        except OSError:  # pragma: no cover - 临时文件已经不在了
            pass
        raise
    return path


# ---------------------------------------------------------------------- index
def _read_index() -> Dict[str, Dict[str, Any]]:
    """Return the index as ``{book_id: entry}``, tolerating a broken file."""
    path = index_file()
    # 还没生成过索引：空表（调用方会顺手重建）
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # 索引是**派生数据**，坏了就从 .md 重建，不必打扰用户
        return {}
    # 顶层必须是字典，条目必须是字典
    if not isinstance(raw, dict):
        return {}
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}


def _write_index(entries: Dict[str, Dict[str, Any]]) -> Path:
    """Write the index atomically (the caller holds the lock)."""
    # ensure_ascii=False 让中文书名在文件里可读
    text = json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return _write_text(index_file(), text)


def _title_from_file(book_id: Any) -> str:
    """Return the book title recorded in the note file header, if any."""
    path = note_file(book_id)
    if not path.is_file():
        return ""
    try:
        # 只读开头一点点就够：文件头就是最前面几行
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    for line in text.split("\n"):
        # 第一个一级标题就是书名
        if line.startswith("# "):
            return line[2:].strip()
        # 空行之外的第一行还没找到标题：说明文件头不完整，放弃
        if line.strip():
            break
    return ""


def _preview_of(note: Dict[str, Any]) -> str:
    """Return the one-line preview shown by ``werd notes``."""
    # 优先用"我的想法"，没有就退回引用
    body = str(note.get("content") or note.get("quote") or "")
    # 压成一行，免得列表里出现换行
    flat = " ".join(body.split())
    return flat[:PREVIEW_LIMIT]


def _entry_for(
    book_id: Any,
    title: Optional[Any] = None,
    preview: Optional[str] = None,
    notes: Optional[List[Dict[str, Any]]] = None,
    modified: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build one index entry from the book's markdown file.

    Everything here is *derived*: ``count`` comes from the notes actually in the
    file, so deleting a note by hand cannot leave a stale number behind.
    """
    stored = notes if notes is not None else load_notes(book_id)
    last = stored[-1] if stored else {}
    # 书名：调用方给的优先，其次文件头，最后退回 id
    name = str(title or "").strip() or _title_from_file(book_id) or str(book_id)
    # 最后修改时间：优先用笔记文件的时间戳（手改文件也算），否则用本次时间
    path = note_file(book_id)
    try:
        stamp = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        stamp = (modified or datetime.now()).isoformat(timespec="seconds")
    return {
        "title": name,
        "count": len(stored),
        "last_modified": stamp,
        "preview": preview if preview is not None else _preview_of(last),
    }


# ----------------------------------------------------------------------- write
def save_note(
    book_id: Any,
    book_title: Any,
    quote_text: Any,
    user_text: Any,
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    """Append one note to ``<book_id>.md`` and refresh the index.

    Returns the stored note (``{index, time, quote, content}``), or ``None`` when
    there is nothing to store -- an empty quote **and** an empty body is a no-op,
    not an error.  The file is opened in append mode, so an existing file is never
    overwritten; the header is only written when the file is created.

    The append and the index rewrite happen under **one** lock: the notes
    directory is serialised as a whole, which sidesteps any lock ordering problem
    between the note file and the index.
    """
    # 引用先按长度截断
    quote = _clip_quote(quote_text)
    # 正文去掉首尾空白（中间的换行保留）
    content = str(user_text or "").strip()
    # 两边都空：按规格"跳过不写"
    if not quote and not content:
        return None
    # 时间戳：测试可注入固定时刻
    moment = now or datetime.now()
    path = note_file(book_id)
    try:
        with file_lock(index_file()):
            # 读现有内容：既用来算序号，也用来判断要不要补文件头
            raw = path.read_text(encoding="utf-8") if path.is_file() else ""
            existing = parse_notes(raw)
            # 序号 = 现有最大序号 + 1（不靠容易漂移的计数）
            index = max((int(note.get("index") or 0) for note in existing), default=0) + 1
            block = _section(index, moment, quote, content)
            if not raw:
                # 第一次写这本书：先落文件头
                block = _header(book_id, book_title, moment) + block
            elif not raw.endswith("\n"):
                # 用户手改过、末尾没换行：补一个，免得和下一条粘在一起
                block = "\n" + block
            # 目录不存在就先建，然后**追加**写入
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(block)
            # 这一条的结构化形式（与 load_notes 的返回形状一致）
            note = {
                "index": index,
                "time": moment.strftime("%Y-%m-%d %H:%M"),
                "quote": quote,
                "content": content,
            }
            # 顺手刷新索引（已经在锁里，所以走不加锁的内部函数）
            entries = _read_index()
            entries[_slug(book_id)] = _entry_for(
                book_id,
                title=book_title,
                preview=_preview_of(note),
                notes=existing + [note],
            )
            _write_index(entries)
    except (OSError, UnicodeDecodeError) as exc:
        raise NotesError("cannot write {}: {}".format(path, exc)) from exc
    return note


# ---------------------------------------------------------------------- drafts
def save_draft(book_id: Any, quote_text: Any, user_text: Any) -> Optional[Path]:
    """Persist an un-committed draft so a crash cannot lose the text.

    This is **not** a note: it is the crash-recovery copy of what is still being
    typed in the panel.  Committing (``Ctrl+S``, or closing the panel with
    unsaved text) writes a real note and clears the draft.  An empty draft deletes
    the file instead of writing an empty one, so a stale draft never comes back.
    """
    quote = _clip_quote(quote_text)
    content = str(user_text or "").strip()
    # 没内容就把旧草稿清掉，别让它下次又冒出来
    if not quote and not content:
        clear_draft(book_id)
        return None
    # 草稿是给人也能直接打开看的小 markdown
    text = "# {}\n\n{}\n\n{}\n{}\n".format(_DRAFT_TITLE, quote, _MY_TEXT, content)
    try:
        return _write_text(draft_file(book_id), text)
    except OSError as exc:
        raise NotesError("cannot write the draft: {}".format(exc)) from exc


def load_draft(book_id: Any) -> Dict[str, str]:
    """Return the un-committed draft as ``{"quote": ..., "text": ...}``."""
    path = draft_file(book_id)
    # 没有草稿：返回空内容，调用方按"全新一条"处理
    if not path.is_file():
        return {"quote": "", "text": ""}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # 草稿坏了不是大事：当作没有，绝不能因此挡着面板打开
        return {"quote": "", "text": ""}
    lines = text.split("\n")
    # 丢掉 "# 未保存的草稿" 那行标题
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    quote, content = _split_body(lines)
    return {"quote": quote, "text": content}


def clear_draft(book_id: Any) -> None:
    """Delete the draft file for *book_id*, ignoring a missing one."""
    try:
        draft_file(book_id).unlink()
    except OSError:
        # 本来就没有（或删不掉）：无所谓，草稿丢了不影响正式笔记
        pass


# --------------------------------------------------------------------- listing
def _note_books() -> List[str]:
    """Return the ids of every book that has a note file (drafts excluded)."""
    directory = notes_dir()
    # 目录还不存在：一条笔记都没有
    if not directory.is_dir():
        return []
    ids: List[str] = []
    try:
        for path in sorted(directory.glob("*.md")):
            # 草稿不是正式笔记，不该出现在列表里
            if path.name.endswith(DRAFT_SUFFIX):
                continue
            ids.append(path.stem)
    except OSError:
        # 目录读不了：当作没有笔记，不要让 `werd notes` 崩掉
        return []
    return ids


def list_all_notes(refresh: bool = True) -> Dict[str, Dict[str, Any]]:
    """Return ``{book_id: {title, count, last_modified, preview}}`` for every book.

    The result is **rebuilt from the markdown files** -- the index is only a cache
    -- so a note you deleted or edited by hand shows up correctly right away.
    With *refresh* (the default) the rebuilt index is written back, which also
    heals a missing or damaged ``index.json``.
    """
    previous = _read_index()
    entries: Dict[str, Dict[str, Any]] = {}
    for book_id in _note_books():
        # 旧索引里的书名优先保留（`.md` 被手改过标题时也不至于改名）
        stored = previous.get(_slug(book_id)) or {}
        entries[_slug(book_id)] = _entry_for(book_id, title=stored.get("title"))
    if refresh:
        try:
            with file_lock(index_file()):
                _write_index(entries)
        except OSError:
            # 写不进去（目录只读之类）也不影响本次展示
            pass
    return entries


def update_index(
    book_id: Any,
    title: Optional[Any] = None,
    preview: Optional[str] = None,
) -> Dict[str, Any]:
    """Refresh ``index.json``'s entry for *book_id* from its markdown file.

    ``count`` is *derived* from the notes actually present rather than a blind
    ``+1``, so the index cannot drift when a note is deleted or hand-written.
    ⚠️ This takes the file lock itself -- never call it while already holding it
    (``flock`` is not reentrant across descriptors, even inside one process).
    """
    with file_lock(index_file()):
        entries = _read_index()
        stored = entries.get(_slug(book_id)) or {}
        # 书名：调用方给的优先，否则沿用索引里已有的
        entry = _entry_for(
            book_id,
            title=title if title is not None else stored.get("title"),
            preview=preview,
        )
        entries[_slug(book_id)] = entry
        _write_index(entries)
    return entry


# ---------------------------------------------------------------------- export
def export_notes(book_id: Any, export_path: Any) -> Path:
    """Copy *book_id*'s note file to *export_path* and return the written path.

    A directory target gets the default file name (``notes_<id>.md``) inside it,
    which is exactly what ``werd notes <id> --export`` relies on.
    """
    source = note_file(book_id)
    # 还没写过笔记：明确报错，别导出一个空文件让人以为导出成功了
    if not source.is_file():
        raise NotesError("{} has no notes yet".format(book_id))
    target = Path(str(export_path)).expanduser()
    # 目标是目录：套用默认文件名
    if target.is_dir():
        target = target / EXPORT_TEMPLATE.format(_slug(book_id))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    except OSError as exc:
        raise NotesError("cannot export to {}: {}".format(target, exc)) from exc
    return target

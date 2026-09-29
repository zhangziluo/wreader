"""Headless JSON-RPC sidecar: the reading core over line-delimited JSON.

The terminal reader and a GUI need the very same book index, chapter tables,
reading position, statistics and achievements.  This module publishes those core
functions over **one JSON object per line** on stdin/stdout, so any desktop shell
can drive them without importing the curses front end and without a second
implementation of the reading maths.

Protocol
--------
Request (one line)::

    {"id": 7, "method": "list", "params": {}}

Response (one line, exactly one per request)::

    {"id": 7, "result": {"books": [...]}}
    {"id": 7, "error": {"type": "LibraryError", "message": "..."}}

Requests are answered in order.  A bad line, an unknown method or a bad parameter
produces an ``error`` response instead of killing the process, so a typo in the
shell can never take the reader down.  Nothing here touches ``curses`` or
``rich``: :mod:`wreader.reader` stays the terminal product, this module is the
headless one, and both go through :mod:`wreader.session` for anything that
writes the index.

Run it with ``python -m wreader.serve``; it reads until stdin is closed.
"""

# 延迟求值类型注解
from __future__ import annotations

# 逐行解析请求 / 序列化响应
import json
# stdin / stdout / stderr
import sys
# 会话缺 started 时按 seconds 往回推
from datetime import datetime, timedelta
# 类型注解
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# 同包引用：版本号 + 内核模块（绝不 import reader / cli —— 那两处才是终端前端）
from . import __version__, achievements, config, library, session, stats, toc, transfer

# 模块公开的名字：协议入口（客户端与测试用）
__all__ = [
    "ServeError",
    "handle_request",
    "main",
    "serve",
]

# text 方法不传 count 时给的行数（一屏多一点）
_DEFAULT_TEXT_COUNT = 200
# text 方法一次最多给多少行（防呆，免得客户端一次要走整本书）
_MAX_TEXT_COUNT = 2000

# 处理函数：吃一个 params 字典，回一个可 JSON 化的结果
Handler = Callable[[Dict[str, Any]], Any]

# 方法表：名字 -> 处理函数
_METHODS: Dict[str, Handler] = {}


class ServeError(Exception):
    """Raised when a request cannot be answered (bad method, bad params, ...)."""


def _method(name: str) -> Callable[[Handler], Handler]:
    """Register the decorated function as the handler of *name*."""

    def register(func: Handler) -> Handler:
        # 登记进方法表
        _METHODS[name] = func
        # 返回原函数，模块内部仍能直接调用
        return func

    # 装饰器工厂：先记名字，再等被装饰的函数
    return register


def _text_param(params: Dict[str, Any], name: str) -> str:
    """Return ``params[name]`` as a stripped string (``""`` when missing)."""
    # 一律转成字符串并去掉首尾空白，id / 关键词都这么取
    return str(params.get(name) or "").strip()


def _parse_moment(value: Any) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp; ``None`` when it is missing or malformed."""
    # 空值直接当作没给
    if value is None or str(value).strip() == "":
        # 客户端确实没给时间戳
        return None
    try:
        # 客户端一般送来 session.iso() 写出的秒级时间戳
        return datetime.fromisoformat(str(value))
    except ValueError:
        # 时间戳坏了：当作没给，由调用方回退到"现在"
        return None


@_method("ping")
def _handle_ping(params: Dict[str, Any]) -> Dict[str, Any]:
    """Liveness probe; the shell uses it to wait for the core to come up."""
    # 回一个 pong + 版本号，客户端据此确认内核已就绪
    return {"pong": True, "version": __version__}


@_method("version")
def _handle_version(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the core version, so the shell can refuse a mismatched core."""
    # 只回版本号，便于客户端做兼容判断
    return {"version": __version__}


@_method("paths")
def _handle_paths(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the data locations, so the shell can show or back them up."""
    # 数据目录 / 正文目录 / 索引与设置文件：全是纯文本，用户随时能手改与备份
    return {
        "data_dir": str(config.data_dir()),
        "novels_dir": str(config.novels_dir()),
        "library_file": str(config.library_file()),
        "settings_file": str(config.settings_path()),
    }


def _book_rows(books: Sequence[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Flatten ``(book_id, record)`` pairs into JSON friendly rows.

    The index record nests the interesting numbers inside ``progress``; a GUI list
    would otherwise have to know that layout, so the flat shape is published here
    once and every book listing method returns it.
    """
    # 结果列表：一行一本
    rows: List[Dict[str, Any]] = []
    # 逐本把嵌套记录拍平
    for book_id, book in books:
        # 取进度块（可能缺、也可能被手改坏）
        progress = book.get("progress")
        # 进度块不是字典就按"没读过"算
        progress = progress if isinstance(progress, dict) else {}
        # 拼成一行：GUI 列表直接照抄这些字段
        rows.append(
            {
                "id": str(book_id),
                "title": str(book.get("title") or ""),
                "author": str(book.get("author") or ""),
                "file_path": str(book.get("file_path") or ""),
                "encoding": str(book.get("encoding") or ""),
                "total_lines": int(book.get("total_lines") or 0),
                "total_words": int(book.get("total_words") or 0),
                "import_date": str(book.get("import_date") or ""),
                "tags": [str(tag) for tag in (book.get("tags") or [])],
                # 下面这些来自 progress：最常用的几个字段
                "current_line": int(progress.get("current_line") or 0),
                "percentage": float(progress.get("percentage") or 0.0),
                "last_read": progress.get("last_read"),
                "total_time_seconds": int(progress.get("total_time_seconds") or 0),
                "finished": bool(progress.get("finished")),
                "bookmarks": list(progress.get("bookmarks") or []),
                # 章节表可能为空（纯文本没识别出章节）
                "chapter_count": len(book.get("chapters") or []),
            }
        )
    # 交出扁平行，顺序沿用传进来的顺序
    return rows


def _require_book(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the book record named by ``params["book_id"]``."""
    # 取 id（空 id 不可能命中，会走到下面的报错）
    book_id = _text_param(params, "book_id")
    # 按 id 找书；找不到返回 None
    book = library.get_book(book_id) if book_id else None
    # 找不到就报错，让客户端弹出提示而不是拿到一份空数据
    if book is None:
        raise ServeError("unknown book id: {}".format(book_id or "(empty)"))
    # 找到就把记录交出去
    return book


@_method("list")
def _handle_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return every book as a flat row (title order)."""
    # 全量书单，排序由 library 负责（标题序）
    return {"books": _book_rows(library.list_books())}


@_method("recent")
def _handle_recent(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the most recently read books (default 3, like ``werd continue``)."""
    # 负数或垃圾值按 0 处理，交给 library 返回空列表
    limit = max(0, int(params.get("limit") or 3))
    # 与 list 一样的扁平行
    return {"books": _book_rows(library.recent_books(limit))}


@_method("search")
def _handle_search(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the books matching ``keyword`` (fuzzy; ``#tag`` searches tags)."""
    # 关键词原样交给 library：它认得 "#标签" 与前缀/子序列匹配
    keyword = str(params.get("keyword") or "")
    # 回显关键词，客户端好知道这份结果对应哪次输入
    return {"keyword": keyword, "books": _book_rows(library.search_books(keyword))}


@_method("get_book")
def _handle_get_book(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return one raw index record, or ``null`` when the id is unknown."""
    # 取 id；空 id 直接算未知
    book_id = _text_param(params, "book_id")
    # 按 id 取记录（取不到就是 None）
    book = library.get_book(book_id) if book_id else None
    # 未知就回 null：客户端自己决定怎么提示，不是错误
    return {"book": book}


@_method("toc")
def _handle_toc(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a book's table of contents (cached; ``rebuild`` re-parses it)."""
    # 先确认书还在（不在就抛 ServeError）
    book = _require_book(params)
    # 书 id（后面按它读缓存）
    book_id = _text_param(params, "book_id")
    # 目录可能一个字都没识别出来：那是空列表，不是错误
    entries = toc.load_toc(book_id, book, rebuild=bool(params.get("rebuild")))
    # 条目里带 line（源行号）与 percentage
    return {"book_id": book_id, "entries": entries}


@_method("text")
def _handle_text(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return a slice of the book text, split exactly like the importer did."""
    # 先确认书还在
    book = _require_book(params)
    # 正文不在磁盘上会抛 LibraryError，客户端会收到一条 error 响应
    lines = session.read_lines(str(book.get("file_path") or ""))
    # 起点按 0 起始；太小夹到 0
    start = max(0, int(params.get("start") or 0))
    # 不传 count 就给一屏多一点，再夹到上限防止一次要走整本书
    count = max(1, min(int(params.get("count") or _DEFAULT_TEXT_COUNT), _MAX_TEXT_COUNT))
    return {
        "book_id": _text_param(params, "book_id"),
        "total_lines": len(lines),
        "start": start,
        "count": count,
        # 切片越界是安全的：start 超过总行数就回空列表
        "lines": lines[start : start + count],
    }


@_method("position")
def _handle_position(params: Dict[str, Any]) -> Dict[str, Any]:
    """Save *just* the reading position (crash insurance, no session record).

    This mirrors what the terminal reader does on its auto-save timer: the position
    is written, the session is not, so nothing is added to the statistics.
    """
    # 先确认书还在（不在就抛 ServeError）
    book = _require_book(params)
    # 总行数缺省用索引里的值，客户端一般不必自己传
    total = int(params.get("total") or book.get("total_lines") or 0)
    # 落库交给会话内核：与 CLI 共用同一套写法
    saved = session.write_position(
        _text_param(params, "book_id"),
        int(params.get("position") or 0),
        float(params.get("percentage") or 0.0),
        list(params.get("bookmarks") or []),
        total,
    )
    # 报回是否真的落库（书被另一个终端删掉时会返回 False）
    return {"saved": saved}


@_method("session")
def _handle_session(params: Dict[str, Any]) -> Dict[str, Any]:
    """Close one reading session: position, duration and achievements.

    ``ranges`` is the list of ``[start, end]`` line ranges walked through this
    session; the achievements engine dedupes them, so a re-read adds no words.
    A GUI that only knows its own coordinate system (an epub CFI) can still pass
    the line ranges it *approximately* covered -- the time and the position are
    the parts that must be exact.
    """
    # 先确认书还在
    book = _require_book(params)
    # 书 id（位置与时长都要按它落库）
    book_id = _text_param(params, "book_id")
    # 本次时长（秒）
    seconds = max(0, int(params.get("seconds") or 0))
    # 结束时刻：没给就按"现在"
    ended = _parse_moment(params.get("ended")) or session.now()
    # 开始时刻：没给就按结束时刻往回推 seconds（保证 sessions[] 里 start <= end）
    started = _parse_moment(params.get("started")) or ended - timedelta(seconds=seconds)
    # 总行数缺省用索引里的值，客户端一般不必自己传
    total = int(params.get("total") or book.get("total_lines") or 0)
    # 会话明细是否计入历史：对应 reader.store_history 设置
    record_history = bool(params.get("record_history", True))
    # 位置 + 时长 + 会话明细，一次性交给会话内核
    saved = session.write_session(
        book_id,
        int(params.get("position") or 0),
        float(params.get("percentage") or 0.0),
        list(params.get("bookmarks") or []),
        total,
        seconds,
        started,
        ended,
        int(params.get("lines_read") or 0),
        record_history=record_history,
    )
    # 成就：把本次读过的行区间交给引擎，返回这次新解锁的
    unlocked = _session_unlocked(book_id, book, params, seconds, started, ended)
    return {"saved": saved, "unlocked": unlocked}


def _session_unlocked(
    book_id: str,
    book: Dict[str, Any],
    params: Dict[str, Any],
    seconds: int,
    started: datetime,
    ended: datetime,
) -> List[Dict[str, Any]]:
    """Hand a finished session to the achievements engine; never raise."""
    try:
        # 读过的行区间：引擎自己按行号去重，重读同一段不会重复加字数
        raw_ranges = params.get("ranges")
        ranges = list(raw_ranges) if isinstance(raw_ranges, (list, tuple)) else []
        payload: Dict[str, Any] = {
            "book_id": book_id,
            "seconds": int(seconds),
            "started": session.iso(started),
            "ended": session.iso(ended),
            "ranges": ranges,
            # 阅读器攒下的按键 / 尺寸计数：GUI 没有这些，缺省就是空
            "deltas": params.get("deltas") or {},
            "maxima": params.get("maxima") or {},
            "width": int(params.get("width") or 0),
            "height": int(params.get("height") or 0),
        }
        # 只有真要结算字数时才把整本正文读进来（大书很贵）
        if ranges:
            try:
                payload["lines"] = session.read_lines(str(book.get("file_path") or ""))
            except library.LibraryError:
                # 正文没了：字数额度就不结算了，时长照记
                payload["lines"] = []
        return achievements.check_achievements("session_end", payload)
    except (achievements.AchievementsError, library.LibraryError, stats.StatsError):
        # 成就系统坏了绝不能影响"时长已记账"这件事：吞掉，回空列表
        return []


@_method("event")
def _handle_event(params: Dict[str, Any]) -> Dict[str, Any]:
    """Record one achievement event and return whatever it unlocked."""
    # 事件名（必须在 achievements.EVENTS 白名单里，否则引擎会抛错）
    event_type = _text_param(params, "event_type")
    # 附加数据：不是字典就按空算
    data = params.get("data")
    unlocked = achievements.check_achievements(
        event_type, data if isinstance(data, dict) else {}
    )
    return {"unlocked": unlocked}


def _safe_event(event_type: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Fire one achievements event; never let a broken state file break the call."""
    try:
        # 唯一入口：记录事件 + 判定解锁 + 落盘（带文件锁）
        return achievements.check_achievements(event_type, data)
    except (achievements.AchievementsError, library.LibraryError, stats.StatsError):
        # 成就系统坏了只是少几条解锁，调用方本身必须成功
        return []


@_method("daily_open")
def _handle_daily_open(params: Dict[str, Any]) -> Dict[str, Any]:
    """Record that the reader was opened today (streak / early bird / holidays)."""
    # 与 CLI 启动时做的完全一样：记一条 daily_open，返回这次新解锁的
    return {"unlocked": _safe_event("daily_open", {})}


@_method("import")
def _handle_import(params: Dict[str, Any]) -> Dict[str, Any]:
    """Scan a path, convert every new book to UTF-8 and index it."""
    # 要扫描的路径 / 文件必填
    target = _text_param(params, "path")
    # 没有路径就没什么可导入的
    if not target:
        raise ServeError("import needs a 'path'")
    result = library.import_books(target)
    # 入库成功就记一次 book_add（"书库初成 / 藏书家 / 移动图书馆"）
    unlocked = _safe_event("book_add", {"count": len(result.imported)})
    return {
        "path": target,
        # scanned 是"看过的候选项"总数，客户端可据此判断目录里到底有没有书
        "scanned": result.scanned,
        "imported": [
            {"id": str(book_id), "title": str(book.get("title") or "")}
            for book_id, book in result.imported
        ],
        # 内容重复被跳过的文件（同一个 book_id 已经在库里）
        "duplicates": [item.name for item in result.duplicates],
        # 失败的文件与原因（编码错误 / 写盘失败 / 没有正文）
        "failed": [[item.name, reason] for item, reason in result.failed],
        "unlocked": unlocked,
    }


@_method("stats")
def _handle_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the whole statistics report (the ``werd stats --json`` shape)."""
    try:
        # 已解锁的权威列表来自 achievements.json（索引里的旧记录只是兼容用）
        unlocked = achievements.unlocked_ids(achievements.load_state())
    except achievements.AchievementsError:
        # 状态文件坏了：当作一个都没解锁，报告照样要出得来
        unlocked = []
    # 渲染表格与 --json 用的是同一份字典，绝不漂移
    return stats.build_report(library.load_library(), unlocked=unlocked)


@_method("achievements")
def _handle_achievements(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return every achievement with its progress and unlock time."""
    # 已解锁的带 unlocked_at，未解锁的带 current / required
    return {"achievements": achievements.list_achievements()}


@_method("config_get")
def _handle_config_get(params: Dict[str, Any]) -> Dict[str, Any]:
    """Return the effective settings as a flat ``section.key`` mapping."""
    settings = config.load_config()
    # flat() 是"点号路径 -> 值"，客户端按路径读写即可，不必懂 TOML
    return {"values": settings.flat(), "paths": config.all_paths()}


@_method("config_set")
def _handle_config_set(params: Dict[str, Any]) -> Dict[str, Any]:
    """Set one setting and write ``settings.toml`` back."""
    path = _text_param(params, "path")
    # 没给键名就没什么可设的
    if not path:
        raise ServeError("config_set needs a 'path'")
    # 没给值也报错：不能默默把设置清成 None
    if "value" not in params:
        raise ServeError("config_set needs a 'value'")
    # config.set 会校验类型（不合法抛 ConfigError）、改内存并立刻落盘
    value = config.set(path, params.get("value"))
    return {"path": config.resolve_path(path), "value": value}


@_method("export")
def _handle_export(params: Dict[str, Any]) -> Dict[str, Any]:
    """Pack reading time, progress and achievements into one JSON bundle."""
    # 目标路径必填（客户端一般先弹保存对话框）
    path = _text_param(params, "path")
    # 没有路径就没地方写
    if not path:
        raise ServeError("export needs a 'path'")
    # 明文 UTF-8 JSON 包；"只加不减"的合并语义在 transfer 里
    return transfer.export_data(path)


@_method("import_data")
def _handle_import_data(params: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an exported bundle into this machine (add-only)."""
    path = _text_param(params, "path")
    # 没有路径就没东西可读
    if not path:
        raise ServeError("import_data needs a 'path'")
    # ⚠️ 同一个包导两次时长就翻倍 —— 有意的"增量合并"取舍，不是 bug
    return transfer.import_data(path)


def _brief(books: Sequence[Tuple[str, Dict[str, Any]]]) -> List[Dict[str, str]]:
    """Return ``{id, title}`` for each removed book (a compact receipt)."""
    # 只回 id 与标题：客户端刷新列表后自己会拿到完整数据
    return [
        {"id": str(book_id), "title": str(book.get("title") or "")}
        for book_id, book in books
    ]


@_method("prune")
def _handle_prune(params: Dict[str, Any]) -> Dict[str, Any]:
    """Drop index records whose converted text file is gone."""
    # 对账逻辑在 library 里（CLI 每个命令启动前也会自动跑一次）
    removed = library.prune_missing_books()
    return {"removed": len(removed), "books": _brief(removed)}


@_method("clear")
def _handle_clear(params: Dict[str, Any]) -> Dict[str, Any]:
    """Empty the library; reading time and achievements are kept on purpose."""
    # 只清书目与转换后的正文，stats / achievements 原样保留
    removed = library.clear_library()
    return {"removed": len(removed), "books": _brief(removed)}


def _ok(request_id: Any, result: Any) -> Dict[str, Any]:
    """Build a success response for *request_id*."""
    # 成功：id 原样带回 + result（可能是 null）
    return {"id": request_id, "result": result}


def _fail(request_id: Any, exc: Exception) -> Dict[str, Any]:
    """Build a failure response for *request_id*."""
    # 失败：id 原样带回 + 错误类型与消息，客户端好分辨该怎么提示
    return {
        "id": request_id,
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def handle_request(request: Any) -> Dict[str, Any]:
    """Answer one decoded request; **always** returns a response dict.

    Never raises: a broken request becomes an ``error`` response, so one bad line
    from the shell cannot take the core down.
    """
    # 请求必须是 JSON 对象，否则连 id 都拿不到
    if not isinstance(request, dict):
        return _fail(None, ServeError("request must be a JSON object"))
    request_id = request.get("id")
    name = request.get("method")
    # method 必须是非空字符串
    if not isinstance(name, str) or not name:
        return _fail(request_id, ServeError("request needs a string 'method'"))
    handler = _METHODS.get(name)
    # 不认识的方法：报错，但继续服务（客户端打错字不该让内核退出）
    if handler is None:
        return _fail(request_id, ServeError("unknown method: {}".format(name)))
    params = request.get("params")
    # params 不是对象（缺省 / null / 数组）就按空对象算
    params = params if isinstance(params, dict) else {}
    try:
        return _ok(request_id, handler(params))
    except ServeError as exc:
        # 我们自己抛的：参数或状态问题
        return _fail(request_id, exc)
    except (
        config.ConfigError,
        library.LibraryError,
        achievements.AchievementsError,
        stats.StatsError,
        transfer.TransferError,
    ) as exc:
        # 内核自己的异常：原样转成一条 error 响应（类型名就是它真实的类名）
        return _fail(request_id, exc)
    except (TypeError, ValueError, KeyError) as exc:
        # 参数类型不对（比如 count 传了 "abc"）：报错但不崩
        return _fail(request_id, ServeError("bad params: {}".format(exc)))
    except Exception as exc:  # pragma: no cover - 兜底，别让内核悄悄死掉
        # 意外异常：stderr 留痕（stdout 是协议，绝不能污染），再回一条错误
        print(
            "wreader.serve: {}: {}".format(type(exc).__name__, exc),
            file=sys.stderr,
        )
        return _fail(request_id, exc)


def serve(instream: Any = None, outstream: Any = None) -> int:
    """Read requests line by line and write one response line for each."""
    # 缺省走标准输入 / 输出；测试可以塞两个 StringIO 进来
    instream = instream if instream is not None else sys.stdin
    outstream = outstream if outstream is not None else sys.stdout
    # 逐行处理：一行一个请求，天然按顺序应答
    for raw in instream:
        line = raw.strip()
        # 空行（心跳 / 排版）直接跳过，不回任何东西
        if not line:
            continue
        try:
            # 解出一行 JSON；不是合法 JSON 就走下面的 error 分支
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            # 坏行：回一条错误而不是退出，客户端能看出是自己发错了
            response = _fail(None, ServeError("bad JSON: {}".format(exc)))
        else:
            response = handle_request(request)
        # 一行一个响应；ensure_ascii=False 让中文原样输出，方便人肉调试
        outstream.write(json.dumps(response, ensure_ascii=False) + "\n")
        # 立刻冲刷：客户端是一问一答地等，不冲刷就会卡住
        outstream.flush()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point for ``python -m wreader.serve``."""
    # 目前不接受命令行参数；argv 只是个预留的接口
    del argv
    return serve()


# `python -m wreader.serve` 直接跑时，用 serve() 的返回值当退出码
if __name__ == "__main__":  # pragma: no cover - 只有直接执行模块时才走到
    raise SystemExit(main())

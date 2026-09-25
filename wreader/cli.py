"""Command line interface for ``werd``.

Owns argument parsing and the top level command dispatch.  Every sub-command is
declared in :func:`build_parser` and wired to a handler function through
``_HANDLERS``.

Every command is wired up: ``import``, ``list``, ``search``, ``read``,
``continue``, ``stats``, ``achievements``, ``config`` and ``toc``.
"""

# 延迟求值类型注解，避免运行时解析注解带来的开销和顺序问题
from __future__ import annotations

# 标准库的命令行参数解析器，所有子命令都靠它声明
import argparse
# `werd stats --json` 要把报告原样输出成 JSON
import json
# 直接写 sys.stdout/sys.exit，绕过 rich 的渲染避免污染重定向输出
import sys
# datetime：daily_open 事件要带上"什么时候打开的"
from datetime import datetime
# 类型注解：Callable 表示"可调用的函数"，其余是容器和可选类型
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

# rich 的 Console：带颜色、高亮的终端输出
from rich.console import Console
# rich 的表格，list/search/stats 都用它排版
from rich.table import Table

# 同包内引用：版本号 + 配置 + 书库 + 统计 + 成就事件
from . import __version__, achievements, config, library, stats

# 对外只暴露这两个函数：构造解析器和程序入口
__all__ = ["build_parser", "main"]

# 正常输出用的 Console（stdout）
console = Console()
# 错误输出用的 Console（stderr），方便 `> file` 时把错误留在终端
err_console = Console(stderr=True)


def _now() -> datetime:
    """Return the current local time (a seam the tests replace)."""
    # 单独包一层，测试里可以注入固定时刻，让"清晨第一眼"可预测
    return datetime.now()


def _record_achievements(
    event_type: str,
    data: Optional[Mapping[str, Any]] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Fire one achievements event; never let it break the command.

    A broken definitions file or an unreadable state file must not stop ``werd
    import`` from importing, so every failure degrades to "no unlocks".
    """
    try:
        # 唯一入口：记录事件 + 判定解锁 + 落盘
        return achievements.check_achievements(event_type, data, now=now)
    except (
        achievements.AchievementsError,
        library.LibraryError,
        stats.StatsError,
    ):
        # 成就系统坏了：静默跳过，命令照常成功
        return []


def _unlocked_ids() -> List[str]:
    """Return the unlocked achievement ids from the state file."""
    try:
        # 权威位置是数据目录里的 achievements.json
        return achievements.unlocked_ids(achievements.load_state())
    except achievements.AchievementsError:
        # 状态文件坏了：当作一个都没解锁（`werd achievements` 会另外提示）
        return []


def build_parser() -> argparse.ArgumentParser:
    """Create the top level ``werd`` parser including every sub-command."""
    # 顶层解析器：定义程序名和整体描述
    parser = argparse.ArgumentParser(
        prog="werd",
        description=(
            "A terminal novel reader with reading statistics and achievements."
        ),
    )
    # 全局 -V/--version 选项：打印版本后直接退出（action="version" 自动干这事）
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version="%(prog)s {}".format(__version__),
        help="show the werd version and exit",
    )
    # --werd：名字彩蛋（与子命令 werd / word 同一个玩笑）
    parser.add_argument(
        "--werd",
        action="store_true",
        help="the name easter egg (same as `werd werd`)",
    )

    # 子命令容器：dest="command" 让解析结果里带一个 command 字段，用来查 handler
    # required=False 是为了让 `werd --werd` 也能跑：没给子命令时由 main 自己按
    # argparse 的老样子报错（用法提示与退出码 2 完全一致）
    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        metavar="<command>",
        required=False,
    )

    # werd import <path>：导入书籍的子命令
    import_parser = subparsers.add_parser(
        "import",
        help="scan a directory and import txt/epub books into the library",
    )
    # 位置参数 path：可以是单个文件，也可以是待扫描的目录
    import_parser.add_argument(
        "path",
        help="book file or directory to scan for .txt/.epub books",
    )

    # werd list：不带任何参数，列出书库
    subparsers.add_parser("list", help="list the books stored in the library")

    # werd search <keyword>：按标题/作者/标签模糊搜索
    search_parser = subparsers.add_parser(
        "search", help="fuzzy search books by title, author or tag",
    )
    # 位置参数 keyword：搜索关键词
    search_parser.add_argument(
        "keyword", help="keyword matched against title, author and tags",
    )

    # werd read <book_id>：进入 curses 阅读界面
    read_parser = subparsers.add_parser(
        "read", help="open the paged curses reader for a book",
    )
    # 位置参数 book_id：要阅读的书
    read_parser.add_argument("book_id", help="id of the book to read")

    # werd continue：列出最近在读的几本书，方便接着上次的进度读
    subparsers.add_parser(
        "continue", help="list the books you read most recently",
    )

    # werd stats [--json]：阅读统计（时长、热力图等）
    stats_parser = subparsers.add_parser("stats", help="show reading statistics")
    # --json：输出机器可读的原始数据，而不是彩色表格
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="print the raw numbers as JSON instead of the table",
    )

    # werd achievements：查看成就解锁情况
    subparsers.add_parser(
        "achievements", help="list achievements and unlock progress",
    )

    # werd config [section.key] [value]：查看/修改设置
    config_parser = subparsers.add_parser(
        "config", help="view or modify the wreader settings",
    )
    # 位置参数 key：点号路径，例如 reader.page_height；nargs="?" 表示可省略
    config_parser.add_argument(
        "key",
        nargs="?",
        help="setting to read or write, as a dotted path (reader.page_height)",
    )
    # 位置参数 value：省略它就是"读"，给了它就是"写"
    config_parser.add_argument(
        "value",
        nargs="?",
        help="new value for the setting (omit it to read the setting)",
    )
    # --path：只打印设置文件的位置
    config_parser.add_argument(
        "--path",
        action="store_true",
        help="print the path of the settings file",
    )
    # --reset：把所有设置恢复成默认值
    config_parser.add_argument(
        "--reset",
        action="store_true",
        help="restore every setting to its default",
    )

    # werd toc <book_id>：查看某本书的目录（章节表）
    toc_parser = subparsers.add_parser(
        "toc", help="show a book's table of contents (chapters)",
    )
    # 位置参数 book_id：看哪本书的目录
    toc_parser.add_argument("book_id", help="id of the book")
    # --rebuild：忽略缓存，重新解析正文并覆写缓存
    toc_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="re-parse the book text and rewrite the cache",
    )

    # werd werd / werd word：名字彩蛋（两个写法都留着，反正就是同一个玩笑）
    subparsers.add_parser("werd", help="the name easter egg")
    subparsers.add_parser("word", help="the name easter egg (the other spelling)")

    # 把组装好的解析器交还给调用方
    return parser


# ---------------------------------------------------------------------------
# Output helpers.
# ---------------------------------------------------------------------------
def _fail(message: str, code: int = 1) -> int:
    """Print *message* as an error and return *code*."""
    # 用红色 "error:" 前缀写到 stderr，页面看起来统一
    err_console.print("[red]error:[/red] {}".format(message))
    # 直接把退出码返回给调用方（handler 的返回值就是进程退出码）
    return code


def _book_table(title: str, rows: Sequence[Tuple[str, Dict[str, Any]]]) -> Table:
    """Build the rich table shared by ``werd list`` and ``werd search``."""
    # 每行形如 (book_id, book_dict)，列宽由 rich 自动算
    table = Table(title=title, title_justify="left")
    # 六列：序号、id、书名、作者、进度、字数
    table.add_column("#", justify="right", style="dim")
    table.add_column("id", style="cyan", no_wrap=True)
    table.add_column("title", style="bold")
    table.add_column("author")
    table.add_column("progress", justify="right")
    table.add_column("words", justify="right")
    # 从 1 开始编号，方便人对着序号引用
    for position, (book_id, book) in enumerate(rows, start=1):
        # 缺失字段都兜个默认值，避免表格里出现 "None"
        table.add_row(
            str(position),
            book_id,
            str(book.get("title") or "untitled"),
            str(book.get("author") or "unknown"),
            "{:.1f}%".format(library.progress_percent(book)),
            library.human_words(int(book.get("total_words") or 0)),
        )
    # 返回搭好的表格，由调用方决定什么时候打印
    return table


def _default_repr(path: str) -> str:
    """Render the default of one setting the way ``werd config`` shows it."""
    # 从配置模块的默认值平表里查这个点号路径
    value = config.DEFAULT_FLAT.get(path)
    # 没有静态默认值（比如依赖其他设置的项）就显示 (auto)
    if value is None:
        return "(auto)"
    # 否则按配置写法渲染
    return _setting_text(value)


def _setting_text(value: Any) -> str:
    """Render a setting value: TOML style booleans, ``(unset)`` for nothing."""
    # 布尔值写成 TOML 风格的小写 true/false
    if isinstance(value, bool):
        return "true" if value else "false"
    # 浮点数特殊处理：整数值的 1.0 打成 "1" 更好看，也跟配置文件里写的一致
    if isinstance(value, float):
        # page_scroll_step is the only float, and `1` reads better than `1.0`
        # -- exactly what the settings file holds.
        return str(int(value)) if value.is_integer() else repr(value)
    # 没设置过就显示 (unset)，提示用户这是空值而不是 0 或空串
    if value is None:
        return "(unset)"
    # 其余（字符串、整数）直接转成字符串
    return str(value)


def _print_config(settings: config.Config) -> None:
    """Show every setting, grouped by section, with its default."""
    # 算出"生效值"：把默认值和用户写在文件里的值合并后的结果
    values = config.effective_values(settings)
    # 三列：键、当前生效值、默认值
    table = Table(title="settings", title_justify="left")
    table.add_column("key", style="cyan", no_wrap=True)
    table.add_column("value", style="bold")
    table.add_column("default", style="dim")
    # 遍历 SCHEMA 里声明的每一个 section 和它下面的设置项
    for index, (section, keys) in enumerate(config.SCHEMA.items()):
        # 不是第一组就先画一条分隔线，让表格按 section 分块
        if index:
            table.add_section()
        for key, _default, _comment in keys:
            # 拼出点号路径，如 reader.page_height
            path = "{}.{}".format(section, key)
            # 一行：路径 / 当前值 / 默认值
            table.add_row(path, _setting_text(values.get(path)), _default_repr(path))
    # 打印整张表
    console.print(table)

    # 用户配置文件里出现了 schema 不认识的键：给个黄色警告（不报错，只是忽略）
    for path in sorted(settings.unknown):
        console.print(
            "[yellow]warning:[/yellow] unknown setting '{}' is ignored".format(path)
        )
    # 值类型不对被丢弃的项：说明用了默认值
    for reason in sorted(settings.invalid.values()):
        console.print("[yellow]warning:[/yellow] {} — using the default".format(reason))
    # 最后提示设置文件在哪
    console.print("[dim]file: {}[/dim]".format(settings.path))
    # 老版本用过的扁平 config.json 会被备份成 .bak，存在就顺带提一句
    backup = settings.path.parent / (config.LEGACY_CONFIG_FILENAME + ".bak")
    if backup.exists():
        console.print("[dim]older flat config kept as: {}[/dim]".format(backup))


# ---------------------------------------------------------------------------
# Sub-command handlers.
# ---------------------------------------------------------------------------
def cmd_import(args: argparse.Namespace) -> int:
    """Handle ``werd import <path>`` -- scan, convert and store books."""
    # 真正的扫描/解析/入库逻辑都在 library 里，这里只负责展示结果
    result = library.import_books(args.path)

    # 一个支持的书籍文件都没扫到，属于失败
    if not result.scanned:
        console.print(
            "no .txt/.epub file found under [bold]{}[/bold]".format(args.path)
        )
        return 1

    # 一行总览：导入成功几条、跳过几条重复、失败几条
    console.print(
        "imported [green]{}[/green] book(s), skipped [yellow]{}[/yellow] "
        "duplicate(s), [red]{}[/red] failed".format(
            len(result.imported), len(result.duplicates), len(result.failed)
        )
    )
    # 逐本列出新导入的书，附带行数、字数、编码、章节数
    for book_id, book in result.imported:
        # 章节列表可能为空（比如没有识别出章节的纯文本）
        chapters = book.get("chapters") or []
        console.print(
            "  [green]+[/green] {}  《{}》 [dim]{} · {} 行 · {} 字 · {}{}[/dim]".format(
                book_id,
                book.get("title"),
                book.get("author"),
                book.get("total_lines"),
                book.get("total_words"),
                book.get("encoding"),
                " · {} 章".format(len(chapters)) if chapters else "",
            )
        )
    # 已存在的书：用 "=" 标记跳过
    for path in result.duplicates:
        console.print(
            "  [yellow]=[/yellow] {} [dim]already imported[/dim]".format(path.name)
        )
    # 失败的：把原因写到 stderr
    for path, reason in result.failed:
        err_console.print("  [red]![/red] {}: {}".format(path.name, reason))
    # 入库成功：记一次 book_add（"书库初成 / 藏书家 / 移动图书馆"）
    _report_unlocked(
        _record_achievements("book_add", {"count": len(result.imported)})
    )
    # 走到这里就返回成功；个别失败不影响整体退出码
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle ``werd list`` -- show the whole library."""
    # 从索引里取出所有书
    books = library.list_books()

    # 书库是空的时候，顺手告诉用户书在哪、怎么导入
    if not books:
        console.print(
            "the library is empty -- add books with [bold]werd import <path>[/bold]"
        )
        console.print("[dim]index:  {}[/dim]".format(config.library_file()))
        console.print("[dim]novels: {}[/dim]".format(config.novels_dir()))
        return 0

    # 有书就画表格；标题里带上总数
    console.print(_book_table("library ({} book(s))".format(len(books)), books))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Handle ``werd search <keyword>`` -- fuzzy search the library."""
    # 关键词同时匹配标题、作者、标签，具体规则在 library 里
    books = library.search_books(args.keyword)

    # 搜不到东西按惯例返回非 0，方便脚本判断
    if not books:
        console.print("no book matches [bold]{}[/bold]".format(args.keyword))
        return 1

    # 复用书库表格展示搜索结果
    console.print(
        _book_table("{} match(es) for '{}'".format(len(books), args.keyword), books)
    )
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Handle ``werd config [section.key] [value]`` -- view or edit ``settings.toml``.

    Keys are dotted paths (``reader.page_height``).  The flat names of the old
    ``config.json`` still resolve, and anything unknown is refused with a
    suggestion rather than written into the file.
    """
    # 先把当前配置加载出来（不存在就用默认值）
    settings = config.load_config()

    # --path：只报设置文件的路径，其它什么都不做
    if args.path:
        console.print(str(settings.path))
        return 0

    # --reset：把所有设置清空回默认值，并落盘
    if args.reset:
        settings.reset()
        settings.save()
        console.print("settings reset to defaults")
        console.print("[dim]file: {}[/dim]".format(settings.path))
        return 0

    # 没给 key：就是想看全部设置
    if args.key is None:
        # 只给 value 不给 key 是用法错误
        if args.value is not None:
            return _fail("a value needs a key: werd config <section.key> <value>")
        _print_config(settings)
        return 0

    # 把用户输入的键名（含旧版扁平名）解析成标准点号路径
    path = config.resolve_path(args.key)
    # 只给了 key 没给 value：读取当前生效值
    if args.value is None:
        console.print(
            "{} = {}".format(path, _setting_text(config.effective_values(settings)[path]))
        )
        return 0

    # 给了 key 和 value：写入并保存
    settings.set(path, args.value)
    settings.save()
    # 回显写入后的值，带个 (saved) 标记确认已落盘
    console.print(
        "{} = {} [green](saved)[/green]".format(
            path, _setting_text(config.effective_values(settings)[path])
        )
    )
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    """Handle ``werd read <book_id>`` -- open the paged curses reader."""
    try:
        # 延迟导入：curses 在部分平台（如某些 Windows 环境）不可用
        from . import reader
    except ImportError as exc:  # pragma: no cover - only on curses-less platforms
        return _fail("the reader needs the curses module: {}".format(exc))

    # 把书 id 交给阅读器，它会进入全屏循环直到用户退出
    return reader.open_reader(args.book_id)


def cmd_continue(args: argparse.Namespace) -> int:
    """Handle ``werd continue`` -- show the books read most recently."""
    # 按 last_read 取最近读过的几本（没读过的书不会出现，时间从新到旧）
    books = library.recent_books()
    # 一本都没读过：提示先去挑一本；退出码与空书库的 list 保持一致，都是 0
    if not books:
        console.print(
            "还没有阅读记录 —— 用 [bold]werd list[/bold] 挑一本，"
            "或 [bold]werd import <路径>[/bold] 导入新书"
        )
        return 0
    # 复用书库表格：id 列直接摆出来，抄给 werd read 就能接着读
    console.print(_book_table("最近在读 (recent)", books))
    return 0


def cmd_toc(args: argparse.Namespace) -> int:
    """Handle ``werd toc <book_id>`` -- print or rebuild a book's table of contents.

    The cache is reused while it is still fresh (``--rebuild`` forces a re-parse),
    so listing the chapters of a big book is instant after the first time.
    """
    # 延迟导入 toc：不用这个命令时就不加载
    from . import toc

    # 按 id 找书
    book = library.get_book(args.book_id)
    # 查不到就报错退出
    if book is None:
        return _fail("unknown book id: {}".format(args.book_id))
    # 读目录（--rebuild 会忽略缓存重新解析）
    entries = toc.load_toc(args.book_id, book, rebuild=args.rebuild)
    # 一个字都没识别出来：给个温和提示，退出码仍是 0
    if not entries:
        console.print(
            "没有识别出章节 —— 可用 [bold]werd config toc.patterns[/bold] 加自定义正则"
        )
        return 0
    # 四列：序号 / 章节名 / 起始行（按 1 起始显示）/ 进度百分比
    table = Table(
        title="{} · {} chapter(s)".format(book.get("title") or args.book_id, len(entries)),
        title_justify="left",
    )
    table.add_column("#", justify="right", style="dim")
    table.add_column("chapter")
    table.add_column("line", justify="right", style="dim")
    table.add_column("%", justify="right", style="dim")
    # 从 1 开始编号；行号也按"给人看的 1 起始"显示
    for position, entry in enumerate(entries, start=1):
        table.add_row(
            str(position),
            str(entry.get("title") or ""),
            str(int(entry.get("line") or 0) + 1),
            "{:.1f}".format(float(entry.get("percentage") or 0.0)),
        )
    console.print(table)
    # 顺带告诉用户缓存文件在哪，方便手动清理
    console.print("[dim]cache: {}[/dim]".format(toc.toc_cache_path(args.book_id)))
    return 0


def _report_unlocked(newly: Sequence[Dict[str, Any]]) -> None:
    """Name the achievements that just unlocked -- a line, not a fanfare."""
    # 没有新成就不用打印任何东西
    if not newly:
        return
    # 一行列出来即可，阅读过程里的庆祝动画留给阅读器
    console.print(
        "🏆 已解锁 [bold]{}[/bold] 个成就：{}".format(
            len(newly),
            "、".join(str(entry.get("name") or entry.get("id")) for entry in newly),
        )
    )


# 这几个指标本身是"秒"，展示时要换算成小时/分钟
_TIME_METRICS = ("total_time", "night_time", "single_session", "weekend_time")

#: Weekday labels for the heatmap grid, Monday first (``date.weekday()`` order).
# 热力图每行的星期名，按 date.weekday() 的顺序（周一是 0）
_WEEKDAY_LABELS = ("一", "二", "三", "四", "五", "六", "日")

# 热力图每个等级字符对应的颜色，从最冷到最亮
#: One colour per heatmap character, cold to bright.
_HEAT_COLOURS: Dict[str, str] = dict(
    zip(stats.HEATMAP_CHARS, ("dim", "green", "bright_green", "yellow", "bright_yellow"))
)


def _metric_text(metric: str, value: int) -> str:
    """Render a metric value, as hours for the time based ones."""
    # 时长类指标交给 stats.format_hours 统一格式化
    if metric in _TIME_METRICS:
        return stats.format_hours(value)
    # 其余（次数、本数、天数）直接显示原值
    return str(value)


def _heatmap_text(report: Dict[str, Any]) -> str:
    """Render the heatmap as a Monday-to-Sunday grid, with its legend.

    Each column is one week, so the picture reads like a paper calendar rather
    than a single long strip; days outside the window are left blank.
    """
    # 按"周"分好组的网格（每行是一个星期几）
    rows = report.get("heatmap_grid") or []
    # 扁平的所有天，用来算日期范围和总天数
    cells = report.get("heatmap") or []
    # 没有数据就返回空串，调用方直接跳过打印
    if not rows or not cells:
        return ""
    # 逐行渲染
    grid = []
    for index, row in enumerate(rows):
        # 这一行里每一格上色后的文本
        painted = []
        for cell in row:
            # 空位（窗口外的日期）用空格占位，保持对齐
            if not cell:
                painted.append(" ")
                continue
            # 按强度等级取颜色，认不出来就用暗色兜底
            colour = _HEAT_COLOURS.get(cell.get("level"), "dim")
            # rich 标记：[颜色]字符[/颜色]
            painted.append("[{0}]{1}[/{0}]".format(colour, cell["level"]))
        # 行首加上星期几标签
        grid.append("[dim]{}[/dim] {}".format(_WEEKDAY_LABELS[index], " ".join(painted)))
    # 图例：每个等级字符配一段时长说明
    legend = " ".join(
        "{}{}".format(char, label)
        for char, label in zip(
            stats.HEATMAP_CHARS, ("0", "<20m", "<40m", "<1h", "1h+")
        )
    )
    # 标题行（天数与起止日期）+ 网格 + 图例
    return (
        "最近 {} 天（{} → {}，每列一周，周一开始）\n"
        "{}\n"
        "[dim]强度：{}[/dim]"
    ).format(
        len(cells), cells[0]["date"], cells[-1]["date"], "\n".join(grid), legend
    )



def cmd_stats(args: argparse.Namespace) -> int:
    """Handle ``werd stats`` -- reading time totals plus a 30 day heatmap grid.

    ``--json`` prints the very dict the table is rendered from, so scripts and
    the human readable view always agree.  ``stats.show_heatmap`` hides the grid
    and ``stats.daily_goal_minutes`` adds the daily goal line.
    """
    try:
        # 统计数据都放在书库索引文件里
        document = library.load_library()
    except library.LibraryError as exc:
        return _fail(str(exc))

    # 读设置：热力图开关、每日目标等都从这里来
    settings = config.load_config()
    # 让 stats 模块算出一份完整报告（一个纯数据的 dict），解锁记录来自成就状态文件
    report = stats.build_report(document, settings=settings, unlocked=_unlocked_ids())
    # --json：直接把这份 dict 原样输出，脚本和人类看到的是同一份数据
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        sys.stdout.flush()
        return 0

    # 下面都是给人看的彩色输出
    console.print("总阅读时长 [bold]{}[/bold]".format(report["total"]))
    # 今日/本周/本月三档时长
    console.print(
        "今日 [green]{}[/green] · 本周 [green]{}[/green] · 本月 [green]{}[/green]".format(
            stats.format_hours(report["today_seconds"]),
            stats.format_hours(report["week_seconds"]),
            stats.format_hours(report["month_seconds"]),
        )
    )
    # 只有设置了每日目标才显示这一行
    goal_seconds = report["daily_goal_seconds"]
    if goal_seconds:
        console.print(
            "每日目标 [bold]{}[/bold] · 今日 [green]{}%[/green]{}".format(
                stats.format_hours(goal_seconds),
                # 用整除算完成百分比
                report["today_seconds"] * 100 // goal_seconds,
                # 达标就打一个绿勾
                " [green]✓[/green]" if report["goal_met"] else "",
            )
        )
    # 连续天数、读完本数
    console.print(
        "连续 [bold]{}[/bold] 天（每天 ≥{} 分钟） · 读完 [bold]{}[/bold] 本".format(
            report["streak_days"],
            # 秒换算成分钟展示
            report["streak_min_seconds"] // 60,
            report["finished_books"],
        )
    )

    # 每本书的累计阅读时长
    if report["books"]:
        table = Table(title="本书累计", title_justify="left")
        table.add_column("book", style="bold")
        table.add_column("id", style="cyan", no_wrap=True)
        table.add_column("time", justify="right")
        for book in report["books"]:
            table.add_row(
                book["title"], book["id"], stats.format_hours(book["seconds"])
            )
        console.print(table)

    # 热力图开关关闭时只提示一句，不画图
    if bool(settings.get("stats.show_heatmap", True)):
        console.print(_heatmap_text(report))
    else:
        console.print(
            "[dim]热力图已隐藏（stats.show_heatmap = false）[/dim]"
        )
    return 0


def cmd_achievements(args: argparse.Namespace) -> int:
    """Handle ``werd achievements`` -- unlocked list plus progress on the rest.

    The unlock state lives in ``<data dir>/achievements.json`` (see
    :mod:`wreader.achievements`).  Running the command also re-checks everything,
    so progress earned outside the reader still gets a timestamp instead of
    waiting for the next book to be closed.  That is idempotent, and a secret
    achievement keeps its name to itself until it fires.
    """
    try:
        # 顺手补记一次（幂等）：把书库那边的进度也结算成解锁；同时数一次
        # "翻开了成就页"，"成就猎人"就是靠它（超过 10 次）
        _record_achievements("achievements_view")
        # 读出全部成就：名字、描述、分类、进度、是否隐藏、解锁时间
        rows = achievements.list_achievements()
    except (
        achievements.AchievementsError,
        library.LibraryError,
        stats.StatsError,
    ) as exc:
        return _fail(str(exc))

    # 分成"已解锁"和"进行中"两组
    done = [row for row in rows if row["unlocked"]]
    pending = [row for row in rows if not row["unlocked"]]
    # 打印已解锁数量
    console.print("[bold]已解锁 {}/{}[/bold]".format(len(done), len(rows)))
    # 逐条列出已解锁的成就（带解锁时间，没有时间就不显示"解锁于"）
    for row in done:
        console.print(
            "  [green]🏆[/green] [bold]{}[/bold] [dim]{}  {}{}[/dim]".format(
                row["name"],
                row["desc"],
                "" if not row["unlocked_at"] else "解锁于 ",
                row["unlocked_at"],
            )
        )
    # 有未完成的就按分类列进度
    if pending:
        console.print("\n[bold]进行中[/bold]")
        category = ""
        for row in pending:
            # 换分类了就打一行小标题
            if row["category"] != category:
                category = str(row["category"])
                console.print("  [bold cyan]{}[/bold cyan]".format(category))
            # 隐藏成就：还没解锁就只说"有这么个东西"，不剧透条件
            if row["secret"]:
                console.print("    [dim]❓ 隐藏成就（解锁后揭晓）[/dim]")
                continue
            console.print(
                "    {}  [bold]{}[/bold] [dim]{}/{}  {}[/dim]".format(
                    # 一个简单的文本进度条
                    stats.progress_bar(row["current"], row["required"]),
                    row["name"],
                    _metric_text(row["metric"], row["current"]),
                    _metric_text(row["metric"], row["required"]),
                    row["desc"],
                )
            )
    return 0


def _word_egg(name: str) -> int:
    """Print the name easter egg and unlock 名字彩蛋.

    ``werd werd``, ``werd word`` and ``werd --werd`` all land here; *name* is only used
    for the event payload (both spellings count as the same achievement).  The joke is
    the point, so the achievement report is best effort: a broken state file must not
    stop the two lines from printing.
    """
    # 两行玩笑：一行是名字，一行是提示
    console.print(
        "[bold]werd[/bold] = [bold]w[/bold]read 少了个 a，"
        "[bold]w[/bold]ord 多了个 e —— 书是真读的。"
    )
    console.print("[dim]彩蛋：把 werd 反过来念一遍，或者敲 werd word。[/dim]")
    # 报一次彩蛋事件（名字彩蛋就挂在这个指标上）
    _report_unlocked(_record_achievements("name_egg", {"egg": name}))
    return 0


def cmd_werd(args: argparse.Namespace) -> int:
    """Handle ``werd werd`` -- see :func:`_word_egg`."""
    # 子命令名就是彩蛋名（werd 反着念还是 werd）
    return _word_egg("werd")


def cmd_word(args: argparse.Namespace) -> int:
    """Handle ``werd word`` -- the same easter egg under the other spelling."""
    # 另一个拼法：同样的玩笑，换个彩蛋名入库
    return _word_egg("word")


# 命令名 -> 处理函数 的映射表；main 靠它把解析结果分发出去
_HANDLERS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "import": cmd_import,
    "list": cmd_list,
    "search": cmd_search,
    "read": cmd_read,
    "continue": cmd_continue,
    "stats": cmd_stats,
    "achievements": cmd_achievements,
    "config": cmd_config,
    "toc": cmd_toc,
    "werd": cmd_werd,
    "word": cmd_word,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point used by the ``werd`` console script."""
    # 构造解析器（每次调用都新建，测试里可以重复使用）
    parser = build_parser()
    # 解析参数；argv 为 None 时 argparse 会自动取 sys.argv[1:]
    args = parser.parse_args(argv)
    # 启动事件：每天第一次打开 werd 都算数（"百日筑基""清晨第一眼"靠它）
    _report_unlocked(_record_achievements("daily_open", {}, now=_now()))
    # `werd --werd`：名字彩蛋（选项形式，不需要子命令）
    if bool(getattr(args, "werd", False)):
        return _word_egg("werd")
    # 一个子命令都没给：按 argparse 的老样子报错（用法提示 + 退出码 2 都不变）
    if args.command is None:
        parser.error("the following arguments are required: <command>")
    # 按子命令名取出对应的处理函数
    handler = _HANDLERS[args.command]
    try:
        # 处理函数的返回值就是进程退出码
        return handler(args)
    except (config.ConfigError, library.LibraryError) as exc:
        # Domain errors are reported the same way for every sub-command, so a
        # broken config file or index never turns into a raw traceback.
        # 领域错误统一渲染成 "error: ..."，不让用户看到原始 traceback
        return _fail(str(exc))
    except KeyboardInterrupt:  # pragma: no cover
        # Ctrl-C：给个提示，并按 shell 惯例用 130 退出
        err_console.print("[yellow]aborted[/yellow]")
        return 130


if __name__ == "__main__":  # pragma: no cover
    # 直接用 `python -m wreader.cli` 运行时的入口，把退出码交给解释器
    sys.exit(main())

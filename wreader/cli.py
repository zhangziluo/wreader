"""Command line interface for ``wreader``.

Owns argument parsing and the top level command dispatch.  Every sub-command is
declared in :func:`build_parser` and wired to a handler function through
``_HANDLERS``.

Wired up so far: ``import``, ``list``, ``search`` and ``config``.  The remaining
handlers (``read``, ``translate``, ``vocab``, ``stats``, ``achievements``) are
still placeholders that only report that they are not implemented.
"""

# 延迟求值类型注解，避免运行时解析注解带来的开销和顺序问题
from __future__ import annotations

# 标准库的命令行参数解析器，所有子命令都靠它声明
import argparse
# `wreader stats --json` 要把报告原样输出成 JSON
import json
# 直接写 sys.stdout/sys.exit，绕过 rich 的渲染避免污染重定向输出
import sys
# 类型注解：Callable 表示"可调用的函数"，其余是容器和可选类型
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# rich 的 Console：带颜色、高亮的终端输出
from rich.console import Console
# 进度条相关组件：转圈、柱状条、文字列
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
# rich 的表格，list/search/vocab/stats 都用它排版
from rich.table import Table

# 同包内引用：版本号 + 配置 + 书库 + 统计
from . import __version__, config, library, stats

# 对外只暴露这两个函数：构造解析器和程序入口
__all__ = ["build_parser", "main"]

# 正常输出用的 Console（stdout）
console = Console()
# 错误输出用的 Console（stderr），方便 `> file` 时把错误留在终端
err_console = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    """Create the top level ``wreader`` parser including every sub-command."""
    # 顶层解析器：定义程序名和整体描述
    parser = argparse.ArgumentParser(
        prog="wreader",
        description=(
            "A terminal novel reader with translation, vocabulary notebook, "
            "reading statistics and achievements."
        ),
    )
    # 全局 -V/--version 选项：打印版本后直接退出（action="version" 自动干这事）
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version="%(prog)s {}".format(__version__),
        help="show the wreader version and exit",
    )

    # 子命令容器：dest="command" 让解析结果里带一个 command 字段，用来查 handler
    subparsers = parser.add_subparsers(
        title="commands",
        dest="command",
        metavar="<command>",
        required=True,
    )

    # wreader import <path>：导入书籍的子命令
    import_parser = subparsers.add_parser(
        "import",
        help="scan a directory and import txt/epub books into the library",
    )
    # 位置参数 path：可以是单个文件，也可以是待扫描的目录
    import_parser.add_argument(
        "path",
        help="book file or directory to scan for .txt/.epub books",
    )

    # wreader list：不带任何参数，列出书库
    subparsers.add_parser("list", help="list the books stored in the library")

    # wreader search <keyword>：按标题/作者/标签模糊搜索
    search_parser = subparsers.add_parser(
        "search", help="fuzzy search books by title, author or tag",
    )
    # 位置参数 keyword：搜索关键词
    search_parser.add_argument(
        "keyword", help="keyword matched against title, author and tags",
    )

    # wreader read <book_id>：进入 curses 阅读界面
    read_parser = subparsers.add_parser(
        "read", help="open the paged curses reader for a book",
    )
    # 位置参数 book_id：要阅读的书
    read_parser.add_argument("book_id", help="id of the book to read")

    # wreader translate <book_id>：把整本书翻成目标语言并缓存
    translate_parser = subparsers.add_parser(
        "translate", help="translate a book into the configured target language",
    )
    # 位置参数 book_id：要翻译的书
    translate_parser.add_argument("book_id", help="id of the book to translate")

    # wreader vocab：默认分页列出笔记本
    vocab_parser = subparsers.add_parser(
        "vocab", help="manage the vocabulary notebook",
    )
    # --review：复习模式，先只给单词、按回车才揭晓释义
    vocab_parser.add_argument(
        "--review",
        action="store_true",
        help="shuffle the words and hide each meaning until you ask for it",
    )
    # --export：目前只支持导出成 anki 格式
    vocab_parser.add_argument(
        "--export",
        choices=("anki",),
        metavar="FORMAT",
        help="export the notebook (only 'anki' for now)",
    )
    # --search：按拼写、释义或例句找词
    vocab_parser.add_argument(
        "--search",
        metavar="KEYWORD",
        help="find words by spelling, meaning or context",
    )
    # --remove：从笔记本里删掉某个词
    vocab_parser.add_argument(
        "--remove",
        metavar="WORD",
        help="delete a word from the notebook",
    )
    # --page：列表模式看第几页，默认第 1 页
    vocab_parser.add_argument(
        "--page",
        type=int,
        default=1,
        help="page to show when listing (default 1)",
    )
    # --per-page：列表模式每页显示多少个词，默认 20
    vocab_parser.add_argument(
        "--per-page",
        type=int,
        default=20,
        help="words per page when listing (default 20)",
    )

    # wreader stats [--json]：阅读统计（时长、热力图等）
    stats_parser = subparsers.add_parser("stats", help="show reading statistics")
    # --json：输出机器可读的原始数据，而不是彩色表格
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="print the raw numbers as JSON instead of the table",
    )

    # wreader achievements：查看成就解锁情况
    subparsers.add_parser(
        "achievements", help="list achievements and unlock progress",
    )

    # wreader config [section.key] [value]：查看/修改设置
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
    """Build the rich table shared by ``wreader list`` and ``wreader search``."""
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
    """Render the default of one setting the way ``wreader config`` shows it."""
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
    """Handle ``wreader import <path>`` -- scan, convert and store books."""
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
    # 走到这里就返回成功；个别失败不影响整体退出码
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle ``wreader list`` -- show the whole library."""
    # 从索引里取出所有书
    books = library.list_books()

    # 书库是空的时候，顺手告诉用户书在哪、怎么导入
    if not books:
        console.print(
            "the library is empty -- add books with [bold]wreader import <path>[/bold]"
        )
        console.print("[dim]index:  {}[/dim]".format(config.library_file()))
        console.print("[dim]novels: {}[/dim]".format(config.novels_dir()))
        return 0

    # 有书就画表格；标题里带上总数
    console.print(_book_table("library ({} book(s))".format(len(books)), books))
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Handle ``wreader search <keyword>`` -- fuzzy search the library."""
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
    """Handle ``wreader config [section.key] [value]`` -- view or edit ``settings.toml``.

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
            return _fail("a value needs a key: wreader config <section.key> <value>")
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
    """Handle ``wreader read <book_id>`` -- open the paged curses reader."""
    try:
        # 延迟导入：curses 在部分平台（如某些 Windows 环境）不可用
        from . import reader
    except ImportError as exc:  # pragma: no cover - only on curses-less platforms
        return _fail("the reader needs the curses module: {}".format(exc))

    # 把书 id 交给阅读器，它会进入全屏循环直到用户退出
    return reader.open_reader(args.book_id)


def _count_translations(count: int) -> List[Dict[str, Any]]:
    """Record *count* translation uses and return the achievements they unlocked."""
    try:
        # 统计写在书库索引文件里，先读出来
        document = library.load_library()
        # 把翻译次数累加上去
        stats.bump_translations(document, count)
        # 再写回磁盘
        library.save_library(document)
    except library.LibraryError:
        # 索引坏了也没关系：章节缓存已经落盘，计数下次再补
        return []  # the chapters are cached either way; the counter can wait
    try:
        # 计数更新后看看有没有新解锁的成就
        return stats.check_achievements()
    except (library.LibraryError, stats.StatsError):
        # 成就检查失败不该影响翻译命令本身的成败，静默返回空
        return []


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


def cmd_translate(args: argparse.Namespace) -> int:
    """Handle ``wreader translate <book_id>`` -- translate every chapter of a book.

    Chapters already in the cache are skipped, so re-running the command after an
    interruption simply carries on where it stopped.
    """
    # 延迟导入 translator：它依赖网络/后端配置，不用的时候不想加载
    from . import translator

    try:
        # 读取翻译相关的设置（后端、目标语言、批大小等）
        settings = translator.load_settings()
        # 按 id 找书
        book = library.get_book(args.book_id)
        # 查不到就报错退出
        if book is None:
            return _fail("unknown book id: {}".format(args.book_id))
        # 数一数这本书有多少章，用来初始化进度条
        chapters = translator.chapter_count(book)
    except translator.TranslationError as exc:
        # 设置或书籍有问题，统一转成友好错误
        return _fail(str(exc))

    # 先打印一行摘要，让用户知道在用什么后端、要翻多少章
    console.print(
        "translating [bold]{}[/bold] · {} chapter(s) · backend [cyan]{}[/cyan] · "
        "batch {} chars".format(
            book.get("title") or args.book_id,
            chapters,
            settings.backend,
            settings.batch_size,
        )
    )

    # 翻译结果汇总；失败时保持 None，靠 failure 传错误信息
    summary: Optional[Dict[str, Any]] = None
    failure = ""
    # with 块负责起停进度条渲染
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        # 注册一个叫 chapters 的任务，总数是章节数
        task = progress.add_task("chapters", total=chapters)

        def report(done: int, total: int) -> None:
            # 回调：translator 每完成一章就调一次，用来刷新进度条
            progress.update(task, completed=done, total=total)

        try:
            # 真正的翻译循环；进度通过 report 回调回传
            summary = translator.translate_book(
                args.book_id, progress=report, settings=settings
            )
        except translator.TranslationError as exc:
            # 整个翻译过程级别的错误（比如后端不可用）
            failure = str(exc)

    # 有全局错误就直接失败
    if failure:
        return _fail(failure)
    # 理论上 translate_book 一定返回，这里只是兜底
    if summary is None:  # pragma: no cover - translate_book always returns
        return _fail("translation produced no result")

    # 打印统计：成功、跳过（已缓存）、失败各多少章
    console.print(
        "translated [green]{}[/green], skipped [yellow]{}[/yellow] (already cached), "
        "[red]{}[/red] failed".format(
            len(summary["translated"]), len(summary["skipped"]), len(summary["failed"])
        )
    )
    # 失败章节逐条列出原因（索引是 0 开始的，展示时 +1）
    for index, reason in summary["failed"]:
        err_console.print("  [red]![/red] chapter {}: {}".format(index + 1, reason))
    # 告诉用户译文缓存放在哪，方便手动清理
    console.print("[dim]cache: {}[/dim]".format(translator.book_cache_dir(args.book_id, settings)))
    # 只要真的翻了内容，就更新翻译次数统计并检查成就
    if summary["translated"]:
        _report_unlocked(_count_translations(len(summary["translated"])))
    # 有失败章节就返回 1，全成功返回 0
    return 1 if summary["failed"] else 0


def _vocab_table(title: str, entries: Sequence[Dict[str, Any]]) -> Table:
    """Build the table shared by the vocabulary listings."""
    # 五列：序号、单词、释义、来源书名、加入日期
    table = Table(title=title, title_justify="left")
    table.add_column("#", justify="right", style="dim")
    table.add_column("word", style="bold cyan")
    table.add_column("translation")
    table.add_column("book", style="dim")
    table.add_column("added", style="dim")
    # 从 1 开始编号
    for position, entry in enumerate(entries, start=1):
        # 所有字段都兜成空串，避免表格里出现 "None"
        table.add_row(
            str(position),
            str(entry.get("word") or ""),
            str(entry.get("translation") or ""),
            str(entry.get("book") or ""),
            # 只取日期部分，ISO 字符串前 10 位就是 YYYY-MM-DD
            str(entry.get("date_added") or "")[:10],
        )
    return table


def _vocab_list(args: argparse.Namespace, vocab: Any) -> int:
    """List the notebook a page at a time, newest first."""
    # 取出全部生词（list_words 默认最新在前）
    words = vocab.list_words()
    # 空笔记本：提示用阅读器里的 v 键做标记
    if not words:
        console.print(
            "the vocabulary notebook is empty -- mark words with "
            "[bold]v[/bold] while reading"
        )
        return 0
    # 按 --page/--per-page 切片，拿回「本页数据、总页数、实际页码」
    page_items, pages, current = vocab.paginate(words, args.page, args.per_page)
    # 标题里带上总数和页码信息
    console.print(
        _vocab_table(
            "vocabulary · {} word(s) · page {}/{}".format(len(words), current, pages),
            page_items,
        )
    )
    # 多页时提示怎么翻页
    if pages > 1:
        console.print(
            "[dim]use --page N to turn the page ({} per page)[/dim]".format(args.per_page)
        )
    return 0


def _vocab_search(args: argparse.Namespace, vocab: Any) -> int:
    """Find words by spelling, meaning or context."""
    # 关键词会同时匹配单词、释义、例句三处
    hits = vocab.search_words(args.search)
    # 没命中按惯例返回 1
    if not hits:
        console.print(
            "nothing in the notebook matches [bold]{}[/bold]".format(args.search)
        )
        return 1
    # 命中结果不分页，一次全列出来
    console.print(
        _vocab_table("{} match(es) for '{}'".format(len(hits), args.search), hits)
    )
    return 0


def _vocab_export(args: argparse.Namespace, vocab: Any) -> int:
    """Print the notebook in Anki's tab separated import format.

    Written with plain ``sys.stdout`` rather than rich so the tabs survive being
    redirected into a file: ``wreader vocab --export anki > deck.txt``.
    """
    # 导出的是全部生词，不分页
    words = vocab.list_words()
    # 空笔记本没什么可导的，提示写在 stderr（不污染导出的数据流）
    if not words:
        err_console.print("[yellow]the vocabulary notebook is empty[/yellow]")
        return 0
    # 用裸 sys.stdout 写，避免 rich 把制表符渲染成空格或自动折行
    sys.stdout.write(vocab.export_anki(words))
    # 立刻刷新缓冲区，保证重定向到文件时数据及时落盘
    sys.stdout.flush()
    # 统计信息写到 stderr，这样 `> deck.txt` 里只有干净的数据
    err_console.print("[dim]exported {} word(s) as Anki tsv[/dim]".format(len(words)))
    return 0


def _vocab_remove(args: argparse.Namespace, vocab: Any) -> int:
    """Delete one word from the notebook."""
    # remove_word 返回被删掉的那条；没找到会返回 None
    removed = vocab.remove_word(args.remove)
    if removed is None:
        return _fail("not in the notebook: {}".format(args.remove))
    # 告诉用户删掉的是哪个词（用记录里规范化的拼写，而不是用户输入的）
    console.print("removed [bold]{}[/bold]".format(removed["word"]))
    return 0


def _vocab_review(vocab: Any) -> int:
    """Shuffle the words and hide each meaning until the reader asks for it."""
    # 打乱顺序，避免每次复习都按同样的次序背
    entries = vocab.review_order()
    # 空笔记本没什么可复习的
    if not entries:
        console.print("the vocabulary notebook is empty")
        return 0
    # 总数用于显示 x/y 进度
    total = len(entries)
    # 非交互环境（比如输出被管道接走）没法等回车，改成直接全部列出来
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        console.print("[dim]not a terminal: printing every word with its meaning[/dim]")
        for position, entry in enumerate(entries, start=1):
            console.print(
                "{:>3}/{:<3} [bold cyan]{}[/bold cyan]  {}".format(
                    position, total, entry["word"], entry["translation"]
                )
            )
        return 0

    # 交互模式：一行操作提示
    console.print("[dim]review: recall the meaning, press Enter to check, q to stop[/dim]")
    for position, entry in enumerate(entries, start=1):
        # 只露单词，先不给释义；用户先自己回忆
        console.print(
            "\n[dim]{}/{})[/dim] [bold cyan]{}[/bold cyan]".format(
                position, total, entry["word"]
            )
        )
        try:
            # 等用户按回车（或输入 q）再揭晓答案
            answer = input()
        except (EOFError, KeyboardInterrupt):
            # Ctrl-D / Ctrl-C 都视为"提前结束"，礼貌地换行退出
            console.print()
            break
        # 输入 q/quit/exit 就结束本次复习
        if answer.strip().lower() in ("q", "quit", "exit"):
            break
        # 揭晓释义（没有释义时给个占位提示）
        console.print("    [green]{}[/green]".format(entry["translation"] or "(no meaning)"))
        # 有例句就一并显示，帮助回忆语境
        if entry["context"]:
            console.print("    [dim]{}[/dim]".format(entry["context"]))
    return 0


def cmd_vocab(args: argparse.Namespace) -> int:
    """Handle ``wreader vocab`` -- list, review, export, search or remove words.

    With no flags the notebook is listed a page at a time, newest first.
    """
    # 延迟导入：只有真的用到 vocab 命令时才加载
    from . import vocab

    try:
        # 五个分支按"互斥的旗标"从上往下判断，谁先命中就走谁
        if args.export:
            return _vocab_export(args, vocab)
        if args.search:
            return _vocab_search(args, vocab)
        if args.remove:
            return _vocab_remove(args, vocab)
        if args.review:
            return _vocab_review(vocab)
        # 什么旗标都没给：默认分页列出笔记本
        return _vocab_list(args, vocab)
    except vocab.VocabError as exc:
        # 笔记本损坏等情况统一转成友好错误
        return _fail(str(exc))


# 这几个指标本身是"秒"，展示时要换算成小时/分钟
_TIME_METRICS = ("total_time", "night_time", "single_session")

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
    """Handle ``wreader stats`` -- reading time totals plus a 30 day heatmap grid.

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
    # 让 stats 模块算出一份完整报告（一个纯数据的 dict）
    report = stats.build_report(document, settings=settings)
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
    # 连续天数、读完本数、生词数、翻译次数
    console.print(
        "连续 [bold]{}[/bold] 天（每天 ≥{} 分钟） · 读完 [bold]{}[/bold] 本 · "
        "生词 [bold]{}[/bold] 个 · 用过翻译 [bold]{}[/bold] 次".format(
            report["streak_days"],
            # 秒换算成分钟展示
            report["streak_min_seconds"] // 60,
            report["finished_books"],
            report["vocab_count"],
            report["translations"],
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
    """Handle ``wreader achievements`` -- unlocked list plus progress on the rest."""
    try:
        # 成就是根据统计数据判定的，先读书库索引
        document = library.load_library()
        # 读出成就定义（名称、条件等）
        definitions = stats.load_achievements()
        # Recording is idempotent, and doing it here means progress earned outside
        # the reader (through `wreader translate`, say) still gets a timestamp instead
        # of waiting for the next book to be closed.  No fanfare: that belongs to
        # the moment of unlocking while reading.
        # 顺手补记一次解锁：这个操作是幂等的，重复调用不会重复记录
        stats.check_achievements(document, achievements=definitions)
    except (library.LibraryError, stats.StatsError) as exc:
        return _fail(str(exc))

    # 当前各项指标的数值，用来算每个成就的进度
    metrics = stats.compute_metrics(document)
    # 已经记录下来的解锁信息
    state = document.get("achievements") or {}
    # 把解锁记录整理成 id -> 记录 的字典，方便下面查
    recorded = {}
    entries = state.get("unlocked") if isinstance(state, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            # 新格式：每条是个字典，取它的 id
            if isinstance(entry, dict) and entry.get("id"):
                recorded[str(entry["id"])] = entry
            # 老格式：每条就是个 id 字符串，补成统一结构
            elif isinstance(entry, str):
                recorded[entry] = {"id": entry, "unlocked_at": ""}

    # 分成"已解锁"和"进行中"两组
    done = []
    pending = []
    for achievement in definitions:
        # 算出这个成就当前进度以及是否达标
        info = stats.achievement_state(achievement, metrics)
        # 有解锁记录或当前指标已达标，都算已完成
        if info["id"] in recorded or info["unlocked"]:
            done.append((info, str((recorded.get(info["id"]) or {}).get("unlocked_at") or "")))
        else:
            pending.append(info)

    # 打印已解锁数量
    console.print(
        "[bold]已解锁 {}/{}[/bold]".format(len(done), len(definitions))
    )
    # 逐条列出已解锁的成就（带解锁时间，没有时间就不显示"解锁于"）
    for info, stamp in done:
        console.print(
            "  [green]🏆[/green] [bold]{}[/bold] [dim]{}  {}{}[/dim]".format(
                info["name"],
                info["desc"],
                "" if not stamp else "解锁于 ",
                stamp,
            )
        )
    # 有未完成的就再列一段进度
    if pending:
        console.print("\n[bold]进行中[/bold]")
        for info in pending:
            console.print(
                "  {}  [bold]{}[/bold] [dim]{}/{}  {}[/dim]".format(
                    # 一个简单的文本进度条
                    stats.progress_bar(info["current"], info["required"]),
                    info["name"],
                    _metric_text(info["metric"], info["current"]),
                    _metric_text(info["metric"], info["required"]),
                    info["desc"],
                )
            )
    return 0


# 命令名 -> 处理函数 的映射表；main 靠它把解析结果分发出去
_HANDLERS: Dict[str, Callable[[argparse.Namespace], int]] = {
    "import": cmd_import,
    "list": cmd_list,
    "search": cmd_search,
    "read": cmd_read,
    "translate": cmd_translate,
    "vocab": cmd_vocab,
    "stats": cmd_stats,
    "achievements": cmd_achievements,
    "config": cmd_config,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Entry point used by the ``wreader`` console script."""
    # 构造解析器（每次调用都新建，测试里可以重复使用）
    parser = build_parser()
    # 解析参数；argv 为 None 时 argparse 会自动取 sys.argv[1:]
    args = parser.parse_args(argv)
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

"""Shared fixtures for the wreader test suite.

Every test runs against a throwaway ``$WREADER_HOME``, so the real
``~/.wreader`` (settings, library, notebook and cache) is never touched.

The modules are written as plain functions over plain data, and the documented
seams are used here: ``$WREADER_HOME`` for the data directory,
:func:`wreader.translator.set_backend` for a network-free back-end,
``review_order(seed=...)`` for a reproducible shuffle and
``load_achievements(path)`` for a custom definition file.
"""

# 延迟求值类型注解
from __future__ import annotations

# 造 epub 测试文件时用
import zipfile
# Home 用 dataclass 定义
from dataclasses import dataclass
# 临时目录路径
from pathlib import Path
# 类型注解
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

# pytest 的 fixture / monkeypatch / raises
import pytest

# 被测模块
from wreader import config, library, translator, vocab

# 一本中文小书：两个章节、三段正文（行号是阅读器/翻译的基准）
#: A small book with three paragraphs and two detected chapters.
BOOK_LINES: Tuple[str, ...] = (
    "第一章 科学边界",
    "",
    "汪淼看到了一串数字在眼前跳动。",
    "他抬头望向窗外的夜空。",
    "",
    "第二章 台球",
    "",
    "“三体世界就在我们眼前。”丁仪说道。",
)

# 一本英文小书，用来测"书本身是英文/中文"时视图的区别
ENGLISH_LINES: Tuple[str, ...] = (
    "Chapter One",
    "",
    "It is a truth universally acknowledged.",
    "",
    "Chapter Two",
    "",
    "She was obliged to be plain.",
)


# 一次测试用的临时"家目录"：数据目录、正文目录、根目录
@dataclass
class Home:
    """The throwaway data directory one test runs against."""

    # ~/.wreader 的替身（放 settings.toml / library.json / vocab.json）
    data: Path
    # 转换后正文的存放目录（通常是 ~/novels）
    novels: Path
    # 整个 tmp 根目录
    root: Path

    def write_book(self, name: str, lines: Sequence[str] = BOOK_LINES) -> Path:
        """Write a txt book next to the other source files."""
        # 书统一放在 root/books/ 下，模拟"待导入的目录"
        target = self.root / "books" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # 按行写入，末尾补换行
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return target


# 自动应用于每个测试：把所有路径重定向到临时目录，并清空全局缓存
@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Home]:
    """Point every test at its own data directory and reset global state."""
    # 每个测试一套全新的目录
    home = Home(data=tmp_path / "data", novels=tmp_path / "novels", root=tmp_path)
    # 通过环境变量把 wreader 的"家"指过去
    monkeypatch.setenv(config.ENV_HOME, str(home.data))
    monkeypatch.setenv(config.ENV_NOVELS_DIR, str(home.novels))
    # The pre-rename names must not leak in from the developer's shell: they are
    # read as a fallback, so a stale value would beat the fixtures above.
    # 旧名字作为兜底会被读取，所以必须删掉，否则开发者本机的旧变量会盖过上面的设置
    monkeypatch.delenv(config.ENV_HOME_LEGACY, raising=False)
    monkeypatch.delenv(config.ENV_NOVELS_DIR_LEGACY, raising=False)
    # API key 同理：不能让本机环境变量影响测试
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # ``wreader.config`` caches by path+stamp and ``wreader.translator`` holds one global
    # back-end; clear both so no test can observe another test's state.
    # 清掉配置缓存与全局后端，保证测试之间互不干扰
    monkeypatch.setattr(config, "_CACHE", None)
    monkeypatch.setattr(config, "_CACHE_PATH", None)
    monkeypatch.setattr(config, "_CACHE_STAMP", None)
    translator.set_backend(None)
    # 把 Home 交给测试用
    yield home
    # 测试结束后再清一次后端，避免污染下一个测试
    translator.set_backend(None)


# 给需要显式拿到临时目录的测试用的同名 fixture
@pytest.fixture
def home(isolated_home: Home) -> Home:
    """Name the throwaway data directory for fixtures that need it explicitly.

    ``isolated_home`` is autouse; this is the same object under a shorter name.
    """
    # 就是 isolated_home 那个对象，只是换了个更好记的名字
    return isolated_home


# 假的翻译后端：记录调用、可控地"改写"结果，全程不联网
class RecordingBackend(translator.Backend):
    """A deterministic back-end that never touches the network.

    ``reflow`` makes the answer split into a different number of pieces than the
    input, which is what exercises the per-item retry path.
    """

    name = "recording"

    def __init__(self, prefix: str = "EN:", reflow: bool = False) -> None:
        # 译文前缀，方便断言"确实是这个后端翻的"
        self.prefix = prefix
        # True 时故意不按分隔符切分返回，用来触发逐条重试逻辑
        self.reflow = reflow
        # 记录每次调用的 (原文, 源语言, 目标语言)
        self.calls: List[Tuple[str, str, str]] = []
        # 记录 pause 被调用了几次（验证批次间限速）
        self.pauses = 0

    def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
        # 记下这次调用
        self.calls.append((text, source, target))
        # reflow 模式：整批只返回一段，份数永远对不上
        if self.reflow:
            # A single piece for the whole batch: never the input's piece count.
            flat = text.replace(translator.PARAGRAPH_SEPARATOR, " ")
            return "{} {}".format(self.prefix, flat)
        # 正常模式：按输入用的分隔符切开，逐段加前缀再拼回去
        separator = (
            translator.PARAGRAPH_SEPARATOR
            if translator.PARAGRAPH_SEPARATOR in text
            else "\n"
        )
        return separator.join(
            "{}{}".format(self.prefix, piece.strip()) for piece in text.split(separator)
        )

    def pause(self) -> None:
        # 计数即可，不真的 sleep
        self.pauses += 1


# 装上假后端的 fixture
@pytest.fixture
def backend() -> RecordingBackend:
    """Install a recording back-end for the duration of one test."""
    # 造一个并把它设为全局后端
    fake = RecordingBackend()
    translator.set_backend(fake)
    return fake


# 造 epub 文件的工厂 fixture
@pytest.fixture
def make_epub(tmp_path: Path):
    """Return a factory building an epub with a manifest and a spine."""

    def build(
        # 文件名
        name: str = "book.epub",
        # [(文件名, XHTML 内容), ...]
        documents: Optional[Sequence[Tuple[str, str]]] = None,
        # spine 里引用的 id 顺序
        spine: Optional[Sequence[str]] = None,
        # 是否写入 META-INF/container.xml（False 用来测兜底逻辑）
        with_container: bool = True,
        # 是否加入悬空引用（manifest/spine 里指向不存在的项）
        dangling: bool = False,
    ) -> Path:
        # 默认两个章节文档
        documents = documents or (
            ("first.xhtml", "<html><body><p>第一章</p></body></html>"),
            ("second.xhtml", "<html><body><p>第二章</p></body></html>"),
        )
        # 默认 spine 顺序
        spine = spine or ["c1", "c2"]
        # 文档名 -> manifest id 的映射
        ids = {"first.xhtml": "c1", "second.xhtml": "c2"}
        target = tmp_path / name
        # 用 zipfile 写一个最小的 epub
        with zipfile.ZipFile(str(target), "w") as archive:
            # container.xml 指向 opf
            if with_container:
                archive.writestr(
                    "META-INF/container.xml",
                    '<?xml version="1.0"?><container><rootfiles>'
                    '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
                )
            # 生成 manifest 里的 <item> 列表
            items = "".join(
                '<item id="{}" href="{}" media-type="application/xhtml+xml"/>'.format(
                    ids.get(document, document), document
                )
                for document, _ in documents
            )
            # 生成 spine 里的 <itemref> 列表
            refs = "".join('<itemref idref="{}"/>'.format(ref) for ref in spine)
            # 写 opf（dangling 时故意加两个悬空引用）
            archive.writestr(
                "OEBPS/content.opf",
                "<package><manifest>{}{}</manifest><spine>{}{}</spine></package>".format(
                    items,
                    '<item id="nohref"/>' if dangling else "",
                    refs,
                    '<itemref idref="dangling"/>' if dangling else "",
                ),
            )
            # 写入各章正文文档
            for document, markup in documents:
                archive.writestr("OEBPS/{}".format(document), markup)
        return target

    # 返回这个工厂函数，测试里可以反复调用
    return build


# 导入两本书（一中一英）并返回 id，方便多个测试复用
@pytest.fixture
def imported(home: Home) -> Dict[str, Any]:
    """Import two books and return their ids together with the import result."""
    # 中文书用"作者-书名"的命名，英文书用英文命名
    home.write_book("刘慈欣-三体.txt", BOOK_LINES)
    home.write_book("Jane Austen-Pride and Prejudice.txt", ENGLISH_LINES)
    # 走真正的导入流程
    result = library.import_books(str(home.root / "books"))
    # book_id 是按内容 SHA-1 生成的
    ids = [book_id for book_id, _ in result.imported]
    # 导入顺序按文件名排序：英文在前、中文在后
    return {"result": result, "ids": ids, "zh": ids[1], "en": ids[0], "home": home}


# 不需要终端就能构造 Pager 的工厂
@pytest.fixture
def pager_factory():
    """Build a :class:`wreader.reader.Pager` without a terminal."""
    # 延迟导入：curses 只在需要时加载
    from wreader import reader

    def build(lines: Sequence[str] = BOOK_LINES, **kwargs: Any):
        # 默认自动识别章节，并把页面压到 4 行方便断言分页
        defaults: Dict[str, Any] = {
            "chapters": library.parse_chapters(list(lines)),
            "page_height": 4,
        }
        # 调用方传的参数覆盖默认值
        defaults.update(kwargs)
        return reader.Pager(list(lines), **defaults)

    return build


# 一份"有统计数据"的书库文档，给成就相关测试用
@pytest.fixture
def achievements_document() -> Dict[str, Any]:
    """A document with one finished book, one started book and its statistics."""
    return {
        "books": {
            # aaa：读完的书，有一场跨午夜的会话（22:00 -> 次日 02:00）
            "aaa": {
                "title": "Read a lot",
                "progress": {
                    "current_line": 99,
                    "finished": True,
                    "total_time_seconds": 7200,
                    "sessions": [
                        {
                            "start": "2026-01-01T22:00:00",
                            "end": "2026-01-02T02:00:00",
                            "lines_read": 99,
                        }
                    ],
                },
            },
            # bbb：读了一点的书，会话在白天
            "bbb": {
                "title": "Started",
                "progress": {
                    "current_line": 5,
                    "finished": False,
                    "total_time_seconds": 600,
                    "sessions": [
                        {
                            "start": "2026-01-03T10:00:00",
                            "end": "2026-01-03T10:10:00",
                            "lines_read": 5,
                        }
                    ],
                },
            },
        },
        # 全局统计：两本书、7800 秒、两个有记录的日子、翻译 3 次
        "stats": {
            "total_books": 2,
            "total_read_time": 7800,
            "daily_read_time": {"2026-01-01": 3600, "2026-01-02": 3000},
            "translations": 3,
        },
        "achievements": {"unlocked": [], "progress": {}},
    }


# 一份测试专用的成就定义，避免依赖打包的那份文件
@pytest.fixture
def definitions() -> List[Dict[str, Any]]:
    """A tiny achievement list so tests do not depend on the shipped file."""
    return [
        {
            "id": "read_one",
            "name": "Read one",
            "desc": "one book with a session",
            "condition": "books_read >= 1",
        },
        {
            "id": "two_hours",
            "name": "Two hours",
            "desc": "two hours in total",
            "condition": "total_time >= 7200",
        },
        {
            "id": "night",
            "name": "Night owl",
            "desc": "an hour at night",
            "condition": "night_time >= 3600",
        },
    ]


# 预先塞两个生词的笔记本
@pytest.fixture
def notebook() -> Path:
    """Seed a notebook with two words and return its path."""
    # 两条记录都带例句，方便测上下文搜索与导出
    vocab.add_word("ephemeral", "短暂的", context="An ephemeral joy.", book="B")
    vocab.add_word("acknowledged", "公认的", context="A truth acknowledged.", book="B")
    return vocab.vocab_file()


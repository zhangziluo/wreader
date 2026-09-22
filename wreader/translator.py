"""Chapter level translation with a per chapter cache.

``wreader`` translates at **chapter** granularity because that is the unit a reader
actually wants cached: translate once, then re-read the English or the bilingual
text forever without paying the API again.

Configuration lives in ``~/.wreader/settings.toml``, in the ``[translator]`` table::

    [translator]
    backend = "google"          # google | deepseek
    batch_size = 3000           # characters per request
    cache_dir = "~/.wreader/cache"   # the default follows the data directory
    deepseek_api_key = ""       # empty -> $DEEPSEEK_API_KEY
    auto_translate_chapter = false
    source_language = "auto"
    target_language = "zh-CN"

:func:`load_settings` reads that table through :mod:`wreader.config`, so the defaults,
the type checks and the migration from the old ``config.json`` all apply; passing
an explicit *path* reads a standalone file instead (which is what the tests do).

Two back-ends are available:

``google``    :class:`GoogleBackend` wraps ``deep_translator.GoogleTranslator``;
              requests are cut at ``batch_size`` characters and throttled with a
              one second pause between batches to stay clear of rate limits.
``deepseek``  :class:`DeepSeekBackend` posts to the OpenAI compatible
              ``/v1/chat/completions`` endpoint with a Chinese-to-English system
              prompt, ``temperature`` 0.3 and streaming enabled.

Cache layout (per book, per chapter) is::

    ~/.wreader/cache/<book_id>/ch<index>_en.txt         the English chapter
    ~/.wreader/cache/<book_id>/ch<index>_bilingual.txt  paragraph paired 中/英

``_en.txt`` keeps one English paragraph per source paragraph, separated by blank
lines, which is what lets :func:`load_chapter_map` rebuild a line level mapping
for the reader.  Because a chapter is cached as one file, an interrupted run
simply skips the chapters that already exist.

The public surface is :func:`translate_chapter`, :func:`translate_viewport` and
:func:`get_cached_translation`, plus :func:`translate_book` for the CLI.  The
back-end is injectable with :func:`set_backend`, which is how the tests exercise
batching, throttling and the cache without a network.
"""

# 延迟求值类型注解
from __future__ import annotations

# 解析 DeepSeek 的 SSE 数据帧
import json
# 读写环境变量（DEEPSEEK_API_KEY）和原子替换文件
import os
# 按空行切段落、清理段落内的换行
import re
# Google 后端批次之间的限速等待
import time
# TranslatorSettings 用 dataclass 定义
from dataclasses import dataclass
# 缓存路径
from pathlib import Path
# 类型注解：Iterator 用于流式返回，Union 表示二选一
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

# 标准库 TOML 解析器（读独立测试用配置文件）
try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - the package requires >= 3.11
    tomllib = None  # type: ignore[assignment]

# 同包引用：配置（默认值/路径解析）与书库（取书记录和正文）
from . import config, library

# 简写：一个 (文本, 源语言, 目标语言) -> 译文 的普通函数，测试可注入
#: A plain ``(text, source, target) -> str`` function, accepted by set_backend().
TranslatorCallable = Callable[[str, str, str], str]

# 模块公开的名字：后端类、异常、设置、缓存与翻译函数
__all__ = [
    "Backend",
    "DeepSeekBackend",
    "GoogleBackend",
    "SettingsError",
    "TranslationError",
    "TranslationUnavailable",
    "TranslatorCallable",
    "TranslatorSettings",
    "batch_text",
    "book_cache_dir",
    "chapter_cache_path",
    "chapter_count",
    "chapter_lines",
    "clear_cache",
    "detect_language",
    "get_cached_translation",
    "load_chapter_map",
    "load_settings",
    "make_backend",
    "normalize_language",
    "set_backend",
    "translate_book",
    "translate_chapter",
    "translate_lines",
    "translate_text",
    "translate_viewport",
]

# 配置文件名与我们要读的那一段表名 [translator]
SETTINGS_FILENAME = "settings.toml"
SETTINGS_SECTION = "translator"

# 各字段的默认值：没配就用这些
DEFAULT_BACKEND = "google"
DEFAULT_BATCH_SIZE = 3000
CACHE_DIRNAME = "cache"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
# temperature 调到 0.3：翻译要稳，不要发挥
DEEPSEEK_TEMPERATURE = 0.3
# 给 DeepSeek 的系统提示词，决定翻译风格
DEEPSEEK_SYSTEM_PROMPT = (
    "你是一个专业的中译英翻译，擅长将中文网络小说翻译成流畅自然的英文，"
    "保留叙事节奏和人物情感。"
)
# 单次请求超时（秒）
DEEPSEEK_TIMEOUT = 120
# Google 批次之间的间隔（秒），用来躲限流
BATCH_SLEEP_SECONDS = 1.0

# 缓存文件后缀：纯英文版 / 中英对照版
EN_SUFFIX = "_en"
BILINGUAL_SUFFIX = "_bilingual"
# 段落分隔符：用连续空行，方便原样切回来
PARAGRAPH_SEPARATOR = "\n\n"

# 配置文件里能写的语言名 -> 后端认识的语言代码
#: Config language names mapped onto the codes the back-ends expect.
LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "cn": "zh-CN",
    "zh-cn": "zh-CN",
    "zh_cn": "zh-CN",
    "chinese": "zh-CN",
    "en": "en",
    "eng": "en",
    "english": "en",
}

# CJK 字符（中日韩）识别用
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# 非空白字符里 CJK 占比超过 15% 就判定为中文
_CJK_RATIO = 0.15


# 翻译失败（非网络原因）时抛这个
class TranslationError(Exception):
    """Raised for a translation that failed for a non-connectivity reason."""


# 后端完全连不上时抛这个（继承自 TranslationError，但调用方会更严格地处理）
class TranslationUnavailable(TranslationError):
    """Raised when the translation back-end cannot be reached at all."""


# 配置文件损坏/不可用时抛这个
class SettingsError(TranslationError):
    """Raised for a damaged or unusable ``settings.toml``."""


def normalize_language(name: Optional[str]) -> str:
    """Map a config language name onto a back-end code (default ``zh-CN``)."""
    # 归一化成小写去空白后再查别名表
    key = str(name or "").strip().lower()
    if key in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[key]
    # 不在别名表里：原样用用户写的值（是空就给默认 zh-CN）
    return str(name) if name else "zh-CN"


def detect_language(text: str) -> str:
    """Guess whether *text* is Chinese (``zh``) or English (``en``).

    The test is the share of CJK characters among all non-space characters,
    which separates the two cleanly: Chinese prose is mostly CJK, English prose
    has none.
    """
    sample = str(text or "")
    # 统计非空白字符个数当分母
    letters = sum(1 for character in sample if not character.isspace())
    # 空文本按英文处理（避免除以 0）
    if not letters:
        return "en"
    # 统计中文字符个数
    cjk = len(_CJK_RE.findall(sample))
    # 占比超过阈值就判成中文
    return "zh" if cjk / float(letters) >= _CJK_RATIO else "en"


# [translator] 配置表的对象化表示
@dataclass
class TranslatorSettings:
    """The ``[translator]`` table of ``settings.toml``."""

    # 用哪个后端：google 或 deepseek
    backend: str = DEFAULT_BACKEND
    # 每次请求最多多少字符
    batch_size: int = DEFAULT_BATCH_SIZE
    # 缓存目录（空串表示跟随数据目录）
    cache_dir: str = ""
    # DeepSeek 的 API key
    deepseek_api_key: str = ""
    deepseek_model: str = DEFAULT_DEEPSEEK_MODEL
    deepseek_url: str = DEEPSEEK_URL
    # 打开新章节时是否自动翻译
    auto_translate_chapter: bool = False
    # 源语言，"auto" 表示自动识别
    source_language: str = "auto"
    # 目标语言
    target_language: str = "zh-CN"

    def cache_root(self) -> Path:
        """Return the resolved cache root directory.

        An empty ``cache_dir`` -- and the documented default ``~/.wreader/cache`` --
        both mean "beside the rest of wreader's data", so the cache lives in
        ``$WREADER_HOME/cache`` when that is set instead of leaking into the real home
        directory.
        """
        # 交给 config 统一解析"跟随数据目录"的语义
        return config.resolve_cache_dir(self.cache_dir)

    def resolved_api_key(self) -> str:
        """Return the DeepSeek key, falling back to ``$DEEPSEEK_API_KEY``."""
        # 配置里有就用配置的，否则读环境变量
        return self.deepseek_api_key or os.environ.get("DEEPSEEK_API_KEY", "")


def settings_path() -> Path:
    """Return the path of ``settings.toml`` (``~/.wreader/settings.toml``)."""
    # 数据目录 + 文件名
    return config.data_dir() / SETTINGS_FILENAME


def _coerce_int(value: Any, key: str) -> int:
    """Return *value* as an int, or raise :class:`SettingsError`."""
    # bool 是 int 子类，必须先排掉（True 不该当成 1）
    if isinstance(value, bool):
        raise SettingsError(
            "[translator] {} must be an integer, got {!r}".format(key, value)
        )
    try:
        return int(value)
    except (TypeError, ValueError):
        raise SettingsError(
            "[translator] {} must be an integer, got {!r}".format(key, value)
        ) from None


def _coerce_bool(value: Any, key: str, fallback: bool) -> bool:
    """Return *value* as a bool, or raise :class:`SettingsError`."""
    # 没写这个键就用默认值
    if value is None:
        return fallback
    # 本来就是 bool
    if isinstance(value, bool):
        return value
    # 字符串写法：认这些"真"值
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on", "y", "t"):
        return True
    # 认这些"假"值
    if text in ("0", "false", "no", "off", "n", "f"):
        return False
    # 其它写法一律报错，避免"打错了却当成 False"
    raise SettingsError(
        "[translator] {} must be a boolean, got {!r}".format(key, value)
    )


def _read_document(target: Path) -> Dict[str, Any]:
    """Read a standalone TOML file, raising :class:`SettingsError`."""
    # 解释器太老没有 tomllib
    if tomllib is None:  # pragma: no cover - requires-python is >= 3.11
        raise SettingsError("reading settings.toml needs Python 3.11 or newer")
    try:
        # TOML 必须二进制模式读
        with target.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError("{} is not valid TOML: {}".format(target, exc)) from exc
    except OSError as exc:
        raise SettingsError("cannot read {}: {}".format(target, exc)) from exc


def _settings_from_section(section: Any, label: str) -> TranslatorSettings:
    """Validate one ``[translator]`` table into a :class:`TranslatorSettings`."""
    # 那一段必须是表
    if not isinstance(section, dict):
        raise SettingsError("{}: [{}] must be a table".format(label, SETTINGS_SECTION))

    # 先从默认值开始
    settings = TranslatorSettings()
    # backend 只接受 google / deepseek
    backend = str(section.get("backend") or DEFAULT_BACKEND).strip().lower()
    if backend not in ("google", "deepseek"):
        raise SettingsError(
            "[translator] backend must be 'google' or 'deepseek', got {!r}".format(backend)
        )
    settings.backend = backend
    # batch_size 至少为 1
    if section.get("batch_size") is not None:
        settings.batch_size = max(1, _coerce_int(section.get("batch_size"), "batch_size"))
    # 这几项只有写了才覆盖（空串保持默认）
    for key in ("cache_dir", "deepseek_api_key", "deepseek_model", "deepseek_url"):
        if section.get(key):
            setattr(settings, key, str(section[key]))
    # 语言项同理
    for key in ("source_language", "target_language"):
        if section.get(key):
            setattr(settings, key, str(section[key]))
    # 布尔项要严格校验
    settings.auto_translate_chapter = _coerce_bool(
        section.get("auto_translate_chapter"), "auto_translate_chapter", False
    )
    return settings


def load_settings(path: Optional[Path] = None) -> TranslatorSettings:
    """Read the ``[translator]`` table of ``settings.toml``.

    Without *path* the table is read through :mod:`wreader.config`, so the defaults,
    the type checks and the migration from the old ``config.json`` all apply.
    Passing an explicit *path* reads a standalone file instead.  Unknown keys
    inside the table are ignored so that a hand edited file carrying extra notes
    still loads.
    """
    # 情况一：显式给了路径（测试用）
    if path is not None:
        target = Path(path)
        # 文件不存在就用全默认值
        if not target.exists():
            return TranslatorSettings()
        # 读 TOML 再校验那一段
        document = _read_document(target)
        return _settings_from_section(
            document.get(SETTINGS_SECTION) or {}, str(target)
        )

    # 情况二：走 config，享受默认值/类型检查/旧配置迁移
    try:
        settings = config.load_config()
    except config.ConfigError as exc:
        # 统一转成 SettingsError，方便调用方只 catch 一种异常
        raise SettingsError(str(exc)) from exc
    # 注意用 raw_section：后端要自己校验 backend 的取值
    return _settings_from_section(
        settings.raw_section(SETTINGS_SECTION), str(settings.path)
    )


def cache_dir(settings: Optional[TranslatorSettings] = None) -> Path:
    """Return the root of the per chapter cache."""
    # 没传设置就现读一份
    settings = settings or load_settings()
    # 解析成真实路径（空值/默认值都跟随数据目录）
    return settings.cache_root()


def book_cache_dir(
    # 书的 id
    book_id: str,
    settings: Optional[TranslatorSettings] = None,
) -> Path:
    """Return the cache directory of one book."""
    # 缓存根目录下按 book_id 建子目录
    return cache_dir(settings) / str(book_id)


def chapter_cache_path(
    book_id: str,
    # 第几章（0 起始）
    chapter_index: int,
    # 文件后缀：_en 或 _bilingual
    suffix: str = EN_SUFFIX,
    settings: Optional[TranslatorSettings] = None,
) -> Path:
    """Return the cache path of one chapter file."""
    # 形如 ~/.wreader/cache/<book_id>/ch3_en.txt
    return book_cache_dir(book_id, settings) / "ch{}{}.txt".format(
        int(chapter_index), suffix
    )


def get_cached_translation(
    book_id: str,
    chapter_index: int,
    settings: Optional[TranslatorSettings] = None,
) -> Optional[Path]:
    """Return the cached English file of a chapter, or ``None`` when absent."""
    # 只看英文版缓存文件
    path = chapter_cache_path(book_id, chapter_index, EN_SUFFIX, settings)
    # 存在且非空才算命中（避免半截文件被当成有效缓存）
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


def clear_cache(
    # 传了就只清这本书的缓存；不传则清全部
    book_id: Optional[str] = None,
    settings: Optional[TranslatorSettings] = None,
) -> int:
    """Delete cached chapter files; returns how many files were removed."""
    # 确定要清理的根目录
    root = book_cache_dir(book_id, settings) if book_id else cache_dir(settings)
    # 目录不存在：没什么可删的
    if not root.exists():
        return 0
    # 统计删掉了多少个文件
    removed = 0
    for path in sorted(root.rglob("*.txt")):
        try:
            path.unlink()
            removed += 1
        except OSError:
            # 单个文件删不掉就跳过，不影响其它
            continue
    # 再自底向上删空目录（reverse=True 保证先删子目录）
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                # 目录非空或没权限：留着即可
                pass
    return removed


def _write_text(path: Path, text: str) -> Path:
    """Write *text* to *path* atomically and return the path."""
    # 父目录先建好
    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再改名，避免读到写了一半的缓存
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(str(temporary), str(path))
    return path


# 翻译后端基类：定义接口，具体实现交给子类
class Backend:
    """Base class for a translation back-end."""

    # 后端名，用于展示和调试
    name = "base"

    def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
        """Translate *text* and return the result."""
        # 基类不实现，强制子类覆写
        raise NotImplementedError

    def translate_stream(
        self, text: str, source: str = "auto", target: str = "en"
    ) -> Iterator[str]:
        """Yield the translation piece by piece when the back-end can stream."""
        # 默认没有流式能力：一次算完再整体 yield 出去
        yield self.translate(text, source, target)

    def pause(self) -> None:
        """Wait between two requests when the back-end is rate limited."""
        # 默认不需要限速
        return None


# 把普通函数包装成后端，方便测试注入假翻译
class _CallableBackend(Backend):
    """Adapts a plain ``(text, source, target) -> str`` function to a back-end."""

    name = "callable"

    def __init__(self, func: Callable[[str, str, str], str]) -> None:
        # 存下被包装的函数
        self._func = func

    def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
        # 调用它，并把 None 兜成空串
        return self._func(text, source, target) or ""


# 免费的 Google 翻译后端，批次之间要限速
class GoogleBackend(Backend):
    """``deep_translator.GoogleTranslator`` with a throttle between batches."""

    name = "google"

    def __init__(
        self,
        # 每次请求的字符上限
        batch_size: int = DEFAULT_BATCH_SIZE,
        # 请求之间的等待秒数
        sleep_seconds: float = BATCH_SLEEP_SECONDS,
    ) -> None:
        # 至少 1 个字符，避免无意义的空请求
        self.batch_size = max(1, int(batch_size))
        # 等待时间不能为负
        self.sleep_seconds = max(0.0, float(sleep_seconds))
        # 统计发过多少次请求（测试会断言这个）
        self.requests = 0

    def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
        """Translate one chunk through Google."""
        # 空文本不发请求，直接返回空
        if not str(text or "").strip():
            return ""
        try:
            # 延迟导入：不装 deep-translator 也能用别的后端
            from deep_translator import GoogleTranslator
        except ImportError as exc:  # pragma: no cover - the dependency is declared
            raise TranslationUnavailable("deep-translator is not installed") from exc
        # 计数 +1
        self.requests += 1
        try:
            # 真正调用；返回 None 时兜成空串
            return (
                GoogleTranslator(source=source or "auto", target=target).translate(text)
                or ""
            )
        except Exception as exc:  # rate limits, DNS failures, rejected codes
            # 限流、DNS 失败、语言码被拒等统一归为"后端不可用"
            raise TranslationUnavailable(
                "Google translation failed: {}".format(
                    str(exc) or exc.__class__.__name__
                )
            ) from exc

    def pause(self) -> None:
        """Wait out the one second throttle between batches."""
        # 配置了等待时间就真的睡一会儿
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)


# DeepSeek 后端：走 OpenAI 兼容的 chat/completions 接口，默认流式
class DeepSeekBackend(Backend):
    """DeepSeek chat completions, streamed by default."""

    name = "deepseek"

    def __init__(
        self,
        # API key；留空则读环境变量
        api_key: str = "",
        model: str = DEFAULT_DEEPSEEK_MODEL,
        url: str = DEEPSEEK_URL,
        temperature: float = DEEPSEEK_TEMPERATURE,
        timeout: int = DEEPSEEK_TIMEOUT,
    ) -> None:
        # 配置优先，其次环境变量
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model = model
        self.url = url
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        # 请求计数
        self.requests = 0

    def payload(self, text: str, target: str, stream: bool = True) -> Dict[str, Any]:
        """Return the JSON body sent to the API (exposed for the tests)."""
        # 标准的 chat completions 请求体：system 定风格，user 放待翻译文本
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _system_prompt(target)},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "stream": bool(stream),
        }

    def headers(self) -> Dict[str, str]:
        """Return the HTTP headers, including the bearer token."""
        # 用 Bearer token 鉴权
        return {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }

    def translate_stream(
        self, text: str, source: str = "auto", target: str = "en"
    ) -> Iterator[str]:
        """Yield the translation as the server streams it."""
        # 空文本不请求
        if not str(text or "").strip():
            return
        # 没 key 就直接给出可操作的提示
        if not self.api_key:
            raise TranslationUnavailable(
                "DeepSeek needs an API key: set [translator] deepseek_api_key in "
                "settings.toml or export DEEPSEEK_API_KEY"
            )
        try:
            # 延迟导入 requests
            import requests
        except ImportError as exc:  # pragma: no cover - the dependency is declared
            raise TranslationUnavailable("requests is not installed") from exc
        # 计数 +1
        self.requests += 1
        try:
            # stream=True 让 requests 不把响应体一次读完
            response = requests.post(
                self.url,
                json=self.payload(text, target, stream=True),
                headers=self.headers(),
                stream=True,
                timeout=self.timeout,
            )
            # 4xx/5xx 直接抛异常
            response.raise_for_status()
        except Exception as exc:
            # 建连阶段失败：归为后端不可用（会中断整本书的翻译）
            raise TranslationUnavailable(
                "DeepSeek request failed: {}".format(
                    str(exc) or exc.__class__.__name__
                )
            ) from exc
        try:
            # 逐行读 SSE（不预先解码，交给 _parse_sse 处理字节）
            for line in response.iter_lines(decode_unicode=False):
                piece = _parse_sse(line)
                if piece is None:  # the server sent [DONE]
                    # None 表示流正常结束，停止读取
                    break
                # 空串表示这一帧没带文本（比如心跳）
                if piece:
                    yield piece
        except TranslationError:
            # 已经是我们的异常（比如 key 无效），原样上抛
            raise
        except Exception as exc:  # a connection that dies mid answer
            # 读到一半连接断了
            raise TranslationUnavailable(
                "DeepSeek stream failed: {}".format(str(exc) or exc.__class__.__name__)
            ) from exc

    def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
        """Return the whole translation, joining the streamed pieces."""
        # 流式接口是核心，非流式就是把所有片段拼起来
        return "".join(self.translate_stream(text, source, target))


def _parse_sse(line: Any) -> Optional[str]:
    """Return the text carried by one SSE *line*.

    ``None`` means the stream is finished (``data: [DONE]``); an empty string
    means the frame carried no text at all.
    """
    # 空行（SSE 的心跳/分隔）：没带文本
    if not line:
        return ""
    # requests 给的是 bytes，先转字符串
    if isinstance(line, bytes):
        raw = line.decode("utf-8", errors="replace")
    else:
        raw = str(line)
    raw = raw.strip()
    # 不是 "data:" 开头的行（比如 event: 行）直接忽略
    if not raw or not raw.startswith("data:"):
        return ""
    # 去掉前缀 "data:"（5 个字符）
    body = raw[5:].strip()
    # [DONE] 表示流结束：返回 None 让调用方 break
    if body == "[DONE]":
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # 半截 JSON（不该发生）：当成空帧
        return ""
    # 收集这一帧里的文本片段
    pieces = []
    for choice in data.get("choices") or []:
        # 流式格式：delta.content
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            pieces.append(str(content))
        # 非流式格式：choice.text（仅在没有 delta 时才取）
        text = choice.get("text")
        if text and not delta:
            pieces.append(str(text))
    return "".join(pieces)


# 进程内当前生效的后端；None 表示还没建
_backend: Optional[Backend] = None


def make_backend(settings: Optional[TranslatorSettings] = None) -> Backend:
    """Build the back-end named by *settings*."""
    # 没传设置就现读
    settings = settings or load_settings()
    # deepseek 需要 key/model/url
    if settings.backend == "deepseek":
        return DeepSeekBackend(
            api_key=settings.resolved_api_key(),
            model=settings.deepseek_model,
            url=settings.deepseek_url,
        )
    # 否则默认用 Google
    return GoogleBackend(batch_size=settings.batch_size)


def set_backend(
    backend: Optional[Union[Backend, TranslatorCallable]],
) -> None:
    """Install a back-end, or a plain ``(text, source, target) -> str`` callable.

    This is the seam the tests use to exercise batching, throttling and the cache
    without touching the network.
    """
    # 要改模块级变量
    global _backend
    # 传 None 表示"清掉，下次重新按配置建"
    if backend is None:
        _backend = None
    # 已经是后端实例：直接用
    elif isinstance(backend, Backend):
        _backend = backend
    # 是普通函数：包一层
    elif callable(backend):
        _backend = _CallableBackend(backend)
    else:  # pragma: no cover - the annotation already rules this out
        raise TypeError("a Backend instance or a callable is required")


def get_backend(settings: Optional[TranslatorSettings] = None) -> Backend:
    """Return the active back-end, building the configured one on first use."""
    global _backend
    # 第一次用到时才真正构造（省得没翻译需求也初始化后端）
    if _backend is None:
        _backend = make_backend(settings)
    return _backend


def batch_text(items: Sequence[str], batch_size: int) -> List[List[int]]:
    """Group *items* into batches of at most *batch_size* characters.

    Returns index lists so the caller can map results back.  An item longer than
    *batch_size* still gets a batch of its own rather than being dropped.
    """
    # 每批的字符上限，至少为 1
    limit = max(1, int(batch_size))
    # 分批结果：每批是一组下标
    batches: List[List[int]] = []
    # 正在攒的这一批
    current: List[int] = []
    # 当前批已攒的字符数
    size = 0
    for index, item in enumerate(items):
        # +1 是给连接符留位置
        length = len(item) + 1
        # 已经攒了东西、再加就超限：先把这批发出去
        if current and size + length > limit:
            batches.append(current)
            current = []
            size = 0
        # 把当前项加进这批
        current.append(index)
        size += length
    # 收尾：最后不满一批的也要发出去
    if current:
        batches.append(current)
    return batches


def _flatten(pieces: Sequence[str]) -> str:
    """Join translated pieces into a single line."""
    # 去空白后拼成一行（一个段落内部的换行会被抹平）
    return " ".join(piece.strip() for piece in pieces if piece.strip())


def _translate_batches(
    # 待翻译的条目（段落或行）
    items: Sequence[str],
    # 条目之间的连接符，同时也是回切的分隔符
    separator: str,
    target: str,
    source: str,
    backend: Backend,
    # 每批的字符上限
    batch_size: int,
    # 进度回调 (已完成批数, 总批数)
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translate *items* batch by batch, returning one result per item.

    The items of one batch are joined with *separator* and sent as a single
    request, and the pause hook of the back-end runs between batches.  When the
    answer does not split back into the same number of pieces, the batch is
    retried one item at a time so the result always lines up with the input.
    """
    # 结果按原下标安放，None 表示还没翻
    results: List[Optional[str]] = [None] * len(items)
    # 空白条目不用翻，直接给空串
    for index, item in enumerate(items):
        if not item.strip():
            results[index] = ""
    # 按字符数分批
    batches = batch_text(items, batch_size)
    # 总批数（给进度条用）
    total = len(batches)
    # order 从 1 开始，方便算进度
    for order, batch in enumerate(batches, start=1):
        # 这批里真正有内容的条目
        wanted = [index for index in batch if items[index].strip()]
        if wanted:
            # 用分隔符把这一批拼成一次请求
            chunk = separator.join(items[index] for index in wanted)
            # 发请求，再按分隔符切回来
            pieces = (backend.translate(chunk, source, target) or "").split(separator)
            # 只有一个条目：全部拼成一行
            if len(wanted) == 1:
                results[wanted[0]] = _flatten(pieces)
            # 切回来的份数正好对得上：一一对应
            elif len(pieces) == len(wanted):
                for index, piece in zip(wanted, pieces):
                    results[index] = piece.strip()
            else:  # the back-end reflowed the text: retry item by item
                # 后端把分隔符弄丢了（或改写格式）：退化成逐条翻译，保证对齐
                for index in wanted:
                    single = backend.translate(items[index], source, target) or ""
                    results[index] = _flatten([single])
        # 每批结束回调一次进度
        if progress is not None:
            progress(order, total)
        # 不是最后一批就调用后端的限速钩子
        if order < total:
            backend.pause()
    # 把 None 兜成空串后返回
    return [value if value is not None else "" for value in results]


def translate_paragraphs(
    # 段落列表
    paragraphs: Sequence[str],
    target: str = "en",
    source: str = "auto",
    # 可注入后端
    backend: Optional[Backend] = None,
    settings: Optional[TranslatorSettings] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translate whole paragraphs, keeping one result per paragraph."""
    # 缺什么补什么
    settings = settings or load_settings()
    backend = backend or get_backend(settings)
    # 用空行当分隔符把多个段落凑成一次请求
    return _translate_batches(
        [str(part) for part in paragraphs],
        PARAGRAPH_SEPARATOR,
        normalize_language(target),
        normalize_language(source or "auto"),
        backend,
        settings.batch_size,
        progress,
    )


def translate_lines(
    # 行列表
    lines: Sequence[str],
    target: str = "en",
    source: str = "auto",
    backend: Optional[Backend] = None,
    settings: Optional[TranslatorSettings] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> List[str]:
    """Translate *lines*, returning one translation per line.

    Kept for callers that need a strict line alignment (the reader's bilingual
    view uses paragraph pairing instead, see :func:`translate_paragraphs`).
    """
    settings = settings or load_settings()
    backend = backend or get_backend(settings)
    # 这里用换行当分隔符，保证逐行对齐
    return _translate_batches(
        [str(line) for line in lines],
        "\n",
        normalize_language(target),
        normalize_language(source or "auto"),
        backend,
        settings.batch_size,
        progress,
    )


def translate_text(
    # 要翻译的文本
    text: str,
    target: str = "en",
    source: str = "auto",
    backend: Optional[Backend] = None,
    settings: Optional[TranslatorSettings] = None,
) -> str:
    """Translate one piece of text and return it (never cached)."""
    needle = str(text or "")
    # 空文本原样返回，不浪费一次请求
    if not needle.strip():
        return needle
    settings = settings or load_settings()
    backend = backend or get_backend(settings)
    # 单次调用后端，不走分批逻辑
    return (
        backend.translate(
            needle, normalize_language(source or "auto"), normalize_language(target)
        )
        or ""
    )


def translate_viewport(
    # 屏幕上这一屏的文本
    text: str,
    target: str = "en",
    source: str = "auto",
    backend: Optional[Backend] = None,
    settings: Optional[TranslatorSettings] = None,
) -> str:
    """Translate the text on screen without caching anything (the reader's ``t``).

    Paragraphs are translated as units and rejoined with a blank line, so the
    back-end sees context instead of a pile of disconnected lines and the caller
    can pair the result back onto paragraphs.
    """
    needle = str(text or "")
    if not needle.strip():
        return needle
    # 按空行切成段落（忽略纯空白的段）
    parts = [part for part in re.split(r"\n\s*\n", needle) if part.strip()]
    # 段落内部的换行抹平成空格，让后端看到完整句子
    blocks = [re.sub(r"\s*\n\s*", " ", part).strip() for part in parts]
    settings = settings or load_settings()
    backend = backend or get_backend(settings)
    # 逐段翻译
    translated = translate_paragraphs(
        blocks, target=target, source=source, backend=backend, settings=settings
    )
    # 用空行重新拼回去，调用方可以按段配对
    return PARAGRAPH_SEPARATOR.join(piece for piece in translated if piece)


def _require_book(book_id: str) -> Dict[str, Any]:
    """Return the library record for *book_id*, or raise."""
    # 从书库按 id 查
    book = library.get_book(str(book_id))
    if book is None:
        raise TranslationError("unknown book id: {}".format(book_id))
    return book


def read_book_lines(book: Dict[str, Any]) -> List[str]:
    """Return the stored UTF-8 text of *book*, split exactly as it was imported."""
    # 导入时存下的 UTF-8 正文路径
    path = Path(str(book.get("file_path") or ""))
    # 文件被删了：明确报错
    if not path.is_file():
        raise TranslationError("book text is missing: {}".format(path))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TranslationError("cannot read {}: {}".format(path, exc)) from exc
    # 与导入时一致地规范化换行，保证行号对得上
    text = library.normalise_newlines(text)
    # 按 \n 切行；空文本返回空列表
    return text.split("\n") if text else []


def chapter_count(book: Dict[str, Any]) -> int:
    """Return how many chapters *book* has (1 when none were detected)."""
    # 没识别出章节的书整体算一章
    chapters = book.get("chapters") or []
    return len(chapters) if chapters else 1


def chapter_start_line(book: Dict[str, Any], chapter_index: int) -> int:
    """Return the absolute source line a chapter starts at."""
    chapters = book.get("chapters") or []
    index = int(chapter_index)
    # 没有章节信息、或下标越界：返回到全书开头
    if not chapters or index < 0 or index >= len(chapters):
        return 0
    # 章节记录里存的就是绝对行号
    return max(0, int(chapters[index].get("line_start") or 0))


def chapter_lines(book: Dict[str, Any], chapter_index: int) -> List[str]:
    """Return the source lines of one chapter (a slice of the whole book)."""
    # 先把整本书的行读出来
    lines = read_book_lines(book)
    chapters = book.get("chapters") or []
    index = int(chapter_index)
    # 整本书算一章的情况：只允许 index 0
    if not chapters:
        if index != 0:
            raise TranslationError("book has a single chapter (index 0)")
        return lines
    # 下标越界
    if index < 0 or index >= len(chapters):
        raise TranslationError(
            "chapter {} is out of range (0-{})".format(index, len(chapters) - 1)
        )
    # 本章起点 = 本条的 line_start
    start = chapter_start_line(book, index)
    # 本章终点 = 下一章的 line_start；最后一章就到全书末尾
    if index + 1 < len(chapters):
        end = int(chapters[index + 1].get("line_start") or 0)
    else:
        end = len(lines)
    # 切片（max 保证起点大于终点时也不会倒序）
    return lines[start : max(start, end)]


def paragraph_spans(
    # 全部行
    lines: Sequence[str],
    # 只关心 [first, last] 范围内的段落
    first: int = 0,
    last: Optional[int] = None,
) -> List[Tuple[int, int]]:
    """Return the inclusive line spans of the blank-line separated paragraphs.

    Only paragraphs intersecting ``[first, last]`` come back, but each one is
    returned whole, so translating a single screenful still gives every touched
    paragraph its complete text.
    """
    total = len(lines)
    if not total:
        return []
    # 关心的区间（夹到合法范围）
    start = max(0, int(first))
    stop = total - 1 if last is None else min(int(last), total - 1)
    # 每个段落记成 (起行, 止行) 闭区间
    spans: List[Tuple[int, int]] = []
    index = 0
    while index < total:
        # 跳过空行（空行是段落分隔）
        if not str(lines[index]).strip():
            index += 1
            continue
        # 段落的第一行
        begin = index
        # 一直走到下一个空行
        while index < total and str(lines[index]).strip():
            index += 1
        # 段落的最后一行
        end = index - 1
        # 与关心的区间没有交集：丢掉
        if end < start or begin > stop:
            continue
        # 有交集就整段收下（保证段落完整）
        spans.append((begin, end))
    return spans


def paragraph_texts(
    # 全部行
    lines: Sequence[str],
    # 段落区间
    spans: Sequence[Tuple[int, int]],
) -> List[str]:
    """Return the source text of each span, with inner newlines flattened."""
    # 每个段落拼成一行文本（段内换行压成空格），方便当成一个整体发给后端
    return [
        re.sub(r"\s*\n\s*", " ", "\n".join(lines[begin : end + 1])).strip()
        for begin, end in spans
    ]


def map_paragraphs(
    # 段落区间
    spans: Sequence[Tuple[int, int]],
    # 每段的译文
    translations: Sequence[str],
) -> Dict[int, str]:
    """Map paragraph translations onto source lines.

    A paragraph's English goes on its first line; the remaining lines of that
    paragraph get an empty string, which the reader reads as "already covered by
    the paragraph above" and therefore does not draw a second time.
    """
    # 行号 -> 译文
    mapping: Dict[int, str] = {}
    # 段落与译文一一配对（zip 会在短的用尽时停下）
    for (begin, end), text in zip(spans, translations):
        # 译文挂在这一段的第一行
        mapping[begin] = text
        # 段内其余行给空串，表示"已经被上一行覆盖"
        for index in range(begin + 1, end + 1):
            mapping[index] = ""
    return mapping


def build_bilingual(
    # 原文全部行
    lines: Sequence[str],
    # 段落区间
    spans: Sequence[Tuple[int, int]],
    # 每段译文
    translations: Sequence[str],
) -> str:
    """Return the paragraph paired 中文/英文 text of a chapter."""
    # 一个段落一段中文 + 一段英文
    blocks: List[str] = []
    for (begin, end), english in zip(spans, translations):
        # 段落原文
        chinese = "\n".join(lines[begin : end + 1]).strip()
        if chinese:
            blocks.append(chinese)
        # 段落译文
        if english.strip():
            blocks.append(english.strip())
    # 段与段之间空一行，末尾补一个换行
    return "\n\n".join(blocks) + "\n"


def translate_chapter(
    book_id: str,
    # 第几章（0 起始）
    chapter_index: int,
    target: str = "en",
    # 源语言；不传就自动识别
    source: Optional[str] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    settings: Optional[TranslatorSettings] = None,
    backend: Optional[Backend] = None,
    # True 表示忽略已有缓存重翻
    force: bool = False,
) -> Path:
    """Translate one chapter into ``ch<index>_en.txt`` and return its path.

    An existing cache file short circuits the call unless *force* is set, which is
    exactly what makes an interrupted run resumable: the chapters already on disk
    are skipped.  The paragraph paired ``_bilingual.txt`` is written beside it.
    """
    settings = settings or load_settings()
    index = int(chapter_index)
    # 已经缓存过且不强制重翻：直接返回缓存路径（这就是"可续传"的关键）
    cached = get_cached_translation(book_id, index, settings)
    if cached is not None and not force:
        return cached

    # 取书和本章原文
    book = _require_book(book_id)
    lines = chapter_lines(book, index)
    # 整章都是空白：没什么可翻的
    if not any(str(line).strip() for line in lines):
        raise TranslationError(
            "chapter {} of {} has no text to translate".format(index, book_id)
        )
    # 划出段落边界
    spans = paragraph_spans(lines)
    # 源语言：调用方没给就用前 40 行自动判断
    source = source or detect_language("\n".join(lines[:40]))
    # 逐段翻译
    english = translate_paragraphs(
        paragraph_texts(lines, spans),
        target=target,
        source=source,
        backend=backend,
        settings=settings,
        progress=progress,
    )
    # 写英文版缓存：段与段之间用空行分隔，末尾补换行
    chapter_path = _write_text(
        chapter_cache_path(book_id, index, EN_SUFFIX, settings),
        PARAGRAPH_SEPARATOR.join(text for text in english if text) + "\n",
    )
    # 顺手写中英对照版（阅读器切换视图时用）
    _write_text(
        chapter_cache_path(book_id, index, BILINGUAL_SUFFIX, settings),
        build_bilingual(lines, spans, english),
    )
    return chapter_path


def load_chapter_map(
    book_id: str,
    chapter_index: int,
    settings: Optional[TranslatorSettings] = None,
) -> Dict[int, str]:
    """Return a cached chapter as a ``source line -> English`` mapping.

    The keys are **absolute** source lines in the whole book, matching what the
    reader's ``Pager`` indexes, so the mapping can be merged straight into its
    translation table.  The mapping follows :func:`map_paragraphs`.
    """
    settings = settings or load_settings()
    # 没有缓存就没有映射
    cached = get_cached_translation(book_id, chapter_index, settings)
    if cached is None:
        return {}
    try:
        text = cached.read_text(encoding="utf-8")
    except OSError as exc:
        raise TranslationError("cannot read {}: {}".format(cached, exc)) from exc
    # 缓存文件本身就是用空行分隔段落的，切回来即可
    paragraphs = [
        part.strip() for part in text.split(PARAGRAPH_SEPARATOR) if part.strip()
    ]
    # 索引里的章节信息用来把"章内行号"换算成"全书行号"
    book = _require_book(book_id)
    offset = chapter_start_line(book, chapter_index)
    # 重新算一遍章节内的段落区间，再整体平移 offset
    spans = [
        (begin + offset, end + offset)
        for begin, end in paragraph_spans(chapter_lines(book, chapter_index))
    ]
    # 缓存段落比实际段落多（多半是手工改过）：只配能配上的
    if len(paragraphs) > len(spans):
        # A hand edited cache: pair what we can instead of failing outright.
        paragraphs = paragraphs[: len(spans)]
    return map_paragraphs(spans, paragraphs)


def translate_book(
    book_id: str,
    target: str = "en",
    # 源语言；不传就每章自动识别
    source: Optional[str] = None,
    # 进度回调 (已完成章数, 总章数)
    progress: Optional[Callable[[int, int], None]] = None,
    settings: Optional[TranslatorSettings] = None,
    backend: Optional[Backend] = None,
    # True 表示已有缓存也重翻
    force: bool = False,
) -> Dict[str, Any]:
    """Translate every chapter of *book_id*, skipping the ones already cached.

    ``progress`` is called with ``(chapters_done, chapters_total)``.  A chapter
    that fails does not abort the run: it lands in ``failed`` so that the next
    invocation picks it up, which together with the cache is the resume story.  A
    connectivity failure still aborts, because trying every remaining chapter
    would only burn time.
    """
    settings = settings or load_settings()
    # 先确认书存在
    book = _require_book(book_id)
    # 总章数
    total = chapter_count(book)
    # 三类结果分别记账
    translated: List[int] = []
    skipped: List[int] = []
    failed: List[Tuple[int, str]] = []
    # 逐章处理
    for index in range(total):
        # 已有缓存且不强制重翻：跳过
        if get_cached_translation(book_id, index, settings) is not None and not force:
            skipped.append(index)
        else:
            try:
                # 真正翻译这一章（内部会写缓存）
                translate_chapter(
                    book_id,
                    index,
                    target=target,
                    source=source,
                    settings=settings,
                    backend=backend,
                    force=force,
                )
                translated.append(index)
            except TranslationUnavailable:
                # 网络/后端整体不可用：继续翻剩下的只会白等，直接中断
                raise
            except TranslationError as exc:
                # 单章失败（比如接口偶发报错）：记下来，下次再补
                failed.append((index, str(exc)))
        # 每章结束回调一次进度
        if progress is not None:
            progress(index + 1, total)
    # 汇总结果，CLI 按这个打印
    return {
        "book_id": str(book_id),
        "chapters": total,
        "translated": translated,
        "skipped": skipped,
        "failed": failed,
    }


def _system_prompt(target: str) -> str:
    """Return the system prompt for *target*.

    The Chinese-to-English prompt is the one the project was specified with; any
    other target gets an equivalent so that single word lookups still work.
    """
    # 目标语言是英文：用项目定制的那段提示词
    if target in ("en", "en-US", "en-GB"):
        return DEEPSEEK_SYSTEM_PROMPT
    # 其它目标语言：套一个通用模板
    return (
        "你是一个专业的翻译，请把用户给出的文本翻译成 {}，"
        "保留叙事节奏和人物情感，只输出译文。".format(target)
    )

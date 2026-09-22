"""User configuration handling.

Everything wreader can be told to do differently lives in one TOML document,
``~/.wreader/settings.toml``::

    [reader]
    page_scroll_step = 1          # 每次翻页行数（默认1页）
    status_bar_format = "time|chapter|duration"
    auto_save_interval = 60       # 自动保存进度间隔（秒），0 = 关闭

    [translator]
    backend = "google"            # google | deepseek
    batch_size = 3000             # 每次请求的字符数上限
    cache_dir = "~/.wreader/cache"     # 译文缓存目录
    deepseek_api_key = ""         # 或读环境变量 DEEPSEEK_API_KEY
    auto_translate_chapter = false  # 是否自动翻译新章节

    [stats]
    daily_goal_minutes = 60       # 每日阅读目标（分钟），0 = 关闭
    show_heatmap = true           # wreader stats 里显示热力图

    [vocab]
    highlight_in_reader = true    # 阅读器中高亮生词
    auto_add_on_mark = true       # 标记后自动加入生词本

Keys are addressed by their dotted path::

    settings = config.load_config()
    settings.get("reader.page_height")              # 24
    settings.set("translator.backend", "deepseek")
    settings.save()

or, in one line each, through the module helpers::

    config.get("reader.page_height")
    config.set("reader.page_height", 30)            # writes settings.toml

The sections the specification lists come first in every table; the keys the rest
of wreader already used (``page_height``, ``theme``, ``store_history``,
``source_language``, ``target_language``, ``deepseek_model``, ``deepseek_url``,
``achievement_sound``, ``novels_dir``) follow them, and ``library.novels_dir``
gets a section of its own.

Three locations matter to wreader:

* the **data directory** (``~/.wreader``) holding ``settings.toml`` and ``library.json``,
* the **novels directory** (``~/novels``) holding the UTF-8 converted texts,
* the **cache directory** (``~/.wreader/cache``) holding the translated chapters.

Each one is resolved as follows (first match wins):

* data directory   -- ``$WREADER_HOME``, otherwise ``~/.wreader``
  (``%APPDATA%\\wreader`` on Windows)
* novels directory -- ``$WREADER_NOVELS_DIR``, otherwise ``library.novels_dir``,
  otherwise ``~/novels``
* cache directory  -- ``translator.cache_dir``, where the documented default
  follows the data directory

The tool was called ``nr`` before the rename, so three old names are still
understood: the environment variables ``$NR_HOME`` / ``$NR_NOVELS_DIR`` (used
only when the new one is unset), the data directory ``~/.nr`` (adopted once,
see :func:`migrate_legacy_data_dir`) and the ``~/.nr/cache`` default value of
``translator.cache_dir`` (still read as "follow the data directory" rather than
as a literal path).

The flat ``config.json`` older versions wrote is folded into the matching
sections the first time the settings are loaded, and then renamed to
``config.json.bak`` so nothing is lost and nothing stale is left behind.
"""

# 延迟求值类型注解，注解不会在运行时被解析
from __future__ import annotations

# difflib：用户把设置名打错时，用它按相似度推荐最接近的名字
import difflib
# 用来读取老版本那个扁平的 config.json
import json
# 读环境变量（WREADER_HOME / APPDATA 等）
import os
# 把旧数据目录 ~/.nr 整个搬到 ~/.wreader 时用 shutil.move
import shutil
# 用 sys.platform 判断是不是 Windows
import sys
# Path 表示目录和文件路径
from pathlib import Path
# 类型注解：Any 任意类型，其余是容器/可选
from typing import Any, Dict, List, Optional, Tuple

# 标准库自带的 TOML 解析器，Python 3.11 起可用（本项目的 requires-python 就是 3.11+）
try:  # the standard library parser, available from Python 3.11 (what wreader needs)
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on an older interpreter
    # 老解释器上没有它：先置 None，等真正读文件时再抛出带说明的 ConfigError
    tomllib = None  # type: ignore[assignment]

# 模块公开的名字：配置类、常量、路径函数和读写辅助
__all__ = [
    "APP_NAME",
    "CACHE_DIRNAME",
    "COMMENTS",
    "Config",
    "ConfigError",
    "DATA_DIRNAME",
    "DEFAULTS",
    "DEFAULT_CACHE_DIR",
    "DEFAULT_FLAT",
    "ENV_HOME",
    "ENV_HOME_LEGACY",
    "ENV_NOVELS_DIR",
    "ENV_NOVELS_DIR_LEGACY",
    "LEGACY_APP_NAME",
    "LEGACY_DATA_DIRNAME",
    "LEGACY_DEFAULT_CACHE_DIR",
    "LEGACY_PATHS",
    "SCHEMA",
    "SETTINGS_FILENAME",
    "all_paths",
    "cache_dir",
    "coerce_value",
    "config_path",
    "data_dir",
    "default_cache_dir",
    "default_for",
    "default_novels_dir",
    "effective_values",
    "get",
    "legacy_config_path",
    "legacy_data_dir",
    "library_file",
    "load",
    "load_config",
    "migrate_legacy_data_dir",
    "novels_dir",
    "reload",
    "render_toml",
    "reset",
    "resolve_cache_dir",
    "resolve_path",
    "section_defaults",
    "set",
    "settings_path",
]

# 应用名；Windows 下数据目录是 %APPDATA%\wreader
APP_NAME = "wreader"
# 主设置文件名
SETTINGS_FILENAME = "settings.toml"
# 旧版扁平配置文件的名字（会被备份成 .bak）
LEGACY_CONFIG_FILENAME = "config.json"
# 书库索引文件名
LIBRARY_FILENAME = "library.json"
# 译文缓存目录的目录名（放在数据目录下面）
CACHE_DIRNAME = "cache"

# 数据目录的目录名：POSIX 下是 ~/.wreader，Windows 下是 %APPDATA%\wreader
#: Directory name of the data directory: ``~/.wreader``, ``%APPDATA%\wreader``.
DATA_DIRNAME = ".wreader"

# 工具改名之前叫 nr，这两个常量描述它的老数据目录
#: The tool was called ``nr`` before the rename; these name its data directory,
#: which is adopted once by :func:`migrate_legacy_data_dir`.
LEGACY_APP_NAME = "nr"
LEGACY_DATA_DIRNAME = ".nr"

# translator.cache_dir 的"字面默认值"；写进文件的是这个字符串，
# 但解析时会理解成"跟随数据目录"，这样 $WREADER_HOME 依然生效
#: The documented default of ``translator.cache_dir``.  It is written to the file
#: as ``~/.wreader/cache`` but resolved beside the data directory, so ``$WREADER_HOME`` keeps
#: working and a test run never writes into the real home directory.
DEFAULT_CACHE_DIR = "~/.wreader/cache"

# 改名之前写下的 settings.toml 里存的是这个值；含义同样是"跟随数据目录"
#: The same setting in a ``settings.toml`` written before the rename.  It means
#: "follow the data directory" just like the current default, not "use ~/.nr".
LEGACY_DEFAULT_CACHE_DIR = "~/.nr/cache"

# 环境变量名：新名字优先，改名前的名字作为兜底
#: Environment variables, new name first and the pre-rename one as a fallback.
ENV_HOME = "WREADER_HOME"
ENV_HOME_LEGACY = "NR_HOME"
ENV_NOVELS_DIR = "WREADER_NOVELS_DIR"
ENV_NOVELS_DIR_LEGACY = "NR_NOVELS_DIR"

# 生成 settings.toml 时，行尾注释左对齐到第几列
#: Column the inline comments of the generated file line up at.
_COMMENT_COLUMN = 32

# 全部设置项的定义表：section -> ((键, 默认值, 行尾注释), ...)
# 默认值同时决定了这个键的类型（见 coerce_value），写入文件的顺序也按这张表
#: ``(key, default, comment)`` for every section, in the order they are written.
#: The default value also declares the type, see :func:`coerce_value`.
SCHEMA: Dict[str, Tuple[Tuple[str, Any, str], ...]] = {
    # 阅读界面相关
    "reader": (
        ("page_scroll_step", 1.0, "每次翻页行数（默认1页）"),
        ("status_bar_format", "time|chapter|duration", ""),
        ("auto_save_interval", 60, "自动保存进度间隔（秒），0 = 关闭"),
        ("page_height", 24, "每屏显示的行数"),
        ("theme", "default", "配色主题名（预留）"),
        ("store_history", True, "退出时把本次会话时长记入统计"),
    ),
    # 翻译后端相关
    "translator": (
        ("backend", "google", "google | deepseek"),
        ("batch_size", 3000, "每次请求的字符数上限"),
        ("cache_dir", DEFAULT_CACHE_DIR, "译文缓存目录，默认跟随数据目录"),
        ("deepseek_api_key", "", "或读环境变量 DEEPSEEK_API_KEY"),
        ("auto_translate_chapter", False, "是否自动翻译新章节"),
        ("source_language", "auto", "原文语言，auto = 自动识别"),
        ("target_language", "zh-CN", "译文语言"),
        ("deepseek_model", "deepseek-chat", "DeepSeek 模型名"),
        ("deepseek_url", "https://api.deepseek.com/v1/chat/completions", "接口地址"),
    ),
    # 统计与成就相关
    "stats": (
        ("daily_goal_minutes", 60, "每日阅读目标（分钟），0 = 关闭"),
        ("show_heatmap", True, "wreader stats 里显示热力图"),
        ("achievement_sound", True, "解锁成就时响铃（\\a）"),
    ),
    # 生词本相关
    "vocab": (
        ("highlight_in_reader", True, "阅读器中高亮生词"),
        ("auto_add_on_mark", True, "标记后自动加入生词本"),
    ),
    # 书库位置相关
    "library": (
        ("novels_dir", None, "留空 = ~/novels"),
    ),
}

# 默认值，按 section 嵌套：DEFAULTS["reader"]["page_height"]
#: The defaults, nested by section (``DEFAULTS["reader"]["page_height"]``).
DEFAULTS: Dict[str, Dict[str, Any]] = {
    # 把 SCHEMA 里每个 section 的 (键, 值) 重新组装成 {键: 值}
    section: {key: value for key, value, _ in keys} for section, keys in SCHEMA.items()
}

# 同样一份默认值，但按"点号路径"存放：DEFAULT_FLAT["reader.page_height"]
#: The same defaults keyed by dotted path (``DEFAULT_FLAT["reader.page_height"]``).
DEFAULT_FLAT: Dict[str, Any] = {
    "{}.{}".format(section, key): value
    for section, keys in SCHEMA.items()
    for key, value, _ in keys
}

# 每个键对应的行尾注释，按点号路径存放
#: The inline comment written after each key, keyed by dotted path.
COMMENTS: Dict[str, str] = {
    "{}.{}".format(section, key): comment
    for section, keys in SCHEMA.items()
    for key, _, comment in keys
}

# 老 config.json 里的扁平键名 -> 现在的点号路径
#: Where the flat keys of the old ``config.json`` moved to.
LEGACY_PATHS: Dict[str, str] = {
    "achievement_sound": "stats.achievement_sound",
    "library_path": "library.novels_dir",
    "novels_dir": "library.novels_dir",
    "page_height": "reader.page_height",
    "source_language": "translator.source_language",
    "store_history": "reader.store_history",
    "target_language": "translator.target_language",
    "theme": "reader.theme",
    "translator": "translator.backend",
}

# 自动生成的 settings.toml 开头的说明文字
_FILE_HEADER = (
    "# wreader settings — 用手改，或者用 `wreader config <section.key> <value>` 改。\n"
    "# 删掉任意一行都会回落到默认值。"
)

# 解析布尔值时认作"真"的写法（大小写不敏感，比较前已 lower）
_TRUE = frozenset({"1", "true", "yes", "on", "y", "t"})
# 解析布尔值时认作"假"的写法
_FALSE = frozenset({"0", "false", "no", "off", "n", "f"})


# 配置出错（未知的设置名、值类型不对、文件损坏）统一抛这个异常
class ConfigError(Exception):
    """Raised for an unknown setting, an unusable value or a damaged file."""


def _env(*names: str) -> Optional[str]:
    """Return the first environment variable among *names* that is set."""
    # 按传入顺序逐个查，谁先有非空值就用谁（新名字在前，旧名字兜底）
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    # 都没设置就返回 None
    return None


def _app_dir(name: str, posix_name: str) -> Path:
    """Return the per-user directory of *name* on this platform."""
    # Windows 走 %APPDATA%，其它平台走家目录下的隐藏目录
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        # 拿不到 APPDATA 就退回到 ~/AppData/Roaming
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / name
    return Path.home() / posix_name


def legacy_data_dir() -> Path:
    """Return the pre-rename data directory (``~/.nr``, ``%APPDATA%\\nr``)."""
    # 改名前的目录名：~/.nr 或 %APPDATA%\nr
    return _app_dir(LEGACY_APP_NAME, LEGACY_DATA_DIRNAME)


def migrate_legacy_data_dir(
    # 目标（新）数据目录；不传则按平台算 ~/.wreader
    target: Optional[Path] = None,
    # 旧数据目录；不传则按平台算 ~/.nr
    legacy: Optional[Path] = None,
) -> Optional[Path]:
    """Adopt a pre-rename ``~/.nr`` directory, once.

    The tool was called ``nr`` until the rename, so an upgraded install would
    leave its settings, library index and notebook behind in ``~/.nr`` while
    looking for them in ``~/.wreader``.  When the new directory does not exist
    yet and the old one does, the old one is moved into place and its new path is
    returned.

    *target* and *legacy* default to those two directories; they exist so the
    tests can drive the move without touching the real home directory.  Nothing
    happens when the new directory already exists or the old one does not, and a
    failure is swallowed: wreader has to start either way.
    """
    # 参数省略时按平台默认值补齐（测试可显式传临时目录）
    target = Path(target) if target is not None else _app_dir(APP_NAME, DATA_DIRNAME)
    legacy = (
        Path(legacy) if legacy is not None else _app_dir(LEGACY_APP_NAME, LEGACY_DATA_DIRNAME)
    )
    # 新目录已存在（说明已迁移过或用过新版），或旧目录不存在，都无需迁移
    if target.exists() or not legacy.exists():
        return None
    try:
        # 确保新目录的父目录存在，否则 move 会失败
        target.parent.mkdir(parents=True, exist_ok=True)
        # 整个目录搬过去（同盘是改名，跨盘是复制+删除）
        shutil.move(str(legacy), str(target))
    except OSError:  # pragma: no cover - read only or otherwise unwritable home
        # 家目录只读等情况：迁移失败就算了，后面的报错里提示"权限不足"也行
        return None
    # 返回迁移后的新路径
    return target


# 旧数据目录每个进程最多只尝试迁移一次，避免反复搬
#: The pre-rename data directory is adopted at most once per process.
_MIGRATED = False


def data_dir() -> Path:
    """Return the directory holding ``settings.toml`` and ``library.json``.

    ``~/.wreader`` by default and ``%APPDATA%\\wreader`` on Windows; ``$WREADER_HOME``
    overrides both, which is what the tests use to stay out of the real home
    directory.  The pre-rename ``$NR_HOME`` and ``~/.nr`` still work: the variable
    is read as a fallback and the directory is adopted on first use.
    """
    # 环境变量优先：WREADER_HOME，其次旧名 NR_HOME
    override = _env(ENV_HOME, ENV_HOME_LEGACY)
    if override:
        # expanduser 把 ~ 展开成真实家目录
        return Path(override).expanduser()
    # 声明要修改模块级全局标志位
    global _MIGRATED
    if not _MIGRATED:
        # 先置位再执行：即使迁移报错，也不要每次调用都重试
        _MIGRATED = True  # set first: a failure must not be retried forever
        migrate_legacy_data_dir()
    # 没有环境变量就用平台默认目录
    return _app_dir(APP_NAME, DATA_DIRNAME)


def settings_path() -> Path:
    """Return the path of the settings file (``~/.wreader/settings.toml``)."""
    # 数据目录 + 文件名
    return data_dir() / SETTINGS_FILENAME


def config_path() -> Path:
    """Alias of :func:`settings_path`, the file ``wreader config`` reads and writes."""
    # 兼容性别名，语义与 settings_path 完全一样
    return settings_path()


def legacy_config_path() -> Path:
    """Return the path of the flat ``config.json`` older versions wrote."""
    # 老版本用的扁平配置文件（需要时会被迁移成 settings.toml + .bak）
    return data_dir() / LEGACY_CONFIG_FILENAME


def library_file() -> Path:
    """Return the path of the library index (``~/.wreader/library.json``)."""
    # 书库索引文件（记录了所有书、进度、统计）
    return data_dir() / LIBRARY_FILENAME


def default_novels_dir() -> Path:
    """Return the directory used when ``library.novels_dir`` is unset."""
    # 没配 library.novels_dir 时，章节正文放 ~/novels
    return Path.home() / "novels"


def default_cache_dir() -> Path:
    """Return the directory used when ``translator.cache_dir`` is the default."""
    # 缓存目录默认跟随数据目录，所以 $WREADER_HOME 一改，缓存也跟着走
    return data_dir() / CACHE_DIRNAME


def all_paths() -> List[str]:
    """Return every known setting as a dotted path, in file order."""
    # 按 SCHEMA 的声明顺序，把 section 和 key 拼成 "section.key"
    return [
        "{}.{}".format(section, key) for section, keys in SCHEMA.items() for key, _, _ in keys
    ]


def default_for(path: str) -> Any:
    """Return the default of *path*, or ``None`` when the path is unknown."""
    # 查不到就当没有默认值（返回 None），这里不抛异常
    return DEFAULT_FLAT.get(str(path))


def section_defaults(section: str) -> Dict[str, Any]:
    """Return the defaults of one section, keyed by the short key."""
    # 拷贝一份再返回，避免调用方改到共享的 DEFAULTS
    return dict(DEFAULTS.get(str(section)) or {})


def _to_bool(value: Any, path: str) -> bool:
    # 本来就是 bool 直接返回（TOML 里的 true/false 会走到这）
    if isinstance(value, bool):
        return value
    # 转成小写字符串再比对，这样 "TRUE"/"Yes"/"on" 都能认
    text = str(value).strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    # 认不出来的写法一律报错，避免"以为是 False 其实是打错了"
    raise ConfigError("'{}' expects a boolean, got {!r}".format(path, value))


def _to_int(value: Any, path: str) -> int:
    # bool 是 int 的子类，所以要先排掉，避免 True 被当成 1
    if isinstance(value, bool):
        raise ConfigError("'{}' expects an integer, got {!r}".format(path, value))
    try:
        # 字符串也允许（命令行传进来的都是字符串），去空白后转 int
        return int(str(value).strip())
    except (TypeError, ValueError):
        # from None 是为了不把内部的 ValueError 显示给用户看
        raise ConfigError("'{}' expects an integer, got {!r}".format(path, value)) from None


def _to_number(value: Any, path: str) -> float:
    # 同样先把 bool 排除掉
    if isinstance(value, bool):
        raise ConfigError("'{}' expects a number, got {!r}".format(path, value))
    try:
        # page_scroll_step 这类浮点设置走这里
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ConfigError("'{}' expects a number, got {!r}".format(path, value)) from None


def _unknown_path(path: str) -> ConfigError:
    """Build the error for an unrecognised path, suggesting the closest match."""
    # 所有合法的点号路径，用来做模糊匹配
    known = all_paths()
    # n=1：只要最像的那个；cutoff=0.6：相似度低于 0.6 就不给建议
    suggestion = difflib.get_close_matches(str(path), known, n=1, cutoff=0.6)
    # 模糊匹配没结果时，再看看是不是老版本的扁平键名
    if not suggestion:
        legacy = LEGACY_PATHS.get(str(path))
        if legacy:
            suggestion = [legacy]
    # 有建议就附上一句 "did you mean ...?"
    hint = " (did you mean '{}'?)".format(suggestion[0]) if suggestion else ""
    # 抛出带建议的 ConfigError
    return ConfigError("unknown setting '{}'{}".format(path, hint))


def resolve_path(path: str) -> str:
    """Return the canonical dotted path, accepting the old flat key names."""
    # 去掉首尾空白，顺便把 None 兜成空串
    text = str(path or "").strip()
    # 本来就是标准点号路径，直接用
    if text in DEFAULT_FLAT:
        return text
    # 否则看看是不是老版本的扁平键名，映射过去
    legacy = LEGACY_PATHS.get(text)
    if legacy:
        return legacy
    # 都不认识：抛错，并附上最接近的候选建议
    raise _unknown_path(text)


def coerce_value(path: str, value: Any) -> Any:
    """Validate *value* for *path* and return it converted to the right type."""
    # 先把键名规范化
    canonical = resolve_path(path)
    # 用默认值的类型来决定该把 value 转成什么
    default = DEFAULT_FLAT[canonical]
    # 默认值是 None 表示"这个键本身没有静态默认值"（如 novels_dir）
    if default is None:
        # 空值统一存成 None（不写进文件时就是留空）
        if value is None or str(value).strip() == "":
            return None
        return str(value)
    # 按默认值的类型分派到相应的转换函数
    if isinstance(default, bool):
        return _to_bool(value, canonical)
    if isinstance(default, float):
        return _to_number(value, canonical)
    if isinstance(default, int):
        return _to_int(value, canonical)
    # 剩下的（字符串）直接转字符串
    return str(value)


def resolve_cache_dir(raw: Any) -> Path:
    """Resolve ``translator.cache_dir``, keeping the default beside the data dir.

    Both the current default and the pre-rename ``~/.nr/cache`` mean "follow the
    data directory", so a settings file written before the rename keeps working
    after the move instead of pointing at an abandoned directory.
    """
    # 取出配置里的字面值
    text = str(raw or "").strip()
    # 没配置，或者等于"默认值"的两种写法，都理解成"跟随数据目录"
    if not text or text in (DEFAULT_CACHE_DIR, LEGACY_DEFAULT_CACHE_DIR):
        return default_cache_dir()
    # 用户写了明确路径：展开 ~ 后使用
    return Path(text).expanduser()


def cache_dir(settings: Optional["Config"] = None) -> Path:
    """Return the resolved directory holding the translated chapters."""
    # 没传配置就现加载一份
    settings = settings or load_config()
    # 读配置里的原始值，再解析成真实路径
    return resolve_cache_dir(settings.get("translator.cache_dir"))


def _flatten(document: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Turn a nested TOML document into ``{"section.key": value}``."""
    # 收集扁平化结果
    flat: Dict[str, Any] = {}
    for key, value in (document or {}).items():
        # 有前缀就拼成 "section.key"，顶层键直接用原名
        name = "{}.{}".format(prefix, key) if prefix else str(key)
        # 值是字典说明还有下一层，递归下去
        if isinstance(value, dict):
            flat.update(_flatten(value, name))
        else:
            # 叶子节点：记下 "路径 -> 值"
            flat[name] = value
    return flat


def _render_value(value: Any) -> str:
    """Render one value as TOML."""
    # 布尔写成 TOML 的 true/false
    if isinstance(value, bool):
        return "true" if value else "false"
    # 整数形态的浮点写成 1 而不是 1.0（page_scroll_step 是唯一的浮点设置）
    if isinstance(value, float):
        # 1.0 reads better as 1 -- page_scroll_step is the only float, and "1 页"
        # is what the specification documents.
        return str(int(value)) if value.is_integer() else repr(value)
    # 整数直接输出
    if isinstance(value, int):
        return str(value)
    # None 写成空字符串（比如 library.novels_dir 留空）
    if value is None:
        return '""'
    # 字符串要转义：反斜杠、双引号、换行、制表符都得处理，否则写出非法 TOML
    text = (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    # 加上双引号
    return '"{}"'.format(text)


def render_toml(values: Dict[str, Any], header: str = _FILE_HEADER) -> str:
    """Render *values* (keyed by dotted path) as the settings file."""
    # 先写文件头说明，再空一行
    lines: List[str] = [header, ""]
    # 按 SCHEMA 的顺序逐段输出，保证文件结构稳定、diff 友好
    for section, keys in SCHEMA.items():
        # 段落标题，如 [reader]
        lines.append("[{}]".format(section))
        for key, _default, comment in keys:
            # 组出点号路径，去 values 里取值
            path = "{}.{}".format(section, key)
            # 一行形如：key = value
            line = "{} = {}".format(key, _render_value(values.get(path)))
            # 有注释就右填充到固定列，再拼上 "# 注释"
            if comment:
                line = line.ljust(_COMMENT_COLUMN - 2) + "  # " + comment
            lines.append(line)
        # 每个段落后面空一行
        lines.append("")
    # 从尾部删掉多余的空白行，避免文件末尾留一串空行
    while lines and not lines[-1].strip():
        lines.pop()
    # 用换行拼成文件内容，末尾恰好一个换行
    return "\n".join(lines) + "\n"


def _read_toml(path: Path) -> Dict[str, Any]:
    """Read a TOML file, raising :class:`ConfigError` when it is unusable."""
    # 解释器里没有 tomllib（< 3.11）就直说需要新版本 Python
    if tomllib is None:  # pragma: no cover - requires-python is >= 3.11
        raise ConfigError("reading {} needs Python 3.11 or newer".format(path))
    try:
        # TOML 必须以二进制模式打开，tomllib 自己负责解码
        with Path(path).open("rb") as handle:
            document = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        # 语法错误：包成 ConfigError 并保留原因
        raise ConfigError("{} is not valid TOML: {}".format(path, exc)) from exc
    except OSError as exc:
        # 读不了文件（权限/不存在等）
        raise ConfigError("cannot read {}: {}".format(path, exc)) from exc
    # 顶层必须是一张表（正常情况下 tomllib 保证如此）
    if not isinstance(document, dict):  # pragma: no cover - tomllib always returns one
        raise ConfigError("{} must contain a TOML table".format(path))
    return document


def _migrate_legacy(document: Any) -> Dict[str, Any]:
    """Map the flat keys of an old ``config.json`` onto the new sections."""
    # 迁移后的嵌套结构
    migrated: Dict[str, Any] = {}
    # 老文件内容不是字典就没什么可迁移的
    if not isinstance(document, dict):
        return migrated
    for key, value in document.items():
        # 查这张扁平键名映射表；不在表里的键（老版本自有的）直接丢掉
        path = LEGACY_PATHS.get(str(key))
        if path is None:
            continue
        # 把 "translator.backend" 拆成 section="translator"、name="backend"
        section, _, name = path.partition(".")
        # setdefault 保证 section 这一层字典存在，再塞进对应的键
        migrated.setdefault(section, {})[name] = value
    return migrated


# 设置对象：把默认值和文件里的值合到一起，并支持用点号路径读写
class Config:
    """The settings document, with defaults filled in and dotted-path access.

    ``values`` holds the coerced values (defaults included) and ``stored`` the
    raw ones that came out of the file, so a caller that wants to validate a
    value itself -- the translator checking ``backend`` -- can ask for the
    untouched value with :meth:`stored` or :meth:`raw_section`.
    """

    def __init__(
        # 设置文件的路径
        self,
        path: Path,
        # 已解析出的 TOML 文档（不传就当空文档，全用默认值）
        document: Optional[Dict[str, Any]] = None,
        # 如果是从老的 config.json 迁移来的，记下原文件路径
        migrated_from: Optional[Path] = None,
    ) -> None:
        # 保存文件路径（顺便保证是 Path 类型）
        self.path = Path(path)
        # 迁移来源；没有就是 None
        self.migrated_from = Path(migrated_from) if migrated_from else None
        # 文件里出现但 schema 不认识的键，留着给 `wreader config` 提示用
        self.unknown: Dict[str, Any] = {}
        # 类型不对被丢弃的键 -> 原因
        self.invalid: Dict[str, str] = {}
        # 强制转换后的生效值
        self._values: Dict[str, Any] = {}
        # 文件里读出来的原始值（未强制转换）
        self._stored: Dict[str, Any] = {}
        # 用文档内容填充上面两个字典
        self._read(document or {})

    def _read(self, document: Dict[str, Any]) -> None:
        """Fill the values from *document*, keeping unknown keys aside."""
        # 先把嵌套的 TOML 拍平成 "section.key" -> 原始值
        for path, raw in _flatten(document).items():
            # 是已知设置就留着待转换
            if path in DEFAULT_FLAT:
                self._stored[path] = raw
            else:
                # 不认识的键只记录下来（不报错，避免手改文件写错一个字就打不开）
                self.unknown[path] = raw
        # 再按 schema 的顺序，把每个键的生效值算出来
        for path in all_paths():
            # 文件里没写：直接用默认值
            if path not in self._stored:
                self._values[path] = DEFAULT_FLAT[path]
                continue
            try:
                # 文件里写了：按默认值的类型做转换和校验
                self._values[path] = coerce_value(path, self._stored[path])
            except ConfigError as exc:
                # A hand edited file that got a type wrong falls back to the
                # default and is reported by `wreader config` instead of refusing
                # to start.
                # 类型写错：回落到默认值，并把原因记在 invalid 里
                self.invalid[path] = str(exc)
                self._values[path] = DEFAULT_FLAT[path]

    def get(self, path: str, default: Any = None) -> Any:
        """Return the value of *path* (``"translator.backend"``).

        An unknown path raises :class:`ConfigError` so a typo is never silently
        answered with a default.
        """
        # resolve_path 会顺带校验键名，拼错时抛 ConfigError
        return self._values.get(resolve_path(path), default)

    def stored(self, path: str, default: Any = None) -> Any:
        """Return the raw value of *path* as it was read from the file."""
        # 与 get 的区别：这里拿的是没做类型转换的原始值
        return self._stored.get(resolve_path(path), default)

    def set(self, path: str, value: Any) -> Any:
        """Set *path* to *value* (coerced) and return the stored value."""
        # 规范化键名
        canonical = resolve_path(path)
        # 校验并转换类型；不合法会抛 ConfigError
        coerced = coerce_value(canonical, value)
        # 同时更新生效值和原始值
        self._values[canonical] = coerced
        self._stored[canonical] = coerced
        # 既然写入了合法值，就把这个键之前的"类型错误"记录清掉
        self.invalid.pop(canonical, None)
        return coerced

    def section(self, name: str) -> Dict[str, Any]:
        """Return one section's coerced values, keyed by the short key."""
        # 前缀形如 "reader."
        prefix = "{}.".format(name)
        # 挑出以该前缀开头的键，并把前缀切掉，只留短键名
        return {
            path[len(prefix):]: value
            for path, value in self._values.items()
            if path.startswith(prefix)
        }

    def raw_section(self, name: str) -> Dict[str, Any]:
        """Return one section exactly as it was read, keyed by the short key."""
        # 效果同 prefix = name + "."，只是写法不同
        prefix = "{}.{}".format(name, "")
        # 和 section() 一样，但用的是未转换的原始值
        return {
            path[len(prefix):]: value
            for path, value in self._stored.items()
            if path.startswith(prefix)
        }

    def flat(self) -> Dict[str, Any]:
        """Return a copy of every value, keyed by dotted path."""
        # 返回拷贝，调用方改动不会影响内部状态
        return dict(self._values)

    def reset(self) -> None:
        """Restore every value to its default."""
        # 生效值换回默认值
        self._values = dict(DEFAULT_FLAT)
        # 清空原始值（等于"文件里什么都没写"）
        self._stored = {}
        # 清掉未知键和错误记录
        self.unknown = {}
        self.invalid = {}

    def as_toml(self) -> str:
        """Return the file contents these values render to."""
        # 把当前生效值渲染成 settings.toml 的文本
        return render_toml(self._values)

    def save(self) -> Path:
        """Write the values to disk and return the path."""
        # 确保目录存在（第一次运行时 ~/.wreader 可能还没建）
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 直接整体覆写（settings.toml 很小，不值得做增量写）
        self.path.write_text(self.as_toml(), encoding="utf-8")
        return self.path

    def __contains__(self, path: object) -> bool:
        # 支持 `"reader.page_height" in settings` 这种写法
        try:
            return resolve_path(str(path)) in self._values
        except ConfigError:
            # 连键名都不合法，当然"不包含"
            return False

    def __getitem__(self, path: str) -> Any:
        # 支持 settings["reader.page_height"] 的取值写法
        return self.get(path)

    def __repr__(self) -> str:
        # 调试时打印出来能直接看到路径和全部生效值
        return "Config(path={!r}, values={!r})".format(str(self.path), self._values)


# 进程内缓存的配置对象；避免每次 config.get 都去读盘
_CACHE: Optional[Config] = None
# 缓存对应的文件路径，路径变了就作废
_CACHE_PATH: Optional[Path] = None
# 缓存时文件的修改时间戳，文件被改了就作废
_CACHE_STAMP: Optional[int] = None


def _stamp(path: Path) -> Optional[int]:
    """Return a cheap fingerprint of *path*, or ``None`` when it is missing."""
    try:
        # 用纳秒级 mtime 当"指纹"，够便宜也够准
        return path.stat().st_mtime_ns
    except OSError:
        # 文件不存在或读不到属性：返回 None，表示"指纹未知"
        return None


def load_config(
    # 指定要读的文件；不传就用标准的 settings.toml
    path: Optional[Path] = None,
    # 强制忽略缓存重新读盘
    force: bool = False,
) -> Config:
    """Return the settings, reading ``settings.toml`` at most once.

    A missing file is created from the defaults, so the values can be discovered
    and hand edited.  When the file is missing but the old ``config.json`` is
    there, its values are folded into the right sections (and the old file is
    renamed to ``config.json.bak``).  A read only location is fine: the values
    then simply stay in memory.

    The cache is dropped when the file changed on disk, so editing
    ``settings.toml`` in another window (or in a test) is picked up.
    """
    # 这三个模块级变量要被重新赋值
    global _CACHE, _CACHE_PATH, _CACHE_STAMP
    # 目标文件：调用方指定的，或者默认的 ~/.wreader/settings.toml
    target = Path(path) if path is not None else settings_path()
    # 当前文件的指纹
    stamp = _stamp(target)
    # 命中缓存的条件：已有缓存 + 没要求强制刷新 + 路径一样 + 文件没被改过
    if (
        _CACHE is not None
        and not force
        and _CACHE_PATH == target
        and _CACHE_STAMP == stamp
    ):
        return _CACHE

    # 以下是要真正读盘的路径
    exists = target.exists()
    # 从 TOML 里读到的文档
    document: Dict[str, Any] = {}
    # 如果值来自老的 config.json，记下它以便稍后改名备份
    migrated: Optional[Path] = None
    if exists:
        # 正常情况：直接读 settings.toml
        document = _read_toml(target)
    elif path is None:
        # 没有 settings.toml：看看有没有老版本的扁平 config.json
        legacy = legacy_config_path()
        if legacy.exists():
            try:
                # 读出来并映射到新的 section 结构
                document = _migrate_legacy(
                    json.loads(legacy.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                # 老文件坏了就当没有，不要因此让程序起不来
                document = {}
            else:
                # 成功迁移，记下老文件
                migrated = legacy

    # 用文档内容构造配置对象（缺的键自动补默认值）
    settings = Config(target, document, migrated_from=migrated)
    # 文件原本不存在时，把默认配置写出去，方便用户发现并手改
    if not exists:
        try:
            settings.save()
        except OSError:  # pragma: no cover - read only data directory
            # 数据目录只读也没关系，值就在内存里用
            pass
        # 老 config.json 迁移完毕后改名成 .bak，避免下次又被当来源
        if migrated is not None:
            try:
                migrated.rename(migrated.parent / (migrated.name + ".bak"))
            except OSError:  # pragma: no cover - read only data directory
                pass
    # 更新缓存（注意：指纹要在写文件之后再取一次）
    _CACHE, _CACHE_PATH, _CACHE_STAMP = settings, target, _stamp(target)
    return settings


def load(force: bool = False) -> Config:
    """Alias of :func:`load_config`, kept for the rest of wreader."""
    # 纯别名，让其它模块可以用 config.load() 这种更短的写法
    return load_config(force=force)


def reload() -> Config:
    """Drop the cached settings and read the file again."""
    # force=True：丢掉缓存，强制重新读盘
    return load_config(force=True)


def get(path: str, default: Any = None) -> Any:
    """Return one setting (``config.get("reader.page_height")``)."""
    # 便捷函数：一步到位读取某个设置
    return load_config().get(path, default)


def set(path: str, value: Any) -> Any:
    """Set one setting and write the file back (``wreader config`` uses this)."""
    # 取当前配置（有缓存就直接用）
    settings = load_config()
    # 写入内存中的值（会校验类型）
    coerced = settings.set(path, value)
    # 立刻落盘
    settings.save()
    # 返回转换后的值，方便回显
    return coerced


def reset() -> Config:
    """Restore every setting to its default and write the file back."""
    settings = load_config()
    # 清空所有自定义值
    settings.reset()
    # 覆盖写回文件
    settings.save()
    return settings


def novels_dir(settings: Optional[Config] = None) -> Path:
    """Resolve the directory holding the UTF-8 converted book texts."""
    # 环境变量优先级最高：WREADER_NOVELS_DIR，其次旧名 NR_NOVELS_DIR
    override = _env(ENV_NOVELS_DIR, ENV_NOVELS_DIR_LEGACY)
    if override:
        return Path(override).expanduser()
    # 其次看配置文件里的 library.novels_dir
    settings = settings or load_config()
    raw = settings.get("library.novels_dir")
    # 留空（None 或空串）就用默认的 ~/novels
    if raw is None or str(raw).strip() == "":
        return default_novels_dir()
    # 用户写了明确路径：展开 ~ 后使用
    return Path(str(raw)).expanduser()


def effective_values(settings: Optional[Config] = None) -> Dict[str, Any]:
    """Return every setting as the rest of wreader will use it, keyed by dotted path.

    The two paths that name a directory are resolved, so ``wreader config`` shows the
    real location rather than ``~/novels``.
    """
    settings = settings or load_config()
    # 先拿一份所有值的拷贝
    values = settings.flat()
    # 把"目录类"设置替换成解析后的真实绝对路径，展示更直观
    values["library.novels_dir"] = str(novels_dir(settings))
    values["translator.cache_dir"] = str(resolve_cache_dir(values["translator.cache_dir"]))
    return values






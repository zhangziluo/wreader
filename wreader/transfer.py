"""Portable export and import of reading time and achievements.

The use case is "move to a new laptop": ``werd data export <file>`` writes one
plain JSON file holding the reading history (total and per day durations, per book
sessions and progress) together with the achievement state, and ``werd data
import <file>`` folds it into another install.

Everything is keyed by ``book_id`` -- the SHA-1 of the converted text, see
:mod:`wreader.library` -- so the same book lines up on both machines with no extra
bookkeeping: import the books first, then the bundle.

Importing never deletes anything: durations add up, unlocks are united and
counters only grow, so a bundle cannot overwrite what the target machine already
recorded.  Only plain UTF-8 JSON is written, in keeping with the rule that every
file the user owns stays hand editable.
"""

# 延迟求值类型注解
from __future__ import annotations

# 包本身就是 JSON：读写都用标准库
import json
# os.replace 做原子写入
import os
# 先写临时文件再改名，靠它建临时文件
import tempfile
# 包里记一个导出时间戳，方便人看新旧
from datetime import datetime
# 路径处理
from pathlib import Path
# 类型注解
from typing import Any, Dict, Union

# 同包引用：书库（时长/进度）与成就（解锁/指标）
from . import achievements, library

# 对外暴露的接口
__all__ = [
    "BUNDLE_KIND",
    "BUNDLE_VERSION",
    "TransferError",
    "export_data",
    "import_data",
]

# 包的自我标识：导入时靠它判断"这是不是一个 werd 数据包"
BUNDLE_KIND = "werd-data"
# 包格式版本：结构变了才 +1；读到不认识的版本会明确拒绝，而不是猜着合并
BUNDLE_VERSION = 1

# 可以接受的文件路径写法
PathLike = Union[str, Path]


# 数据包写不出/读不懂时统一抛这个异常（CLI 把它渲染成一行 error）
class TransferError(Exception):
    """Raised when a data bundle cannot be written, read or understood."""


def _resolve(path: PathLike) -> Path:
    """Return *path* as an expanded :class:`~pathlib.Path`."""
    # ~ 展开，相对路径留给调用方的工作目录来解析
    return Path(path).expanduser()


def _write_bundle(target: Path, bundle: Dict[str, Any]) -> None:
    """Write *bundle* to *target* atomically.

    Same rule as the other data files: a temporary file in the same directory is
    renamed over the target, so a reader never sees half a bundle.
    """
    # 父目录可能还不存在（用户给了个新目录）
    target.parent.mkdir(parents=True, exist_ok=True)
    # 临时文件必须和目标同目录，os.replace 才是原子的
    handle, temp_name = tempfile.mkstemp(prefix="_werd_data.", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            # ensure_ascii=False 让中文标题/成就名在包里保持可读
            json.dump(bundle, stream, ensure_ascii=False, indent=2)
            # 结尾补换行，和 library.json / achievements.json 一个风格
            stream.write("\n")
        # 原子替换成正式文件
        os.replace(temp_name, str(target))
    except OSError:
        # 写失败：清掉临时文件，别在用户目录里留垃圾
        try:
            os.unlink(temp_name)
        except OSError:  # pragma: no cover - 临时文件已经不在了
            pass
        raise


def _read_bundle(path: Path) -> Dict[str, Any]:
    """Read and validate the data bundle at *path*."""
    # 文件必须真的存在：目录或者不存在的路径都明确报错
    if not path.is_file():
        raise TransferError("no such data file: {}".format(path))
    try:
        # 包是 UTF-8 的纯 JSON，手改过也读得回来
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferError("{} cannot be read: {}".format(path, exc)) from exc
    # 格式自检：认不出的 JSON 直接拒绝，别把别的文件当数据包悄悄合并
    if not isinstance(raw, dict) or raw.get("kind") != BUNDLE_KIND:
        raise TransferError("{} is not a werd data file".format(path))
    try:
        version = int(raw.get("version") or 0)
    except (TypeError, ValueError):
        raise TransferError("{} has no usable version".format(path)) from None
    # 版本不认识：字段含义可能已经变了，宁可拒绝也不猜
    if version != BUNDLE_VERSION:
        raise TransferError(
            "{} was written by another version (bundle {}, expected {})".format(
                path, version, BUNDLE_VERSION
            )
        )
    return raw


def _load_state() -> Dict[str, Any]:
    """Return the achievements state, or raise :class:`TransferError`."""
    try:
        # 状态文件坏了（手改出语法错误）时给出统一的错误提示
        return achievements.load_state()
    except achievements.AchievementsError as exc:
        raise TransferError(str(exc)) from exc


def export_data(path: PathLike) -> Dict[str, Any]:
    """Write this machine's reading time and achievements to *path*.

    Returns a small summary (where it was written, and what went in) so the CLI
    can report it without reading the bundle back.
    """
    target = _resolve(path)
    # 目标是目录：明说，免得用户以为导出成功了
    if target.is_dir():
        raise TransferError("{} is a directory, give a file name".format(target))
    # 书库侧：全局时长 + 每本书的阅读记录（读不出来会抛 LibraryError）
    document = library.load_library()
    reading = library.reading_data(document)
    # 成就侧：解锁记录 + 计数器 + 指标
    state = _load_state()
    # 包的结构固定：身份 -> 摘要 -> 两段数据；摘要方便 `head` 一眼看清规模
    bundle: Dict[str, Any] = {
        "kind": BUNDLE_KIND,
        "version": BUNDLE_VERSION,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "summary": {
            "books": len(reading["books"]),
            "unlocked": len(state.get("unlocked") or []),
            "total_read_time": reading["total_read_time"],
        },
        "reading": reading,
        "achievements": state,
    }
    # 原子落盘
    _write_bundle(target, bundle)
    return {
        "path": str(target),
        "books": int(bundle["summary"]["books"]),
        "unlocked": int(bundle["summary"]["unlocked"]),
        "seconds": int(reading["total_read_time"]),
    }


def import_data(path: PathLike) -> Dict[str, Any]:
    """Merge the data bundle at *path* into this machine's data.

    Durations add up and unlocks are united, nothing is overwritten, so importing
    the same bundle twice is safe -- the second time it only fills in whatever is
    still missing.  Books this machine does not know about are skipped (without the
    book there is nowhere to attach the sessions) and counted in the summary.
    """
    source = _resolve(path)
    bundle = _read_bundle(source)
    # 先算后写：两份合并都在内存里做完再落盘，中途出错不会留下半份数据
    document = library.load_library()
    incoming = bundle.get("reading")
    merged = library.merge_reading_data(
        document, incoming if isinstance(incoming, dict) else {}
    )
    # 成就侧同样先合并再写（状态文件坏了会在这里明确报错）
    state = _load_state()
    incoming_state = bundle.get("achievements")
    merged_state = achievements.merge_states(
        state, incoming_state if isinstance(incoming_state, dict) else {}
    )
    # 落盘：书库先、成就后；进度快照会在下一次成就判定时刷新
    library.save_library(document)
    achievements.save_state(merged_state)
    return {
        "path": str(source),
        "books": int(merged["books"]),
        "skipped": int(merged["skipped"]),
        "seconds": int(merged["seconds"]),
        "unlocked": len(merged_state.get("unlocked") or []),
    }

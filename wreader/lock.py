"""A tiny cross-process file lock, shared by the plain-text stores.

State files that need a read-modify-write cycle use this to serialise it
(:mod:`wreader.achievements` today): two terminals writing at the same moment
would otherwise lose one of the updates.

The lock is a sibling ``<file>.lock`` taken with POSIX ``flock``.  Windows has no
``fcntl``, so there the lock degrades to a no-op and correctness rests on the
atomic write (``mkstemp`` + ``os.replace``) instead -- an explicit trade, written
down rather than forgotten.
"""

# 延迟求值类型注解
from __future__ import annotations

# contextmanager：把锁写成一个 with 块
from contextlib import contextmanager
# 锁文件与被保护的文件同目录
from pathlib import Path
# 类型注解：handle 是打开的文件对象
from typing import Any, Iterator

# 模块对外暴露的名字
__all__ = ["file_lock", "lock_file", "unlock_file"]


def lock_file(handle: Any) -> bool:
    """Take an exclusive lock on *handle*; ``False`` when locking is unavailable."""
    try:
        # 局部导入：Windows 上没有 fcntl，不能放在模块顶部（否则静态检查找不到）
        import fcntl
    except ImportError:  # pragma: no cover - 只有 Windows 会走到
        return False
    try:
        # 独占锁：第二个进程会在这里等到第一个写完
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError:  # pragma: no cover - 文件系统不支持锁
        return False
    return True


def unlock_file(handle: Any) -> None:
    """Release a lock taken by :func:`lock_file`, ignoring failures."""
    try:
        # 与加锁对称：解锁失败也不该抛给调用方
        import fcntl
    except ImportError:  # pragma: no cover - 只有 Windows 会走到
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:  # pragma: no cover - 关文件时也会顺带解锁
        pass


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Serialise the read-modify-write of *path* across processes.

    The caller passes the file it is about to touch; the lock lives in
    ``<path>.lock`` right next to it.  A directory that cannot be written to
    degrades to "no lock" rather than raising: an unwritable directory will fail
    loudly on the real write anyway.
    """
    # 锁文件放在被保护文件旁边（<name>.lock），与它一一对应
    handle = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(str(path) + ".lock", "a+", encoding="utf-8")
    except OSError:
        # 目录不可写：退化成"不加锁"，但原子替换仍能保证文件不会被写坏
        handle = None
    # 拿不到文件句柄就没法加锁
    if handle is not None:
        lock_file(handle)
    try:
        yield
    finally:
        if handle is not None:
            unlock_file(handle)
            handle.close()

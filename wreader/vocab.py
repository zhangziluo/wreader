"""Vocabulary notebook.

Words collected while reading (the reader's ``v`` key) live in
``~/.wreader/vocab.json`` as a plain list, one object per word::

    [
      {
        "word": "acknowledged",
        "translation": "公认的",
        "context": "It is a truth universally acknowledged.",
        "book": "Pride and Prejudice",
        "chapter": "Chapter 1",
        "date_added": "2026-09-21T14:15:40"
      }
    ]

Looking the same word up twice refreshes the existing entry rather than adding a
duplicate.  A notebook written by an older version (the ``{"words": [...]}``
wrapper with ``book_title``/``created``) still loads, because
:func:`normalise_entry` understands the old field names.
"""

# 让类型注解"延迟求值"：注解会被当成字符串存着，不用等运行时解析，少踩引用顺序的坑
from __future__ import annotations

# 读、写 JSON 笔记本都靠它
import json
# os.replace 负责"原子改名"：先写临时文件再改名，中途崩溃也不会弄坏原来的笔记本
import os
# 复习模式要抽签打乱，用的是 random
import random
# 导出 Anki 时用正则把字段里的制表符、换行统一压成空格
import re
# datetime 用来给生词打"加入时间"戳，列表默认按它倒序排
from datetime import datetime
# pathlib 的 Path 表示文件路径，exists()/with_name() 比手拼字符串稳妥
from pathlib import Path
# 类型注解用到的名字：Any 是任意类型，其余是容器和"可能为 None"
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# 同包内引用 config，主要是为了拿到数据目录 ~/.wreader
from . import config

# 模块的公开接口清单：`from wreader.vocab import *` 只会带出下面这些名字
__all__ = [
    # 一条生词记录的字段顺序（元组）
    "FIELDS",
    # 笔记本读写失败时抛的专用异常
    "VocabError",
    # 添加或刷新一个生词
    "add_word",
    # 导出成 Anki 的制表符分隔文本
    "export_anki",
    # 按拼写精确查词
    "find_word",
    # 列出全部生词（默认最新在前）
    "list_words",
    # 从磁盘读出整本笔记本
    "load_vocab",
    # 把列表切成"第几页"，给 CLI 分页用
    "paginate",
    # 从笔记本删掉一个生词
    "remove_word",
    # 打乱顺序，供复习模式用
    "review_order",
    # 原子地把笔记本写回磁盘
    "save_vocab",
    # 按拼写/释义/例句模糊搜索
    "search_words",
    # 笔记本文件路径（~/.wreader/vocab.json）
    "vocab_file",
    # 所有生词的小写集合，阅读时高亮关键词用
    "word_set",
]

# 笔记本的文件名；完整路径 = config.data_dir() / VOCAB_FILENAME
VOCAB_FILENAME = "vocab.json"

# 一条生词记录有哪些字段；元组顺序就是写进 JSON 时的键顺序
#: The fields of one entry, in the order they are written out.
FIELDS: Tuple[str, ...] = (
    # 生词本身，比如 acknowledged
    "word",
    # 释义，比如 公认的
    "translation",
    # 生词出现时所在的原文句子，方便回忆语境
    "context",
    # 来源书名
    "book",
    # 来源章节名
    "chapter",
    # 加入时间，ISO 格式字符串（精确到秒），排序靠它
    "date_added",
)

# 旧版本用过的字段名 -> 现在的字段名，读旧笔记本时靠它平滑迁移
#: Field names used by earlier versions, mapped onto the current ones.
LEGACY_FIELDS = {
    # 旧版叫 book_title，现在统一叫 book
    "book_title": "book",
    # 旧版叫 created，现在统一叫 date_added
    "created": "date_added",
    # 旧版还有个 updated，也归并到 date_added 上
    "updated": "date_added",
}


# 笔记本读写出问题时抛这个异常，CLI 会把它转成友好的错误提示而不是裸 traceback
class VocabError(Exception):
    """Raised when the vocabulary notebook cannot be read or written."""


def vocab_file() -> Path:
    """Return the path of the vocabulary notebook."""
    # 数据目录统一由 config 管，拼上文件名就是笔记本的绝对路径
    return config.data_dir() / VOCAB_FILENAME


def _now() -> str:
    # 当前时间转成 ISO 字符串（形如 2026-09-21T14:15:40），精确到秒足够用
    return datetime.now().isoformat(timespec="seconds")


def normalise_entry(item: Any) -> Optional[Dict[str, Any]]:
    """Return a clean entry, or ``None`` when it carries no word.

    Legacy field names are folded in first, so an old notebook keeps its
    translation and context when it is re-saved in the new shape.
    """
    # 不是字典（比如 JSON 里混进了字符串或数字）就当作无效记录
    if not isinstance(item, dict):
        return None
    # 先复制一份，避免就地改动调用方传进来的原始数据
    source = dict(item)
    # 逐条搬运旧字段名：新字段没有、旧字段有时，把旧值填到新名字上
    for old, new in LEGACY_FIELDS.items():
        if new not in source and old in source:
            source[new] = source[old]
    # 取出 word，去掉首尾空白，同时把 None/数字等统统转成 str
    word = str(source.get("word") or "").strip()
    # 连单词都没有的记录没有意义，返回 None 让调用方跳过
    if not word:
        return None
    # 按 FIELDS 的顺序把每个字段转成字符串（缺失的补空串），保证结构整齐
    entry = {field: str(source.get(field) or "") for field in FIELDS}
    # 单词用刚才清洗过的版本，覆盖掉上面可能带空白的值
    entry["word"] = word
    # 返回规整好的一条记录
    return entry


def load_vocab() -> List[Dict[str, Any]]:
    """Load the notebook, accepting both the list and the legacy wrapper shape."""
    # 先算出笔记本文件的位置
    path = vocab_file()
    # 文件还不存在（第一次使用）就当空笔记本，不报错
    if not path.exists():
        return []
    try:
        # 以 UTF-8 打开文件；with 保证用完自动关闭
        with path.open("r", encoding="utf-8") as handle:
            # 把整个 JSON 文件解析成 Python 对象
            raw = json.load(handle)
    # JSON 语法错误：包成 VocabError，并保留原始异常链方便排查
    except json.JSONDecodeError as exc:
        raise VocabError("{} is not valid JSON: {}".format(path, exc)) from exc
    # 文件读不动（权限、磁盘问题等）：同样包成 VocabError
    except OSError as exc:
        raise VocabError("cannot read {}: {}".format(path, exc)) from exc

    # 兼容老版本 {"words": [...]} 的包装写法：把里面的列表取出来
    if isinstance(raw, dict):  # the legacy {"words": [...]} wrapper
        raw = raw.get("words") or []
    # 到这一步必须是列表，否则说明文件结构不对
    if not isinstance(raw, list):
        raise VocabError("{} must contain a list of words".format(path))

    # 收集清洗后的有效记录
    words: List[Dict[str, Any]] = []
    # 一条条过 normalise_entry，脏数据会被丢掉
    for item in raw:
        entry = normalise_entry(item)
        # 规整成功（非 None）才收进结果
        if entry:
            words.append(entry)
    # 返回整本笔记本
    return words


def save_vocab(words: Iterable[Dict[str, Any]]) -> Path:
    """Write the notebook atomically and return its path."""
    # 目标文件：~/.wreader/vocab.json
    path = vocab_file()
    # 确保父目录存在（第一次运行时 ~/.wreader 还没建），已存在也不报错
    path.parent.mkdir(parents=True, exist_ok=True)
    # 先写同目录下的临时文件，成功后再改名，这就是"原子写"的关键
    temporary = path.with_name(path.name + ".tmp")
    # 把每条记录按 FIELDS 顺序转成纯字符串，顺手过滤掉非字典的脏数据
    payload = [
        {field: str(entry.get(field) or "") for field in FIELDS}
        for entry in words
        if isinstance(entry, dict)
    ]
    # 以 UTF-8 打开临时文件准备写入
    with temporary.open("w", encoding="utf-8") as handle:
        # ensure_ascii=False 让中文原样落盘；indent=2 方便人肉查看、diff
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        # 末尾补一个换行，符合 POSIX 文本文件的习惯
        handle.write("\n")
    # 原子替换：把临时文件改名成正式文件，同一文件系统上是瞬间完成的
    os.replace(str(temporary), str(path))
    # 返回写好的文件路径，调用方有时会打印它
    return path


def _sort_key(entry: Dict[str, Any]) -> Tuple[str, str]:
    """Sort key giving newest first, then alphabetical."""
    # 主键是加入时间，副键是单词小写；元组比较天然实现"先按时间、再按字母"
    return str(entry.get("date_added") or ""), str(entry.get("word") or "").lower()


def list_words(newest_first: bool = True) -> List[Dict[str, Any]]:
    """Return every entry, newest first by default."""
    # 先把笔记本整个读进来
    words = load_vocab()
    # 按时间倒序（reverse=True）排序；传 False 则变成最旧在前
    words.sort(key=_sort_key, reverse=newest_first)
    # 返回排好序的列表
    return words


def find_word(word: str) -> Optional[Dict[str, Any]]:
    """Return the entry for *word* (case insensitive), or ``None``."""
    # 统一成"去空白 + 小写"，这样查 word/WORD/Word 都能命中同一条
    wanted = str(word or "").strip().lower()
    # 空查询直接返回 None，省得去遍历
    if not wanted:
        return None
    # 简单线性扫描，笔记本一般不大，够用了
    for entry in load_vocab():
        if str(entry["word"]).lower() == wanted:
            # 命中就返回这一条
            return entry
    # 找遍都没有，返回 None
    return None


def add_word(
    # 要收藏的单词（必填）
    word: str,
    # 释义（必填，可以是空串）
    translation: str,
    # 生词所在的原文句子，默认空
    context: str = "",
    # 来源书名，默认空
    book: str = "",
    # 来源章节名，默认空
    chapter: str = "",
) -> Dict[str, Any]:
    """Add *word*, or refresh the existing entry when it is already there."""
    # 去掉首尾空白后的单词；同时把 None 等情况兜成空串
    cleaned = str(word or "").strip()
    # 单词是必填项，空的直接报错
    if not cleaned:
        raise VocabError("a word is required")
    # 读出笔记本，准备就地改某一条（或用 append 加新的）
    words = load_vocab()
    # 先找有没有同名的（忽略大小写），有就"刷新"而不是插入重复项
    for entry in words:
        if str(entry["word"]).lower() == cleaned.lower():
            # 释义总是覆盖成最新查到的
            entry["translation"] = str(translation or "")
            # 时间戳刷新成"刚刚"，这样它会重新排到列表最前
            entry["date_added"] = _now()
            # 下面几项只有传了非空值才覆盖，避免用空串冲掉已有的上下文
            if context:
                entry["context"] = str(context)
            if book:
                entry["book"] = str(book)
            if chapter:
                entry["chapter"] = str(chapter)
            # 把改好的整本笔记本写回磁盘
            save_vocab(words)
            # 返回被刷新的那条记录
            return entry
    # 走到这里说明是新词：先规整成标准结构（顺便过滤空单词）
    entry = normalise_entry(
        {
            "word": cleaned,
            "translation": translation,
            "context": context,
            "book": book,
            "chapter": chapter,
            "date_added": _now(),
        }
    )
    # 理论上不会发生（cleaned 已确认非空），留着这层保护以防代码改动
    if entry is None:  # pragma: no cover - cleaned is non-empty, see above
        raise VocabError("a word is required")
    # 追加到列表末尾
    words.append(entry)
    # 整个列表写回磁盘
    save_vocab(words)
    # 返回新建的记录
    return entry


def remove_word(word: str) -> Optional[Dict[str, Any]]:
    """Drop *word* from the notebook, returning the removed entry."""
    # 同样先归一化成"去空白 + 小写"再比对
    wanted = str(word or "").strip().lower()
    # 空单词没什么可删的
    if not wanted:
        return None
    # 读出全部记录
    words = load_vocab()
    # 保留下来（没被删掉）的记录
    kept: List[Dict[str, Any]] = []
    # 被删掉的那条；只删第一个匹配的，避免同名多条被一起清空
    removed: Optional[Dict[str, Any]] = None
    # 一次遍历把列表分成"留下"和"删掉"两份
    for entry in words:
        # 只有当还没删过、且单词匹配时，才判定为要删的那条
        if removed is None and str(entry["word"]).lower() == wanted:
            removed = entry
        else:
            # 其余统统留下
            kept.append(entry)
    # 没找到匹配的词，说明笔记本里本来就没有
    if removed is None:
        return None
    # 把去掉一条之后的结果写回磁盘
    save_vocab(kept)
    # 返回被删掉的记录，方便调用方展示
    return removed


def search_words(keyword: str) -> List[Dict[str, Any]]:
    """Return the entries whose word, translation or context contains *keyword*.

    Searching all three fields makes the notebook usable from the other
    direction too: ``wreader vocab --search 公认`` finds the word by its meaning.
    """
    # 关键词同样先做"去空白 + 小写"，实现大小写不敏感的模糊匹配
    needle = str(keyword or "").strip().lower()
    # 空关键词直接返回空结果
    if not needle:
        return []
    # 命中的记录都放这里
    hits = []
    # 遍历整本笔记本
    for entry in load_vocab():
        # 把单词、释义、例句拼成一大段文本当"干草堆"，这样一次就搜三个字段
        haystack = " ".join(
            (
                str(entry.get("word") or ""),
                str(entry.get("translation") or ""),
                str(entry.get("context") or ""),
            )
        ).lower()
        # 关键词出现在其中任意位置就算命中（子串匹配，不是整词匹配）
        if needle in haystack:
            hits.append(entry)
    # 结果按"最新在前"排序，和列表页保持一致
    hits.sort(key=_sort_key, reverse=True)
    # 返回命中列表
    return hits


def word_set() -> Set[str]:
    """Return every collected word lowercased, for highlighting while reading."""
    # 集合推导式：顺手把小写化后的单词去重，供阅读界面 O(1) 查表高亮
    return {str(entry["word"]).lower() for entry in load_vocab() if entry.get("word")}


def export_anki(words: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    """Return the notebook as tab separated ``word / translation / context`` lines.

    Tabs and newlines inside a field are collapsed to spaces, because either one
    would break the row when the text is pasted into Anki.
    """
    # 传了就用传进来的，没传就把磁盘上的笔记本整个列出来
    entries = list(words) if words is not None else list_words()
    # 每一行代表一张卡片
    lines = []
    for entry in entries:
        # 只导出三个字段，并把字段内部的连续空白（含换行、制表符）压成单个空格
        fields = [
            re.sub(r"\s+", " ", str(entry.get(field) or "")).strip()
            for field in ("word", "translation", "context")
        ]
        # 用制表符把三个字段连成一行，正是 Anki 导入时的分隔格式
        lines.append("\t".join(fields))
    # 用换行拼成完整文本；有内容时末尾补一个换行
    return "\n".join(lines) + ("\n" if lines else "")


def review_order(
    # 要打乱顺序的记录；不传就读整个笔记本
    words: Optional[Sequence[Dict[str, Any]]] = None,
    # 随机种子；传了就固定洗牌结果，测试靠它复现
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return the entries shuffled, for a randomised review session.

    Passing *seed* makes the shuffle reproducible, which the tests rely on.
    """
    # 拷贝一份再洗，避免把调用方的列表原地打乱
    entries = list(words) if words is not None else list_words()
    # 有 seed 就用独立 Random 实例（可复现）；没有就直接全局随机洗牌
    random.Random(seed).shuffle(entries) if seed is not None else random.shuffle(entries)
    # 返回洗好的顺序
    return entries


def paginate(
    # 待分页的全部条目
    items: Sequence[Dict[str, Any]],
    # 想看第几页，从 1 开始
    page: int = 1,
    # 每页多少条
    per_page: int = 20,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Return ``(page_items, page_count, page)``, clamping *page* into range."""
    # 每页条数至少为 1，防止传 0 或负数导致除零/死循环
    size = max(1, int(per_page))
    # 拷贝成列表，下面要用 len() 和切片
    entries = list(items)
    # 总页数 = 向上取整(总数 / 每页数)，最少也报 1 页
    pages = max(1, (len(entries) + size - 1) // size)
    # 把请求的页码夹到 [1, pages]，越界就退化成第一页/最后一页
    current = max(1, min(int(page), pages))
    # 该页第一条在整体列表中的下标
    start = (current - 1) * size
    # 返回「这一页的条目、总页数、实际页码」
    return entries[start : start + size], pages, current

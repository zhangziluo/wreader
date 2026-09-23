"""Tests for :mod:`wreader.translator` — back-ends, batching and the chapter cache.

No test touches the network: :func:`wreader.translator.set_backend` installs the
recording back-end from ``conftest`` instead.
"""

# 延迟求值类型注解
from __future__ import annotations

# 写测试用的独立配置文件
import json
# 临时路径
from pathlib import Path
# 收进度回调的类型注解
from typing import List, Tuple

# pytest.raises / parametrize
import pytest

# 被测模块 + 配置、书库与可插拔引擎
from wreader import config, library, translate, translator
# 引擎内部细节（限速用到的 time、SSE 解析、系统提示词）
from wreader.translate import deepseek as deepseek_engine
from wreader.translate import google as google_engine

# 复用样例正文与假后端
from conftest import BOOK_LINES, RecordingBackend


# ------------------------------------------------------------------- languages
# 参数化：各种语言写法都要归一成后端认识的语言码
@pytest.mark.parametrize(
    "name, expected",
    [
        ("zh", "zh-CN"),
        ("CN", "zh-CN"),
        ("zh_cn", "zh-CN"),
        ("chinese", "zh-CN"),
        ("en", "en"),
        ("English", "en"),
        ("fr", "fr"),
        (None, "zh-CN"),
        ("", "zh-CN"),
    ],
)
def test_normalize_language(name, expected: str) -> None:
    assert translator.normalize_language(name) == expected


def test_detect_language() -> None:
    # 中文散文：判 zh
    assert translator.detect_language("汪淼看到了一串数字在眼前跳动。") == "zh"
    # 英文散文：判 en
    assert translator.detect_language("It is a truth universally acknowledged.") == "en"
    # 空文本按英文处理
    assert translator.detect_language("") == "en"
    # The implementation guards with ``str(text or "")``, so a None sneaking in
    # from a hand edited file is tolerated even though the annotation is ``str``.
    assert translator.detect_language(None) == "en"  # type: ignore[arg-type]


# -------------------------------------------------------------------- settings
def test_translator_settings_defaults() -> None:
    # 不读文件时，全部字段都应当是文档里写的默认值
    settings = translator.TranslatorSettings()
    assert settings.backend == "google"
    assert settings.batch_size == translator.DEFAULT_BATCH_SIZE
    assert settings.target_language == "zh-CN"
    assert settings.source_language == "auto"
    assert settings.auto_translate_chapter is False
    # 没配 key 也没环境变量时是空串
    assert settings.resolved_api_key() == ""


def test_load_settings_reads_the_settings_file() -> None:
    # 先通过 config 写进 settings.toml
    config.set("translator.backend", "deepseek")
    config.set("translator.batch_size", 500)
    config.set("translator.target_language", "en")
    config.set("translator.auto_translate_chapter", True)

    # 再经 translator 读出来，四项都要对上
    settings = translator.load_settings()
    assert settings.backend == "deepseek"
    assert settings.batch_size == 500
    assert settings.target_language == "en"
    assert settings.auto_translate_chapter is True


def test_load_settings_reads_a_standalone_file(tmp_path: Path) -> None:
    # 显式路径时读独立 TOML；表里多出来的 notes 键被忽略
    target = tmp_path / "settings.toml"
    target.write_text(
        '[translator]\nbackend = "deepseek"\nbatch_size = 10\nnotes = "ignored"\n',
        encoding="utf-8",
    )
    settings = translator.load_settings(target)
    assert settings.backend == "deepseek"
    assert settings.batch_size == 10


def test_load_settings_of_a_missing_file_is_the_default(tmp_path: Path) -> None:
    # 文件不存在：退回默认（google）
    assert translator.load_settings(tmp_path / "nope.toml").backend == "google"


def test_load_settings_rejects_an_unknown_backend(tmp_path: Path) -> None:
    # backend 只接受已知引擎名（清单由 wreader.translate 维护）
    target = tmp_path / "settings.toml"
    target.write_text('[translator]\nbackend = "bing"\n', encoding="utf-8")
    with pytest.raises(translator.SettingsError) as excinfo:
        translator.load_settings(target)
    assert "must be one of" in str(excinfo.value)


def test_load_settings_clamps_a_zero_batch_size(tmp_path: Path) -> None:
    # batch_size 写 0 时会被夹到 1
    target = tmp_path / "settings.toml"
    target.write_text("[translator]\nbatch_size = 0\n", encoding="utf-8")
    assert translator.load_settings(target).batch_size == 1


def test_load_settings_rejects_a_fractional_batch_size(tmp_path: Path) -> None:
    # 不是整数的值要报错
    target = tmp_path / "settings.toml"
    target.write_text('[translator]\nbatch_size = "many"\n', encoding="utf-8")
    with pytest.raises(translator.SettingsError) as excinfo:
        translator.load_settings(target)
    assert "must be an integer" in str(excinfo.value)


def test_resolved_api_key_prefers_the_file_then_the_environment(
    isolated_home, monkeypatch
) -> None:
    # 只设环境变量时用它
    monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
    assert translator.load_settings().resolved_api_key() == "from-env"
    # 配置里有值时，配置优先
    config.set("translator.deepseek_api_key", "from-file")
    assert translator.load_settings().resolved_api_key() == "from-file"


def test_cache_root_follows_the_data_directory(
    isolated_home, monkeypatch
) -> None:
    # 未配置 cache_dir 时跟随数据目录
    monkeypatch.delenv("WREADER_NOVELS_DIR")
    assert translator.TranslatorSettings().cache_root() == isolated_home.data / "cache"
    # 配置了具体路径就用它
    config.set("translator.cache_dir", str(isolated_home.root / "chosen"))
    assert translator.load_settings().cache_root() == isolated_home.root / "chosen"


def test_cache_paths_are_per_book_and_chapter(isolated_home) -> None:
    settings = translator.load_settings()
    root = isolated_home.data / "cache"
    # 缓存根目录
    assert translator.cache_dir(settings) == root
    # 每本书一个子目录
    assert translator.book_cache_dir("abc", settings) == root / "abc"
    # 每章两个文件：_en 与 _bilingual
    assert (
        translator.chapter_cache_path("abc", 3, settings=settings) == root / "abc" / "ch3_en.txt"
    )
    assert translator.chapter_cache_path("abc", 3, "_bilingual", settings) == (
        root / "abc" / "ch3_bilingual.txt"
    )


def test_get_cached_translation_ignores_missing_and_empty_files(isolated_home) -> None:
    settings = translator.load_settings()
    # 文件不存在
    assert translator.get_cached_translation("abc", 0, settings) is None

    # 文件存在但是空的：也算没缓存
    empty = translator.chapter_cache_path("abc", 0, settings=settings)
    empty.parent.mkdir(parents=True)
    empty.write_text("", encoding="utf-8")
    assert translator.get_cached_translation("abc", 0, settings) is None

    # 有内容才算命中
    empty.write_text("译文\n", encoding="utf-8")
    assert translator.get_cached_translation("abc", 0, settings) == empty


# --------------------------------------------------------------------- batching
def test_batch_text_groups_by_character_budget() -> None:
    # 预算充足：全在一批
    assert translator.batch_text(["a", "b", "c", "d", "e"], 10) == [[0, 1, 2, 3, 4]]
    # 预算 4（每项算 2 个字符）：两两一批
    assert translator.batch_text(["a", "b", "c", "d", "e"], 4) == [[0, 1], [2, 3], [4]]
    # 预算 1：每项单独一批
    assert translator.batch_text(["a", "b"], 1) == [[0], [1]]
    # 空输入
    assert translator.batch_text([], 10) == []


def test_batch_text_gives_an_oversized_item_its_own_batch() -> None:
    # 超长条目不会被丢掉，而是独占一批
    assert translator.batch_text(["x" * 50, "b"], 10) == [[0], [1]]


# ------------------------------------------------------------------ translating
def test_translate_paragraphs_keeps_one_result_per_paragraph(backend) -> None:
    results = translator.translate_paragraphs(["甲", "乙", "丙"])
    # 一段对一段，顺序不变
    assert results == ["EN:甲", "EN:乙", "EN:丙"]
    # 三次内容被合成一次请求（用空行连接）
    assert backend.calls[0][0] == "甲\n\n乙\n\n丙"


def test_a_short_source_code_is_expanded_for_the_backend(backend) -> None:
    """``deep_translator`` rejects ``"zh"`` outright: it wants ``"zh-CN"``.

    ``detect_language`` and a hand written ``source_language`` both produce the
    short form, so every path has to map it before it reaches a back-end.
    """
    # 三条翻译入口都应当把 "zh"/"cn"/"chinese" 展开成 "zh-CN"
    translator.translate_paragraphs(["甲"], source="zh")
    assert backend.calls[0][1] == "zh-CN"
    translator.translate_lines(["甲"], source="cn")
    assert backend.calls[1][1] == "zh-CN"
    translator.translate_text("甲", source="chinese")
    assert backend.calls[2][1] == "zh-CN"


def test_auto_and_en_sources_are_left_alone(backend) -> None:
    # auto 原样传；en 原样传；空串被当成 auto
    translator.translate_paragraphs(["甲"], source="auto")
    translator.translate_paragraphs(["甲"], source="en")
    translator.translate_paragraphs(["甲"], source="")
    assert [call[1] for call in backend.calls] == ["auto", "en", "auto"]


def test_translate_paragraphs_skips_blanks_without_a_request(backend) -> None:
    # 空白段落直接给空串，不消耗请求
    results = translator.translate_paragraphs(["甲", "", "   ", "乙"])
    assert results == ["EN:甲", "", "", "EN:乙"]
    # 只有一段真正需要翻译，所以只发了一次请求
    assert len(backend.calls) == 1


def test_translate_paragraphs_reports_progress_and_pauses_between_batches() -> None:
    # 自定义后端：额外记录 pause 被调用次数
    class CountingBackend(RecordingBackend):
        def __init__(self) -> None:
            super().__init__()
            self.paused = 0

        def pause(self) -> None:
            self.paused += 1

    fake = CountingBackend()
    # 收集进度回调
    progress: List[Tuple[int, int]] = []
    results = translator.translate_paragraphs(
        ["a", "b", "c"],
        backend=fake,
        # batch_size=5：每项算 2 字符，所以会分成 2 批
        settings=translator.TranslatorSettings(batch_size=5),
        progress=lambda done, total: progress.append((done, total)),
    )
    assert results == ["EN:a", "EN:b", "EN:c"]
    # 每批结束回调一次
    assert progress == [(1, 2), (2, 2)]
    assert fake.paused == 1  # between the two batches, not after the last one


def test_translate_paragraphs_retries_item_by_item_when_reflowed() -> None:
    # reflow=True：后端不按分隔符返回，份数对不上
    fake = RecordingBackend(reflow=True)
    results = translator.translate_paragraphs(["甲", "乙"], backend=fake)
    # 退化成逐条翻译，结果照样对齐
    assert results == ["EN: 甲", "EN: 乙"]
    # 一次批量尝试 + 每条一次单独调用 = 3 次
    assert len(fake.calls) == 3  # one batch attempt plus one call per item


def test_translate_lines_aligns_with_the_input(backend) -> None:
    assert translator.translate_lines(["one", "two"]) == ["EN:one", "EN:two"]
    # 用换行当分隔符拼成一次请求
    assert backend.calls[0][0] == "one\ntwo"


def test_translate_text_never_caches_and_short_circuits_blanks(backend) -> None:
    assert translator.translate_text("hello") == "EN:hello"
    # 空白/空串原样返回，不发请求
    assert translator.translate_text("   ") == "   "
    assert translator.translate_text("") == ""
    # 只有 hello 那次真的调了后端
    assert len(backend.calls) == 1


def test_translate_viewport_rejoins_paragraphs(backend) -> None:
    # 段内换行压成空格，段间用空行分隔
    text = "first\nline\n\n\nsecond"
    assert translator.translate_viewport(text) == "EN:first line\n\nEN:second"
    # 发给后端的是"压平后的段落 + 空行"
    assert backend.calls[0][0] == "first line\n\nsecond"


def test_translate_viewport_of_blank_text_is_unchanged(backend) -> None:
    assert translator.translate_viewport("  ") == "  "
    # 没发任何请求
    assert backend.calls == []


# --------------------------------------------------------------- paragraph maths
LINES = ["甲甲", "乙乙", "", "丙丙", "", "丁丁"]


def test_paragraph_spans_returns_whole_paragraphs() -> None:
    # 三个段落：(0,1)、(3,3)、(5,5)
    assert translator.paragraph_spans(LINES) == [(0, 1), (3, 3), (5, 5)]
    # A screenful that only touches the middle paragraph still returns it whole.
    # 只碰到段落的一部分时，仍然返回整段
    assert translator.paragraph_spans(LINES, first=1, last=1) == [(0, 1)]
    assert translator.paragraph_spans(LINES, first=3, last=3) == [(3, 3)]
    assert translator.paragraph_spans(LINES, first=5, last=5) == [(5, 5)]
    # A blank line belongs to no paragraph, so a screenful of blanks finds nothing.
    # 只有空行的区间没有段落
    assert translator.paragraph_spans(LINES, first=4, last=4) == []
    assert translator.paragraph_spans([]) == []


def test_paragraph_texts_flattens_inner_newlines() -> None:
    # 段内换行被压成空格
    assert translator.paragraph_texts(LINES, [(0, 1), (3, 3)]) == ["甲甲 乙乙", "丙丙"]


def test_map_paragraphs_covers_the_lines_of_a_paragraph() -> None:
    # 译文放在段落首行，段内其余行给空串（表示"已被上一行覆盖"）
    assert translator.map_paragraphs([(0, 1), (3, 3)], ["one", "two"]) == {
        0: "one",
        1: "",
        3: "two",
    }


def test_build_bilingual_pairs_the_paragraphs() -> None:
    # 中英对照：每段先原文后译文，段间空行
    text = translator.build_bilingual(LINES, [(0, 1), (3, 3)], ["one", "two"])
    assert text == "甲甲\n乙乙\n\none\n\n丙丙\n\ntwo\n"


# ------------------------------------------------------------ chapter mechanics
def test_chapter_count_and_start_line(imported) -> None:
    # 样例中文书识别出 2 章
    book = library.get_book(imported["zh"])
    assert isinstance(book, dict)
    assert translator.chapter_count(book) == 2
    # 第 0 章从第 0 行开始，第 1 章从第 5 行开始
    assert translator.chapter_start_line(book, 0) == 0
    assert translator.chapter_start_line(book, 1) == 5
    # 越界时返回 0
    assert translator.chapter_start_line(book, 9) == 0  # out of range
    # 没有章节信息的书整体算一章
    assert translator.chapter_count({"chapters": []}) == 1


def test_chapter_lines_slices_the_book(imported) -> None:
    book = library.get_book(imported["zh"])
    assert isinstance(book, dict)
    # 第 0 章 = 前 5 行
    assert translator.chapter_lines(book, 0) == list(BOOK_LINES[0:5])
    # 第 1 章 = 之后的所有行
    assert translator.chapter_lines(book, 1) == list(BOOK_LINES[5:])
    # 越界的章节号要报错
    with pytest.raises(translator.TranslationError) as excinfo:
        translator.chapter_lines(book, 5)
    assert "out of range" in str(excinfo.value)


def test_read_book_lines_needs_the_file(imported) -> None:
    book = library.get_book(imported["zh"])
    assert isinstance(book, dict)
    # 正常读取时与源文本完全一致
    assert translator.read_book_lines(book) == list(BOOK_LINES)
    # 把路径改成不存在的文件
    book["file_path"] = "/nope/missing.txt"
    with pytest.raises(translator.TranslationError) as excinfo:
        translator.read_book_lines(book)
    assert "book text is missing" in str(excinfo.value)


def test_translate_chapter_writes_both_cache_files(imported, backend) -> None:
    settings = translator.load_settings()
    # 翻译第 0 章
    path = translator.translate_chapter(imported["zh"], 0, settings=settings)
    # 返回的就是 _en 缓存路径
    assert path == translator.chapter_cache_path(imported["zh"], 0, settings=settings)
    # 英文版内容：逐段加前缀，段间空行
    assert path.read_text(encoding="utf-8") == (
        "EN:第一章 科学边界\n\n"
        "EN:汪淼看到了一串数字在眼前跳动。 他抬头望向窗外的夜空。\n"
    )
    # 同时写出了中英对照版
    bilingual = path.with_name("ch0_bilingual.txt")
    assert bilingual.read_text(encoding="utf-8") == (
        "第一章 科学边界\n\nEN:第一章 科学边界\n\n"
        "汪淼看到了一串数字在眼前跳动。\n他抬头望向窗外的夜空。\n\n"
        "EN:汪淼看到了一串数字在眼前跳动。 他抬头望向窗外的夜空。\n"
    )


def test_translate_chapter_skips_the_cache_unless_forced(imported, backend) -> None:
    settings = translator.load_settings()
    # 第一次：真的调用后端
    translator.translate_chapter(imported["zh"], 0, settings=settings)
    calls_after_first = len(backend.calls)

    # 第二次：命中缓存，不再请求
    translator.translate_chapter(imported["zh"], 0, settings=settings)
    assert len(backend.calls) == calls_after_first  # straight from the cache

    # force=True：忽略缓存重翻
    translator.translate_chapter(imported["zh"], 0, settings=settings, force=True)
    assert len(backend.calls) > calls_after_first


def test_translate_chapter_expands_the_detected_source(imported, backend) -> None:
    translator.translate_chapter(imported["zh"], 0)
    # detect_language() reports the short code "zh"; a back-end needs "zh-CN".
    # 检测出来的是 "zh"，传给后端前被展开成 "zh-CN"
    assert backend.calls[0][1] == "zh-CN"
    assert backend.calls[0][2] == "en"


def test_translate_chapter_rejects_an_unknown_book(backend) -> None:
    with pytest.raises(translator.TranslationError) as excinfo:
        translator.translate_chapter("nope", 0)
    assert "unknown book id" in str(excinfo.value)


def test_translate_chapter_needs_text(isolated_home, home, backend) -> None:
    # 造一个只有空行的正文文件
    blank = home.novels / "blank_utf8.txt"
    blank.parent.mkdir(parents=True, exist_ok=True)
    blank.write_text("\n\n\n", encoding="utf-8")
    document = library.load_library()
    document["books"]["blank"] = {
        "title": "Blank",
        "file_path": str(blank),
        "total_lines": 3,
        "chapters": [{"title": "c", "line_start": 0}],
    }
    library.save_library(document)

    # 整章无内容：报错而不是发空请求
    with pytest.raises(translator.TranslationError) as excinfo:
        translator.translate_chapter("blank", 0)
    assert "no text to translate" in str(excinfo.value)


def test_load_chapter_map_marks_the_covered_lines(imported, backend) -> None:
    settings = translator.load_settings()
    # 先翻出缓存
    translator.translate_chapter(imported["zh"], 0, settings=settings)
    # 再把缓存读成"全书行号 -> 译文"
    mapping = translator.load_chapter_map(imported["zh"], 0, settings)
    # 首行挂译文；第 2 行挂段落译文；第 3 行给空串（已被上一段覆盖）
    assert mapping == {
        0: "EN:第一章 科学边界",
        2: "EN:汪淼看到了一串数字在眼前跳动。 他抬头望向窗外的夜空。",
        3: "",
    }
    # 第 1 章还没缓存：返回空字典
    assert translator.load_chapter_map(imported["zh"], 1, settings) == {}


def test_translate_book_summarises_and_resumes(imported, backend) -> None:
    settings = translator.load_settings()
    # 第一次翻译整本书：两章都翻
    first = translator.translate_book(imported["zh"], settings=settings)
    assert first["chapters"] == 2
    assert first["translated"] == [0, 1]
    assert first["skipped"] == [] and first["failed"] == []

    # 第二次：全部走缓存，这就是"可续传"的体现
    second = translator.translate_book(imported["zh"], settings=settings)
    assert second["translated"] == []
    assert second["skipped"] == [0, 1]


def test_translate_book_reports_a_failed_chapter_without_aborting(
    imported, backend
) -> None:
    # 塞一本正文文件不存在的书
    document = library.load_library()
    document["books"]["blank"] = {
        "title": "Blank",
        "file_path": str(imported["home"].novels / "missing.txt"),
        "chapters": [{"title": "c", "line_start": 0}],
    }
    library.save_library(document)

    # 单章失败不会中断整本书的流程，而是进 failed 列表
    summary = translator.translate_book("blank")
    assert summary["translated"] == []
    assert summary["failed"] and summary["failed"][0][0] == 0
    assert "missing" in summary["failed"][0][1]


def test_translate_book_reports_progress(imported, backend) -> None:
    # 收集 (已完成章数, 总章数)
    progress: List[Tuple[int, int]] = []
    translator.translate_book(
        imported["zh"], progress=lambda done, total: progress.append((done, total))
    )
    assert progress == [(1, 2), (2, 2)]


def test_clear_cache_removes_the_book_directory(imported, backend) -> None:
    translator.translate_book(imported["zh"])
    # Two chapters, and each one writes a _en and a _bilingual file.
    # 2 章 × 2 个文件 = 4
    assert translator.clear_cache(imported["zh"]) == 4
    assert translator.get_cached_translation(imported["zh"], 0) is None
    # 再清一次：没有文件可删
    assert translator.clear_cache(imported["zh"]) == 0


def test_build_bilingual_skips_missing_pieces() -> None:
    # 只有原文没有译文时，只输出原文
    assert translator.build_bilingual(["甲"], [(0, 0)], [""]) == "甲\n"


# --------------------------------------------------------------------- backends
def test_make_backend_picks_the_configured_engine() -> None:
    # 默认配置 -> Google 引擎（免费、免密钥），包在 EngineBackend 里
    google = translator.make_backend(translator.TranslatorSettings())
    assert isinstance(google, translator.EngineBackend)
    assert google.name == "google"

    # [translate].engine 选百度：凭证被带进引擎
    baidu = translator.make_backend(
        translator.TranslatorSettings(
            engine="baidu", credentials={"baidu_appid": "a", "baidu_secret": "s"}
        )
    )
    assert isinstance(baidu, translator.EngineBackend)
    assert baidu.name == "baidu"
    assert baidu.engine.credential("baidu_appid") == "a"

    # engine 为空时回退到旧的 [translator].backend
    legacy = translator.make_backend(
        translator.TranslatorSettings(backend="deepseek", deepseek_api_key="k")
    )
    assert isinstance(legacy, translator.EngineBackend)
    assert legacy.name == "deepseek"
    # 旧字段的 key 也被回退过去了（用基类 API 读，不依赖具体引擎的字段名）
    assert legacy.engine.credential("deepseek_api_key") == "k"


def test_make_backend_rejects_an_unknown_engine() -> None:
    # 引擎名写错：属于配置错误，报错里列出可选值
    with pytest.raises(translator.SettingsError) as excinfo:
        translator.make_backend(translator.TranslatorSettings(engine="bing"))
    assert "baidu" in str(excinfo.value)


def test_engine_ready_reports_missing_credentials() -> None:
    # 百度缺 appid/secret：不 ready，并说清楚缺什么
    ready, reason = translator.engine_ready(
        translator.TranslatorSettings(engine="baidu")
    )
    assert ready is False
    assert "APPID" in reason
    # 默认的 Google 不需要任何凭证
    assert translator.engine_ready(translator.TranslatorSettings()) == (True, "")


def test_engine_backend_maps_engine_errors(monkeypatch) -> None:
    # 引擎抛"不可达" -> 后端的 TranslationUnavailable（整本书会因此中止）
    class Unreachable(translate.Translator):
        name = "boom"

        def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
            raise translate.TranslateUnavailable("no network")

    backend = translator.EngineBackend(Unreachable())
    assert backend.name == "boom"
    with pytest.raises(translator.TranslationUnavailable):
        backend.translate("hi")

    # 引擎抛普通错误 -> TranslationError（只影响这一次）
    class Broken(translate.Translator):
        name = "broken"

        def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
            raise translate.TranslateError("bad signature")

    with pytest.raises(translator.TranslationError):
        translator.EngineBackend(Broken()).translate("hi")


def test_the_backend_base_class_is_abstract() -> None:
    # 基类的 translate 必须抛 NotImplementedError
    with pytest.raises(NotImplementedError):
        translator.Backend().translate("hi")


def test_a_plain_callable_can_be_the_backend() -> None:
    # 传普通函数也能当后端
    translator.set_backend(lambda text, source, target: "L:" + text.upper())
    assert translator.get_backend().translate("hi") == "L:HI"
    # 包装类沿用基类的"非流式"实现
    assert translator.get_backend().translate_stream("hi") is not None
    assert translator.get_backend().name == "callable"


def test_set_backend_round_trip() -> None:
    # 自定义一个后端类
    class Fake(translator.Backend):
        def translate(self, text: str, source: str = "auto", target: str = "en") -> str:
            return "F:" + text

    fake = Fake()
    translator.set_backend(fake)
    # 装上去之后拿到的就是它本身
    assert translator.get_backend() is fake
    # 传 None 清掉，下次会按配置重建（默认 Google 引擎）
    translator.set_backend(None)
    rebuilt = translator.get_backend()
    assert isinstance(rebuilt, translator.EngineBackend)
    assert rebuilt.name == "google"


# 参数化：不是后端也不是可调用对象的输入
@pytest.mark.parametrize("bad", [123, "not a backend", []])
def test_set_backend_rejects_anything_else(bad) -> None:
    with pytest.raises(TypeError) as excinfo:
        translator.set_backend(bad)
    assert "Backend instance or a callable" in str(excinfo.value)


def test_the_default_backend_is_built_once() -> None:
    translator.set_backend(None)
    first = translator.get_backend()
    # 第二次取到的是同一个实例（不会重复构造）
    assert translator.get_backend() is first


def test_google_engine_short_circuits_blank_text() -> None:
    google = translate.make_engine("google")
    # 工厂返回的就是 Google 引擎（收窄类型，下面要读它自己的计数器）
    assert isinstance(google, google_engine.GoogleTranslator)
    # 空白文本直接返回空串，连请求都不发
    assert google.translate("   ") == ""
    assert google.requests == 0  # no request was even attempted


def test_google_engine_pauses_between_batches(monkeypatch) -> None:
    # 把 time.sleep 换成记录器，避免真的等待
    slept: List[float] = []
    monkeypatch.setattr(google_engine.time, "sleep", slept.append)
    translate.make_engine("google", sleep_seconds=3.0).pause()
    assert slept == [3.0]
    # 等待时间设 0 时完全不睡
    translate.make_engine("google", sleep_seconds=0).pause()
    assert slept == [3.0]  # a zero throttle does not sleep at all


def test_deepseek_payload_and_headers() -> None:
    engine = translate.make_engine(
        "deepseek",
        {"deepseek_api_key": "k", "deepseek_model": "m", "deepseek_url": "u"},
    )
    # 收窄到具体引擎：下面要用它自己的 payload() / headers()
    assert isinstance(engine, deepseek_engine.DeepSeekTranslator)
    payload = engine.payload("你好", "en")
    # 请求体：模型名、流式开关、temperature、消息列表
    assert payload["model"] == "m"
    assert payload["stream"] is True
    assert payload["temperature"] == deepseek_engine.TEMPERATURE
    assert payload["messages"][-1] == {"role": "user", "content": "你好"}
    assert payload["messages"][0]["role"] == "system"
    # stream=False 时关闭流式
    assert engine.payload("你好", "en", stream=False)["stream"] is False
    # 请求头带 Bearer token
    assert engine.headers() == {
        "Authorization": "Bearer k",
        "Content-Type": "application/json",
    }


def test_deepseek_needs_a_key() -> None:
    # 没有 key（环境变量也已被清掉）时，一开始迭代流就报"需要 API key"
    engine = translate.make_engine("deepseek")
    assert isinstance(engine, deepseek_engine.DeepSeekTranslator)
    with pytest.raises(translate.TranslateUnavailable) as excinfo:
        list(engine.stream("hi"))
    assert "API key" in str(excinfo.value)


def test_the_system_prompt_follows_the_target_language() -> None:
    # 目标是英文：用定制提示词
    assert deepseek_engine.system_prompt("en") == deepseek_engine.DEEPSEEK_SYSTEM_PROMPT
    # 其它目标语言：通用模板里带上目标语言
    assert "zh-CN" in deepseek_engine.system_prompt("zh-CN")


# 参数化：各种 SSE 行的解析结果
@pytest.mark.parametrize(
    "line, expected",
    [
        ('data: {"choices":[{"delta":{"content":"hi"}}]}', "hi"),
        ('data: {"choices":[{"delta":{"content":"a"},"text":"b"}]}', "a"),
        ('data: {"choices":[{"text":"old style"}]}', "old style"),
        (b'data: {"choices":[{"delta":{"content":"bytes"}}]}', "bytes"),
        ("data: [DONE]", None),
        ("", ""),
        (": comment", ""),
        ("data: not json", ""),
        ('data: {"choices":[]}', ""),
    ],
)
def test_parse_sse(line, expected) -> None:
    assert deepseek_engine.parse_sse(line) == expected


def test_clearing_the_whole_cache(imported, backend) -> None:
    translator.translate_book(imported["zh"])
    # 不传 book_id 就清全部缓存
    assert translator.clear_cache() == 4  # 2 chapters x (_en + _bilingual)






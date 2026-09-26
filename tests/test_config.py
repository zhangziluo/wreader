"""Tests for :mod:`wreader.config` — the settings document and its file."""

# 延迟求值类型注解
from __future__ import annotations

# 测旧 config.json 迁移时用
import json
# 路径断言
from pathlib import Path
# 类型注解
from typing import List

# pytest.raises / parametrize
import pytest

# 被测模块
from wreader import config


def test_schema_has_a_default_for_every_path() -> None:
    # SCHEMA 里声明的每一条路径都要有默认值
    paths = config.all_paths()
    # 当前 schema 共 20 项（reader 13 + stats 4 + library 1 + toc 2）
    assert len(paths) == 20
    # 不能有重复
    assert len(set(paths)) == len(paths)
    for path in paths:
        # 每项都能在 DEFAULT_FLAT 里查到
        assert path in config.DEFAULT_FLAT, path
        # default_for 与 DEFAULT_FLAT 保持一致
        assert config.default_for(path) == config.DEFAULT_FLAT[path]


def test_mobile_scrolling_settings_are_declared() -> None:
    # 移动端滚动：滚轮/触摸一格滚 1 行，拖动即滚动默认开
    assert config.DEFAULT_FLAT["reader.wheel_scroll_step"] == 1
    assert config.DEFAULT_FLAT["reader.touch_scroll"] is True
    # 类型按默认值推断：一个是整数、一个是布尔
    assert config.coerce_value("reader.wheel_scroll_step", "3") == 3
    assert config.coerce_value("reader.touch_scroll", "off") is False


def test_auto_scroll_settings_are_declared() -> None:
    # 自动翻页：默认每 5 秒走 1 屏幕行（与 reader 的默认值一致）
    assert config.DEFAULT_FLAT["reader.auto_scroll_interval"] == 5.0
    assert config.DEFAULT_FLAT["reader.auto_scroll_step"] == 1
    # 类型按默认值推断：间隔是浮点（"2" 变成 2.0）、步长是整数
    assert config.coerce_value("reader.auto_scroll_interval", "2") == 2.0
    assert config.coerce_value("reader.auto_scroll_step", "3") == 3
    # 非数字直接报错（写入时就被拦住，别让它变成 0 秒狂翻）
    with pytest.raises(config.ConfigError):
        config.coerce_value("reader.auto_scroll_interval", "abc")


def test_auto_scroll_check_settings_are_declared() -> None:
    # 自动翻页的防作弊校验：连续 10 分钟弹一道题、每题最多等 30 秒
    assert config.DEFAULT_FLAT["reader.auto_scroll_check_minutes"] == 10.0
    assert config.DEFAULT_FLAT["reader.auto_scroll_check_seconds"] == 30
    # 分钟数是浮点（0.5 = 半分钟，方便试效果），回答时限是整数；0 都要原样保留
    assert config.coerce_value("reader.auto_scroll_check_minutes", "15") == 15.0
    assert config.coerce_value("reader.auto_scroll_check_minutes", "0.5") == 0.5
    assert config.coerce_value("reader.auto_scroll_check_minutes", "0") == 0.0
    assert config.coerce_value("reader.auto_scroll_check_seconds", "45") == 45
    # 非数字照样被拦下
    with pytest.raises(config.ConfigError):
        config.coerce_value("reader.auto_scroll_check_seconds", "soon")
    with pytest.raises(config.ConfigError):
        config.coerce_value("reader.auto_scroll_check_minutes", "soon")


def test_page_overlap_setting_is_declared() -> None:
    # 翻页重叠默认保留 3 行上下文，0 表示关掉（值本身合法，不能被吃成默认值）
    assert config.DEFAULT_FLAT["reader.page_overlap"] == 3
    # 类型是整数
    assert config.coerce_value("reader.page_overlap", "5") == 5
    assert config.coerce_value("reader.page_overlap", "0") == 0


def test_settings_paths_follow_nr_home(isolated_home) -> None:
    # 所有路径都应当以 $WREADER_HOME（临时目录）为根
    assert config.data_dir() == isolated_home.data
    assert config.settings_path() == isolated_home.data / "settings.toml"
    # config_path 是 settings_path 的别名
    assert config.config_path() == config.settings_path()
    assert config.library_file() == isolated_home.data / "library.json"
    assert config.legacy_config_path() == isolated_home.data / "config.json"
    # 缓存目录默认跟随数据目录
    assert config.default_cache_dir() == isolated_home.data / "cache"


# 参数化：老版本扁平键名 -> 现在的点号路径
@pytest.mark.parametrize(
    "alias, canonical",
    [
        ("page_height", "reader.page_height"),
        ("theme", "reader.theme"),
        ("store_history", "reader.store_history"),
        ("novels_dir", "library.novels_dir"),
        ("library_path", "library.novels_dir"),
        ("achievement_sound", "stats.achievement_sound"),
    ],
)
def test_resolve_path_accepts_the_legacy_flat_names(alias: str, canonical: str) -> None:
    # 旧名都能解析成新路径
    assert config.resolve_path(alias) == canonical


def test_resolve_path_keeps_canonical_names() -> None:
    # 标准路径原样返回
    assert config.resolve_path("reader.page_height") == "reader.page_height"
    # 首尾空白会被去掉
    assert config.resolve_path("  reader.theme  ") == "reader.theme"


def test_resolve_path_suggests_the_closest_name() -> None:
    # 打错一个字时应当报错，并给出最接近的候选
    with pytest.raises(config.ConfigError) as excinfo:
        config.resolve_path("reader.pag_height")
    assert "unknown setting 'reader.pag_height'" in str(excinfo.value)
    assert "did you mean 'reader.page_height'?" in str(excinfo.value)


def test_resolve_path_without_a_close_match_has_no_suggestion() -> None:
    # 差得太远时不硬凑建议
    with pytest.raises(config.ConfigError) as excinfo:
        config.resolve_path("zzz.not_a_setting")
    assert "did you mean" not in str(excinfo.value)


def test_coerce_value_types() -> None:
    # 整数：字符串与整数都能转
    assert config.coerce_value("reader.page_height", "30") == 30
    assert config.coerce_value("reader.page_height", 30) == 30
    # 浮点：'0.5' 与 '1'（整数形态）都行
    assert config.coerce_value("reader.page_scroll_step", "0.5") == 0.5
    assert config.coerce_value("reader.page_scroll_step", "1") == 1.0
    # 布尔：认 yes/off 这类写法，也接受真正的 bool
    assert config.coerce_value("reader.store_history", "yes") is True
    assert config.coerce_value("reader.store_history", "off") is False
    assert config.coerce_value("reader.store_history", True) is True
    # 字符串键：数字会被转成字符串
    assert config.coerce_value("reader.theme", 5) == "5"
    assert config.coerce_value("reader.status_bar_format", "book|percent") == "book|percent"


# 参数化：几种不能当整数的值
@pytest.mark.parametrize("value", ["abc", "", None, True])
def test_coerce_value_rejects_a_bad_integer(value) -> None:
    with pytest.raises(config.ConfigError) as excinfo:
        config.coerce_value("reader.page_height", value)
    assert "expects an integer" in str(excinfo.value)


def test_coerce_value_rejects_a_bad_boolean() -> None:
    # 认不出的布尔写法要报错（避免静默当成 False）
    with pytest.raises(config.ConfigError) as excinfo:
        config.coerce_value("reader.store_history", "maybe")
    assert "expects a boolean" in str(excinfo.value)


def test_coerce_value_blank_directory_is_none() -> None:
    # 目录类设置留空统一存成 None
    assert config.coerce_value("library.novels_dir", "") is None
    assert config.coerce_value("library.novels_dir", "   ") is None
    assert config.coerce_value("library.novels_dir", None) is None
    # 写了具体路径就保留
    assert config.coerce_value("library.novels_dir", "/tmp/books") == "/tmp/books"


def test_coerce_value_checks_the_path() -> None:
    # 键名本身不合法时也要报错
    with pytest.raises(config.ConfigError):
        config.coerce_value("reader.nope", 1)


def test_load_config_creates_the_file_with_the_defaults(isolated_home) -> None:
    settings = config.load_config()
    assert settings.path == isolated_home.data / "settings.toml"
    assert settings.path.is_file()
    text = settings.path.read_text(encoding="utf-8")
    assert text.startswith("# wreader settings")
    assert "[reader]" in text and "[stats]" in text and "[library]" in text
    assert settings.get("reader.page_height") == 24
    assert settings.get("reader.page_scroll_step") == 1.0


def test_config_get_and_set_round_trip(isolated_home) -> None:
    settings = config.load_config()
    settings.set("reader.page_height", "32")
    settings.save()

    again = config.reload()
    assert again.get("reader.page_height") == 32


def test_config_get_rejects_an_unknown_path() -> None:
    settings = config.load_config()
    with pytest.raises(config.ConfigError):
        settings.get("reader.nope")
    assert "reader.page_height" in settings
    assert "reader.nope" not in settings
    assert settings["reader.page_height"] == 24


def test_config_reports_unknown_keys_without_refusing_to_load(isolated_home) -> None:
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        "[reader]\npage_height = 30\nnotes = \"mine\"\n", encoding="utf-8"
    )
    settings = config.load_config()
    assert settings.get("reader.page_height") == 30
    assert settings.unknown == {"reader.notes": "mine"}


def test_config_falls_back_to_the_default_for_an_invalid_value(isolated_home) -> None:
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        '[reader]\npage_height = "abc"\n', encoding="utf-8"
    )
    settings = config.load_config()
    assert settings.get("reader.page_height") == 24
    assert "reader.page_height" in settings.invalid
    assert "expects an integer" in settings.invalid["reader.page_height"]


def test_a_damaged_toml_file_is_a_config_error(isolated_home) -> None:
    # 写一个语法坏掉的 TOML（少了个右括号）
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        "[reader\npage_height = ", encoding="utf-8"
    )
    # 加载时应当明确报"不是合法 TOML"
    with pytest.raises(config.ConfigError) as excinfo:
        config.load_config()
    assert "not valid TOML" in str(excinfo.value)


def test_config_sections_and_flat_view(isolated_home) -> None:
    settings = config.load_config()
    # section() 返回"短键名 -> 值"
    reader = settings.section("reader")
    assert reader["page_height"] == 24
    # 短键名里不带前缀
    assert "reader.page_height" not in reader
    # flat() 返回"点号路径 -> 值"
    flat = settings.flat()
    assert flat["reader.page_height"] == 24
    # 条目数与 schema 一致
    assert len(flat) == len(config.all_paths())


def test_raw_section_only_holds_what_the_file_stored(isolated_home) -> None:
    # 文件里只写了 daily_goal_minutes 一项
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        "[stats]\ndaily_goal_minutes = 30\n", encoding="utf-8"
    )
    settings = config.load_config()
    # raw_section 只反映文件里真正写过的内容
    assert settings.raw_section("stats") == {"daily_goal_minutes": 30}
    # The coerced view still fills in every documented default.
    # 而常规视图会把默认值补齐
    assert settings.section("stats")["show_heatmap"] is True
    assert settings.get("stats.show_heatmap") is True


def test_config_stored_keeps_the_raw_value(isolated_home) -> None:
    # 文件里故意把整数写成字符串
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        '[reader]\npage_height = "30"\n', encoding="utf-8"
    )
    settings = config.load_config()
    # stored() 给出原始值，get() 给出转换后的值
    assert settings.stored("reader.page_height") == "30"
    assert settings.get("reader.page_height") == 30


def test_config_reset_restores_every_default(isolated_home) -> None:
    # 改一项并存盘，再 reset
    settings = config.load_config()
    settings.set("reader.page_height", 40)
    settings.save()
    settings.reset()
    # 全部回到默认值
    assert settings.get("reader.page_height") == 24
    assert settings.flat() == config.DEFAULT_FLAT
    # 未知键与错误记录也被清空
    assert settings.unknown == {}
    assert settings.invalid == {}


def test_config_module_helpers_write_the_file(isolated_home) -> None:
    # 模块级便捷函数：读默认值 -> 写入 42 -> 再读 -> reload 仍是 42 -> reset 回 24
    assert config.get("reader.page_height") == 24
    assert config.set("reader.page_height", 42) == 42
    assert config.get("reader.page_height") == 42
    assert config.reload().get("reader.page_height") == 42
    assert config.reset().get("reader.page_height") == 24


def test_legacy_config_json_is_migrated_and_kept_as_a_backup(isolated_home) -> None:
    # 手写一份老版本的扁平 config.json（含一个不认识的键）
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    legacy = isolated_home.data / "config.json"
    legacy.write_text(
        json.dumps(
            {
                "page_height": 30,
                "novels_dir": "/tmp/old-novels",
                "unknown_old_key": 1,
            }
        ),
        encoding="utf-8",
    )

    settings = config.load_config()
    # 记录下迁移来源
    assert settings.migrated_from == legacy
    # 扁平键都被映射到了正确的段
    assert settings.get("reader.page_height") == 30
    assert settings.get("library.novels_dir") == "/tmp/old-novels"
    # 映射表里没有的老键直接丢掉，不算"未知键"
    assert "unknown_old_key" not in settings.unknown
    # 老文件被改名备份
    assert not legacy.exists()
    assert (isolated_home.data / "config.json.bak").exists()


def test_legacy_config_is_not_read_once_settings_toml_exists(isolated_home) -> None:
    # 两份文件同时存在时，以新的 settings.toml 为准
    isolated_home.data.mkdir(parents=True, exist_ok=True)
    (isolated_home.data / "settings.toml").write_text(
        "[reader]\npage_height = 12\n", encoding="utf-8"
    )
    (isolated_home.data / "config.json").write_text('{"page_height": 99}', encoding="utf-8")
    assert config.load_config().get("reader.page_height") == 12
    # 也没有触发迁移，所以不会留下 .bak
    assert not (isolated_home.data / "config.json.bak").exists()


def test_novels_dir_prefers_the_environment(isolated_home, monkeypatch) -> None:
    # 环境变量优先：conftest 已经把它指到临时目录
    assert config.novels_dir() == isolated_home.novels
    monkeypatch.delenv("WREADER_NOVELS_DIR")
    # The setting is empty, so the documented default wins.
    # 环境变量没了、配置也留空 -> 用文档里的默认值 ~/novels
    assert config.novels_dir() == Path.home() / "novels"
    # 配置里写了具体路径就用它
    config.set("library.novels_dir", str(isolated_home.root / "elsewhere"))
    assert config.novels_dir() == isolated_home.root / "elsewhere"


def test_resolve_cache_dir_follows_the_data_directory(isolated_home) -> None:
    # 空值与"默认值字面量"都理解成"跟随数据目录"
    assert config.resolve_cache_dir("") == isolated_home.data / "cache"
    assert config.resolve_cache_dir(config.DEFAULT_CACHE_DIR) == isolated_home.data / "cache"
    # 明确路径则展开 ~ 后使用
    assert config.resolve_cache_dir("~/chosen") == Path.home() / "chosen"
    assert config.resolve_cache_dir("/tmp/cache") == Path("/tmp/cache")


def test_cache_dir_uses_the_setting(isolated_home) -> None:
    # cache_dir() 走配置：设了就返回设的值
    chosen = isolated_home.root / "toc-cache"
    config.set("toc.cache_dir", str(chosen))
    assert config.cache_dir() == chosen


def test_effective_values_resolves_the_two_directory_paths(isolated_home) -> None:
    # effective_values 会把两个"目录类"设置替换成真实路径
    values = config.effective_values()
    assert values["library.novels_dir"] == str(isolated_home.novels)
    assert values["toc.cache_dir"] == str(isolated_home.data / "cache")


# ------------------------------------------------- the rename from nr to wreader
def test_the_default_data_directory_is_the_new_name(monkeypatch) -> None:
    # 清掉环境变量与迁移标志，并打桩 _app_dir，避免依赖真实家目录
    monkeypatch.delenv(config.ENV_HOME, raising=False)
    monkeypatch.delenv(config.ENV_HOME_LEGACY, raising=False)
    monkeypatch.setattr(config, "_MIGRATED", False)
    monkeypatch.setattr(config, "migrate_legacy_data_dir", lambda *a, **k: None)
    # ``_app_dir`` is stubbed so the assertion never depends on the real home.
    monkeypatch.setattr(
        config, "_app_dir", lambda name, posix_name: Path("/fake-home") / posix_name
    )
    # 新名字是 .wreader
    assert config.DATA_DIRNAME == ".wreader"
    assert config.data_dir() == Path("/fake-home") / ".wreader"


def test_legacy_data_dir_points_at_the_pre_rename_name() -> None:
    # 改名前的目录名是 .nr
    assert config.LEGACY_DATA_DIRNAME == ".nr"
    assert config.legacy_data_dir().name == ".nr"


def test_the_new_environment_variables_win(monkeypatch, tmp_path: Path) -> None:
    # 新旧环境变量同时存在时，新名字优先
    monkeypatch.setenv(config.ENV_HOME, str(tmp_path / "new-home"))
    monkeypatch.setenv(config.ENV_HOME_LEGACY, str(tmp_path / "old-home"))
    assert config.data_dir() == tmp_path / "new-home"

    # novels 目录同理
    monkeypatch.setenv(config.ENV_NOVELS_DIR, str(tmp_path / "new-novels"))
    monkeypatch.setenv(config.ENV_NOVELS_DIR_LEGACY, str(tmp_path / "old-novels"))
    assert config.novels_dir() == tmp_path / "new-novels"


def test_the_pre_rename_environment_variables_still_work(
    monkeypatch, tmp_path: Path
) -> None:
    # 只设旧变量时，作为兜底依然生效
    monkeypatch.delenv(config.ENV_HOME, raising=False)
    monkeypatch.setenv(config.ENV_HOME_LEGACY, str(tmp_path / "old-home"))
    assert config.data_dir() == tmp_path / "old-home"

    monkeypatch.delenv(config.ENV_NOVELS_DIR, raising=False)
    monkeypatch.setenv(config.ENV_NOVELS_DIR_LEGACY, str(tmp_path / "old-novels"))
    assert config.novels_dir() == tmp_path / "old-novels"


def test_data_dir_adopts_the_old_directory_once(monkeypatch) -> None:
    # 用列表记录迁移函数被调用的次数
    adopted: List[str] = []
    monkeypatch.delenv(config.ENV_HOME, raising=False)
    monkeypatch.delenv(config.ENV_HOME_LEGACY, raising=False)
    monkeypatch.setattr(config, "_MIGRATED", False)
    monkeypatch.setattr(
        config, "migrate_legacy_data_dir", lambda: adopted.append("adopt")
    )
    monkeypatch.setattr(
        config, "_app_dir", lambda name, posix_name: Path("/fake-home") / posix_name
    )
    # 连续调用两次
    config.data_dir()
    config.data_dir()
    assert adopted == ["adopt"]  # once per process, not on every call


def test_migrate_legacy_data_dir_moves_everything(tmp_path: Path) -> None:
    # 造一个"旧家目录"，里面有配置、索引、缓存（含子目录）
    legacy = tmp_path / ".nr"
    (legacy / "cache" / "abc").mkdir(parents=True)
    (legacy / "settings.toml").write_text("[reader]\npage_height = 30\n", encoding="utf-8")
    (legacy / "library.json").write_text('{"books": {}}', encoding="utf-8")
    (legacy / "cache" / "abc" / "abc123_toc.json").write_text(
        '{"chapters": []}', encoding="utf-8"
    )
    target = tmp_path / ".wreader"

    # 迁移成功并返回新路径
    assert config.migrate_legacy_data_dir(target=target, legacy=legacy) == target
    # 旧目录整体消失
    assert not legacy.exists()
    # 三类内容都还在，内容一字不差
    assert (target / "settings.toml").read_text(encoding="utf-8") == (
        "[reader]\npage_height = 30\n"
    )
    assert (target / "library.json").is_file()
    assert (
        target / "cache" / "abc" / "abc123_toc.json"
    ).read_text("utf-8") == '{"chapters": []}'


def test_the_adopted_settings_are_what_wreader_then_reads(
    monkeypatch, tmp_path: Path
) -> None:
    # 旧目录里的配置写的是改名前的缓存默认值 "~/.nr/cache"
    legacy = tmp_path / ".nr"
    legacy.mkdir()
    (legacy / "settings.toml").write_text(
        '[reader]\npage_height = 30\n\n[toc]\ncache_dir = "~/.nr/cache"\n',
        encoding="utf-8",
    )
    target = tmp_path / ".wreader"
    config.migrate_legacy_data_dir(target=target, legacy=legacy)

    # 把 WREADER_HOME 指到迁移后的目录再读配置
    monkeypatch.setenv(config.ENV_HOME, str(target))
    settings = config.reload()
    assert settings.get("reader.page_height") == 30
    # The pre-rename cache default means "beside the data directory", not "~/.nr".
    # 老默认值应当被理解成"跟随数据目录"，而不是字面量的 ~/.nr
    assert config.cache_dir(settings) == target / "cache"


def test_migrate_legacy_data_dir_leaves_an_existing_target_alone(tmp_path: Path) -> None:
    # 新旧目录同时存在：不该做任何迁移
    legacy = tmp_path / ".nr"
    legacy.mkdir()
    (legacy / "settings.toml").write_text("old", encoding="utf-8")
    target = tmp_path / ".wreader"
    target.mkdir()
    (target / "settings.toml").write_text("current", encoding="utf-8")

    # 返回 None 表示"什么都没做"
    assert config.migrate_legacy_data_dir(target=target, legacy=legacy) is None
    # 旧目录还在，新目录内容没被覆盖
    assert legacy.is_dir()
    assert (target / "settings.toml").read_text("utf-8") == "current"


def test_migrate_legacy_data_dir_without_an_old_directory(tmp_path: Path) -> None:
    # 旧目录不存在：同样什么都不做
    assert (
        config.migrate_legacy_data_dir(
            target=tmp_path / ".wreader", legacy=tmp_path / ".nr"
        )
        is None
    )


def test_resolve_cache_dir_accepts_the_pre_rename_default(isolated_home) -> None:
    # 改名前的默认值同样表示"跟随数据目录"
    assert config.resolve_cache_dir(config.LEGACY_DEFAULT_CACHE_DIR) == (
        isolated_home.data / "cache"
    )
    assert config.resolve_cache_dir(config.DEFAULT_CACHE_DIR) == (
        isolated_home.data / "cache"
    )
    # 但 ~/.nr 下的其它路径就是普通路径，照常展开
    assert config.resolve_cache_dir("~/.nr/somewhere-else") == Path.home() / ".nr/somewhere-else"



def test_render_toml_writes_every_key_with_its_comment(isolated_home) -> None:
    text = config.load_config().as_toml()
    # 每一个 schema 里的键都应当在生成的文件里出现
    for path in config.all_paths():
        section, _, key = path.partition(".")
        assert "\n{} = ".format(key) in text, path
    # 浮点默认值写成 1 而不是 1.0
    assert "page_scroll_step = 1 " in text  # a float default reads as 1, not 1.0
    # 行尾注释也写了出来
    assert "# 每次翻页行数" in text
    # 文件以换行结尾
    assert text.endswith("\n")




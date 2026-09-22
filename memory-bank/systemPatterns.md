# System Patterns — 架构与关键设计

> 系统怎么搭的、关键设计模式、组件关系、容易踩的实现路径。最后更新：2026-09-22。

## 分层架构

```
                    ┌──────────────────────────────┐
  用户 ──命令──▶    │ cli.py    argparse + 子命令   │  ← 唯一对外入口（含 rich 渲染）
                    └───────┬──────────────────────┘
                            │ 调用纯函数式 API
        ┌───────────────────┼───────────────────┬──────────────┐
        ▼                   ▼                   ▼              ▼
   library.py          translator.py        vocab.py       stats.py
   导入/索引/搜索       后端+章节缓存        生词本         指标/热力图/成就
        │                   │                   │              │
        └───────────────────┴───────────────────┴──────────────┘
                            ▼
                       config.py            ← 数据目录、settings.toml、SCHEMA 驱动
                            ▼
                  ~/.wreader/{settings.toml, library.json, vocab.json, cache/}
                  ~/novels/<书名>_utf8.txt

  纯数据层之外的特例：
  reader.py ── curses 全屏前端（Pager + 绘制 + 按键），只在真 TTY 里跑
```

**核心分层约定**：除了 `reader.py` 的 curses 前端和 `cli.py` 的输出渲染，
其余模块都是**纯函数 + 普通数据**，不依赖终端、不依赖全局状态（除 `translator` 的
可注入后端与 `config` 的带戳缓存）。这让分页数学、章节边界、统计指标、成就条件都能脱离 TTY 测试。

## 模块职责与规模（2026-09-22 实测）

| 文件 | 行数 | 职责 | `__all__` |
| --- | --- | --- | --- |
| `wreader/__init__.py` | 18 | `__version__`、模块地图 | `["__version__"]` |
| `wreader/cli.py` | 1006 | argparse 定义 + 9 个子命令处理函数 | `["build_parser", "main"]` |
| `wreader/config.py` | 985 | settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁 | 30+ 个（`SCHEMA`/`DEFAULTS`/`Config`…） |
| `wreader/library.py` | 1077 | txt/epub 导入、编码识别、书名解析、索引、模糊搜索 | **无 `__all__`** |
| `wreader/reader.py` | 1948 | curses 分页阅读器：视图、搜索、书签、状态栏、绘制 | 10 个（`Pager`/`open_reader`…） |
| `wreader/stats.py` | 849 | 指标、热力图、连续天数、成就判定与庆祝动画 | 28 个 |
| `wreader/translator.py` | 1305 | Google/DeepSeek 后端 + 章节缓存 + 语言规范化 | 25 个 |
| `wreader/vocab.py` | 436 | 生词本增删查、复习、Anki 导出 | 14 个（含逐项中文注释） |
| `wreader/data/achievements.json` | — | 10 个成就定义（可被 `$WREADER_HOME` 覆盖） | — |

## 关键设计模式

### 1. SCHEMA 驱动配置（单一事实来源）
`config.py` 的 `SCHEMA` 是 `section -> ((key, default, comment), ...)` 的表。它同时决定：
- **默认值**（`DEFAULTS` 按 section 嵌套、`DEFAULT_FLAT` 按点号路径）
- **类型**（`coerce_value` 用 `type(default)` 推断该键该是 int/float/bool/str）
- **写文件顺序**与**行尾注释**（`COMMENTS`）

加一个设置项 = 在 `SCHEMA` 加一行，其余自动生效。

### 2. 行号坐标系统一
`library.py` 与 `reader.py` 共用同一套坐标：`normalise_newlines(text).split("\n")` 的下标。
- `progress.current_line`、`bookmarks[].line`、`chapters[].line_start`、`sessions[].lines_read`
- 翻译缓存 `load_chapter_map()` 的键也是这个行号

**任何读写正文的地方都必须先 `library.normalise_newlines()`**，否则行号会错位。

### 3. 可注入后端 + 纯函数翻译管线
`translator.set_backend(x)` 给测试注入假的 `TranslatorCallable`；`None` 表示用配置里的真后端。
管线全程是纯函数：`paragraph_spans` → `paragraph_texts` → `translate_paragraphs` → `map_paragraphs` → `Pager.translations`。
所以"段落切分/合并"能完全离线测试，只有 `make_backend()` 之后才碰网络。

### 4. 视图层与数据层分离（Pager）
`Pager` 是一个**数据对象**：位置、视图模式、搜索命中、书签、计时、译文字典。
- `rows_for(index)` 决定"一个源行在该视图下显示成哪些行"
- `visible_rows(height, width=None)` 决定"这一屏填哪些行"（给了 width 会按显示宽度折行）
- `_draw` 只负责画，`handle_key` 只负责改 `Pager` 状态
=> 分页/视图逻辑可脱离 curses 测试（`tests/test_reader.py` 从来不启动真终端）。

### 5. 显示宽度工具（终端 CJK 的唯一正确做法）
| 函数 | 作用 |
| --- | --- |
| `_char_width(ch)` | 东亚 Wide/Fullwidth → 2 列，其余 1 列（`unicodedata.east_asian_width`） |
| `_text_width(text)` | 整串占几列 |
| `_clip_line(text, room)` | 按列裁，绝不劈开全角字符 |
| `_pad_line(text, room)` | 裁到 room 列后再补空格到**正好** room 列（擦掉上一帧残影） |
| `_wrap_line(text, width)` | 按列折行：英文在空格处断（不劈单词）、汉字逐字断、Tab 展开、行尾空格丢弃、空行保留一行 |

**所有宽度判断都必须走这几个函数，禁止 `len()`。**

### 6. 失败可恢复 / 绝不崩阅读
- 单个坏文件 → 进 `import` 的 `failed` 列表，不中止整批
- 生词本、成就定义损坏 → 只 `say()` 一句提示
- 翻译失败 → `TranslationError` / `TranslationUnavailable` → 消息行提示
- 索引写不进 → `save_position()` 返回 `False`，下次自动保存再试
- 章节缓存缺失 → 回落到逐段翻译，不影响阅读

## 关键实现路径（改动时必看）

| 场景 | 调用链 |
| --- | --- |
| 导入一本书 | `cli.cmd_import` → `library.import_books` → `load_source_text`（编码识别/EPUB）→ `write_utf8_text` → `build_record` → `save_library` |
| 打开阅读器 | `cli.cmd_read` → `reader.open_reader` → `read_lines`（保持行号一致）→ `Pager(...)` → `curses.wrapper(_run)` → `_run` 首行 `_init_colors()` |
| 画一帧 | `_run` → `_draw` → `Pager.visible_rows(rows, width-1)` → 逐行 `_draw_text` → `_draw_status` → `refresh` |
| 翻页 | `handle_key` → `Pager.next_page/scroll` → `move_to` → `_sync_chapter`（章节计时滚动） |
| 退出落库 | `open_reader` → `save_session` → `_write_position` + `accumulate_stats` + `bump_translations` → `save_library` |
| 成就解锁 | `_celebrate_achievements` → `stats.check_achievements` → `evaluate_condition`（表达式）→ `stats.celebrate` |

## 值得记住的坑（血泪）

1. **curses `addstr` 越界会抛 `curses.error`**。早期用 `except curses.error: pass` 吞掉它，
   结果是**整行文字静默消失**（不是截断）。现在 `_addstr` 先 `_clip_line` 到可用列数再写。
2. **`start_color()` 单独调用会把默认配色锁成白底黑字**。要背景透明必须
   `start_color()` **紧跟** `use_default_colors()`，且都在 `initscr()` 之后（即 `_run` 内）。
3. **`A_REVERSE` 用于状态栏、`A_DIM` 用于消息行与书签位**：开了颜色后依然正常，
   因为全程只用属性位、不 `init_pair()`。
4. **折行后一个源行会占多条屏幕行**，所以书签 `★` 只在"某源行的第一行"画，
   `_draw` 用 `previous_index` 判断。
5. **写满整行的英文单词不要被推到下一行**：`_wrap_line` 里"溢出的字符本身是空格"时
   不回头找更早的空格（否则第一行会白空一大截）。
6. **curses 右下角最后格写入受限**：所以状态栏 `room = width - 1`，永远留出最后一列。

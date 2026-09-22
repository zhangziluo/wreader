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
| `wreader/config.py` | 989 | settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁 | 30+ 个（`SCHEMA`/`DEFAULTS`/`Config`…） |
| `wreader/library.py` | 1077 | txt/epub 导入、编码识别、书名解析、索引、模糊搜索 | **无 `__all__`** |
| `wreader/reader.py` | 2287 | curses 分页阅读器：视图、搜索、书签、状态栏、绘制、滚轮/触摸 | 11 个（`Pager`/`open_reader`…） |
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
- **屏顶坐标 = `(position, line_offset)`**：`position` 是源行号（与落库坐标一致），
  `line_offset` 是这一行里已经翻过去的**折行屏幕行数**（纯显示态，**不落库**）
- `rows_for(index)` 决定"一个源行在该视图下显示成哪些行"；`_row_texts(index, width)` 把它摊平成屏幕行
- `visible_rows(height, width, offset)` 决定"这一屏填哪些行"（含折行与段内偏移）
- `_walk_forward(start, offset, budget, width)` 是分页的核心：返回 `(这一屏的行, 下一屏的屏顶坐标)`
- `next_top` / `previous_top` 按屏幕行预算算出下一屏 / 上一屏的 `(行, 段内偏移)`
- `viewport_rows` / `viewport_width` 由 `_draw` **每帧**按真实终端填入
- `move_to(line, offset=0)`：goto / 搜索 / 章节 / 首尾跳转一律回到**行首**（offset 归零）
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
| 翻页 | `handle_key` → `Pager.next_page/previous_page` → `next_top/previous_top(page_budget, viewport_width)` → `move_to(行, 段内偏移)` → `_sync_chapter`（章节计时滚动）。`page_budget = round(page_scroll_step × viewport_rows) − page_overlap`，单位是**屏幕行**；屏顶坐标是 `(position, line_offset)` |
| 鼠标/触摸 | `_run` 首行 `_enable_mouse()`（`mouseinterval(0)` + `mousemask`）→ `get_wch` 返回 `KEY_MOUSE` → `_mouse_event_delta` → `curses.getmouse()` → `_mouse_scroll_delta`（滚轮按 `wheel_scroll_step`、拖动按手指位移）→ `Pager.scroll` |
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
7. **触摸拖动必须先把 `curses.mouseinterval` 设成 0**：默认的"点击 / 双击 / 三击判定窗口"
   会把**按下事件扣住**，于是拖动状态来不及建立，随后来的位置报告全被当成普通移动丢掉 ——
   现象就是"拖动完全没反应"。**单测发现不了**，只有在真 pty 里灌鼠标序列才暴露
   （见 `tools/verify_mouse.py`，它就是为了守这个 bug 才写的）。
8. **别指望 ncurses 都有 BUTTON5**：实测 macOS 这套 Python 的 curses 里**没有任何 `BUTTON5_*` 常量**，
   灌 button5（滚轮下）只会得到一个位置报告。所以代码**不做位猜测** ——
   猜出来的 `_WHEEL_UP << 6` 恰好等于 `BUTTON_SHIFT`，会把 shift+点击误判成滚轮。
   拿不到常量的平台就是"滚轮下不生效"，宁可少一个方向也不要误判。
9. **拖动的 button 位会被终端丢掉**：SGR 的 motion 事件到这里只报
   `REPORT_MOUSE_POSITION`（0x8000000），**不带** `BUTTON1_PRESSED`。所以"是否正在拖动"
   只能用自己的状态机维护（见过按下 → 见过抬手之间），不能直接看 bstate 的按键位。
10. **测鼠标必须用 `TERM=xterm-1006`**：macOS 的 `xterm-256color` terminfo 没有 `XM` 能力，
    curses 只开 `?1000h`，SGR 序列会被当成普通按键收进来 —— 测出来的"失败"是假的。
11. **翻页必须按「屏幕行」算，不能按「文本行」**：长段落没有换行，在终端里被折成多行，
    所以"一屏"对应的文本行数是变的。翻页走 `page_budget = round(page_scroll_step × viewport_rows) − page_overlap`
    （单位屏幕行，`page_overlap` 默认 3），再由 `next_position` / `previous_position` 用
    `visible_rows`（= 已有的正确折行）换算成源行号。
    ⚠️ **绝不能**用 `ceil(len(text) / width)` 这类字符数近似：汉字占 2 列，`len()` 会把折行算错，
    而且会劈开英文单词、无视双语视图的多行。这是 `_wrap_line` 存在的唯一理由，必须复用。
    ⚠️ `tools/verify_mouse.py` 键盘基准是 **pty 真实高度**（40 行 → 正文区 38 行 → `j` 走 38−3=35 行），
    不是 `page_height`；各项期望值**顺序累积**，改翻页逻辑 / 重叠 / pty 尺寸都要全部重算。
    滚轮 / 触摸拖动走 `scroll(±wheel_scroll_step)` 逐行走，**不经过翻页路径**，不受影响。
    ⚠️ **屏顶必须是 `(源行号, 段内偏移)` 两元组**：只记源行号 → 一屏中途被折行截断的那半截
    会在下一页被跳过（`position` 一加就丢掉这一行剩下的折屏行）。所以 `Pager.line_offset`
    记着"这一行里已经翻过去几条折屏行"，`visible_rows` 从它开始画；
    `next_top`/`previous_top` 返回的都是这个两元组。
12. **段内偏移是显示态、绝不落库**：`progress["current_line"]` 永远只写源行号，
    否则书签 / 章节 / 翻译缓存共用的「行号坐标唯一」约定就被破坏。代价是重开书时从行首开始
    （会重看一小段半截行）—— 这是刻意的取舍，不是遗漏。
    另外**窗口变宽会让折屏行变少**，旧偏移可能越界：`_walk_forward` 会把偏移夹到
    「这一行的最后一条」，`visible_rows` 还有一层「offset 一条都取不出来就退回行首」的兜底 ——
    少了这两层会画出**空白屏**。

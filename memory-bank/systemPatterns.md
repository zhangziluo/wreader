# System Patterns — 架构与关键设计

> 系统怎么搭的、关键设计模式、组件关系、容易踩的实现路径。最后更新：2026-09-23。

## 分层架构

```
                    ┌──────────────────────────────┐
  用户 ──命令──▶    │ cli.py    argparse + 子命令   │  ← 唯一对外入口（含 rich 渲染）
                    └───────┬──────────────────────┘
                            │ 调用纯函数式 API
        ┌───────────────────┼───────────────────┬──────────────┐
        ▼                   ▼                   ▼              ▼
   library.py          translator.py        vocab.py       stats.py
   导入/索引/搜索       引擎适配+章节缓存    生词本         指标/热力图/成就定义
        │                   │                   │              │
        └───────────────────┴───────────────────┴──────────────┘
                            │  ✔ 事件（daily_open / session_end / book_add …）
                            ▼
                    achievements.py         ← 记事件 + 判解锁 + 写状态
                            │
                            ▼
                       notes.py             ← 笔记 markdown + 派生索引 + 草稿
                            │
                            ▼
                        lock.py             ← 两者共用：flock 串行化 + 原子替换
                            ▼
                       config.py            ← 数据目录、settings.toml、SCHEMA 驱动
                            ▼
                  ~/.wreader/{settings.toml, library.json, vocab.json,
                              achievements.json, notes/, cache/}
                  ~/novels/<书名>_utf8.txt

  纯数据层之外的特例：
  reader.py ── curses 全屏前端（Pager + 绘制 + 按键），只在真 TTY 里跑

  翻译引擎是可插拔的一层，挂在 translator.py 下面：
  translator.py ──▶ translate/__init__.py ──▶ base.py（Translator ABC）
                                              ├── google.py / baidu.py / youdao.py
                                              ├── tencent.py / deepseek.py / local.py

  成就的两条"探测"支线（都只在 reader.py 的开书路径上各调一次）：
  reader.py ──▶ env.py   ← 纯读环境变量 / platform.release() / direct_url.json
                geo.py   ← ip-api（一小时缓存，可注入 fetcher，离线返回空）
```

**核心分层约定**：除了 `reader.py` 的 curses 前端和 `cli.py` 的输出渲染，
其余模块都是**纯函数 + 普通数据**，不依赖终端、不依赖全局状态（除 `translator` 的
可注入后端与 `config` 的带戳缓存）。这让分页数学、章节边界、统计指标、成就条件都能脱离 TTY 测试。

## 模块职责与规模（2026-09-23 实测）

| 文件 | 行数 | 职责 | `__all__` |
| --- | --- | --- | --- |
| `wreader/__init__.py` | 19 | `__version__`、模块地图 | `["__version__"]` |
| `wreader/achievements.py` | 1145 | **事件驱动成就引擎**：状态文件、事件累加、解锁判定、字数去重、**实时门槛（`metric_thresholds`/`crossed_thresholds`）与基线（`session_metrics`）** | 26 个（`check_achievements`/`record_event`/…） |
| `wreader/cli.py` | 1510 | argparse 定义 + 子命令处理函数（含 `toc`、`notes`、`config translate` 向导、`werd werd` 彩蛋） | `["build_parser", "main"]` |
| `wreader/config.py` | 1008 | settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁 | 30+ 个（`SCHEMA`/`DEFAULTS`/`Config`…） |
| `wreader/env.py` | 183 | **环境探测**：云主机 / WSL / tmux / 可编辑安装（四个输入全部可注入） | 8 个（`detect`/`flags`/`SIGNAL_NAMES`…） |
| `wreader/geo.py` | 343 | **地理位置**：ip-api 查询 + 一小时缓存 + 国家→大洲 + 世仇组合；注入式 fetcher、离线降级 | 14 个（`load_location`/`continent_of`/`feud_hit`…） |
| `wreader/library.py` | 1159 | txt/epub 导入、编码识别、书名解析、索引、模糊搜索、最近在读 | **无 `__all__`** |
| `wreader/lock.py` | 81 | **跨进程文件锁**（POSIX `flock`；Windows 退化为"只有原子替换"） | 3 个 |
| `wreader/notes.py` | 786 | **笔记存储**：每本书一个 markdown + 派生索引 + 崩溃草稿 + 章节/译文元数据 | 21 个 |
| `wreader/reader.py` | 4478 | curses 分页阅读器：视图、搜索、书签、状态栏、绘制、滚轮/触摸、目录浮层、标记/笔记、译文弹窗、**帮助页、成就通知、中断恢复** | 17 个（`Pager`/`open_reader`…） |
| `wreader/stats.py` | 785 | 指标、热力图、连续天数、**成就定义加载**与庆祝动画 | 27 个 |
| `wreader/toc.py` | 474 | 目录：章节提取、epub nav/ncx 解析、百分比、可重建缓存 | 10 个 |
| `wreader/translator.py` | 1199 | 章节缓存 + 分批 + 段落映射 + 语言规范化 + 引擎适配（`EngineBackend`） | 26 个 |
| `wreader/vocab.py` | 436 | 生词本增删查、复习、Anki 导出 | 14 个（含逐项中文注释） |
| `wreader/translate/base.py` | 151 | `Translator` ABC：`translate()` 契约、凭证/可选包检查、语言码映射 | 3 个 |
| `wreader/translate/google.py` | 92 | Google（deep-translator，免密钥，默认引擎） | 2 个 |
| `wreader/translate/baidu.py` | 155 | 百度通用翻译 API V2（MD5 签名） | 2 个 |
| `wreader/translate/youdao.py` | 179 | 有道智云 v3（SHA-256 签名 + `truncate`） | 3 个 |
| `wreader/translate/tencent.py` | 240 | 腾讯云 TMT（TC3-HMAC-SHA256） | 4 个 |
| `wreader/translate/deepseek.py` | 221 | DeepSeek chat completions + SSE 解析 | 5 个 |
| `wreader/translate/local.py` | 129 | 本地 Argos Translate（惰性导入） | 3 个 |
| `wreader/translate/__init__.py` | 150 | 引擎注册表 + 工厂（`make_engine`/`engine_from_settings`/`available_engines`） | 13 个 |
| `wreader/data/achievements.json` | 348 | **48 个**成就定义（可被 `$WREADER_HOME` 覆盖） | — |

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

### 6. 可插拔翻译引擎（注册表 + 适配器）
`wreader/translate/` 是一个**自洽的小包**：
- `base.Translator` 只要求实现**一个**方法 `translate(text, from_lang, to_lang) -> str`，
  外加三个可选声明：`required_credentials`（缺了就没法用，前端据此提示）、
  `credential_keys`（这个引擎读 `[translate]` 里的哪些键）、`requires_package`（可选第三方包）。
- `__init__.ENGINES` 是**唯一的注册表**：`{"google": GoogleTranslator, ...}`。
  加厂商 = 一个模块 + 一行登记，**配置向导与 `available_engines()` 都会自动跟着变**。
- **这个包不 import `config` / `translator`**：凭证由调用方以普通 dict 传进来。
  这样既没有循环导入，也让工厂能被单测直接驱使。
- 关键错误语义：`TranslateError`（单次失败，比如签名错）与
  `TranslateUnavailable`（连不上）分开 —— `translator.EngineBackend` 把它们分别映射成
  `TranslationError` / `TranslationUnavailable`，而**后者决定整本书是"立即中止"还是"继续下一章"**。
- 每个引擎都把"请求构造"（签名 / 规范请求串 / 请求体）做成**纯方法**，只留**一个**模块级
  `_http_get` / `_http_post` 作为网络接缝。于是"签名对不对"能离线断言，
  "请求真的发出去了吗"也能用替身断言。

### 7. 失败可恢复 / 绝不崩阅读
- 单个坏文件 → 进 `import` 的 `failed` 列表，不中止整批
- 生词本、成就定义损坏 → 只 `say()` 一句提示
- 翻译失败 → `TranslationError` / `TranslationUnavailable` → 消息行提示
- 索引写不进 → `save_position()` 返回 `False`，下次自动保存再试
- 章节缓存缺失 → 回落到逐段翻译，不影响阅读

### 8. 成就：事件驱动 + 单一解锁存储（`achievements.py`）
- **唯一解锁存储**是 `<data dir>/achievements.json`（不是 `library.json`）。旧版本写在
  `library.json` 的 `achievements.unlocked` 里，**第一次读状态时自动迁移一次**，
  之后那里的旧内容不再被读（`stats.unlocked_ids(document)` 只留给迁移与兼容测试）。
- **唯一入口**是 `achievements.check_achievements(event_type, data)`：记事件 → 算指标 →
  逐条判定 → 写回。事件名被 `EVENTS` 白名单校验，写错立刻抛 `AchievementsError`（绝不静默丢事件）。
- **条件是表达式**（`"words_read >= 10000"`），指标 = `stats.compute_metrics(document)`
  ∪ 状态派生指标（`words_read`/`days_opened`/`early_open`/`weekend_time`/`library_books`）。
  加一条成就 = 往 `data/achievements.json` 加一行，代码不用动。
- **字数按行号区间去重**：`Pager.read_ranges` 在 `move_to()` 里记下每次"向前"走过的
  `[起点, 终点)`；退出时整段交给引擎，引擎只统计"没统计过的那些行"（`uncovered_words`），
  并把区间并进 `books[id].counted`。所以同一页读两遍不会重复累加。
- **文件锁**：读-改-写整个包在 `_file_lock()`（POSIX `flock`；Windows 无 `fcntl` →
  退化成"只有原子替换"）。写盘一律 `mkstemp` + `os.replace`。
- **容错姿态**：状态文件坏 → 改名成 `achievements.json.broken` 再从空状态开始；
  定义文件坏 / 指标写错 → 只是"这次不判定"，绝不让阅读或命令失败。

### 9. 笔记：markdown 为源 + 派生索引 + 崩溃草稿（`notes.py`）
- **存储**：`<data dir>/notes/<book_id>.md`，一本书一个文件，第一次写时落文件头
  （`# 书名` / `书籍ID:` / `创建时间:`），之后每一条 `## 笔记 #N — YYYY-MM-DD HH:MM` **只追加**。
- **`index.json` 是派生缓存**：书名 / 条数 / 最后修改 / 预览。`count` 由 `.md` 里的小节**数出来**
  （不是盲目 `+1`），`list_all_notes()` 每次都从 `.md` 重建并回写，所以手改文件也不会让索引说谎。
- **崩溃草稿**：编辑区每 30 秒把"还没提交的内容"写进 `<book_id>.draft.md`。`Esc` = 提交成正式笔记
  （并删草稿），`Ctrl-C` = 只留草稿。下次打开面板自动捞回来 → **掉电/崩溃一个字都不丢**。
- **一个锁管一个目录**：`save_note` 的"追加 + 刷新索引"都在 `file_lock(index_file())` 里
  （`index.json.lock`）。一次只拿一把锁，避免了"笔记文件 → 索引"这种锁顺序问题。
- **CLI 分页只在两端都是 tty 时等按键**（`_paging_is_interactive`），否则 `werd notes <id> | less`
  会永远挂着（详见坑 #31）。

### 10. 成就的实时门槛：读者攒数、引擎只在越线时被叫醒（Phase 2）
一次 `check_achievements()` = 文件锁 + 整个状态文件重写 + 读一遍书库索引，
**按一次键就写一次盘绝对不行**。所以拆成两半：

- **引擎侧（纯函数，可单测）**：`metric_thresholds(definitions)` 把定义里的条件解析成
  `{指标: (门槛, ...)}`；`session_metrics()` 给出"现在各项指标是多少"（阅读器的基线）；
  `crossed_thresholds(values, thresholds, fired)` 回答"有哪些线刚刚被越过"。
- **阅读器侧（只读内存）**：`Pager.note_key/note_chapter_change/note_width` 累加自己的计数；
  `_achievement_tick()` 每次按键/换尺寸调一次，**没越线就直接返回**（零 I/O）；
  越线才把 `{"deltas", "maxima"}` 交给引擎，并把 `(指标, 门槛)` 记进 `Pager.fired` 防止重复触发。
- **不丢数据**：增量在**真的发出去之后**才推进水位（`Pager.commit_report`），
  引擎报错就原地留着下次再报；会话结束时 `session_end` 把余下的计数一次交账。
- **基线预标记**：开书时把"基线就已达标"的门槛全部塞进 `fired`，
  否则早就解锁的成就会在第一次按键时白写一次状态文件。

### 11. 两条"探测"支线：可注入 + 离线是正常状态（Phase 3）
`geo.py`（位置）与 `env.py`（环境）都遵守同一套形状：

- **输入全部可注入**：`geo.fetch(fetcher=...)` / `load_location(fetcher=..., now=..., allow_fetch=...)`；
  `env.detect(env=..., release=..., direct_url=...)`。所以测试既不联网也不看本机。
- **失败不是异常而是"空"**：`load_location()` 返回 `{}`、`fetch()` 永不抛、
  `env.detect()` 永远返回四个 bool。调用方只需 `if not location: 啥也不记`。
- **缓存 + 降级**：`geo.json` 一小时有效；过期后查询失败就**退回旧数据**，
  再不行才返回空。`stats.geo_lookup = false` 时一步网络都不发。
- **只上报事实**：`reader._probe_achievements()` 把结果原样交给引擎，
  引擎侧 `_record_geo` / `_record_env` 只做"去重入库 + 算世仇组合"。

### 12. 意外中断的现场标记（`reading_session.json`）
- 进阅读器时 `write_marker()` 写"我正在读这本书"（书 id / 行号 / 段内偏移 / 一行预览 / 时间 / pid），
  `save_position()` 每次自动保存顺手刷新，**正常退出**时 `clear_marker()` 删掉。
- 下次开书：`read_marker()` 拿到现场 → **只有 `book_id` 对得上**才交给 `Pager.resume_marker` →
  `_run` 开头问一句 → `y` 回现场（`move_to(position, offset)`）、其他键从头开始。
- ⚠️ 位置的**权威**始终是 `library.json` 的 `progress.current_line`；现场只是"要不要问一句"的依据，
  丢了顶多少问一次（写一半被 kill 的现场会被当作不存在）。

## 关键实现路径（改动时必看）

| 场景 | 调用链 |
| --- | --- |
| 导入一本书 | `cli.cmd_import` → `library.import_books` → `load_source_text`（编码识别/EPUB）→ `write_utf8_text` → `build_record` → `save_library` |
| 打开阅读器 | `cli.cmd_read` → `reader.open_reader` → `read_lines`（保持行号一致）→ `Pager(...)` → `curses.wrapper(_run)` → `_run` 首行 `_init_colors()` |
| 继续上次的书 | `cli.cmd_continue` → `library.recent_books(limit=3)`（按 `progress.last_read` 倒序，跳过从没读过的书）→ `_book_table` 打印 id，抄给 `werd read` |
| 选翻译引擎 | `translator.load_settings()`（读 `[translator]` + `[translate]`）→ `TranslatorSettings.resolved_engine()`（空则回退 `[translator].backend`）→ `translate.make_engine(name, credentials)` → `translator.EngineBackend` |
| 翻译一段文字 | `Pager.translate_screen` → `translator.paragraph_spans` / `translate_paragraphs` → `get_backend()` → `EngineBackend.translate`（映射异常）→ `translate/<engine>.translate`（引擎内 `_http_get`/`_http_post` 是唯一网络接缝）→ `map_paragraphs` 回填行号 |
| 阅读器按 `t` | `handle_key` → `_translate_screen` → `_translation_ready()`（`translator.engine_ready`）→ `Pager.translate_screen(first, last, target=...)` → `_screen_translation_text` → `_show_translation_popup`（`_sub_window` + `TRANSLATION_POPUP_SECONDS` 轮询，未配置则只 `say()` 提示） |
| 配置翻译引擎 | `werd config translate` → `cmd_config` 特判 → `cmd_config_translate` → `_choose_translate_engine`（`translate.engine_names` / `ENGINE_LABELS`）→ `_ask_engine_credentials`（`translate.credential_keys` + `config.COMMENTS` 当提示语）→ `_save_translate_settings` → `engine_ready()` 自查 |
| 画一帧 | `_run` → `_draw` → `Pager.visible_rows(rows, width-1)` → 逐行 `_draw_text` → `_draw_status` → `refresh` |
| 翻页 | `handle_key` → `Pager.next_page/previous_page` → `next_top/previous_top(page_budget, viewport_width)` → `move_to(行, 段内偏移)` → `_sync_chapter`（章节计时滚动）。`page_budget = round(page_scroll_step × viewport_rows) − page_overlap`，单位是**屏幕行**；屏顶坐标是 `(position, line_offset)` |
| 鼠标/触摸 | `_run` 首行 `_enable_mouse()`（`mouseinterval(0)` + `mousemask`）→ `get_wch` 返回 `KEY_MOUSE` → `_mouse_event_delta` → `curses.getmouse()` → `_mouse_scroll_delta`（滚轮按 `wheel_scroll_step`、拖动按手指位移）→ `Pager.scroll` |
| 退出落库 | `open_reader` → `save_session` → `_write_position` + `accumulate_stats` + `bump_translations` → `save_library` |
| 目录浮层跳转 | `handle_key`（`Tab`）→ `_jump_via_toc` → `_toc_overlay`（模态循环：`_draw_toc` + `toc.filter_toc` + `_toc_move_cursor`）→ `Pager.move_to(line)` |
| 目录缓存 | `open_reader` → `toc.load_toc`（命中缓存即返回；否则 `_read_lines` → `build_toc` / `build_toc_from_epub` → `save_toc`）；epub 另在 `library.import_books` 里 `_cache_epub_toc` → `toc.save_toc` |
| 标记选字 | `handle_key`（`m`，此后 `pager.mark_mode` 走 `_handle_mark_key`）→ `_enter_mark` / `_mark_move`（作用于 `Pager.viewport` 的纯函数）；高亮在 `_draw` → `_mark_row_span` + `_draw_marked_row`（`A_REVERSE`）；`y` → `_copy_selection` → `_mark_selection` → `Pager.note_buffer` |
| 笔记面板（写一条） | `handle_key`（`o`）→ `_note_panel`（模态循环，200ms 节拍：`_draw_note_panel` + `_draw_quote`；逐键 `_note_validate` → `Textbox.do_command`；`Tab` 切 `note_focus`；`Ctrl+S` → `_save_note` → `_commit_note` → `notes.save_note` 落盘 markdown；`Esc` = 提交、`Ctrl-C` = 留草稿）；子窗口由 `reader._sub_window()` 建 |
| 笔记草稿 | 面板每 30 秒（`NOTE_AUTOSAVE_SECONDS`）→ `_autosave_draft` → `notes.save_draft`；关面板 `_finish_note_panel`（提交或留草稿）；重开面板 `_restore_draft`（ASCII 正文填编辑区、中文正文交回调用方直接落盘） |
| 成就解锁 | `cli.main` / `cmd_import` / `open_reader` → `achievements.check_achievements(事件, 数据)` → `record_event` → `compute_metrics`（`stats.compute_metrics` ∪ 状态指标）→ `stats.evaluate_condition` → 写 `achievements.json` → `_celebrate_achievements` → `stats.celebrate` |
| 阅读中实时判定 | `handle_key` → `Pager.note_key`（或 `KEY_RESIZE` → `Pager.note_width`）→ `_achievement_tick` → `achievements.crossed_thresholds`（纯内存）→ 越线才 `_fire_event` → `check_achievements("key"/"resize")` → `_announce_unlocks` → `Pager.announce` → 下一帧 `_draw` → `_draw_notice` |
| 换章结算 | `Pager.move_to` / `sync()` → `_sync_chapter` → `Pager.note_chapter_change`（方向键怀旧 / 窄屏挑战）→ 下一帧的 `_achievement_tick` 交账 |
| 帮助页 | `handle_key`（`?`）→ `_help_overlay` → `_fire_event("help")` → `help_lines` / `_help_layout` / `_draw_help`（模态循环，`finally` 里恢复 `_TICK_MS`） |
| 意外中断恢复 | `open_reader` → `read_marker`（book_id 对得上才用）→ `Pager.resume_marker` → `_run` → `_offer_recovery` → `_confirm(hint=_RECOVER_HINT)` → `Pager.move_to` + `_fire_event("recover")`；`open_reader` 收尾 `clear_marker` |
| 环境 / 位置探测 | `open_reader` → `_prepare_achievements`（门槛 + 基线 + 预标记）→ `_probe_achievements("env", {"flags": env.flags()})` → `_probe_geo(pager, settings)` →（`geo.load_location` 命中缓存就不联网）→ `_probe_achievements("geo_change", location)` |
| 名字彩蛋 | `cli.main`（`--werd`）或 `_HANDLERS["werd"/"word"]` → `_word_egg(name)` → `_record_achievements("name_egg", {"egg": name})` |
| 笔记 CLI | `cmd_notes` → `notes.list_all_notes`（清单）/ `notes.load_notes` + `_page_notes`（翻看）/ `notes.export_notes`（导出） |
| 终端流控 | `_run` → `_disable_flow_control()`（POSIX 用 `termios` 清 `IXON|IXOFF`，让 `Ctrl+S` 到得了程序；`endwin()` 负责还原） |

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
13. **目录浮层写到右下角会让整行消失**：面板**最后一行**必须只填 `panel - 1` 列 ——
    `_addstr` 撞上 curses「不能写右下角」的限制后会静默 `pass`，那一行就**整行不见**。
    非最后一行的最右列是安全的（状态栏早就在用 `room = width - 1` 规避这个）。
14. **ncx 的 `navPoint` 是嵌套结构**：`point.iter()` 会把子 `navPoint` 的 `<text>` / `<content>`
    也算到父节点上 → 标题重复。只取**直接子节点**（`list(point)`）。
15. **epub 的 nav 行号只在内置提取器路径上成立**：`extract_epub_builtin` 是把各 spine 文档用 `\n`
    拼起来的，"每份文档的起始行"可算；换成外部 `ebook-convert`，正文布局完全不同。判据是
    「spine 布局总行数 == 正文行数」，不符就退回正则 —— 宁可标题退化，也不给错行号（错行号比没有更糟）。
16. **`curses.window` 对象没有 `newwin` 方法**：只有模块级的 `curses.newwin`（窗口对象上对应的是 `derwin`）。
    第一版写成 `stdscr.newwin(...)`，`FakeStdscr` 恰好也实现了 `newwin` → **单测全绿**，
    真 pty 里立刻 `AttributeError: '_curses.window' object has no attribute 'newwin'`。
    现在走 `reader._sub_window()`（生产 `curses.newwin`、测试 monkeypatch 成假窗口），见 `tools/verify_notes.py`。
    **教训：假窗口实现得越像真 curses，越容易掩盖真 API 的差异 —— UI 改动必须过一遍真 pty。**
17. **画叠窗要"主窗口先刷、子窗口后刷"**：`stdscr.erase()` 会把子窗口覆盖的那几行**一起标脏**，
    顺序反了就会被主窗口的空白格擦掉。`_draw_note_panel` 里 `stdscr.refresh()` 在前，
    `quote_win.refresh()` / `edit_win.refresh()` 在后。
18. **`Ctrl-S` 会被终端行规程吃掉**：`curses.wrapper` 只调 `cbreak()`，`IXON` 仍开着 →
    终端把 `Ctrl-S`（XOFF）当流控吞掉，面板的保存键永远到不了程序。要么自己清 `IXON`
    （`_disable_flow_control()`），要么别把保存键放在 Ctrl-S 上。**单测不经过行规程，只有真 pty 能验。**
19. **构造参数的默认值会把"凭证回退"短路**：`TencentTranslator(region=DEFAULT_REGION)` 里
    `region or self.credential("tencent_region", ...)` 永远走左边 → 配置里的地域永远读不到。
    参数默认值要留**空串**，让"关键字参数 > 凭证表 > 默认值"这个优先级在函数体里正常生效。
    （同类坑：任何 `x or fallback` 只要 `x` 有非空默认值，fallback 就是死代码。）
20. **`check_doc_numbers.py` 只认 `wreader/<文件名>`**：子包里的同名文件（`translate/__init__.py`
    与包根的 `__init__.py`）会被错算到包根那份上，报出莫名其妙的 FAIL。
    所以 README 里的**子包条目不写"（N 行）"**，行数记在 `techContext.md`。
21. **`editor` 工具超长替换会"假成功"**：一次 ~5900 字符的替换返回"File created successfully"，
    实际却在**仓库根**留下一个野生 `cli.py`（目标文件只改了一半）。迷惑点在于
    `grep 新函数名` 找不到、`pyright` 依然 0 报错（根目录不在 `[tool.pyright] include` 里）。
    **对策：单次替换保持 <6000 字符、改完立刻 `grep` 确认、收尾 `git status` 扫一眼有没有怪文件。**
22. **测试替身必须复刻真函数的语义**：被 monkeypatch 掉的 `cli._prompt_line` 一开始直接返回队列里的
    空串，漏掉了真函数"空输入 = 用默认值"的行为，于是"回车保留当前引擎"这条路径**静默失去覆盖**
    （向导把空串当成不认识的名字而取消）。替身要照着真函数的契约写。
23. **`params()` 是厂商专有的，不在 `Translator` 基类上**：只有 `BaiduTranslator` /
    `YoudaoTranslator` 定义了它，`translate/base.py` 的契约里只有 `translate()` 与 `pause()`。
    所以把引擎变量注解成（或被推断成）基类 `Translator` 之后再调 `.params()`，静态检查会报
    「无法访问类 Translator 的属性 params」。写法：**直接构造具体类**，或对 `make_engine()`
    的返回值用 `isinstance` 收窄。`make_engine()` 声明返回基类类型是**故意**的（它要能返回六家
    引擎），别为了让临时脚本好写就把 `params` 提到基类 —— 那会变成"每个引擎都得实现"的假契约。
24. **`daily_open` 每次启动都触发 → 与"跑测试的时刻"耦合**：`cli.main()` 一进来就记
    `daily_open`，所以测试若恰好在北京时间 05:00-07:00 跑，`early_bird` 会**自己解锁**，
    `assert "已解锁 0/28"` 当场翻车。对策：`cli._now()` 是**注入缝**，测试把它换成固定中午。
    凡是"依赖当前时刻/日期"的新事件，都要留这种缝，否则测试会变成按钟点随机失败。
25. **成就的"解锁"只能有一个写入路径**：权威存储是 `<data dir>/achievements.json`。
    曾经的两套（`stats.check_achievements` 写 `library.json`）会造成"到底谁说了算"，
    所以那个函数**已删除**（连同它的 6 个测试）；`stats` 只保留**定义加载**与指标计算。
    新增解锁逻辑时不要再往 `library.json` 写。
26. **`_normalise_state` 里的行区间必须统一成 `list[list[int]]`**：`merge_ranges()` 返回
    tuple，直接塞进 state 会让"内存形状"与"JSON 形状"不一致 → 读回来 `==` 断言永远失败
    （本次实测：`[(0, 2)] != [[0, 2]]`）。**同一份数据只允许一种表示**。
27. **不要为了跨平台在模块顶部 `import msvcrt`**：pyright 在 macOS 上会报"无法解析"。
    `_lock_file()` 的做法是**局部** `import fcntl` + `except ImportError: return False`，
    Windows 侧退化成"只有原子替换"，这个取舍写进了函数 docstring 与 README。
28. **条件里的指标名必须真实存在**：写成 `condition: "book_adds >= 1"`（指标拼错）时，
    `parse_condition` 不报错、进程不崩，但那条成就**永远解锁不了** —— 静默失效最难查。
    `tests/test_achievements.py::test_packaged_conditions_only_use_metrics_that_exist`
    专门拦这个：拿 `compute_metrics()` 的键集合逐个对拍，加新指标/新成就时它会立刻失败。
29. ⚠️ **`Textbox.gather()` 会把字符截成 7 位，中文进编辑区必坏**：它内部用
    `chr(curses.ascii.ascii(self.win.inch(y, x)))` 拼字符串，`ascii()` 是 `& 0x7f` ——
    实测 `草稿正文` 读回来变成 `I?c\x07`（草→`I`、稿→`?`、正→`c`、文→BEL）。
    所以**中文草稿绝不能经编辑区**：`_restore_draft` 只把 ASCII 正文填进窗口，
    非 ASCII 正文原样交给 `_commit_note` 直接落盘（并在消息行说一句）。
    写测试时如果拿中文当"草稿正文"，会撞上这个 7 位截断 —— 这不是 bug，是 curses 的限制。
30. ⚠️ **`~` 展开 + 不存在的目录会造出"名叫 books 的文件"**：`export_notes(book_id, "~/books")`
    在 `~/books` 尚不存在时，`Path("~/books").is_dir()` 为假 → 走"按文件复制"分支 →
    真的写出一个文件叫 `~/books`。**导出必须由调用方拼出完整文件名**
    （`~/books/notes_<id>.md`），或先确保目录存在。
31. ⚠️ **CLI 分页必须"两端都是 tty"才等按键**：只看 `stdin.isatty()` 时，
    `subprocess.run(..., capture_output=True)` 之类的场景（stdout 被管道/捕获，stdin 还是终端）
    会让 `werd notes <id>` 卡在第一页等键 —— 实测把 `tools/verify_notes.py` 整个挂死，
    只能 `pkill`。规则与阅读器一致：`sys.stdin.isatty() and sys.stdout.isatty()`。
    给这类工具起子进程时也顺手 `stdin=subprocess.DEVNULL`。
32. ⚠️ **`flock` 不可重入（同一进程也不行）**：`file_lock(path)` 每次都新开一个 `.lock` 句柄，
    所以**在同一个 `with` 里再调用一次公共写函数会死锁**（第二个 `flock(LOCK_EX)` 等自己）。
    `notes.py` 因此把不加锁的 `_write_index` 留给"已经持锁"的内部调用，
    公共的 `update_index()` 自己拿锁 —— 两者的 docstring 都写明"别在持锁时调用"。
33. ⚠️ **`Pager.viewport_width` 是"正文区宽度"，不是终端列数**：`_draw` 每帧把它设成
    `width - 1`（第 0 列留给书签）。成就里的"≤40 列 / ≤60 列"说的是**终端**列数，
    所以另开一个 `Pager.terminal_width`（由 `note_width` 写）。
    把两者混用会差一列，而且这种错**只在边界宽度上露出来**（60 列时 `viewport_width == 59`）。
34. ⚠️ **`importlib.metadata.distribution("wreader")` 在仓库根会命中 `wreader.egg-info`**：
    它没有 `direct_url.json`，于是"可编辑安装"探测在源码树里误判为 `False`
    （site-packages 里那份 `wreader-0.1.0.dist-info` 才是对的）。
    写法：遍历 `metadata.distributions(name=...)` 逐个尝试，取第一个读得到的那份。
35. ⚠️ **给 `daily_open` 钉时间的测试要躲开节日**：有了「节日读者」之后，
    `datetime(2026, 1, 1, 12, 0)` 这种"看起来最中立"的固定时刻会让它当场解锁。
    要同时避开 05:00-07:00（清晨第一眼）与 `achievements.HOLIDAYS` / `LUNAR_HOLIDAYS`。
36. ⚠️ **`_confirm` 的默认提示是"加入生词本"**：它是给 `v` 查词用的。
    别的地方复用这个弹窗时必须传 `hint=`（恢复提示就是这么做的），
    否则用户会看到"是否加入生词本"却被问到"要不要接着读"。
37. ⚠️ **屏内通知必须"画得下才画"**：`_notice_layout()` 返回 `None`（窗口太小）时，
    调用方要把文字退到消息行（`_message_row(..., notice=...)`），不能就那么丢掉 ——
    "解锁了但屏幕上什么都没发生"是最难受的一种 bug。


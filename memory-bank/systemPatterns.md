# System Patterns — 架构与关键设计

> 系统怎么搭的、关键设计模式、组件关系、容易踩的实现路径。最后更新：**2026-09-25**。

## 分层架构

```
                    ┌──────────────────────────────┐
  用户 ──命令──▶    │ cli.py    argparse + 子命令   │  ← 唯一对外入口（含 rich 渲染）
                    └───────┬──────────────────────┘
                            │ 调用纯函数式 API
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   library.py            toc.py             stats.py
   导入/索引/搜索        章节/目录缓存      指标/热力图/成就定义加载
        │                   │                   │
        └───────────────────┴───────────────────┘
                            │  ✔ 事件（daily_open / session_end / book_add …）
                            ▼
                    achievements.py         ← 记事件 + 判解锁 + 写状态
                            │
                            ▼
                        lock.py             ← flock 串行化 + 原子替换（成就/书库共用）
                            ▼
                        config.py           ← 数据目录、settings.toml、SCHEMA 驱动
                            ▼
                  ~/.wreader/{settings.toml, library.json, achievements.json,
                              reading_session.json, geo.json, cache/}
                  ~/novels/<书名>_utf8.txt

  纯数据层之外的特例：
  reader.py ── curses 全屏前端（Pager + 绘制 + 按键），只在真 TTY 里跑
               │
               ├──▶ toc.py      ← 目录浮层用的章节表
               └──▶ 探索支线（开书时各探一次）：
                    env.py   ← 纯读环境变量 / platform.release() / direct_url.json
                    geo.py   ← ip-api（一小时缓存，可注入 fetcher，离线返回空）

  ⚠️ 2026-09-25 起不再有 translator.py / translate/ / vocab.py / notes.py，
     也没有任何"引擎可插拔层"；成就引擎只把老 vocab.json / notes/*.md **只读**数一遍。
```

**核心分层约定**：除了 `reader.py` 的 curses 前端和 `cli.py` 的输出渲染，
其余模块都是**纯函数 + 普通数据**，不依赖终端、不依赖全局状态（除 `config` 的带戳缓存）。
这让分页数学、章节边界、统计指标、成就条件都能脱离 TTY 测试。

## 模块职责与规模（2026-09-26 实测：12 个 `.py` 共 9,561 行）

| 文件 | 行数 | 职责 | `__all__` |
| --- | --- | --- | --- |
| `wreader/__init__.py` | 22 | `__version__`、模块地图 | 1 个 |
| `wreader/achievements.py` | 1250 | **事件驱动成就引擎**：状态文件、事件累加、解锁判定、字数去重、**实时门槛（`metric_thresholds`/`crossed_thresholds`）与基线（`session_metrics`）**、**遗留老数据只读计数（`vocab` / `notes`）**、**跨机合并（`merge_states`，只加不减）** | 31 个（`check_achievements`/`record_event`/`merge_states`…） |
| `wreader/cli.py` | 1004 | argparse 定义 + 子命令处理函数（`import`/`list`/`search`/`read`/`continue`/`stats`/`achievements`/`config`/`toc`/`data`/`prune`/`clear`/`werd`+`word`）；`_auto_prune_books` 在每个命令前对账一次（`clear` / `prune` 自己跳过） | `["build_parser", "main"]` |
| `wreader/config.py` | 966 | settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁；`SCHEMA` 是 4 section / 16 键的单一事实来源 | 44 个（`SCHEMA`/`DEFAULTS`/`Config`…） |
| `wreader/env.py` | 183 | **环境探测**：云主机 / WSL / tmux / 可编辑安装（四个输入全部可注入） | 8 个（`detect`/`flags`/`SIGNAL_NAMES`…） |
| `wreader/geo.py` | 343 | **地理位置**：ip-api 查询 + 一小时缓存 + 国家→大洲 + 世仇组合；注入式 fetcher、离线降级 | 15 个（`load_location`/`continent_of`/`feud_hit`…） |
| `wreader/library.py` | 1425 | txt/epub 导入、编码识别、书名解析、索引、模糊搜索、最近在读、**阅读统计的落库侧（`accumulate_stats`）**、**书库清理（`prune_missing_books` 摘死记录 / `clear_library` 清书库保成绩）** | **无 `__all__`** |
| `wreader/lock.py` | 80 | **跨进程文件锁**（POSIX `flock`；Windows 退化为"只有原子替换"） | 3 个 |
| `wreader/reader.py` | 2799 | curses 分页阅读器：视图、搜索、书签、状态栏、绘制、滚轮/触摸、目录浮层、**标记选字（仅引用缓冲区）**、**帮助页、成就通知、中断恢复** | 18 个（`Pager`/`open_reader`…） |
| `wreader/stats.py` | 817 | 指标、热力图、连续天数、**成就定义加载**、庆祝动画、**遗留数据只读计数（`vocab_legacy_count` / `notes_count`）** | 27 个 |
| `wreader/toc.py` | 474 | **目录解析**：中文卷/章正则、epub nav/ncx、缓存与失效判定 | 10 个（`build_toc`/`load_toc`…） |
| `wreader/transfer.py` | 198 | **数据搬家**：把阅读时长 / 每日桶 / 位置 / 书签 / 会话 / 成就解锁打成纯 JSON 包（`BUNDLE_KIND` / `BUNDLE_VERSION`），并把别的机器的包**只加不减**合并进来；坏包抛 `TransferError` | 5 个（`export_data`/`import_data`/`TransferError`…） |
| `wreader/data/achievements.json` | 348 | **48 个**成就定义（可被 `$WREADER_HOME` 下的同名文件覆盖） | — |

## 关键设计模式

### 1. SCHEMA 驱动配置（单一事实来源）
`config.py` 的 `SCHEMA` 是 `section -> ((key, default, comment), ...)` 的表。它同时决定：
- **默认值**（`DEFAULTS` 按 section 嵌套、`DEFAULT_FLAT` 按点号路径）
- **类型**（`coerce_value` 用 `type(default)` 推断该键该是 int/float/bool/str）
- **写文件顺序**与**行尾注释**（`COMMENTS`）

加一个设置项 = 在 `SCHEMA` 加一行，其余自动生效。当前是 **4 个 section / 16 个键**。
用户文件里多出来的键**不报错**：收进 `Config.unknown`，由 `cli._print_config` 打一行警告（见坑 #16）。

### 2. 行号坐标系统一
`library.py` 与 `reader.py` 共用同一套坐标：`normalise_newlines(text).split("\n")` 的下标。
- `progress.current_line`、`bookmarks[].line`、`chapters[].line_start`、`sessions[].lines_read`
- 成就的 `books[id].counted` 行区间也是这套行号

**任何读写正文的地方都必须先 `library.normalise_newlines()`**，否则行号会错位。

### 3. 视图层与数据层分离（Pager）
`Pager` 是一个**数据对象**：位置、搜索命中、书签、计时、成就计数、通知文案。
- **屏顶坐标 = `(position, line_offset)`**：`position` 是源行号（与落库坐标一致），
  `line_offset` 是这一行里已经翻过去的**折行屏幕行数**（纯显示态，**不落库**）
- `_row_texts(index, width)` 把**一个源行**摊平成屏幕行；`visible_rows(height, width, offset)` 决定
  这一屏填哪些行（含折行与段内偏移）；`_screen_rows(index, width)` 回答"一个源行占几屏行"
- `_walk_forward(start, offset, budget, width)` 是分页的核心：返回 `(这一屏的行, 下一屏的屏顶坐标)`
- `next_top` / `previous_top` 按屏幕行预算算出下一屏 / 上一屏的 `(行, 段内偏移)`
- `viewport_rows` / `viewport_width` 由 `_draw` **每帧**按真实终端填入；`terminal_width` 由
  `note_width()` 填（**两者不是一个东西**，见坑 #23）
- `move_to(position, offset=0)` 是**唯一的位移入口**：翻页 / 滚轮 / 搜索 / 章节 / 首尾跳转都走它，
  它同时负责记 `read_ranges`、`_sync_chapter()` 与重置段内偏移
- `_draw` 只负责画，`handle_key` 只负责改 `Pager` 状态
=> 分页/视图逻辑可脱离 curses 测试（`tests/test_reader.py` 从来不启动真终端）。

### 4. 显示宽度工具（终端 CJK 的唯一正确做法）
| 函数 | 作用 |
| --- | --- |
| `_char_width(ch)` | 东亚 Wide/Fullwidth → 2 列，其余 1 列（`unicodedata.east_asian_width`） |
| `_text_width(text)` | 整串占几列 |
| `_clip_line(text, room)` | 按列裁，绝不劈开全角字符 |
| `_pad_line(text, room)` | 裁到 room 列后再补空格到**正好** room 列（擦掉上一帧残影） |
| `_wrap_line(text, width)` | 按列折行：英文在空格处断（不劈单词）、汉字逐字断、Tab 展开、行尾空格丢弃、空行保留一行 |

**所有宽度判断都必须走这几个函数，禁止 `len()`。** 它们有属性测试：
`tools/verify_wrap.py`（40,077 项检查）与 `tools/verify_draw.py`（140 项绘制检查）。

### 5. 可注入的外部依赖 + 唯一网络接缝
项目里**唯一**会联网的地方是 `geo.py`，而且它把网络收在一个可注入的接缝上：
- `geo.fetch(fetcher=...)` / `load_location(fetcher=..., now=..., allow_fetch=...)`，
  默认 fetcher 内部才 `import requests`；测试注入假 fetcher，**离线也能测**。
- `env.detect(env=..., release=..., direct_url=...)` 三个输入全部可注入，测试不读本机。
- 失败**不是异常而是"空"**：`fetch()` 永不抛、`load_location()` 返回 `{}`、
  `env.detect()` 永远返回四个 bool。调用方只需 `if not location: 啥也不记`。
- 于是"联网"变成一个有默认值的参数：`stats.geo_lookup = false` 时连 fetcher 都不会被调用。

同样的形状也用在**时间**上：`reader._now()` / `cli._now()` 是注入缝，
测试要"钉住时刻"就换掉它（否则成就测试会按钟点随机失败，见坑 #24）。

### 6. 失败可恢复 / 绝不崩阅读
- 单个坏文件 → 进 `import` 的 `failed` 列表，不中止整批
- 成就状态文件坏 → 改名 `achievements.json.broken`，从空状态重来
- 成就定义坏 / 条件里指标名拼错 → 只是"这次不判定"，绝不让阅读或命令失败
- 书库索引读不出来 → `read_library` 返回空书库 + 一句提示，不抛异常
- 索引写不进 → `save_position()` 返回 `False`，下次自动保存再试
- 目录缓存缺失 / 失效 → 当场重解析，不影响阅读
- 地理位置查不到 → 返回 `{}`（离线是正常状态，不是错误）

### 7. 成就：事件驱动 + 单一解锁存储（`achievements.py`）
- **唯一解锁存储**是 `<data dir>/achievements.json`（不是 `library.json`）。旧版本写在
  `library.json` 的 `achievements.unlocked` 里，**第一次读状态时自动迁移一次**，
  之后那里的旧内容不再被读（`stats.unlocked_ids(document)` 只留给迁移与兼容测试）。
- **唯一入口**是 `achievements.check_achievements(event_type, data)`：记事件 → 算指标 →
  逐条判定 → 写回。事件名被 `EVENTS` 白名单（**16 个**）校验，写错立刻抛
  `AchievementsError`（绝不静默丢事件）。`word_add` / `note_add` 仍在白名单里但已无调用方 ——
  **保留是为了兼容老脚本**，删掉它会打断"外部按老事件名驱动成就"的用法。
- **条件是表达式**（`"words_read >= 10000"`），指标 = `stats.compute_metrics(document)`
  ∪ 状态派生指标（`words_read` / `days_opened` / `early_open` / `weekend_time` / `library_books` /
  `notes_count` / `translate_hits` …）。加一条成就 = 往 `data/achievements.json` 加一行，代码不用动。
- **字数按行号区间去重**：`Pager.read_ranges` 在 `move_to()` 里记下每次"向前"走过的
  `[起点, 终点)`；退出时整段交给引擎，引擎只统计"没统计过的那些行"（`uncovered_words`），
  并把区间并进 `books[id].counted`。所以同一页读两遍不会重复累加。
- **文件锁**：读-改-写整个包在 `lock.file_lock(path)`（POSIX `flock`；Windows 无 `fcntl` →
  退化成"只有原子替换"）。写盘一律 `mkstemp` + `os.replace`。
- **容错姿态**：状态文件坏 → 改名 `.broken` 再重来；指标算不出来 → 夹回 0（`_normalise_state`）。

### 8. 成就的实时门槛：读者攒数、引擎只在越线时被叫醒
一次 `check_achievements()` = 文件锁 + 整个状态文件重写 + 读一遍书库索引，
**按一次键就写一次盘绝对不行**。所以拆成两半：

- **引擎侧（纯函数，可单测）**：`metric_thresholds(definitions)` 把定义里的条件解析成
  `{指标: (门槛, ...)}`；`session_metrics()` 给出"现在各项指标是多少"（阅读器的基线）；
  `crossed_thresholds(values, thresholds, fired)` 回答"有哪些线刚刚被越过"。
- **阅读器侧（只读内存）**：`Pager.note_key` / `note_chapter_change` / `note_width` 累加自己的计数；
  `_achievement_tick()` 每次按键/换尺寸调一次，**没越线就直接返回**（零 I/O）；
  越线才把 `pending_deltas()` / `current_maxima()` 交给引擎，并把 `(指标, 门槛)` 记进
  `Pager.fired` 防止重复触发。
- **不丢数据**：增量在**真的发出去之后**才推进水位（`Pager.commit_report`），
  引擎报错就原地留着下次再报；会话结束时 `session_end` 把余下的计数一次交账。
- **基线预标记**：开书时把"基线就已达标"的门槛全部塞进 `fired`，
  否则早就解锁的成就会在第一次按键时白写一次状态文件。

### 9. 意外中断的现场标记（`reading_session.json`）
- 进阅读器时 `write_marker()` 写"我正在读这本书"（书 id / 行号 / 段内偏移 / 一行预览 / 时间 / pid），
  `save_position()` 每次自动保存顺手刷新，**正常退出**时 `clear_marker()` 删掉。
- 下次开书：`read_marker()` 拿到现场 → **只有 `book_id` 对得上**才交给 `Pager.resume_marker` →
  `_run` 开头 `_offer_recovery()` 问一句 → `y` 回现场（`move_to(position, offset)`）、其他键从头开始。
- ⚠️ 位置的**权威**始终是 `library.json` 的 `progress.current_line`；现场只是"要不要问一句"的依据，
  丢了顶多少问一次（写一半被 kill 的现场会被当作不存在）。

### 10. 模态浮层：同一套"小循环 + 自己管按键"的写法
帮助页（`?`）与目录浮层（`Tab`）都是**子循环**：`_draw_*` 画一帧 → `get_wch` 带超时 →
自己解释按键 → `Esc`/`q`/`Enter` 退出。共同约定：
- **不另开线程**，主循环的 `_TICK_MS` 在 `finally` 里恢复（否则退出浮层后按键会变"迟钝"）。
- 浮层的**最后一行只填 `panel - 1` 列** —— 写右下角会被 curses 静默吞掉，导致整行消失（坑 #13）。
- 名字彩蛋走 CLI 而不是阅读器：`werd werd` / `werd word` / `werd --werd` → `_word_egg(name)` →
  `_record_achievements("name_egg", {...})`。

### 11. 遗留数据的只读兼容层（2026-09-25 新增）
翻译 / 生词本 / 笔记被删掉后，**老数据文件一个都不动**，只在成就侧读一遍换成指标：
- `stats._vocab_file_size()`：数 `<data dir>/vocab.json` 里真带 `word` 的记录（兼容老的
  `{"words": [...]}` 包装），文件缺失/坏 JSON/坏编码一律返回 **0**，绝不抛异常。
- `achievements._note_total()`：扫 `<data dir>/notes/*.md`，只数形如 `## 笔记 #N — …` 的小节标题，
  目录不存在就 0。**每次现数**，不保存计数（所以用户手改笔记不会让指标漂移）。
- `stats.compute_metrics(document, vocab_size=None)` 保留 `vocab_count` 与 `translations`
  两个"遗产指标"（后者来自老 `library.json` 的 `stats.translations`），
  `werd stats --json` 也照旧输出 `vocab_count` / `translations` / `notes_count` / `translate_hits` ——
  删掉这些键会让 5 条老成就永远解锁不了、也会打断按旧键名解析的脚本。
- **写入路径一律不存在**：`grep -rn 'vocab.json\|notes/' wreader/` 只会命中上面两个只读函数。
- ⚠️ **已知代价**：「翻译狂魔」（`translate_hits >= 100`）以后再也无法新解锁（阅读器里没有翻译键了），
  只有老用户拿着旧计数；「双语者」「词汇积累」「生词狂魔」「笔记达人」只对**还留着老数据文件**的用户可解锁。
  这是刻意的取舍：宁可少数成就"封存"，也不虚构指标。

### 12. 数据搬家：包 + 「只加不减」的合并（2026-09-26 新增）

跨机器搬「阅读时长 + 成就」不引入服务端：`transfer.py` 把状态**导出成一个纯 UTF-8 JSON 包**，
在另一台机器上再**合并**回来。

- **包的形状（`kind` / `version` 是硬判据）**：`{"kind": "werd-data", "version": 1, "exported_at": …,
  "books": {<book_id>: {progress, stats, sessions, bookmarks}}, "achievements": {…}}`。
  `book_id` 就是正文 SHA-1 前 12 位，所以**两台机器只要导入了同一份内容，id 自然对上**，不靠书名匹配。
- **只收有阅读痕迹的书**：`progress.last_read` 为空**且** `total_time_seconds == 0` 的书不进包
  （刚导入还没读过的书搬过去只是空壳，还会让「已合并 N 本」虚高）。
- **合并语义（`library` 侧 + `achievements.merge_states`）**：时长与每日桶**相加**、
  `sessions` 按内容**去重**、`bookmarks` 取**并集**、`finished` **粘住**（任一侧为真就是真）、
  位置**只在本机没有任何历史时才采用**；成就 `unlocked` 取并集、`counters` 取 max。
- **本机没有的书进 `skipped`**（`transfer.import_data` 的返回值里带计数，CLI 打印出来），不静默丢弃。
- **坏包一律拒绝**：文件不存在 / 是目录 / 不是 JSON / `kind` 不是 `werd-data` / `version` 比本机新
  → 抛 `TransferError` → `cli` 统一打印 `error: …` 并 `exit 1`。
- ⚠️ **代价：重复导入会把时长翻倍**（没有「谁更新」的可信标记，只加不减是最不坏的策略，
  详见 `progress.md` 的决策行与坑 #34）。

## 关键实现路径（改动时必看）

| 场景 | 调用链 |
| --- | --- |
| 导入一本书 | `cli.cmd_import` → `library.import_books` → `load_source_text`（编码识别 / EPUB）→ `write_utf8_text` → `build_record` → `save_library` |
| 打开阅读器 | `cli.cmd_read` → `reader.open_reader` → `read_lines`（保持行号一致）→ `Pager(...)` → `curses.wrapper(_run)` → `_run` 首行 `_init_colors()` |
| 继续上次的书 | `cli.cmd_continue` → `library.recent_books(limit=3)`（按 `progress.last_read` 倒序，跳过从没读过的书）→ `_book_table` 打印 id，抄给 `werd read` |
| 画一帧 | `_run` → `_draw` → `Pager.visible_rows(viewport_rows, width-1)` → 逐行 `_draw_text` → `status_segment` + `_draw_status` → `_draw_notice` → `refresh` |
| 翻页 | `handle_key` → `Pager.next_page` / `previous_page` → `next_top` / `previous_top(page_budget, viewport_width)` → `move_to(行, 段内偏移)` → `_sync_chapter`（章节计时滚动）。`page_budget = round(page_scroll_step × viewport_rows) − page_overlap`，单位是**屏幕行** |
| 鼠标 / 触摸 | `_run` 首行 `_enable_mouse()`（`mouseinterval(0)` + `mousemask`）→ `get_wch` 返回 `KEY_MOUSE` → `_mouse_event_delta` → `curses.getmouse()` → `_mouse_scroll_delta`（滚轮按 `wheel_scroll_step`、拖动按手指位移）→ `Pager.scroll` |
| 退出落库 | `open_reader` → `save_session` → `_write_position` + `accumulate_stats` → `save_library`；收尾 `clear_marker` 删掉现场 |
| 目录浮层跳转 | `handle_key`（`Tab`）→ `_jump_via_toc` → `_toc_overlay`（模态循环：`_draw_toc` + `toc.filter_toc` + `_toc_move_cursor`）→ `Pager.move_to(line)` |
| 目录缓存 | `open_reader` → `toc.load_toc`（命中缓存即返回；否则 `_read_lines` → `build_toc` / `build_toc_from_epub` → `save_toc`）；epub 另在 `library.import_books` 里 `_cache_epub_toc` → `toc.save_toc` |
| 成就解锁 | `cli.main` / `cmd_import` / `open_reader` → `achievements.check_achievements(事件, 数据)` → `record_event` → `achievements.compute_metrics`（`stats.compute_metrics` ∪ 状态指标 ∪ `_note_total()`）→ `stats.evaluate_condition` → 写 `achievements.json` → `reader._celebrate_achievements` / `cli._report_unlocked` → `stats.celebrate` |
| 阅读中实时判定 | `handle_key` → `Pager.note_key`（或 `KEY_RESIZE` → `Pager.note_width`）→ `_achievement_tick` → `achievements.crossed_thresholds`（纯内存）→ 越线才 `_fire_event` → `check_achievements("key"/"resize")` → `_announce_unlocks` → `Pager.announce` → 下一帧 `_draw` → `_draw_notice` |
| 换章结算 | `Pager.move_to` / `sync()` → `_sync_chapter` → `Pager.note_chapter_change`（方向键怀旧 / 窄屏挑战）→ 下一帧的 `_achievement_tick` 交账 |
| 帮助页 | `handle_key`（`?`）→ `_help_overlay` → `_fire_event("help")` → `help_lines` / `_help_layout` / `_draw_help`（模态循环，`finally` 里恢复 `_TICK_MS`） |
| 意外中断恢复 | `open_reader` → `read_marker`（book_id 对得上才用）→ `Pager.resume_marker` → `_run` → `_offer_recovery` → `_confirm(hint=_RECOVER_HINT)` → `Pager.move_to` + `_fire_event("recover")`；`open_reader` 收尾 `clear_marker` |
| 环境 / 位置探测 | `open_reader` → `_prepare_achievements`（门槛 + 基线 + 预标记）→ `_probe_achievements("env", {"flags": env.flags()})` → `_probe_geo(pager, settings)` →（`geo.load_location` 命中缓存就不联网）→ `_probe_achievements("geo_change", location)` |
| 名字彩蛋 | `cli.main`（`--werd`）或 `_HANDLERS["werd"/"word"]` → `_word_egg(name)` → `_record_achievements("name_egg", {"egg": name})` |
| **遗留数据计数** | `cli.cmd_stats` → `stats.build_report` → `stats.compute_metrics` → `stats._vocab_file_size()`（数 `vocab.json`）；成就侧 `achievements.compute_metrics` → `achievements._note_total()`（数 `notes/*.md`）。**两条路都只读** |
| 导出搬运包 | `cli.cmd_data`（`data export`）→ `transfer.export_data(path)` → 读 `library.json` + `achievements.json`（缺失按空处理）→ **只留有阅读痕迹的书** → `path.write_text(json.dumps(..., ensure_ascii=False))`，返回 `{"books": n, "path": …}` |
| 导入搬运包 | `cli.cmd_data`（`data import`）→ `transfer.import_data(path)` → 校验 `kind` / `version` → 逐本对 `book_id` 合并（时长与每日桶相加、`sessions` 去重、书签并集、位置按需采用）→ `achievements.merge_states` → `save_library`；返回 `{"books": n, "skipped": m, …}` |
| 书库对账 | 每个命令 `cli.main` 顶部 → `if args.command not in ("clear", "prune"): _auto_prune_books()` → `library.prune_missing_books()` → `file_path` 指向的文件已不存在的记录摘掉（空路径保留）→ 有变化才 `save_library` 并打一行提示 |
| 清空书库 | `cli.cmd_clear` → `library.clear_library()` → `books = {}` 落盘 → 逐本 `_delete_text_file` + `_drop_toc_cache`；**不碰** `achievements.json` 与阅读时长（打一行说明保留了它们） |
| 终端流控 | `_run` → `_disable_flow_control()`（POSIX 用 `termios` 清 `IXON\|IXOFF`；`endwin()` 负责还原） |

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
   只能用自己的状态机维护（`_DragScroll`：见过按下 → 见过抬手之间），不能直接看 bstate 的按键位。
10. **测鼠标必须用 `TERM=xterm-1006`**：macOS 的 `xterm-256color` terminfo 没有 `XM` 能力，
    curses 只开 `?1000h`，SGR 序列会被当成普通按键收进来 —— 测出来的"失败"是假的。
11. **翻页必须按「屏幕行」算，不能按「文本行」**：长段落没有换行，在终端里被折成多行，
    所以"一屏"对应的文本行数是变的。翻页走 `page_budget = round(page_scroll_step × viewport_rows) − page_overlap`
    （单位屏幕行，`page_overlap` 默认 3），再由 `next_top` / `previous_top` 用
    `visible_rows`（= 已有的正确折行）换算成源行号。
    ⚠️ **绝不能**用 `ceil(len(text) / width)` 这类字符数近似：汉字占 2 列，`len()` 会把折行算错，
    而且会劈开英文单词。这是 `_wrap_line` 存在的唯一理由，必须复用。
    ⚠️ `tools/verify_mouse.py` 键盘基准是 **pty 真实高度**（40 行 → 正文区 38 行 → `j` 走 38−3=35 行），
    不是 `page_height`；各项期望值**顺序累积**，改翻页逻辑 / 重叠 / pty 尺寸都要全部重算。
    滚轮 / 触摸拖动走 `scroll(±wheel_scroll_step)` 逐行走，**不经过翻页路径**，不受影响。
    ⚠️ **屏顶必须是 `(源行号, 段内偏移)` 两元组**：只记源行号 → 一屏中途被折行截断的那半截
    会在下一页被跳过（`position` 一加就丢掉这一行剩下的折屏行）。所以 `Pager.line_offset`
    记着"这一行里已经翻过去几条折屏行"，`visible_rows` 从它开始画；
    `next_top` / `previous_top` 返回的都是这个两元组。
12. **段内偏移是显示态、绝不落库**：`progress["current_line"]` 永远只写源行号，
    否则书签 / 章节 / 成就行区间共用的「行号坐标唯一」约定就被破坏。代价是重开书时从行首开始
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

16. **用户配置里多出来的键：只警告，别报错、别静默**：`Config.unknown` 收着这些键，
    `cli._print_config`（即 `werd config` 列表时）逐键打一行
    `warning: unknown setting '...' is ignored`。2026-09-25 删掉 `translator.*` / `translate.*` /
    `vocab.*` 三个 section 后，老用户的 `settings.toml` 全靠这条路径"体面地"被忽略。
    ⚠️ **反过来**：`werd config <path>` 试图**写**一个不存在的键时**必须报错**
    （`config._unknown_path` → `ConfigError`）—— 打错字的设置项如果静默落盘，用户会以为生效了。
17. **`curses.window` 对象没有 `newwin` 方法**（历史坑，`_sub_window` 已随笔记面板删除，但教训留着）：
    只有模块级的 `curses.newwin`。第一版写成 `stdscr.newwin(...)`，`FakeStdscr` 恰好也实现了
    `newwin` → **单测全绿**，真 pty 里立刻 `AttributeError: '_curses.window' object has no attribute 'newwin'`。
    **教训：假窗口实现得越像真 curses，越容易掩盖真 API 的差异 —— UI 改动必须过一遍真 pty。**
18. **`Ctrl-S` 会被终端行规程吃掉**：`curses.wrapper` 只调 `cbreak()`，`IXON` 仍开着 → 终端把
    `Ctrl-S`（XOFF）当流控吞掉，`Ctrl-S` 键永远到不了程序（现在没有 Ctrl-S 键了，但
    `_disable_flow_control()` 仍保留着：以后任何 Ctrl-Q/Ctrl-S 绑定都靠它，`endwin()` 负责还原）。
    **单测不经过行规程，只有真 pty 能验。**
19. **`flock` 不可重入（同一进程也不行），而且"原子替换 ≠ 串行化"**：`lock.file_lock(path)` 每次都新开
    一个 `.lock` 句柄，所以**在同一个 `with` 里再调用一次会自己拿锁的公共写函数就会死锁**。
    现行约定：**公共入口自己拿锁**（`achievements.check_achievements` 里 `with file_lock(target)`），
    而 `save_state()` / `load_state()` 是**不加锁的裸读写**，只能由已持锁的调用方使用 ——
    两边的 docstring 都写着这条。多终端同时读书时，串行化完全依赖这一条。
20. **`editor` 工具超长替换会"假成功"，而本环境 `heredoc` 直接不可用**：一次 ~5900 字符的替换返回
    "File created successfully"，实际却在**仓库根**留下一个野生 `cli.py`（目标文件只改了一半）。
    迷惑点在于 `grep 新函数名` 找不到、`pyright` 依然 0 报错（根目录不在 `[tool.pyright]` include 里）。
    **2026-09-25 另记**：`cat > file <<EOF` 这类 heredoc 在本环境会把 shell 搅乱、文件却**一个字节都没写**
    （看着像成功了）——**改文件一律用 `editor` 工具，别用 heredoc**。
    通用对策：单次替换保持 <6000 字符、改完立刻 `grep`/`head` 确认、收尾 `git status` 扫一眼有没有怪文件。
21. **测试替身必须复刻真函数的语义**：被 monkeypatch 掉的 `cli._prompt_line` 一开始直接返回队列里的
    空串，漏掉了真函数"空输入 = 用默认值"的行为，于是"回车保留当前值"这条路径**静默失去覆盖**。
    替身要照着真函数的契约写。
22. **`daily_open` 每次启动都触发 → 与"跑测试的时刻"耦合**：`cli.main()` 一进来就记
    `daily_open`，所以测试若恰好在北京时间 05:00-07:00 跑，`early_bird` 会**自己解锁**，
    断言当场翻车。对策：`cli._now()` 是**注入缝**，测试把它换成固定中午。
    凡是"依赖当前时刻/日期"的新事件，都要留这种缝，否则测试会变成按钟点随机失败。
23. **成就的"解锁"只能有一个写入路径**：权威存储是 `<data dir>/achievements.json`。
    曾经的两套（`stats.check_achievements` 写 `library.json`）会造成"到底谁说了算"，
    所以那个函数**已删除**（连同它的 6 个测试）；`stats` 只保留**定义加载**与指标计算。
    新增解锁逻辑时不要再往 `library.json` 写。
24. **`_normalise_state` 里的行区间必须统一成 `list[list[int]]`**：`merge_ranges()` 返回
    tuple，直接塞进 state 会让"内存形状"与"JSON 形状"不一致 → 读回来 `==` 断言永远失败
    （实测：`[(0, 2)] != [[0, 2]]`）。**同一份数据只允许一种表示**。
25. **不要为了跨平台在模块顶部 `import msvcrt`**：pyright 在 macOS 上会报"无法解析"。
    `lock._lock_file()` 的做法是**局部** `import fcntl` + `except ImportError: return False`，
    Windows 侧退化成"只有原子替换"，这个取舍写进了函数 docstring 与 README。
26. **条件里的指标名必须真实存在**：写成 `condition: "book_adds >= 1"`（指标拼错）时，
    `parse_condition` 不报错、进程不崩，但那条成就**永远解锁不了** —— 静默失效最难查。
    `tests/test_achievements.py::test_packaged_conditions_only_use_metrics_that_exist`
    专门拦这个：拿 `compute_metrics()` 的键集合逐个对拍，加新指标/新成就时它会立刻失败。
    同理，**删指标前必须先删/改引用它的条件**（2026-09-25 删翻译功能时就踩在这里：
    条件里的 `vocab_count` / `translations` / `notes_count` / `translate_hits` 全部保留成遗产指标才安全）。
27. **`importlib.metadata.distribution("wreader")` 在仓库根会命中 `wreader.egg-info`**：
    它没有 `direct_url.json`，于是"可编辑安装"探测在源码树里误判为 `False`
    （site-packages 里那份 `wreader-0.1.0.dist-info` 才是对的）。
    写法：遍历 `metadata.distributions(name=...)` 逐个尝试，取第一个读得到的那份。
28. **给 `daily_open` 钉时间的测试要躲开节日**：有了「节日读者」之后，
    `datetime(2026, 1, 1, 12, 0)` 这种"看起来最中立"的固定时刻会让它当场解锁。
    要同时避开 05:00-07:00（清晨第一眼）与 `achievements.HOLIDAYS` / `LUNAR_HOLIDAYS`。
29. **`_confirm()` 的 `hint` 要按场景传**：默认是通用的"`[y] 确认    其他键 取消`"，
    而恢复流程传的是 `_RECOVER_HINT`（"接着上次读 / 从头开始"）。复用这个弹窗时不传 `hint`
    就会出现"标题问 A、按钮说 B"的歧义。
30. **屏内通知必须"画得下才画"**：`_notice_layout()` 返回 `None`（窗口太小）时，
    调用方要把文字退到消息行（`_message_row(..., notice=...)`），不能就那么丢掉 ——
    "解锁了但屏幕上什么都没发生"是最难受的一种 bug。
31. **删功能要"全仓清幽灵引用"**（2026-09-25 的教训）：删掉 `translator.py` / `vocab.py` /
    `notes.py` / `translate/` 之后，还要逐个清掉 —— `cli` 的 subparser 与 `_HANDLERS` 条目、
    `reader` 的键位与 `_HELP_LINES`、`config.SCHEMA` 的 section、`pyproject.toml` 的 extras 与
    依赖、`[tool.pyright]` 的 include、`tools/` 里的专用校验脚本、README/使用指南/`tools/README.md`
    的表格与数字、以及**测试文件本身**。漏任何一处都是"启动即 ImportError"或"文档数字 FAIL"。
    收尾必查：`grep -rn 'vocab\\|translate\\|notes' wreader/ tests/ tools/ README.md` 是否只剩"合法命中"。
32. **只读兼容函数必须"坏数据返回 0，绝不抛"**：`stats._vocab_file_size()` 与
    `achievements._note_total()` 挂在**每次统计、每次成就判定**的路径上（连 `werd read` 都会走），
    所以坏 JSON / 坏编码 / 没权限 / 目录不存在一律吞掉返回 `0`。让它们抛异常等于"用户的老数据文件
    一损坏，整个阅读器就打不开"。
33. **`tools/check_doc_numbers.py` 只对拍 `README.md`**：memory-bank / 使用指南里的数字它**不管**，
    所以那两处的数字要么实测后手写、要么写判据（例如"`git status` 不显示领先/落后"）。
    另外它按 `wreader/<文件名>` 认条目，子包里的同名文件会被错算到包根那份上 ——
    所以 README 里的**子包条目不写行数**（现在包内没有子包了，这条留给将来）。
34. **搬运包的合并是「只加不减」，同一个包导两次会把时长加两遍**（2026-09-26）：实测
    `total_time_seconds` 600 → 1200 → 1800。这不是 bug 而是取舍（数据里没有「谁更新」的可信标记，
    取 max 会丢时长），所以三份文档（`README.md` / `README.en.md` / `使用指南.md`）都写明了
    「同一份包导两遍，时长就算两遍」。
    `test_importing_the_same_bundle_twice_does_not_duplicate_sessions` 只保证**会话不重复计数**，
    时长那部分**是有意相加的** —— 别把它当 bug「修好」。
35. **自动对账必须跳过 `clear` / `prune` 自己**（2026-09-26）：`cli.main` 里是
    `if args.command not in ("clear", "prune"): _auto_prune_books()`。漏掉这个白名单，
    `werd prune` 会先被自动对账摘干净、自己再跑一遍只剩「没有失效书目」（看着像命令失效），
    `werd clear` 则会多刷一行「已清理 N 个失效书目」的噪音。
36. **`prune` 只认 `file_path` 这一条证据**：路径为**空串**的记录**保留**（空 = 未知，
    不等于已删除）；手写的、没走过导入流程的记录不能被「猜」成死记录抹掉。
    另：摘记录**先把索引落盘再删文件**（`clear_library` 同理），删文件失败不回退索引。
37. **`werd clear` 没有二次确认**（2026-09-26 现状）：命令直接执行，风险由两点兜住 ——
    只删书目与 `~/novels/` 下的转换正文，`achievements.json`、阅读时长、`settings.toml` 全不动，
    且输出明确写「阅读时长与成就已保留」。以后给别的命令加确认时别顺手把它也加上，
    否则 `werd clear` 在脚本里会卡住（现状是可以直接跑）。






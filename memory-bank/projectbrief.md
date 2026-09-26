# Project Brief — wreader

> MemoryBank 的根基文件：项目是什么、必须满足哪些硬性要求、边界在哪。
> 其他文件都从这里派生。最后更新：**2026-09-26**。

## 一句话

`wreader` 是一个**终端里的中文小说阅读器**：把 txt/epub 导入成本地书库，在 TTY 里全屏分页阅读，
带目录、搜索、书签、阅读统计与 **48 个成就**；数据全在本地，换机可以用 `werd data export/import`
整包搬走。

> ⚠️ **2026-09-25 的功能裁剪**：翻译、生词本（词汇笔记本）、笔记三个功能已**整体删除**
> （源码、测试、工具、文档全部清掉）。老版本留下的 `~/.wreader/vocab.json` 与
> `~/.wreader/notes/*.md` **只被只读地计数**，用来喂 `vocab_count` / `notes_count` 两个成就指标，
> 所以老用户的进度不会丢。**不要再把它们加回代码里**（见「明确的非目标」）。

## 基本档案

| 项 | 值 |
| --- | --- |
| 包名 / 版本 | `wreader` / `0.1.0`（Pre-Alpha） |
| 许可证 | MIT（`LICENSE`；`pyproject.toml` 里 `license = "MIT"`） |
| Python | **>= 3.11**（本机实测跑在 3.13） |
| 入口 | console script `werd` → `wreader.cli:main` |
| 安装 | **`./install.sh`**（克隆后一条命令：建 venv + 装依赖 + 配别名）；手动步骤见 README |
| 打包 | setuptools（`[tool.setuptools.package-data]` 带 `data/*.json`） |
| 运行时依赖 | 只有 **3 个**：`chardet`、`rich`、`requests`（后者只服务地理成就的可选联网） |
| 规模（2026-09-26 实测） | `wreader/` **12** 个 `.py`（**9,561** 行）+ `data/achievements.json`（348 行 / 48 条）；`tests/` **10** 个测试文件 + `conftest.py`，**592** 项测试；`tools/` **8** 个校验脚本 |
| 版本控制 | **git 仓库**（2026-09-22 建）：`main` → `origin` = `https://github.com/zhangziluo/wreader`；判据是 `git status` 不显示领先/落后（不写提交数） |
| 文档 | `README.md`（中文，主文档）、`README.en.md`、`使用指南.md`（小白教程） |

## 核心功能需求

1. **导入**：`werd import <路径>` 递归扫描 txt/epub → 统一转 UTF-8 → 按正文 SHA-1 前 12 位生成
   `book_id` → 去重入库；单个坏文件只进 `failed`，不中止整次导入。
2. **书库**：`werd list`、`werd search <关键词>`（模糊匹配）、`werd search '#tag'`、`werd toc <id>`、
   `werd continue`（按 `progress.last_read` 倒序列出最近打开阅读的三本）。
3. **阅读**：`werd read <book_id>` 全屏 curses 分页器；位置、书签、本次时长落库，随时续读。
   除键盘外还支持**鼠标滚轮 / 触摸拖动逐行滚动**（手机终端 Termux 上就是靠它翻页），
   以及 `?` 帮助页、意外中断后的恢复提示。
4. **目录**：章节表由正则识别（`toc.patterns` 可加自定义正则），epub 优先用书自带的 `nav` / `ncx`；
   阅读中按 `Tab` 呼出目录浮层（`/` 过滤、回车跳转），`werd toc <id> [--rebuild]` 查看 / 重建；
   缓存在 `~/.wreader/cache/<book_id>_toc.json`，按正文 mtime 自动失效。
5. **统计与成就**：阅读时长、热力图、连续天数；**事件驱动**的成就引擎
   （`wreader/achievements.py`）把 `daily_open` / `session_end` / `book_add` 等事件记进
   `~/.wreader/achievements.json`；`wreader/data/achievements.json` 里 **48** 个成就定义
   （Phase 1 的 28 个 + 笔记联动的 1 个 + Phase 2/3 的 19 个），条件是 `指标 比较符 数字` 表达式，
   用户可自行追加。含阅读器**实时按键/尺寸事件**、解锁时的**屏内 5 秒通知**、阅读器**帮助页**、
   **意外中断恢复**（`~/.wreader/reading_session.json` 现场 + 开书时问一句）、
   `wreader/geo.py`（位置，一小时缓存，可完全关掉联网）与 `wreader/env.py`
   （云主机 / WSL / tmux / 可编辑安装）。命令行另有名字彩蛋 `werd werd` / `werd word` / `werd --werd`。
6. **配置**：`~/.wreader/settings.toml`（**4 个 section / 16 个键**）；
   `werd config <section.key> [value]` 读写，`--path` 看路径、`--reset` 复原；
   `werd config` 列出设置时（`cli._print_config`）会对每个这样的键打一行
   `warning: unknown setting '...' is ignored`（**不报错、不改写、不删用户的文件**）。
7. **老数据的只读兼容**（2026-09-25 裁剪后唯一新增的"对外承诺"）：
   - `~/.wreader/vocab.json` 里带 `word` 的条目 → 指标 `vocab_count`（「词汇积累」「生词狂魔」）；
   - `~/.wreader/notes/*.md` 里 `## 笔记 #N` 小节 → 指标 `notes_count`（「笔记达人」）；
   - 老 `library.json` 里 `stats.translations` → 指标 `translations`（「双语者」），
     并作为 `werd stats --json` 的遗留键输出；`translate_hits`（「翻译狂魔」）继续从成就状态里读；
   - 程序**只读不写**这三个位置，用户随时可以删（指标立刻归零，已解锁的成就不会掉）。
8. **数据搬家与清理（2026-09-26）**：`werd data export <文件>` 把阅读时长、每日桶、位置、书签、会话
   与成就解锁写成一个**纯 UTF-8 JSON 包**（`kind=werd-data` / `version=1`），`werd data import <文件>`
   在另一台机器上**只加不减**地合并；本机没有的 `book_id` 记进 `skipped`。
   配套两个清理入口：`werd prune`（摘掉正文文件已删的失效书目，每个命令启动前也会自动对账一次）、
   `werd clear`（清空书库与正文文件，**保留**阅读时长与成就）。**不做云同步 / 账号**（见「非目标」）。

## 硬性技术约束（不要破坏）

- **数据全是纯文本**：JSON / TOML / UTF-8 文本，用户随时能手改、备份、用脚本处理。
- **行号坐标唯一**：`正文.split("\n")` 的下标就是 `progress.current_line`、`bookmarks[].line`、
  `chapters[].line_start` 的唯一坐标，三者必须永远对齐（`library.py` 与 `reader.py` 共用）。
  **任何读写正文的地方都必须先 `library.normalise_newlines()`**。
- **终端 CJK 宽度**：汉字在终端占 **2 列**。任何宽度/截断/折行/补位都不能用 `len()`，
  必须走 `reader._char_width` / `_text_width` / `_clip_line` / `_pad_line` / `_wrap_line`。
- **阅读器只跑真 TTY**：`open_reader` 有 `isatty()` 检查，重定向时抛 `LibraryError`。
- **分层**：除 `reader.py` 的 curses 前端和 `cli.py` 的输出渲染外，其余模块必须是
  **纯函数 + 普通数据**，可脱离终端单独测试或复用。
- **测试纪律**：绝不联网、绝不碰真实数据
  （autouse fixture 把 `$WREADER_HOME`/`$WREADER_NOVELS_DIR` 指向 `tmp_path`；
  HTTP 与位置探测一律走可注入的替身；需要输入时 monkeypatch `reader._prompt` / `_confirm`）。
- **静态检查**：`npx pyright` 必须 **0 errors / 0 warnings**（`wreader/`、`tests/`、`tools/` 都纳入）。
- **注释规范**：每条逻辑语句上方都要有一行**口语化中文注释**（讲清"在干嘛 + 类型/副作用/边界"）；
  同时保留原有 docstring 与英文注释。
  ⚠️ **实测校正（2026-09-26 复测）**：这条目前是**目标**而非既成事实 ——
  `tools/check_comments.py` 严格测出 `wreader/` + `tests/` 仍有 **3099** 条语句上方没有紧邻注释行
  （`tests/test_reader.py` 591、`wreader/reader.py` 480、`wreader/achievements.py` 256、
  `wreader/library.py` 233、`tests/test_library.py` 229 最多；2026-09-25 测得 2771）。
  早先记录的 "TOTAL: 0" 是校验脚本自身 bug 造成的假绿，不可再引用。
  实际遵循的风格是"一段逻辑配一段中文注释"，别执行到每条 `return` / `assert` 都单独加。
- **已删除的功能不许复活、老数据只许读**：`wreader/` 里不再有翻译 / 生词本 / 笔记的实现，
  新增代码也不得写 `vocab.json` / `notes/`（否则老用户的数据会被程序改写）。

## 明确的非目标

- 不做 GUI / Web / **手机 App**，只做终端 —— 但**要能在手机上的终端里用**：
  Termux 等移动终端已支持触摸拖动 / 滚轮逐行翻页。
- 不做电子书格式转换器：EPUB 优先交给 Calibre 的 `ebook-convert`，没装才用内置提取器。
- 不做云同步 / 账号 / **自动**多设备同步 —— 换机靠用户自己拷一个 JSON 包
  （`werd data export/import`）：服务端、登录、后台同步都不做。
  注意：**手动搬包不是云同步**，它是本地命令的延伸（见核心功能需求 #8）。
- **不做翻译、不做生词本、不做笔记**（2026-09-25 明确移除）：这是产品边界，不是"还没做"。
  老数据文件仍会被成就引擎只读计数，但不会新增任何写入路径。
- `reader.theme` 是**预留项，未实现**，改了没有任何效果。


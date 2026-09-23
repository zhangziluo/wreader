# Project Brief — wreader

> MemoryBank 的根基文件：项目是什么、必须满足哪些硬性要求、边界在哪。
> 其他文件都从这里派生。最后更新：2026-09-23。

## 一句话

`wreader` 是一个**终端里的中文小说阅读器**：把 txt/epub 导入成本地书库，在 TTY 里全屏分页阅读，
可机翻中英对照、记生词本、看阅读统计、解锁成就。

## 基本档案

| 项 | 值 |
| --- | --- |
| 包名 / 版本 | `wreader` / `0.1.0` |
| 许可证 | MIT（`LICENSE`，`pyproject.toml` 里 `license = "MIT"`） |
| Python | **>= 3.11** |
| 入口 | console script `werd` → `wreader.cli:main` |
| 安装 | **`./install.sh`**（克隆后一条命令：建 venv + 装依赖 + 配别名）；手动步骤见 README |
| 打包 | setuptools（`pyproject.toml`，`[tool.setuptools.package-data]` 带 `data/*.json`） |
| 版本控制 | **git 仓库**（2026-09-22 建）：`main` 分支，远端 `origin` = `https://github.com/zhangziluo/wreader`；首个提交 `7ecc3eb`，**64 个跟踪文件**（2026-09-23 成就 Phase 2/3 后实测），与远端同步 |
| 文档 | `README.md`（中文，主文档）、`README.en.md`、`使用指南.md`（小白教程） |

## 核心功能需求

1. **导入**：`werd import <路径>` 递归扫描 txt/epub → 统一转 UTF-8 → 按正文 SHA-1 前 12 位生成
   `book_id` → 去重入库；单个坏文件只进 `failed`，不中止整次导入。
2. **书库**：`list`、`search <关键词>`（模糊匹配）、`search '#tag'`。
3. **阅读**：`read <book_id>` 全屏 curses 分页器；位置、书签、本次时长落库，随时续读。
   除键盘外还支持**鼠标滚轮 / 触摸拖动逐行滚动**（手机终端 Termux 上就是靠它翻页）。
4. **翻译（可插拔）**：`wreader/translate/` 里一个厂商一个模块 —— `google`（默认，免密钥）、`baidu`、
   `youdao`、`tencent`、`deepseek`、`local`（Argos，可选依赖）；`[translate] engine` 选引擎，
   `werd config translate` 交互式向导配置密钥。`t` 翻当前屏并在底部弹窗显示 3 秒（**不缓存**），
   `T` 翻整章并写入 `cache/<book_id>/`，`werd translate <id>` 翻整本。
   ⚠️ 引擎没配好时按 `t` **只提示**"运行 `werd config translate`"，不偷偷发请求。
5. **生词本**：阅读中按 `v` 查词入库；命令行增删查、`--review` 复习、`--export anki`。
6. **统计与成就**：阅读时长、热力图、连续天数；**事件驱动**的成就引擎
   （`wreader/achievements.py`）把 `daily_open` / `session_end` / `book_add` 等事件记进
   `~/.wreader/achievements.json`；`wreader/data/achievements.json` 里 **48** 个成就定义
   （Phase 1 的 28 个 + 笔记联动 1 个 + Phase 2/3 的 19 个），条件写成 `指标 比较符 数字` 表达式，
   用户可自行追加。Phase 2/3 补齐了规格里的"彩蛋"部分：阅读器**实时按键/终端尺寸事件**
   （连击、连续翻页、方向键怀旧、窄屏、翻译键）、解锁时的**屏内 5 秒通知**、阅读器**帮助页** `?`、
   **意外中断自动恢复**（`~/.wreader/reading_session.json` 现场 + 开书时问一句）、
   以及 `wreader/geo.py`（位置，一小时缓存，可完全关掉联网）与 `wreader/env.py`
   （云主机 / WSL / tmux / 可编辑安装）。命令行另有名字彩蛋 `werd werd` / `werd word` / `werd --werd`。
7. **配置**：`~/.wreader/settings.toml`；`werd config <section.key> [value]` 读写，`--reset` 复原。
8. **目录**：章节表由正则识别（`toc.patterns` 可加自定义正则），epub 优先用书自带的 `nav` / `toc`；
   阅读中按 `Tab` 呼出目录浮层（`/` 过滤、回车跳转），`werd toc <id> [--rebuild]` 可查看 / 重建；
   缓存在 `~/.wreader/cache/<book_id>_toc.json`，按正文 mtime 自动失效。
9. **笔记**：阅读中按 `m` 进入**标记模式**（`h/j/k/l` 或方向键选字、反色高亮、`y` 复制进引用缓冲区、
   `Esc` 取消，只在一屏内选字、不翻页，上限 2000 字）；按 `o` 展开**笔记面板**
   （下方 25%，引用区只读 + `curses.textpad.Textbox` 编辑区，`Tab` 切焦点、`Ctrl+S` 保存、`Esc` 关闭）。
   **笔记落盘**成 markdown（`wreader/notes.py`）：一本书一个 `~/.wreader/notes/<book_id>.md`，
   只追加不覆盖，另有派生索引 `index.json` 与崩溃草稿 `<book_id>.draft.md`（每 30 秒）；
   命令行用 `werd notes [book_id] [--export]` 查看 / 导出。

## 硬性技术约束（不要破坏）

- **数据全是纯文本**：JSON / TOML / UTF-8 文本，用户随时能手改、备份、用脚本处理。
- **行号坐标唯一**：`正文.split("\n")` 的下标就是 `progress.current_line`、`bookmarks[].line`、
  `chapters[].line_start` 的唯一坐标，三者必须永远对齐（`library.py` 与 `reader.py` 共用）。
- **终端 CJK 宽度**：汉字在终端占 **2 列**。任何宽度/截断/折行/补位都不能用 `len()`，
  必须走 `reader._char_width` / `_text_width` / `_clip_line` / `_pad_line` / `_wrap_line`。
- **阅读器只跑真 TTY**：`open_reader` 有 `isatty()` 检查，重定向时抛 `LibraryError`。
- **分层**：除 `reader.py` 的 curses 前端和 `cli.py` 的输出渲染外，其余模块必须是
  **纯函数 + 普通数据**，可脱离终端单独测试或复用。
- **测试纪律**：绝不联网（翻译走注入的 `RecordingBackend`）、绝不碰真实数据
  （autouse fixture 把 `$WREADER_HOME`/`$WREADER_NOVELS_DIR` 指向 `tmp_path`）。
- **静态检查**：`npx pyright` 必须 **0 errors / 0 warnings**（`wreader/`、`tests/`、`tools/` 都纳入）。
- **注释规范**：每条逻辑语句上方都要有一行**口语化中文注释**（讲清"在干嘛 + 类型/副作用/边界"）；
  保留原有 docstring 与英文注释。
  ⚠️ **实测校正（2026-09-23）**：这条目前是**目标**而非既成事实 ——
  `tools/check_comments.py` 严格测出 `wreader/` + `tests/` 仍有 **4513** 条语句上方没有紧邻注释行
  （`test_reader.py`、`reader.py` 最多）。早先记录的 "TOTAL: 0" 是校验脚本自身 bug 造成的假绿，不可再引用。
  实际遵循的风格是"一段逻辑配一段中文注释"。

## 明确的非目标

- 不做 GUI / Web / **手机 App**，只做终端 —— 但**要能在手机上的终端里用**：
  Termux 等移动终端已支持触摸拖动 / 滚轮逐行翻页，音量键可通过终端自身映射来翻页。
- 不做电子书格式转换器：EPUB 优先交给 Calibre 的 `ebook-convert`，没装才用内置提取器。
- 不做云同步 / 账号 / 多设备。
- `reader.theme` 是**预留项，未实现**，改了没有任何效果。

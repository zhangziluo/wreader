# Tech Context — 技术栈、环境与命令

> 用什么技术、怎么装、什么约束、跑哪些命令。最后更新：**2026-09-26**。

## 运行时依赖（`pyproject.toml`）

| 依赖 | 用途 |
| --- | --- |
| `chardet` | 导入 txt 时探测编码（GB2312 / UTF-16 / …） |
| `rich` | CLI 表格、进度条、彩色输出；退出后的阅读摘要 |
| `requests` | **唯一联网功能**：地理成就的可选位置查询（`stats.geo_lookup`，可一键关掉） |
| `curses` | **标准库自带**（macOS/Linux），因此**故意不写进 dependencies** |
| `windows-curses` | 仅 Windows：`pip install -e ".[windows]"` |
| `pytest>=8` | 仅开发：`pip install -e ".[dev]"` |

> 2026-09-25 随功能删掉的依赖：`deep-translator`（Google 引擎）、`argostranslate`
> （本地引擎的 `local` extra）。**extras 现在只剩 `windows` 与 `dev` 两个。**

## 开发环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 可编辑安装 + pytest
werd --version                   # werd 0.1.0
```

- **本机实测环境**：macOS（darwin），`.venv/bin/python` 为 Python **3.13**，
  `$TERM=xterm-256color`，`curses.COLORS=256`、`COLOR_PAIRS=32767`。
- **IDE**：`.vscode/settings.json` 把解释器指向 `${workspaceFolder}/.venv/bin/python`，
  并把工作区根加进 `python.analysis.extraPaths`（否则 Pylance 报 `rich.console` 无法解析）。
- **`[tool.pyright]` 只对 pyright CLI 生效**，VS Code 的 Pylance 读的是 `.vscode/settings.json`；
  两者都指向同一个 `.venv`。
- **新终端里怎么敲 `werd`**：它是**项目内** `.venv` 的可编辑安装，`.venv/bin` **不在**默认 PATH 上，
  所以重开终端后默认不可用。`~/.zshrc` 里有一行**别名**：
  `alias werd="/Users/zhangziluo/Downloads/wreader/.venv/bin/werd"`。
  ⚠️ **故意不用 PATH 前置**：实测会把新终端的 `python3` / `pip` 变成 venv 里那份，干扰其它项目。
- **Linux 上同理**：bash 写 `~/.bashrc`、zsh 写 `~/.zshrc`，`./install.sh` 会自动写。
  重启后日常两行：`werd continue`（抄 id）→ `werd read <id>`。

## 环境变量

```bash
WREADER_HOME=~/my-wreader-data     # 换掉整个数据目录（默认 ~/.wreader）
WREADER_NOVELS_DIR=~/my-novels     # 换掉小说正文目录（默认 ~/novels）
NR_HOME / NR_NOVELS_DIR            # 改名前的旧名，兜底（仅在新名未设时读取）
```

> 2026-09-25 起 `DEEPSEEK_API_KEY` 已无人读取（那是翻译引擎的键）。

## 文件位置

| 内容 | 路径 | 可被覆盖 |
| --- | --- | --- |
| 设置 | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| 书库索引 | `~/.wreader/library.json` | `$WREADER_HOME` |
| 成就状态 | `~/.wreader/achievements.json`（另有 `.lock` 锁文件；坏掉时被改名为 `.broken`） | `$WREADER_HOME` |
| 阅读现场 | `~/.wreader/reading_session.json`（"我正在读这本书"的标记：正常退出时删除，崩溃后下次开书靠它问一句要不要接着读；写一半被 kill 会被当作不存在） | `$WREADER_HOME` |
| 地理位置缓存 | `~/.wreader/geo.json`（ip-api 的结果缓存 1 小时；可随时删，删了下次重查一遍） | `$WREADER_HOME` |
| 目录缓存 | `~/.wreader/cache/<book_id>_toc.json`（随正文 mtime 自动失效，可随时删） | `toc.cache_dir` |
| 正文（UTF-8） | `~/novels/<书名>_utf8.txt` | `$WREADER_NOVELS_DIR`、`library.novels_dir` |
| **老数据（只读，程序不写也不删）** | `~/.wreader/vocab.json`（老生词本）、`~/.wreader/notes/*.md`（老笔记） | `$WREADER_HOME` |
| **老译文缓存（无人读取）** | `~/.wreader/cache/<book_id>/ch{N}_en.txt`、`ch{N}_bilingual.txt` —— 代码里已没有读取路径，用户可自行删 | 旧 `translator.cache_dir` |
| **搬运包（`werd data export` 的输出）** | **用户指定的文件路径**（不是目录），习惯放 `~/werd-data.json`；Windows 上常放 `%APPDATA%\wreader\` | 命令里给（不写死、不自动放进数据目录） |

Windows 数据目录：`%APPDATA%\wreader`。

## settings.toml 的 4 个 section（共 20 个键）

| section | 键（默认值） |
| --- | --- |
| `reader` | `page_scroll_step`=1.0、`page_overlap`=3、`wheel_scroll_step`=1、`touch_scroll`=true、`status_bar_format`=`time\|chapter\|duration`、`auto_save_interval`=60、**`auto_scroll_interval`=5.0**、**`auto_scroll_step`=1**、**`auto_scroll_check_minutes`=10.0**、**`auto_scroll_check_seconds`=30**、`page_height`=24、`theme`=`default`（**预留未实现**）、`store_history`=true —— **13 键**（粗体四条是 2026-09-26 新增的自动翻页速度与防作弊校验；`check_minutes` 是 **float**，所以能设 `0.5` 分钟做快速验证） |
| `stats` | `daily_goal_minutes`=60、`show_heatmap`=true、`achievement_sound`=true、`geo_lookup`=true（关掉 = 完全不联网，地理成就停住） —— **4 键** |
| `library` | `novels_dir`（留空 = `~/novels`） —— **1 键** |
| `toc` | `patterns`（**追加**的章节标题正则，多个用 `\|` 分隔；内置规则始终生效）、`cache_dir`（派生缓存目录，默认跟随数据目录） —— **2 键** |

> 2026-09-25 删掉的 section：`translator`（9 键）、`translate`（11 键）、`vocab`（2 键）。
> 老 `settings.toml` 里这些键现在被收进 `config.Config.unknown`，`werd config` 列出设置时
> 逐键打一行 `warning: unknown setting '...' is ignored`（`cli._print_config` 里的 `rich` 输出），
> **不报错、不改写文件**。`tests/test_config.py::test_config_reports_unknown_keys_without_refusing_to_load`
> 与 `tests/test_cli.py::test_config_warns_about_unknown_and_invalid_keys` 守着这条行为。

## 仓库顶层结构（非包内容）

| 路径 | 说明 |
| --- | --- |
| `wreader/` | 包本体（**12** 个模块 + `data/achievements.json`） |
| `install.sh` | **一键安装脚本**（219 行，bash，幂等）：建 venv → `pip install -e .` → 往 `~/.bashrc`/`~/.zshrc` 写 `werd` 别名 → 自检版本号；`--dev` / `--no-alias` / `--help` |
| `tests/` | **11 个文件**（10 个测试文件 + `conftest.py`），**633** 项 |
| `tools/` | **开发期校验脚本**（**8** 个 + `README.md`）：文档锚点 / 数字对拍 / 注释覆盖 / 折行 / 绘制 / 配色 / 鼠标 / 成就；不参与打包 |
| `.clinerules/` | **AI 规则目录**：`memory-bank.md` = MemoryBank 维护协议，每次会话自动生效 |
| `memory-bank/` | **项目长期记忆**：6 个状态文件 + `README.md` 索引（协议在 `.clinerules/`） |
| `book/` | 开发用真实电子书样例（体积极大，不属于分发包，已被 `.gitignore`） |
| `pyproject.toml` | 打包、依赖、`[project.scripts]`、`[tool.pytest]`、`[tool.pyright]` |
| `README.md` / `README.en.md` / `使用指南.md` | 中文主文档 / 英文文档 / 小白教程（前两份的数字由 `tools/check_doc_numbers.py` 对拍，当前 ALL OK；**`使用指南.md` 不在脚本覆盖范围**） |
| `.vscode/settings.json` | 把 Pylance 与终端指向 `.venv` |
| `.gitignore` | Python / venv / 工具缓存 / `.DS_Store` / `*.log` / **`book/`**（**不排除** `memory-bank/` 与 `.clinerules/`） |
| `.git/` + 远端 | git 仓库本体（2026-09-22 建）。`origin` = `https://github.com/zhangziluo/wreader`，`main` 为默认分支 |
| `LICENSE` | MIT |

## 常用命令

```bash
# 安装（别的机器上复现时用；install.sh 幂等，重复跑安全）
git clone https://github.com/zhangziluo/wreader.git && cd wreader && ./install.sh
./install.sh --dev                            # 额外装 pytest（要跑测试时用）
./install.sh --no-alias                       # 不改 ~/.bashrc / ~/.zshrc

# 启动（新终端里 `werd` 来自 ~/.zshrc 的别名，见「开发环境」一节）
werd --version                             # werd 0.1.0
.venv/bin/werd list                        # 没配别名 / 没激活 venv 时的等价写法
source .venv/bin/activate                     # 或先激活 venv，之后直接敲 werd

# 功能
werd import <路径>            # 导入 txt/epub
werd list                     # 看书库（记下 book_id）
werd search <关键词>          # 模糊搜索；'#tag' 按标签
werd read <book_id>           # 开读（真 TTY）
werd continue                 # 最近打开阅读的三本书（附 id，抄去 read 续读）
werd stats [--json]           # 阅读统计（--json 里仍保留 vocab_count / translations 等遗留键）
werd achievements             # 成就清单与进度
werd config [<section.key> [value]] [--path] [--reset]
werd toc <book_id> [--rebuild]  # 查看目录（章节表）；--rebuild 强制重解析并覆写缓存
werd data export <文件>        # 把阅读时长 + 成就写成一个 JSON 包（换机、备份用）
werd data import <文件>        # 把包并进本机（只加不减；本机没有的书进 skipped）
werd prune                     # 摘掉正文文件已被删除的失效书目（每个命令启动前也会自动对账）
werd clear                     # 清空书库（书目 + 转换后的正文），保留阅读时长与成就
werd werd                     # 名字彩蛋（等同 werd word / werd --werd）

# 版本控制（2026-09-22 起，仓库已在 GitHub 上）
git status                                    # 动手前先看工作区是否干净
git diff                                      # "只加注释、没动逻辑"必须靠它证明，别再靠猜
git add -A && git commit -m "..."             # 提交
# 代理没开时**不要**推：`curl -x http://127.0.0.1:7897 https://github.com` 返回 200 才推得了；
# `git -c http.proxy= push` 这种"绕过"会挂在直连上（实测只能 pkill git-remote-https）

# 开发
.venv/bin/python -m pytest tests/              # 618 项，约 8~26 秒（随负载浮动）
.venv/bin/python -m pytest tests/test_reader.py              # 单文件
.venv/bin/python -m pytest -k "streak or heatmap"            # 按名字筛
npx pyright                                   # 期望 0 errors / 0 warnings / 0 informations
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 .venv/bin/python -m pytest   # 证明不联网

# 开发期校验脚本（tools/，详见 tools/README.md；都能从任意目录运行）
.venv/bin/python tools/check_docs.py              # 文档锚点 + 代码围栏配对（RESULT: OK）
.venv/bin/python tools/check_doc_numbers.py       # README 里的行数/测试项数与实际对拍（ALL OK）
.venv/bin/python tools/check_comments.py          # 注释覆盖（默认只报告；TOTAL: 3204）
.venv/bin/python tools/verify_wrap.py             # 折行属性（OK: 40077 checks passed）
.venv/bin/python tools/verify_draw.py             # 绘制不越界（OK: 140 draw checks passed）
.venv/bin/python tools/verify_colors.py           # 需 pty：script -q /dev/null .venv/bin/python tools/verify_colors.py
.venv/bin/python tools/verify_mouse.py            # 真 pty 端到端验证滚轮/触摸拖动（RESULT: 全部通过）
.venv/bin/python tools/verify_achievements.py     # 真 pty：帮助页 / 屏内 5 秒通知 / 中断恢复 / 名字彩蛋（RESULT: 全部通过）

# 不污染真实数据做实验
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
```

> 注意：`pyproject.toml` 里 `addopts = "-q --strict-markers"`，再手动加 `-q` 会变 `-qq`，
> 此时 pytest **只输出 `文件: 数量` 行，不打印 "N passed" 汇总**。想看到汇总就少加一个 `-q`。

## 测试基础设施

- **框架**：`pytest`（`tests/` 目录，**NO network / NO real data** 是铁律）。
- **`tests/conftest.py` 提供的 fixture**：
  - `isolated_home`（**autouse**）：把 `$WREADER_HOME` / `$WREADER_NOVELS_DIR` 指到 `tmp_path`，
    清掉 `$NR_HOME`、`$NR_NOVELS_DIR`、`$DEEPSEEK_API_KEY`，返回带 `write_book(name, lines)`
    辅助方法的 `Home` 对象 —— **所有测试都自动跑在沙箱里**。
  - `home`：同一沙箱的显式引用（想强调"这个测试要写数据"时用）。
  - `make_epub`：在 `tmp_path` 里构造最小 EPUB（`mimetype` / `META-INF/container.xml` /
    `content.opf` / `toc.ncx` / XHTML），测 `library.import_books` 的 epub 分支。
  - `imported`：先把一本样本书导入书库，返回 `werd import --json` 风格的结果字典。
  - `pager_factory`：造 `Pager` 用的（内部包了 `FakeStdscr`）。
  - `achievements_document`：一份**最小成就定义文档**（只含测试关心的条目），
    让成就测试不依赖 `wreader/data/achievements.json` 的真实条数。
- **阅读器测试**：`tests/test_reader.py` 自定义 `FakeStdscr` —— 只实现阅读器用到的那一小片
  curses API（`getmaxyx` / `addstr` / `addnstr` / `attrset` / `bkgd` / `timeout` …），
  **不依赖真 TTY**。要"按键输入"时 monkeypatch `reader._prompt` / `reader._confirm`，
  要"终端尺寸"时给 `FakeStdscr(height=..., width=...)`。
- **`tests/test_achievements.py`** 用 `monkeypatch` 替换 `geo.fetch_country` 与
  `env.detect_signals`，所以**连环境下探测都不联网**。
- **无测试的模块**：`wreader/lock.py`、`wreader/__init__.py` —— 前者靠被调用方
  （成就状态、书库索引）的用例间接覆盖，后者只有 `__version__`。
  想零风险打磨 `lock.py` 的 `fcntl.flock` 窗口，用 `tools/` 下临时加脚本调，**别把新脚本留在 `/tmp`**。

## 当前测试规模（2026-09-26 实测：`633 passed in 43.84s`）

| 文件 | 项数 | 侧重 |
| --- | --- | --- |
| `test_reader.py` | 213 | `Pager`、`FakeStdscr`、折行、滚轮 / 触摸、标记与浮层、**自动翻页（排期 / 调速 / 到末自停）**、**防作弊校验（出题 / 排期 / 作答与超时的两条出口 / 弹窗）** |
| `test_library.py` | 132 | 导入 / 书库索引 / 章节 / 正文读写 / `prune` 与 `clear` |
| `test_stats.py` | 70 | 时长统计、热力图、连续天数、`--json` |
| `test_achievements.py` | 51 | 表达式求值、事件指标、解锁与去重 / `merge_states` |
| `test_config.py` | 51 | `SCHEMA`、TOML 读写、旧配置迁移、**自动翻页四个键的默认值与类型** |
| `test_cli.py` | 45 | 命令分发与输出形态（含 `data` / `prune` / `clear`） |
| `test_geo.py` | 31 | 位置解析 / 缓存 / 离线降级 |
| `test_toc.py` | 18 | 章节正则 / epub 目录 / 缓存失效 |
| `test_env.py` | 14 | 云主机 / WSL / tmux / 可编辑安装信号 |
| `test_transfer.py` | 8 | 搬运包导出 / 合并 / 拒绝坏包 / 缺书计数 |

> 上表是**实测值**（逐文件 `pytest --collect-only`），总计 633；
> `tools/check_doc_numbers.py` 会把这些数字与 README 表格对拍（当前 `RESULT: ALL OK`）。
> 2026-09-25 之前是 **832** 项（含 `test_notes` / `test_translate` / `test_translator` / `test_vocab`），
> 2026-09-25 是 559 项 / 9 个测试文件。
> 2026-09-26 新增 `test_transfer.py` 8 项，其余增量来自 `test_library.py`（119 → 132）与
> `test_cli.py`（33 → 45）。
> 同日晚些的**自动翻页**再加 25 项（`test_reader.py` 174 → 199）+ 1 项（`test_config.py` 49 → 50）
> → 592 变 **618**；跑全量约 8~44 秒（实测 7.94 / 14.59 / 26.35 / 43.84 秒，随负载浮动，
> 别拿单次耗时当回归判据）。
> 紧接着的**防作弊校验**再加 14 项（`test_reader.py` 199 → 213）+ 1 项（`test_config.py` 50 → 51）
> → 618 变 **633**。`tests/test_reader.py` 的 `FakeStdscr` 为这次验证加了两个小钩子
> （`empty_key="timeout"` 让 `get_wch` 抛 `curses.error`、`timeout_value` 记住最后一次 `timeout()`），
> 默认行为不变。

## 开发用样例数据

- `book/`：真实电子书样例（**367 MB**，单文件最大 **147 MB**），开发时用来试导入与折行；
  已被 `.gitignore` 忽略，**绝对不要 `git add -f`** —— GitHub 单文件硬上限 100 MB，推上去必失败。
- 位置在仓库根的 `book/`：`werd import book/` 可直接导入。



# Tech Context — 技术栈、环境与命令

> 用什么技术、怎么装、什么约束、跑哪些命令。最后更新：2026-09-22。

## 运行时依赖（`pyproject.toml`）

| 依赖 | 用途 |
| --- | --- |
| `chardet` | 导入 txt 时探测编码（GB2312 / UTF-16 / …） |
| `rich` | CLI 表格、进度条、彩色输出；退出后的阅读摘要 |
| `deep-translator` | `google` 翻译后端 |
| `requests` | `deepseek` 后端（HTTP + SSE 流式解析） |
| `curses` | **标准库自带**（macOS/Linux），因此**故意不写进 dependencies** |
| `windows-curses` | 仅 Windows：`pip install -e ".[windows]"` |
| `pytest>=8` | 仅开发：`pip install -e ".[dev]"` |

## 开发环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 可编辑安装 + pytest
wreader --version                # wreader 0.1.0
```

- **本机实测环境**：macOS（darwin），`.venv/bin/python` 为 Python **3.13**，
  `$TERM=xterm-256color`，`curses.COLORS=256`、`COLOR_PAIRS=32767`。
- **IDE**：`.vscode/settings.json` 把解释器指向 `${workspaceFolder}/.venv/bin/python`，
  并把工作区根加进 `python.analysis.extraPaths`（否则 Pylance 报 `rich.console` 无法解析）。
- **`[tool.pyright]` 只对 pyright CLI 生效**，VS Code 的 Pylance 读的是 `.vscode/settings.json`；
  两者都指向同一个 `.venv`。

## 环境变量

```bash
WREADER_HOME=~/my-wreader-data     # 换掉整个数据目录（默认 ~/.wreader）
WREADER_NOVELS_DIR=~/my-novels     # 换掉小说正文目录（默认 ~/novels）
DEEPSEEK_API_KEY=sk-xxx            # 优先级低于 settings.toml 里的 translator.deepseek_api_key
NR_HOME / NR_NOVELS_DIR            # 改名前的旧名，兜底（仅在新名未设时读取）
```

## 文件位置

| 内容 | 路径 | 可被覆盖 |
| --- | --- | --- |
| 设置 | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| 书库索引 | `~/.wreader/library.json` | `$WREADER_HOME` |
| 生词本 | `~/.wreader/vocab.json` | `$WREADER_HOME` |
| 译文缓存 | `~/.wreader/cache/<book_id>/ch{N}_en.txt`、`ch{N}_bilingual.txt` | `translator.cache_dir` |
| 正文（UTF-8） | `~/novels/<书名>_utf8.txt` | `$WREADER_NOVELS_DIR`、`library.novels_dir` |

Windows 数据目录：`%APPDATA%\wreader`。

## settings.toml 的 5 个 section（共 21 个键）

| section | 键 |
| --- | --- |
| `reader` | `page_scroll_step`=1.0、`status_bar_format`=`time\|chapter\|duration`、`auto_save_interval`=60、`page_height`=24、`theme`=`default`（**预留未实现**）、`store_history`=true |
| `translator` | `backend`=`google`、`batch_size`=3000、`cache_dir`、`deepseek_api_key`、`auto_translate_chapter`=false、`source_language`=`auto`、`target_language`=`zh-CN`、`deepseek_model`=`deepseek-chat`、`deepseek_url` |
| `stats` | `daily_goal_minutes`=60、`show_heatmap`=true、`achievement_sound`=true |
| `vocab` | `highlight_in_reader`=true、`auto_add_on_mark`=true |
| `library` | `novels_dir`（留空 = `~/novels`） |

## 仓库顶层结构（非包内容）

| 路径 | 说明 |
| --- | --- |
| `wreader/` | 包本体（8 个模块 + `data/achievements.json`） |
| `tests/` | 8 个测试文件（含 `conftest.py`），494 项 |
| `.clinerules/` | **AI 规则目录**：`memory-bank.md` = MemoryBank 维护协议，每次会话自动生效 |
| `memory-bank/` | **项目长期记忆**：6 个状态文件 + `README.md` 索引（协议在 `.clinerules/`） |
| `book/` | 开发用真实电子书样例（体积极大，不属于分发包） |
| `pyproject.toml` | 打包、依赖、`[project.scripts]`、`[tool.pytest]`、`[tool.pyright]` |
| `README.md` / `README.en.md` / `使用指南.md` | 中文主文档 / 英文文档 / 小白教程（**结构一节尚未同步**） |
| `.vscode/settings.json` | 把 Pylance 与终端指向 `.venv` |
| `.gitignore` | Python / venv / 工具缓存（**不排除** `memory-bank/` 与 `.clinerules/`） |
| `LICENSE` | MIT |

## 常用命令

```bash
# 功能
wreader import <路径>            # 导入 txt/epub
wreader list                     # 看书库（记下 book_id）
wreader search <关键词>          # 模糊搜索；'#tag' 按标签
wreader read <book_id>           # 开读（真 TTY）
wreader translate <book_id>      # 命令行整本/整章翻译
wreader vocab [--review|--export anki|--search KW|--remove W|--page N|--per-page N]
wreader stats [--json]
wreader achievements
wreader config [<section.key> [value]] [--path] [--reset]

# 开发
pytest                                        # 494 项，约 5 秒
python -m pytest tests/test_reader.py -q      # 单文件
python -m pytest -k "streak or heatmap" -q    # 按名字筛
npx pyright                                   # 期望 0 errors / 0 warnings
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 pytest   # 证明不联网

# 不污染真实数据做实验
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
```

> 注意：`pyproject.toml` 里 `addopts = "-q --strict-markers"`，再手动加 `-q` 会变 `-qq`，
> 此时 pytest **只输出 `文件: 数量` 行，不打印 "N passed" 汇总**。想看到汇总就少加一个 `-q`。

## 测试基础设施（`tests/conftest.py`）

| Fixture | 作用 |
| --- | --- |
| `isolated_home`（autouse） | 把 `$WREADER_HOME`/`$WREADER_NOVELS_DIR` 指向 `tmp_path`，删掉旧环境变量与 `DEEPSEEK_API_KEY`，清 `config._CACHE*` 与 `translator` 全局后端 |
| `pager_factory` | 不依赖终端构造 `reader.Pager`（默认 `page_height=4` 方便断言分页） |
| `imported` | 真跑一遍 import，产出 `{result, ids, zh, en, home}` |
| `backend` | `RecordingBackend`，记录调用且不联网 |
| `window` / `FakeStdscr` | 实现阅读器真正用到的那部分 curses API（`getmaxyx`/`erase`/`addstr`/`move`…），并保存屏幕快照与 `writes` 记录 |
| `notebook` / `achievements_document` / `definitions` | 生词本、带统计的书库文档、自定义成就定义 |

测试纪律：**绝不联网、绝不碰真实数据、不需要终端**。唯一"注定失败"的路径是
`open_reader` 的 tty 检查，正好拿来断言那条报错。

## 当前测试规模（2026-09-22 实测）

| 文件 | 项数 |
| --- | --- |
| `tests/test_cli.py` | 33 |
| `tests/test_config.py` | 49 |
| `tests/test_library.py` | 116 |
| `tests/test_reader.py` | **115** |
| `tests/test_stats.py` | 76 |
| `tests/test_translator.py` | 74 |
| `tests/test_vocab.py` | 31 |
| **合计** | **494** |

> `README.md` 的"项目结构"一节仍写着 474 项与旧的源码行数，**已过期**，
> 下次改 README 时一并更正（详见 `progress.md`）。

## 样例数据

`book/` 目录放着开发用的真实电子书（不是包的一部分，体积很大）：
`史記.epub`、`易中天中华史：全24卷.epub`、`柏杨白话版资治通鉴 全72册.epub`、
`To Kill A Mockingbird.txt`、`book/zxcs/《诡秘之主》…txt` 等，另有若干
`卷X·… - 尹小林.txt`（古籍点校本，用来验证章节识别与文件名解析）。

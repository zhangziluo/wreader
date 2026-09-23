# Tech Context — 技术栈、环境与命令

> 用什么技术、怎么装、什么约束、跑哪些命令。最后更新：2026-09-23。

## 运行时依赖（`pyproject.toml`）

| 依赖 | 用途 |
| --- | --- |
| `chardet` | 导入 txt 时探测编码（GB2312 / UTF-16 / …） |
| `rich` | CLI 表格、进度条、彩色输出；退出后的阅读摘要 |
| `deep-translator` | **默认翻译引擎** `google` 的地基（故意**不**放进 extra：默认引擎的依赖做成可选 = 装完就坏） |
| `requests` | 四家 HTTP 引擎（baidu / youdao / tencent / deepseek） |
| `curses` | **标准库自带**（macOS/Linux），因此**故意不写进 dependencies** |
| `windows-curses` | 仅 Windows：`pip install -e ".[windows]"` |
| `argostranslate` | 仅**本地引擎** `local`：`pip install -e ".[local]"`（模型动辄几百 MB，所以默认不装） |
| `pytest>=8` | 仅开发：`pip install -e ".[dev]"` |

## 开发环境

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # 可编辑安装 + pytest
werd --version                # werd 0.1.0
```

- **本机实测环境**：macOS（darwin），`.venv/bin/python` 为 Python **3.13**，
  `$TERM=xterm-256color`，`curses.COLORS=256`、`COLOR_PAIRS=32767`。
- **IDE**：`.vscode/settings.json` 把解释器指向 `${workspaceFolder}/.venv/bin/python`，
  并把工作区根加进 `python.analysis.extraPaths`（否则 Pylance 报 `rich.console` 无法解析）。
- **`[tool.pyright]` 只对 pyright CLI 生效**，VS Code 的 Pylance 读的是 `.vscode/settings.json`；
  两者都指向同一个 `.venv`。
- **新终端里怎么敲 `werd`**（2026-09-22 补）：它是**项目内** `.venv` 的可编辑安装，
  `.venv/bin` **不在**默认 PATH 上，且 `~/.zprofile`/`~/.zshenv`/`/etc/paths*` 都没配它，
  所以**重开终端后 `werd` 默认不可用**（实测干净 shell 里 `command -v werd` 找不到）。
  为此新建了 `~/.zshrc`（此前不存在），里面只加了一行**别名**：
  `alias werd="/Users/zhangziluo/Downloads/wreader/.venv/bin/werd"`。
  别名只在交互式 shell 生效，**`python3` / `pip` 不受影响**。
  ⚠️ **故意不用 PATH 前置**：实测把 `.venv/bin` 前置进 PATH 后，新终端的
  `python3` 会变成 `.venv/bin/python3`、`pip` 会变成 `.venv/bin/pip`，会干扰其它 Python 项目。
  数据（`~/.wreader`、`~/novels`）与 `.venv` 无关，所以换环境不会丢书和进度。
  没有别名时的两种等价写法：`.venv/bin/werd ...`，或
  `cd <项目> && source .venv/bin/activate` 之后再敲 `werd`。
  这三种办法与"为什么新终端找不到 werd"已写进面向用户的文档
  **《使用指南.md》的「关掉终端之后：下次怎么打开 werd」一节**（2026-09-22）。
- **Linux 上同理，重启后两行开读**（2026-09-22 补，用户诉求「重启之后一到两行就能开 werd 看书」）：
  bash 写 `~/.bashrc`、zsh 写 `~/.zshrc`，内容都是
  `alias werd="$HOME/Downloads/wreader/.venv/bin/werd"`（**只配一次**）。
  之后重启再开终端，日常就是两行：`werd continue`（列出最近打开阅读的**三本**书，抄 id）
  → `werd read <id>`。数据在 `~/.wreader` / `~/novels`，与 `.venv` 无关，
  所以重启机器 / 换环境都不会丢书和进度。

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
| 成就状态 | `~/.wreader/achievements.json`（另有 `.lock` 锁文件；坏掉时被改名为 `.broken`） | `$WREADER_HOME` |
| 生词本 | `~/.wreader/vocab.json` | `$WREADER_HOME` |
| 笔记 | `~/.wreader/notes/<book_id>.md`（一本书一个 markdown）+ `index.json`（派生索引）+ `<book_id>.draft.md`（未提交草稿）+ `index.json.lock`（锁文件） | `$WREADER_HOME` |
| 译文缓存 | `~/.wreader/cache/<book_id>/ch{N}_en.txt`、`ch{N}_bilingual.txt` | `translator.cache_dir` |
| 目录缓存 | `~/.wreader/cache/<book_id>_toc.json`（随正文 mtime 自动失效，可随时删） | 同 `translator.cache_dir` |
| 正文（UTF-8） | `~/novels/<书名>_utf8.txt` | `$WREADER_NOVELS_DIR`、`library.novels_dir` |

Windows 数据目录：`%APPDATA%\wreader`。

## settings.toml 的 7 个 section（共 36 个键）

| section | 键 |
| --- | --- |
| `reader` | `page_scroll_step`=1.0、`page_overlap`=3、`wheel_scroll_step`=1、`touch_scroll`=true、`status_bar_format`=`time\|chapter\|duration`、`auto_save_interval`=60、`page_height`=24、`theme`=`default`（**预留未实现**）、`store_history`=true |
| `translator` | `backend`=**`google`（旧字段：`engine` 为空时的回退）**、`batch_size`=3000、`cache_dir`、`deepseek_api_key`、`auto_translate_chapter`=false、`source_language`=`auto`、`target_language`=`zh-CN`、`deepseek_model`=`deepseek-chat`、`deepseek_url` |
| `translate` | `engine`（**空 = 回退 `translator.backend`**）、`baidu_appid`、`baidu_secret`、`youdao_appid`、`youdao_secret`、`tencent_secret_id`、`tencent_secret_key`、`tencent_region`=`ap-beijing`、`deepseek_api_key`、`deepseek_model`、`deepseek_url` |
| `stats` | `daily_goal_minutes`=60、`show_heatmap`=true、`achievement_sound`=true |
| `vocab` | `highlight_in_reader`=true、`auto_add_on_mark`=true |
| `library` | `novels_dir`（留空 = `~/novels`） |
| `toc` | `patterns`（**追加**的章节标题正则，多个用 `\|` 分隔；内置规则始终生效） |

> `[translate]` 的密钥以**明文**存在 `settings.toml` 里（纯文本是项目的硬约束）。
> DeepSeek 的 key 还有个更安全的选择：留空并 `export DEEPSEEK_API_KEY=...`。

## 仓库顶层结构（非包内容）

| 路径 | 说明 |
| --- | --- |
| `wreader/` | 包本体（9 个模块 + `data/achievements.json`） |
| `install.sh` | **一键安装脚本**（219 行，bash，幂等）：建 venv → `pip install -e .` → 往 `~/.bashrc`/`~/.zshrc` 写 `werd` 别名 → 自检版本号；`--dev` / `--no-alias` / `--help` |
| `tests/` | 9 个测试文件（含 `conftest.py`），570 项 |
| `tools/` | **开发期校验脚本**（7 个 + `README.md`）：文档锚点/数字对拍/注释覆盖/折行/绘制/配色/鼠标；不参与打包 |
| `.clinerules/` | **AI 规则目录**：`memory-bank.md` = MemoryBank 维护协议，每次会话自动生效 |
| `memory-bank/` | **项目长期记忆**：6 个状态文件 + `README.md` 索引（协议在 `.clinerules/`） |
| `book/` | 开发用真实电子书样例（体积极大，不属于分发包） |
| `pyproject.toml` | 打包、依赖、`[project.scripts]`、`[tool.pytest]`、`[tool.pyright]` |
| `README.md` / `README.en.md` / `使用指南.md` | 中文主文档 / 英文文档 / 小白教程（2026-09-22 已同步行数与测试项数，并补上"新终端怎么打开"一节） |
| `.vscode/settings.json` | 把 Pylance 与终端指向 `.venv` |
| `.gitignore` | Python / venv / 工具缓存 / `.DS_Store` / `*.log` / **`book/`**（**不排除** `memory-bank/` 与 `.clinerules/`） |
| `.git/` + 远端 | git 仓库本体（2026-09-22 建）。`origin` = `https://github.com/zhangziluo/wreader`，`main` 为默认分支 |
| `LICENSE` | MIT |

## 常用命令

```bash
# 安装（别的机器上复现时用；install.sh 幂等，重复跑安全）
git clone https://github.com/zhangziluo/wreader.git && cd wreader && ./install.sh
./install.sh --dev                            # 额外装 pytest（要跑测试时）
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
werd translate <book_id>      # 命令行整本/整章翻译
werd vocab [--review|--export anki|--search KW|--remove W|--page N|--per-page N]
werd stats [--json]
werd achievements
werd config [<section.key> [value]] [--path] [--reset]
werd config translate           # 交互式向导：选翻译引擎 + 填密钥 + 当场自查
werd toc <book_id> [--rebuild]  # 查看目录（章节表）；--rebuild 强制重解析并覆写缓存

# 版本控制（2026-09-22 起，仓库已在 GitHub 上）
git status                                    # 动手前先看工作区是否干净
git diff                                      # "只加注释、没动逻辑"必须靠它证明，别再靠猜
git add -A && git commit -m "..."             # 提交
git push                                      # 推 origin/main；HTTPS + Keychain，不弹密码
git -c http.proxy= push                       # 本机代理 127.0.0.1:7897 没开时绕过
GIT_TERMINAL_PROMPT=0 git push                # 自动化场景：认证失败就立刻报错，不卡住
git check-ignore -v book                      # 确认 `book/` 仍被忽略（切勿 `git add -f`）

# 开发
pytest                                        # 545 项，约 3~25 秒
python -m pytest tests/test_reader.py -q      # 单文件
python -m pytest -k "streak or heatmap" -q    # 按名字筛
npx pyright                                   # 期望 0 errors / 0 warnings
HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 pytest   # 证明不联网

# 开发期校验脚本（tools/，详见 tools/README.md；都能从任意目录运行）
python tools/check_docs.py                    # 文档锚点 + 代码围栏配对
python tools/check_doc_numbers.py             # README 里的行数/测试项数与实际对拍
python tools/check_comments.py                # 注释覆盖（默认只报告；--strict 才是门禁）
python tools/verify_wrap.py                   # 折行属性（期望 OK: 40077 checks passed）
python tools/verify_draw.py                   # 绘制不越界（期望 OK: 420 draw checks passed）
python tools/verify_colors.py                 # 需 pty（见 tools/README.md 的 script 用法）
python tools/verify_mouse.py                  # 真 pty 端到端验证滚轮/触摸拖动（期望 RESULT: 全部通过）
python tools/verify_notes.py                  # 真 pty 端到端验证标记 + 笔记面板（期望 RESULT: 全部通过）
python tools/verify_translate.py              # 真 pty 验证 t 的未配置提示 + 配置向导落盘（期望 RESULT: 全部通过）

# 不污染真实数据做实验
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
```

> 注意：`pyproject.toml` 里 `addopts = "-q --strict-markers"`，再手动加 `-q` 会变 `-qq`，
> 此时 pytest **只输出 `文件: 数量` 行，不打印 "N passed" 汇总**。想看到汇总就少加一个 `-q`。

## 测试基础设施（`tests/conftest.py`）

| Fixture | 作用 |
| --- | --- |
| `isolated_home`（autouse） | 把 `$WREADER_HOME`/`$WREADER_NOVELS_DIR` 指向 `tmp_path`，删掉旧环境变量与 `DEEPSEEK_API_KEY`，清 `config._CACHE*` 与 `translator` 全局后端 |
| `pager_factory` | 不依赖终端构造 `reader.Pager`（默认 `page_height=4`、`page_overlap=0`，让分页数学好断言） |
| `imported` | 真跑一遍 import，产出 `{result, ids, zh, en, home}` |
| `backend` | `RecordingBackend`，记录调用且不联网 |
| `window` / `FakeStdscr` | 实现阅读器真正用到的那部分 curses API（`getmaxyx`/`erase`/`addstr`/`move`…），并保存屏幕快照与 `writes` 记录 |
| `notebook` / `achievements_document` / `definitions` | 生词本、带统计的书库文档、自定义成就定义 |

测试纪律：**绝不联网、绝不碰真实数据、不需要终端**。唯一"注定失败"的路径是
`open_reader` 的 tty 检查，正好拿来断言那条报错。

## 当前测试规模（2026-09-23 实测）

| 文件 | 项数 |
| --- | --- |
| `tests/test_achievements.py` | **35** |
| `tests/test_cli.py` | 49 |
| `tests/test_config.py` | 51 |
| `tests/test_library.py` | 119 |
| `tests/test_notes.py` | **30** |
| `tests/test_reader.py` | **198** |
| `tests/test_stats.py` | 70 |
| `tests/test_toc.py` | 18 |
| `tests/test_translate.py` | **49** |
| `tests/test_translator.py` | **77** |
| `tests/test_vocab.py` | 31 |
| **合计** | **727** |

> **两份 README 的结构数字已与代码同步**（最近一次：2026-09-23 笔记 Phase 3：
> `notes.py` **558**、`lock.py` **81** 两个新模块，`cli.py` **1450**、`reader.py` **3515**、
> `achievements.py` **715**（文件锁抽走后变短）、`test_notes.py` **30**、总数 **727**）。
> 以后改完代码或测试，跑一句 `tools/check_doc_numbers.py` 就能查出漂移 ——
> 它把 README 声称的数字与真实文件行数、pytest 实际收集数逐项对拍（当前 **ALL OK**）。
> ⚠️ **子包里的文件不在它的校验范围内**（`wreader/translate/*` 的名字会跟包根撞车），
> 所以那些行数只记在上面「模块职责与规模」里，README 中不写。

## 样例数据

`book/` 目录放着开发用的真实电子书（不是包的一部分，体积很大）：
`史記.epub`、`易中天中华史：全24卷.epub`、`柏杨白话版资治通鉴 全72册.epub`、
`To Kill A Mockingbird.txt`、`book/zxcs/《诡秘之主》…txt` 等，另有若干
`卷X·… - 尹小林.txt`（古籍点校本，用来验证章节识别与文件名解析）。

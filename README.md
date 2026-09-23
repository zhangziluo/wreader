# wreader · 终端小说阅读器

> 在终端里读 txt / epub 小说：中英双语对照、生词本、阅读统计与成就。
> 纯 Python 命令行工具，书存在本地，进度、生词和统计都记得住。

不用鼠标，不用装 GUI。把小说丢进一个文件夹，敲一行命令，就能在终端里一页一页往下读；
读到不认识的词按一个键就查、顺手收进生词本；读完关掉终端，下次打开自动回到原来的位置。

**第一次用？直接看 [使用指南.md](使用指南.md)** —— 从安装 Python 开始，一步一步带你读出第一页。

🌐 **English**: [README.en.md](README.en.md)

---

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [新开一个终端后怎么用 werd](#新开一个终端后怎么用-werd)
- [快速开始](#快速开始)
- [命令手册](#命令手册)
- [阅读器快捷键](#阅读器快捷键)
- [设置项](#设置项)
- [文件位置](#文件位置)
- [数据格式](#数据格式)
- [成就清单](#成就清单)
- [项目结构](#项目结构)
- [开发说明](#开发说明)
- [常见问题](#常见问题)
- [已知问题](#已知问题)
- [许可](#许可)
- [相关文档](#相关文档)

---

## 特性

| 功能 | 说明 |
| --- | --- |
| 📚 导入 | 递归扫描目录，认 `.txt` / `.epub`；自动识别编码（BOM 认 UTF-8/UTF-16/UTF-32 → chardet → UTF-8 → GB18030），统一转成 UTF-8 存好，之后再也不碰编码问题 |
| 🆔 去重 | 书号是正文的 SHA-1，同一本书重复导入直接跳过，不会出现两份 |
| 🔖 章节 | 导入时自动识别章节标题（`第一章`、`Chapter 1` 等）；阅读中按 `Tab` 呼出**目录浮层**（可搜索过滤、回车跳转），也能用 `werd toc <id>` 单独看；epub 会优先采用它自带的 `nav` / `toc` 标题 |
| 🔍 搜索 | 模糊搜索书库：标题、作者、标签都认，还能首字母跳跃匹配（`hptr` 找得到 *Harry Potter*） |
| 📖 阅读器 | curses 分页阅读：跳行、跳章、搜索高亮、书签、状态栏、自动保存进度；按终端宽度自动折行（汉字按 2 列算），配色跟随终端主题与透明背景 |
| 🌍 三种视图 | `中文` / `英文` / `双语对照`，按 `l` 循环切换；本来就是中文的书看中文视图不需要翻译，离线也能读 |
| 🈶 翻译 | **可插拔引擎**：Google（免密钥，默认）/ 百度 / 有道智云 / 腾讯云 / DeepSeek / 本地 Argos；`werd config translate` 向导式配置。章节级翻译 + 磁盘缓存，译一次永久复用 |
| 📝 生词本 | 阅读中按 `v` 查词并收录，阅读器里自动给生词加下划线；支持搜索、复习、删除、导出 Anki |
| 🗒️ 笔记 | 按 `m` 在**当前屏**里用 `h/j/k/l`（或方向键）选中一段文字（反色高亮），`y` 复制；按 `o` 展开**笔记面板**（下方 25%）：上半只读引用选中的原文，下半是编辑区，`Tab` 切换焦点，`Ctrl+S` 保存。⚠️ 目前只存在内存里，落盘见「已知问题」 |
| 📊 统计 | 总时长 / 今日 / 本周 / 本月 / 每日目标 / 连续天数 / 30 天热力图；`--json` 输出给脚本用 |
| 🏆 成就 | 28 个成就（开卷有益、深夜书虫、百日筑基、周末战士……），事件驱动解锁，命令行按分类显示进度条，解锁时有动画和提示音 |
| ⚙️ 配置 | 一个 `settings.toml` 管全部，`werd config` 读写并带拼写纠错提示；旧版 `config.json` 自动迁移 |

---

## 环境要求

- **Python 3.11 或更高**（用到了标准库 `tomllib`）
- **macOS / Linux**：`curses` 是 Python 自带的，开箱即用
- **Windows**：需要额外装 `windows-curses`（见安装一节）
- 终端需要支持 UTF-8（读中文书必备；macOS 自带终端、iTerm2、Windows Terminal 都可以）
- 用 Google 翻译或 `werd translate` 时需要联网；只想本地读书的话全程离线可用

运行时会用到这几个第三方库，安装时会自动装好：
`rich`（表格和进度条）、`chardet`（编码识别）、`deep-translator`（Google 翻译）、`requests`（DeepSeek 翻译）。

---

## 安装

### 三条命令装好（推荐）

需要 **Python 3.11+** 和 `git`：

```bash
git clone https://github.com/zhangziluo/wreader.git
cd wreader
./install.sh
```

`./install.sh` 会自动把剩下的活全干完：建 `.venv` 虚拟环境 → 装 4 个依赖 →
把 `werd` 命令**配好别名**（写进 `~/.bashrc` 或 `~/.zshrc`，重复运行不会写第二遍）→ 自检版本号。
按它最后的提示 `source ~/.zshrc`（或干脆重开一个终端）就能用了：

```bash
werd --version        # werd 0.1.0
```

装的时候可以加参数：

| 参数 | 作用 |
| --- | --- |
| `./install.sh --dev` | 额外装上 `pytest`（要改代码 / 跑测试时才需要） |
| `./install.sh --no-alias` | 不动 `~/.bashrc` / `~/.zshrc`，之后用完整路径调用 |
| `./install.sh --help` | 看用法 |

### 手动安装（脚本跑不动、或想自己来）

<details>
<summary><b>展开看手动步骤（Windows 用户走这条）</b></summary>

在项目根目录（也就是 `pyproject.toml` 和 `wreader/` 所在的那一层）执行：

```bash
# 1. 建虚拟环境（推荐，避免污染系统 Python）
python3 -m venv .venv

# 2. 激活它
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows (PowerShell / CMD)

# 3. 以可编辑模式安装
pip install -e .
```

Windows 用户请改用：

```bash
pip install -e ".[windows]"
```

装完之后，**在当前这个终端窗口里**就有了 `werd` 命令：

```bash
werd --version
# werd 0.1.0
```

</details>

### 新开一个终端后怎么用 werd

`werd` 装在**项目自己的 `.venv`** 里，而 `.venv/bin` 默认不在系统的 `PATH` 上 ——
所以**关掉终端再新开一个窗口，直接敲 `werd` 会报 `command not found`**。
这不是装坏了，是正常的。

**用 `./install.sh` 装的话不用管这一步**：它已经往 `~/.bashrc` / `~/.zshrc` 写好别名了，
重开终端就能直接用（唯一可能要做的只是 `source ~/.zshrc`）。
下面这张表是给「当初用了 `--no-alias`」或「手动装的」人看的：

| 办法 | 每次要敲什么 | 说明 |
| --- | --- | --- |
| **① 配一次别名**（推荐） | `werd read <id>` | 配一次，此后**所有新终端**都能直接用 |
| **② 用完整路径** | `<项目路径>/.venv/bin/werd read <id>` | 不改任何配置文件 |
| **③ 每次激活虚拟环境** | `cd <项目路径>` → `source .venv/bin/activate` → `werd ...` | 顺手，但每个新窗口都要来一遍 |

办法①在 macOS / Linux（zsh）下就是往 `~/.zshrc` 追加一行（把路径换成你的实际位置）：

```bash
echo 'alias werd="$HOME/Downloads/wreader/.venv/bin/werd"' >> ~/.zshrc
source ~/.zshrc                       # 立刻生效；或者干脆重开一个窗口
werd --version                     # 验证：应输出 werd 0.1.0
```

用 bash 的话把 `~/.zshrc` 换成 `~/.bashrc`；Windows PowerShell 则在 `$PROFILE` 里定义一个同名函数。

> ⚠️ **不要把 `.venv/bin` 前置进 `PATH`**（`export PATH=".../.venv/bin:$PATH"`）。
> 那样 `werd` 确实能用了，但新终端里的 `python3` 和 `pip` 也会一起变成这个虚拟环境的版本，
> 会干扰你在其它 Python 项目上的工作；别名只多一条命令，没有这个副作用。
>
> `install.sh` 也守着这条：它始终用 `.venv/bin/python -m pip` 装东西，
> **从不**把 `.venv/bin` 加进 `PATH`。

> **只是临时用一下？** 也可以完全不配置，直接把 `werd xxx` 换成
> `python -m wreader.cli xxx`——本文档里两种写法等价。
> 面向新手的详细版（含 Windows 写法、以及"为什么书和进度不会丢"）见
> [使用指南.md](使用指南.md) 的「关掉终端之后」一节。

### 从旧版 `nr` 升级

这个工具以前叫 `nr`。装过旧版的人**不需要手动搬数据**：第一次运行 `werd` 时，如果 `~/.wreader`
还不存在而 `~/.nr` 存在，老的整个目录会被搬过去——设置、书库索引、生词本、译文缓存都在里面——
老目录随即消失。几个老名字的兼容情况：

| 老名字 | 现在 | 兼容方式 |
| --- | --- | --- |
| 命令 `nr` | `werd` | 重新 `pip install -e .`，旧命令随旧发行版一起卸载 |
| `python -m nr.cli` | `python -m wreader.cli` | 模块名随包名改了，老写法不再可用 |
| `$NR_HOME` / `$NR_NOVELS_DIR` | `$WREADER_HOME` / `$WREADER_NOVELS_DIR` | 新变量没设时，老变量仍然生效 |
| `~/.nr` | `~/.wreader` | 首次运行自动搬迁（见上） |
| `settings.toml` 里写死的 `cache_dir = "~/.nr/cache"` | `"~/.wreader/cache"` | 老值仍按"跟随数据目录"解析，不会指向废弃路径 |

Python 包名也从 `nr` 改成了 `wreader`：`from nr import library` → `from wreader import library`，
`pip show wreader` 看到的是新发行版名。想干净重来的话删掉 `~/.wreader` 即可。

---

## 快速开始

四步就能开始读书：

```bash
# ① 把书放好（或者直接指向你已有的下载目录）
#    文件名写成「作者-书名.txt」最省事，例如：刘慈欣-三体.txt

# ② 导入书库
werd import ~/Downloads/books

# ③ 看看书库里有什么，把 id 记下来
werd list

# ④ 开读（把 id 换成上一步看到的）
werd read 3e027c4de949

# 忘了上次读到哪本？它会列出最近打开阅读的三本书
werd continue
```

`werd import` 的真实输出长这样：

```
imported 2 book(s), skipped 0 duplicate(s), 0 failed
  + ab912556b66b  《Nameless》 unknown · 7 行 · 12 字 · ascii · 2 章
  + 3e027c4de949  《三体》 刘慈欣 · 281 行 · 2000 字 · utf-8 · 41 章
```

`werd list` 的真实输出长这样：

```
                              library (2 book(s))
┏━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ # ┃ id           ┃ title    ┃ author  ┃ progress ┃ words ┃
┡━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ 1 │ ab912556b66b │ Nameless │ unknown │     0.0% │    12 │
│ 2 │ 3e027c4de949 │ 三体     │ 刘慈欣  │     0.0% │  2000 │
└───┴──────────────┴──────────┴─────────┴──────────┴───────┘
```

读到一半退出的样子（`q` 键）：

```
[双语对照 · 停在 120/281 行 (42.7%) · 本次 12:30 · 书签 2 个]
```

---

## 命令手册

一句话总览：

| 命令 | 作用 |
| --- | --- |
| `werd import <路径>` | 扫描文件或目录，把 txt/epub 导入书库 |
| `werd list` | 列出书库里的书 |
| `werd search <关键词>` | 模糊搜索书名 / 作者 / 标签 |
| `werd read <book_id>` | 打开分页阅读器 |
| `werd continue` | 列出最近打开阅读的三本书（附 id，抄去 `read` 即可续读） |
| `werd translate <book_id>` | 把整本书逐章翻译并缓存 |
| `werd vocab` | 生词本：列表 / 复习 / 搜索 / 删除 / 导出 |
| `werd stats` | 阅读统计 + 热力图（`--json` 给脚本用） |
| `werd achievements` | 成就清单与解锁进度 |
| `werd toc <book_id>` | 查看某本书的目录（章节 + 进度百分比）；`--rebuild` 强制重解析 |
| `werd config` | 查看 / 修改设置 |

退出码约定：成功 `0`；参数有误、找不到东西（`no book matches ...`）、
或翻译出现失败章节时返回 `1`（`Ctrl-C` 中断是 `130`）。
所有错误都以 `error: ...` 的形式打印，不会甩出 Python traceback。

### `werd import <路径>`

```bash
werd import ~/Downloads/books        # 递归扫描整个目录
werd import ~/Downloads/三体.txt     # 也可以直接导入单个文件
```

- 只认 `.txt` 和 `.epub`，隐藏文件（macOS 的 `._xxx`、`.DS_Store`）自动跳过。
- `.epub` 优先调用系统里的 `ebook-convert`（Calibre）或 `epub2txt`；都没有时用内置解析器（标准库 `zipfile` + `ElementTree`，按 spine 顺序读正文）。
- 标题和作者从文件名猜，支持 `作者-书名`、`[作者] 书名`、`《书名》（校对版全本）作者：某人`、以及单纯的书名；
  文件名结尾的 `（校对版全本）` / `(annotated)` 这类括号注释会自动剥掉，猜不出来时作者记为 `unknown`。
- 转换后的 UTF-8 正文写进小说目录（`~/novels/<书名>_utf8.txt`），同名自动加 `(2)` 后缀。
- 重复导入同一本书会显示 `skipped N duplicate(s)`，不会重复占地方。

### `werd list`

```bash
werd list
```

表格里的 `progress` 是阅读进度百分比，`words` 是按中文习惯格式化的字数（`5.7万`、`1.2亿`）。
书库为空时会告诉你索引文件和小说的目录在哪。

### `werd search <关键词>`

```bash
werd search 三体          # 中文关键词
werd search tolkien       # 作者名，大小写无所谓
werd search hptr          # 首字母跳跃匹配 → Harry Potter
werd search '#fantasy'    # 带 # 前缀表示只搜标签
```

匹配优先级：完全相等 > 前缀 > 包含（越靠前分越高）> 子序列匹配。书名权重是作者的 2 倍。
没找到就返回 `1` 并提示 `no book matches ...`。

### `werd read <book_id>`

整本书的核心体验，详细按键见[阅读器快捷键](#阅读器快捷键)。

- 打开时自动检测书的语言，中文书默认进中文视图，英文书默认进英文视图（检测靠 CJK 字符占比，离线纯本地计算）。
- 每 60 秒自动保存一次阅读位置（可关），退出时再完整保存一次。
- 退出时把这次会话的时长、读过的行数写进统计，并把 `session_end` 事件交给成就引擎
  （本次读过的**行区间**会按行号去重地折算成字数，所以同一页读两遍不会重复计数）。
- 每次启动 `werd` 都会记一次 `daily_open` 事件（「百日筑基」「清晨第一眼」看的就是它），
  `werd import` 记 `book_add`，`werd translate` 之后再让引擎重算一次。
- **需要真正的交互式终端**，重定向或管道里跑会报错：
  `error: werd read needs an interactive terminal (a tty on stdin and stdout)`

### `werd continue`

```bash
werd continue        # 最近打开阅读的三本书（附 id）
```

按 `last_read`（退出阅读器时写入的时间戳）倒序排列，只列**真正读过**的书，最多三本：

```
最近在读 (recent)
┏━━━┳━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ # ┃ id           ┃ title ┃ author ┃ progress ┃ words ┃
┡━━━╇━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ 1 │ f1ba2379642f │ 呐喊  │ 鲁迅   │     0.0% │     8 │
│ 2 │ 421d50d43552 │ 基地  │ 艾萨克 │     0.0% │     8 │
│ 3 │ a43433e88bb3 │ 三体  │ 刘慈欣 │     0.0% │     8 │
└───┴──────────────┴───────┴────────┴──────────┴───────┘
```

把表格里的 `id` 抄给 `werd read` 就能接着上次的位置读。一本都没读过时它会提示你先
`werd list` 挑一本（或 `werd import` 导入新书），退出码仍是 `0`。

> 配上别名（见[新开一个终端后怎么用 werd](#新开一个终端后怎么用-werd)）之后，
> 重开终端接着读书就是两行：`werd continue` 看最近在读，`werd read <id>` 开读。

### `werd translate <book_id>`

```bash
werd translate 3e027c4de949
```

适合"想一次性把整本书翻译好，以后随手切双语"的场景。真实输出：

```
translating 《三体》 · 41 chapter(s) · backend google · batch 3000 chars
translated 41, skipped 0 (already cached), 0 failed
cache: /Users/you/.wreader/cache/3e027c4de949
```

- **按章缓存**，已经译好的章节会自动跳过，所以中途 Ctrl-C 了再跑一遍就是断点续传。
- 单章失败不会中断整轮，失败的章节号会列出来，下次重跑自动补上。
- 网络不通会直接中止（继续跑只会浪费时间）。

### `werd vocab`

不带参数时列出笔记（每页 20 条，新的在前）：

```bash
werd vocab                          # 查看（第 1 页）
werd vocab --page 2 --per-page 50    # 翻页，调整每页条数
werd vocab --search 公认             # 按含义反查单词（词 / 释义 / 例句都会搜）
werd vocab --review                  # 复习模式：打乱顺序，先看单词再按回车核对释义
werd vocab --remove ephemeral        # 删掉一个词
werd vocab --export anki > deck.txt  # 导出 Anki 制表符格式，可直接导入 Anki
```

`--review` 在真终端里是交互式的（回车看释义，`q` 停）；如果输出被重定向，它会降级成"一次性把所有词和释义都打印出来"。
`--export anki` 刻意不走 rich，用纯 `stdout` 输出，保证制表符不会被美化掉。

### `werd stats`

```bash
werd stats          # 人类可读的表格 + 热力图
werd stats --json   # 同一个 dict 的原始 JSON，给脚本/看板用
```

真实输出：

```
总阅读时长 12小时34分钟
今日 45分钟 · 本周 5小时12分钟 · 本月 12小时34分钟
每日目标 1小时 · 今日 75% ✓
连续 3 天（每天 ≥30 分钟） · 读完 2 本 · 生词 128 个 · 用过翻译 46 次
最近 30 天（2026-08-23 → 2026-09-21，每列一周，周一开始）
一   ░ · · ▒ ▓
二   · ▒ ░ · █
...
强度：·0 ░<20m ▒<40m ▓<1h █1h+
```

- 热力图每一列是一周（周一在上、周日在下），没数据的格子留白。
- `--json` 的顶层键：`generated_at`、`today`、`total_seconds`、`total`、`today_seconds`、`week_seconds`、`month_seconds`、`daily_goal_seconds`、`goal_met`、`streak_days`、`streak_min_seconds`、`books_read`、`finished_books`、`vocab_count`、`translations`、`night_seconds`、`longest_session_seconds`、`achievements`、`books`、`daily`、`heatmap`、`heatmap_grid`。
- 表格和 JSON 是同一份数据渲染的，不会出现"两边数字不一致"。

### `werd achievements`

```bash
werd achievements
```

真实输出：

```
已解锁 1/28
  🏆 🗄️ 书库初成 书库里添加第 1 本书  解锁于 2026-09-21T16:13:43

进行中
  阅读习惯
    ░░░░░░░░░░░░░░  ⏱️ 初窥门径 0分钟/1小时  累计阅读满 1 小时
    ░░░░░░░░░░░░░░  🧱 百日筑基 3/100  连续 100 天打开 werd
    ...
  数据积累
    ██████░░░░░░░░  ✒️ 万字户 4200/10000  累计阅读 1 万字
    ...
```

行首数字是"已解锁 / 总数"，解锁的会带时间戳；未解锁的按**分类**分组，每条一个进度条。

### `werd config`

```bash
werd config                            # 打印全部设置（值 / 默认值 / 来源文件）
werd config --path                     # 只打印设置文件路径
werd config reader.page_height         # 读一项
werd config reader.page_height 30      # 写一项（立即存盘）
werd config translate                  # 交互式配置翻译引擎与密钥（向导）
werd config --reset                    # 全部恢复默认
```

真实交互：

```
$ werd config reader.page_height
reader.page_height = 24

$ werd config reader.page_height 30
reader.page_height = 30 (saved)

$ werd config reader.pag_height 20
error: unknown setting 'reader.pag_height' (did you mean 'reader.page_height'?)
```

设置用**点分路径**（`reader.page_height`），旧版 `config.json` 里的扁平名字（`page_height`、`novels_dir`……）依然能用，会自动迁移到对应 section。
写错名字会给出拼写建议，而不是把错键写进文件。类型不匹配（比如给布尔项写 `abc`）也会报错并保持原样。

### `werd toc <book_id>`

```bash
werd toc 3e027c4de949            # 列出目录：章节名 + 起始行 + 进度百分比
werd toc 3e027c4de949 --rebuild  # 忽略缓存，重新解析正文并覆写缓存
```

- 章节来自**正则识别标题**（`第一章`、`Chapter 1`、`第N节`、`卷X` 等内置规则）；
  epub 会优先采用它自带的 `nav.xhtml` / `toc.ncx` 标题（拿不到行号时再退回正则）。
- 结果缓存在 `~/.wreader/cache/<book_id>_toc.json`，**转换后正文的修改时间一变就自动重建**，
  所以不需要手动清缓存；想立刻重建用 `--rebuild`。
- 识别不出章节、或想认别的写法（例如 `### 楔子`），在 `settings.toml` 的 `[toc]` 里追加正则：
  ```bash
  werd config toc.patterns '^### |^第.+回'
  ```
- 阅读器里按 `Tab` 打开的目录与这里同源（多一个实时过滤）。

---

## 阅读器快捷键

阅读器**底部提示栏默认就写着这排按键**（有临时消息时才临时被替换掉），所以不用背：

```
q退出 j/space翻页 g跳行 [/]章节 Tab目录 /搜索 n下一个 b书签 v生词 m标记 o笔记 l语言 t翻屏 T翻章 c中文
```

| 按键 | 作用 |
| --- | --- |
| `q` / `Q` / `Ctrl-C` | 退出阅读器（会保存进度、书签、本次时长） |
| `j` / `空格` / `回车` / `↓` / `PageDown` | 往下翻页（按**屏幕行**精确推进：长段落折行后一屏装不下，下一页就从段落中间接着显示，不漏也不重；翻页量由 `reader.page_scroll_step` 决定，并保留 `reader.page_overlap` 行上下文） |
| `k` / `↑` / `PageUp` | 往上翻页 |
| 滚轮下 · 手指向上滑 | 往后**逐行**滚动（一行一行往下读；一格滚几行由 `reader.wheel_scroll_step` 决定） |
| 滚轮上 · 手指向下滑 | 往前**逐行**滚动（回看上文） |
| `g` | 跳到指定行号（提示 `跳到行号 (1-281):`，输入数字回车；`Esc` 取消） |
| `G` | 跳到全书最后一行 |
| `[` | 跳到上一章开头 |
| `]` | 跳到下一章开头 |
| `Tab` | 打开**目录浮层**（屏幕右侧 40%）：`↑↓` 选章、`回车` 跳转、`/` 实时过滤、`q` / `Esc` 关闭；左侧正文变暗但内容不动 |
| `/` | 搜索关键词（中文也能输；命中后自动跳到第一个匹配并高亮） |
| `n` | 跳到下一个匹配（循环） |
| `b` | 在当前行加 / 删书签，状态栏显示书签数量 |
| `l` | 循环切换视图：`中文` → `英文` → `双语对照` → `中文`…… |
| `c` | 直接切到中文视图（英文书常用：边读边看中文） |
| `t` | 翻译**当前屏幕**上的段落，译文在底部弹窗显示 **3 秒**（任意键提前关掉），**不写缓存**（适合随手瞄一眼）；引擎没配好时会先提示你跑 `werd config translate` |
| `T` | 翻译并缓存**整章**，带进度条；下次再进这一章直接读缓存，不花钱 |
| `v` | 查一个单词并收进生词本（输入框会预填当前行最长的英文单词） |
| `m` | 进入**标记模式**：光标变成反色方块，用 `h` / `j` / `k` / `l`（或方向键）扩展选区；`y` 复制选中的文字，`Esc` 取消。标记模式下**不翻页**，只能在同一屏内选字 |
| `o` | 展开 / 折叠**笔记面板**（占屏幕下方 25%，正文区相应缩小）：上半是**引用区**（只读，灰字，显示刚才 `y` 复制的文字，格式 `> …`），下半是**编辑区**（`curses` 文本框，回车换行、退格、左右光标）；`Tab` 在引用区 / 编辑区之间切焦点，`Ctrl+S` 保存，`Esc` 关闭面板 |

几个实用细节：

- **手机上读（Termux 等）**：手指按住上下拖动 = 逐行滚动 —— **向上滑往后读**（下一屏方向）、
  **向下滑往前看**，一格滚几行由 `reader.wheel_scroll_step` 决定；
  不想用拖动就设 `reader.touch_scroll false`。
  滚轮同理（下滚往后、上滚往前）。
  ⚠️ 有个终端限制：terminfo 里缺 `XM` 能力的终端（**macOS 自带终端**就是）只能上报"滚轮上"，
  滚轮下不会触发；那种环境下用方向键或拖动即可，功能不受影响。
- **底部两行是状态栏**：倒数第二行由 `reader.status_bar_format` 拼成（反色显示），
  最后一行是提示栏——平时显示按键清单，有临时消息（"已加入生词本：xxx = 承认"之类）时优先显示消息。
- **每行最左边一列是书签栏**：有书签的行显示 `★`，其余行留空。
- **搜索高亮**：当前跳到的命中行是反色，同一批的其他命中行是加粗。
- **生词会有下划线**（`vocab.highlight_in_reader = true` 时）；关闭后就不打扰阅读。
- **按 `v` 之后**：如果 `vocab.auto_add_on_mark = true`，查完直接收进生词本；设为 `false` 则会弹一个小窗问你 `[y] 加入生词本　其他键 取消`。
- **记笔记**：`m` 进入标记模式 → `h/j/k/l`（或方向键）选中一段 → `y` 复制（超过 2000 字自动截断并提示）→ `o` 打开面板，引用区自动显示选中的原文，在编辑区写批注 → `Ctrl+S` 保存。
  面板折叠时底部提示行会显示 `📝 N条笔记 | 按o展开`。三个坑要知道：
  1. 编辑区基于 `curses.textpad.Textbox`，**中文输入依赖系统 IME**，实际以英文 / 拼音为主；
  2. `Ctrl+S` 需要终端没开 XON/XOFF 流控（阅读器启动时会尝试自动关掉 `IXON`，关不掉就只能改用别的键）；
  3. ⚠️ 笔记目前**只存在内存里** —— 退出阅读器就没了，落盘留给后续版本（见「已知问题」）。
- **读到很慢的章节**（同一章停留超过 30 分钟），提示栏会顺手建议你按 `c` 看看中文。
- **中途 Ctrl-C** 不会丢进度：退出前同样会保存位置和本次时长。

---

## 设置项

设置都在 `~/.wreader/settings.toml` 里，分 6 个 section。可以直接用编辑器改，也可以用 `werd config <section.key> <value>` 改。
**删掉任意一行都会回落到默认值**，所以不用担心改坏。

### `[reader]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `page_scroll_step` | `1` | 每次翻页滚几屏（一屏 = 终端正文区的高度）。翻页按**屏幕行**计算：长段落折行后一屏装不下，就分多屏读完，下一页从段落**中间**接着显示，既不跳过也不重复。`0.5` = 半屏（更细腻），`2` = 两屏 |
| `page_overlap` | `3` | 翻页时上下各保留几行**屏幕行**上下文（上一屏末尾的这几行会留在新屏幕顶部，读起来连得上）；`0` = 关掉重叠，翻页就是整屏跳转 |
| `wheel_scroll_step` | `1` | 滚轮一格 / 触摸拖动一格滚几行（移动端建议 1~3） |
| `touch_scroll` | `true` | 触摸拖动即滚动（手机终端）；设 `false` 只留滚轮与键盘 |
| `status_bar_format` | 状态栏显示 `time`、`chapter`、`duration` 三段 | 选状态栏显示哪几段，多段用竖线分隔（详见下表） |
| `auto_save_interval` | `60` | 自动保存进度间隔（秒），`0` = 关闭 |
| `page_height` | `24` | 拿不到终端尺寸时的**回退**每屏行数（真实终端里翻页按正文区实际高度算，通常不用改） |
| `theme` | `"default"` | 配色主题名（当前预留，尚未生效） |
| `store_history` | `true` | 退出时把本次会话时长记入统计；设 `false` 可只读书不记时长 |

`status_bar_format` 可用的段落共 12 个，拼出来的样子是 `段1 · 段2 · 段3`：

| 标记 | 显示 |
| --- | --- |
| `time` | 当前时间 `21:34` |
| `book` | 书名 |
| `chapter` | 当前章节标题（没有章节时显示 `无章节`） |
| `position` | `行 120/281` |
| `percent` | `42.7%` |
| `mode` | 当前视图 `中文` / `英文` / `双语对照` |
| `duration` | `本章 05:20` |
| `elapsed` | `本次 12:30` |
| `streak` | `连续 3 天` |
| `bookmarks` | `书签 2` |
| `vocab` | `生词 128` |
| `translations` | `翻译 46` |

写错标记不会显示原文，而是被安静地忽略；如果一段都拼不出来，会退回只显示时钟。

### `[translator]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `backend` | `"google"` | **旧字段**：当 `[translate] engine` 为空时用它选引擎（`google` / `deepseek`） |
| `batch_size` | `3000` | 每次请求的字符数上限 |
| `cache_dir` | `"~/.wreader/cache"` | 译文缓存目录；默认跟随数据目录（所以 `$WREADER_HOME` 也管用） |
| `deepseek_api_key` | `""` | 留空则读环境变量 `DEEPSEEK_API_KEY` |
| `auto_translate_chapter` | `false` | 进入新章节时自动翻译整章（真·懒人模式） |
| `source_language` | `"auto"` | 原文语言，`auto` = 自动识别 |
| `target_language` | `"zh-CN"` | 译文语言 |
| `deepseek_model` | `"deepseek-chat"` | DeepSeek 模型名 |
| `deepseek_url` | `"https://api.deepseek.com/v1/chat/completions"` | 接口地址（兼容 OpenAI 协议的服务也能填这里） |

引擎的选择与密钥**不在这一节**，见下面的 `[translate]`。

### `[translate]`

翻译引擎是**可插拔**的：`wreader/translate/` 里每个厂商一个模块，`[translate] engine` 挑用哪个。
**最快的方式是跑向导**，它会列出所有引擎、逐个问密钥、写完立刻自查一遍：

```bash
werd config translate
```

手动配置就是改这一节：

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `engine` | `""` | `google` / `baidu` / `youdao` / `tencent` / `deepseek` / `local`；**空 = 回退到 `[translator] backend`** |
| `baidu_appid` / `baidu_secret` | `""` | 百度翻译的 APPID 与密钥（MD5 签名） |
| `youdao_appid` / `youdao_secret` | `""` | 有道智云的应用 ID 与应用密钥（SHA-256 签名） |
| `tencent_secret_id` / `tencent_secret_key` | `""` | 腾讯云的 SecretId 与 SecretKey（TC3-HMAC-SHA256 签名） |
| `tencent_region` | `"ap-beijing"` | 腾讯云地域，**参与签名**，写错会被服务端拒 |
| `deepseek_api_key` | `""` | 留空则读环境变量 `DEEPSEEK_API_KEY` |
| `deepseek_model` | `"deepseek-chat"` | DeepSeek 模型名 |
| `deepseek_url` | `"https://api.deepseek.com/v1/chat/completions"` | 接口地址（兼容 OpenAI 协议的服务也能填这里） |

六个引擎的差别：

| 引擎 | 要不要密钥 | 说明 |
| --- | --- | --- |
| `google` | 不用 | **默认**。走 `deep-translator`，免注册开箱可用；每批之间有 1 秒节流，整本翻译偏慢 |
| `baidu` | 要（APPID + 密钥） | 通用翻译 API V2，国内快、有免费额度 |
| `youdao` | 要（应用 ID + 密钥） | 有道智云 v3，中英互译质量不错 |
| `tencent` | 要（SecretId + SecretKey） | 腾讯云 TMT，签名最复杂（TC3），适合已经在用腾讯云的人 |
| `deepseek` | 要（API key） | 大模型翻译，按章整段翻质量最连贯；`temperature` 0.3、流式输出 |
| `local` | 不用，但**要装包** | 本地 Argos Translate，**完全离线**；先 `pip install 'wreader[local]'` 并装好语言包，否则不可用 |

几个例子：

```bash
werd config translate.engine deepseek
werd config translate.deepseek_api_key sk-你的密钥
# 或者更安全的做法（不写进文件）：
export DEEPSEEK_API_KEY=sk-你的密钥

werd config translate.engine baidu
werd config translate.baidu_appid 你的APPID
werd config translate.baidu_secret 你的密钥
```

⚠️ 引擎没配好时，阅读器里按 `t` 不会去发请求，而是直接提示你跑 `werd config translate`。

### `[stats]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `daily_goal_minutes` | `60` | 每日阅读目标（分钟），`0` = 不显示目标 |
| `show_heatmap` | `true` | `werd stats` 里是否显示 30 天热力图 |
| `achievement_sound` | `true` | 解锁成就时是否响铃（`\a`）；嫌吵就改 `false` |

### `[vocab]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `highlight_in_reader` | `true` | 阅读器里给生词加下划线 |
| `auto_add_on_mark` | `true` | 按 `v` 查到词后直接收录，不弹确认框 |

### `[library]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `novels_dir` | `""` | UTF-8 正文存放目录，留空 = `~/novels` |

### `[toc]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `patterns` | `""` | **追加**的章节标题正则；多个用 `\|` 分隔（内置规则始终生效），用来认 `### 楔子` 这类写法 |

---

## 文件位置

| 内容 | 路径（macOS / Linux） | 可被覆盖 |
| --- | --- | --- |
| 设置 | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| 书库索引 | `~/.wreader/library.json` | `$WREADER_HOME` |
| 成就状态 | `~/.wreader/achievements.json` | `$WREADER_HOME` |
| 生词本 | `~/.wreader/vocab.json` | `$WREADER_HOME` |
| 译文缓存 | `~/.wreader/cache/<book_id>/ch0_en.txt`、`ch0_bilingual.txt` | `translator.cache_dir` |
| 小说正文（UTF-8） | `~/novels/<书名>_utf8.txt` | `$WREADER_NOVELS_DIR`、`library.novels_dir` |

Windows 下数据目录是 `%APPDATA%\wreader`。

三个环境变量：

```bash
export WREADER_HOME=~/my-wreader-data    # 换掉整个数据目录（测试 / 多套配置很有用）
export WREADER_NOVELS_DIR=~/my-novels    # 换掉小说正文目录
export DEEPSEEK_API_KEY=sk-xxx           # DeepSeek 密钥，优先级低于配置文件里的值
```

旧名字 `$NR_HOME` / `$NR_NOVELS_DIR` 依然有效，但只有在没设新名字时才会被读取。

旧版本写的扁平 `config.json` 会在第一次加载设置时自动折叠进 `settings.toml` 的对应 section，
原文件改名为 `config.json.bak` 保留下来，不会丢东西。

---

## 数据格式

所有数据都是纯 JSON / TOML / 纯文本，随时可以手改、备份、用脚本处理。

### `~/.wreader/library.json` —— 书库索引

三个顶层字段：`books`、`stats`、`achievements`。

```json
{
  "books": {
    "3e027c4de949": {
      "title": "三体",
      "author": "刘慈欣",
      "file_path": "/Users/you/novels/三体_utf8.txt",
      "encoding": "GB2312",
      "total_lines": 812,
      "total_words": 208400,
      "chapters": [{ "title": "第一章 科学边界", "line_start": 0 }],
      "progress": {
        "current_line": 120,
        "percentage": 14.8,
        "last_read": "2026-09-21T16:13:43",
        "total_time_seconds": 3600,
        "bookmarks": [{ "line": 240, "label": "", "created": "2026-09-21T16:00:00" }],
        "finished": false,
        "sessions": [
          { "start": "2026-09-21T15:00:00", "end": "2026-09-21T16:00:00", "lines_read": 120 }
        ]
      },
      "tags": [],
      "import_date": "2026-09-21"
    }
  },
  "stats": {
    "total_books": 2,
    "total_read_time": 3600,
    "daily_read_time": { "2026-09-21": 3600 },
    "translations": 46
  },
  "achievements": {
    "unlocked": [{ "id": "first_book", "name": "📖 开卷有益", "unlocked_at": "2026-09-21T16:13:43" }],
    "progress": { "first_book": { "current": 1, "required": 1 } }
  }
}
```

要点：

- `book_id` 是转换后正文的 SHA-1 前 12 位，所以重复导入必然被识别。
- `total_lines` 和每个 `chapters[].line_start` 都是 `正文.split("\n")` 的下标，
  阅读器的 `current_line`、书签的 `line` 用的是同一套坐标，互相不会错位。
- `tags` 目前由 `werd search '#tag'` 使用，命令行还没有加标签的入口，需要手改索引。
- `achievements` 段是**旧版**存放解锁记录的地方。解锁记录现在住在
  `~/.wreader/achievements.json`（见下节），第一次读成就状态时会**自动迁移一次**；
  迁移后这里的旧内容不再被读取，留着只是为了不让旧文件"看起来丢了东西"。

### `~/.wreader/achievements.json` —— 成就状态

```json
{
  "version": 1,
  "unlocked": [
    { "id": "first_shelf", "name": "🗄️ 书库初成", "unlocked_at": "2026-09-21T16:13:43" }
  ],
  "counters": { "daily_open": 12, "book_add": 3, "session_end": 9 },
  "metrics": {
    "days_opened": ["2026-09-21", "2026-09-22"],
    "early_open": 0,
    "weekend_seconds": { "2026-09-20": 10800 },
    "words_read": 42000
  },
  "books": { "3e027c4de949": { "words": 42000, "counted": [[0, 812]] } },
  "progress": { "first_book": { "current": 2, "required": 1 } }
}
```

要点：

- `unlocked` 是**解锁记录**（成就定义本身在包的 `data/achievements.json` 里）；
- `counters` 是事件次数，`metrics` 是只有事件流才知道的数字（打开过几天、周末多少秒、读了多少字）；
- `books[].counted` 是**每本书已经统计过的行号区间**（半开区间 `[start, end)`），
  字数去重就靠它：同一段正文读第二遍不会再累加；
- 手改坏了也不会让 `werd` 起不来：读不出来时会把坏文件改名成 `achievements.json.broken`，
  然后从空状态重新开始；写盘一律"临时文件 + 原子替换"，并且全程持有 `achievements.json.lock`
  文件锁（Windows 没有 `flock`，退化成只有原子替换）。

### `~/.wreader/vocab.json` —— 生词本

```json
[
  {
    "word": "acknowledged",
    "translation": "公认的",
    "context": "It is a truth universally acknowledged.",
    "book": "Pride and Prejudice",
    "chapter": "Chapter 1",
    "date_added": "2026-09-21T14:15:40"
  }
]
```

同一个词查两次是**刷新**已有条目，不会出现重复行。
旧版本的 `{"words": [...]}` 包装结构、以及 `book_title` / `created` 这些旧字段名依然能读进来。

### `~/.wreader/cache/<book_id>/` —— 译文缓存

```
ch0_en.txt          第 1 章的译文（每段一行 + 空行分隔）—— 固定叫 _en，
                    虽然内容是译到 translator.target_language 的结果
ch0_bilingual.txt   第 1 章的中英段落对照（喂给阅读器的双语视图）
```

文件名后缀固定是 `_en` 和 `_bilingual`（`_en` 是历史命名，容器里装的是"目标语言"的译文）。
缓存以"章"为单位，所以整个目录删掉也不影响别的数据，只是下次要重新翻译。

---

## 成就清单

定义在 `wreader/data/achievements.json`，一共 **28** 个（Phase 1），分四类。
条件是简单的 `指标 比较符 数字` 表达式，可以自己加；**解锁状态**存在
`~/.wreader/achievements.json`（纯 JSON，随便改、随便备份）。

| 成就 | 名称 | 分类 | 条件 |
| --- | --- | --- | --- |
| `first_book` | 📖 开卷有益 | 数据积累 | 第一次打开一本书 |
| `book_finished` | 🏁 第一本 | 数据积累 | 读完第一本书 |
| `ten_books` | 📚 十本大关 | 数据积累 | 累计读完 10 本书 |
| `fifty_books` | 🎯 半百 | 数据积累 | 累计读完 50 本书 |
| `hundred_books` | 💰 百本富翁 | 数据积累 | 累计读完 100 本书 |
| `thousand_books` | 🏛️ 千本富豪 | 数据积累 | 累计读完 1000 本书 |
| `first_shelf` | 🗄️ 书库初成 | 数据积累 | 书库里添加第 1 本书 |
| `collector` | 📦 藏书家 | 数据积累 | 书库里累计 50 本书 |
| `mobile_library` | 🚚 移动图书馆 | 数据积累 | 书库里累计 100 本书 |
| `words_10k` | ✒️ 万字户 | 数据积累 | 累计阅读 1 万字 |
| `words_100k` | ⛰️ 十万大山 | 数据积累 | 累计阅读 10 万字 |
| `words_1m` | 💵 百万富翁 | 数据积累 | 累计阅读 100 万字 |
| `words_10m` | 🎩 千万俱乐部 | 数据积累 | 累计阅读 1000 万字 |
| `words_100m` | 👑 亿万富豪 | 数据积累 | 累计阅读 1 亿字 |
| `words_1b` | 🌌 十亿富豪 | 数据积累 | 累计阅读 10 亿字 |
| `vocab_100` | 📝 词汇积累 | 数据积累 | 生词本满 100 个 |
| `vocab_500` | 🧠 生词狂魔 | 数据积累 | 生词本累计记录 500 个单词 |
| `translator` | 🌍 双语者 | 数据积累 | 首次使用翻译功能 |
| `first_hour` | ⏱️ 初窥门径 | 阅读习惯 | 累计阅读满 1 小时 |
| `ten_hours` | 🎓 学富五车 | 阅读习惯 | 累计阅读满 10 小时 |
| `night_owl` | 🌙 深夜书虫 | 阅读习惯 | 凌晨 0-4 点阅读超 1 小时 |
| `streak_7` | 🔥 七日不断 | 阅读习惯 | 连续 7 天每天阅读 30 分钟 |
| `streak_30` | 🗿 铁血读者 | 阅读习惯 | 连续 30 天每天阅读 |
| `hundred_days` | 🧱 百日筑基 | 阅读习惯 | 连续 100 天打开 werd |
| `early_bird` | 🌅 清晨第一眼 | 阅读习惯 | 在 05:00-07:00 期间首次打开 |
| `marathon` | 🏃 马拉松 | 阅读习惯 | 单次会话阅读超过 2 小时 |
| `ultra_marathon` | 🛌 超长待机 | 阅读习惯 | 单次会话阅读超过 4 小时 |
| `weekend_warrior` | ⚔️ 周末战士 | 阅读习惯 | 周六或周日累计阅读 3 小时 |

条件里可用的指标：

| 指标 | 含义 | 来源 |
| --- | --- | --- |
| `books_read` / `finished` | 读过的书数 / 读完的书数 | 书库索引 |
| `total_time` / `night_time` / `single_session` / `weekend_time` | 累计 / 夜间 / 单次最长 / 周末阅读秒数 | 索引 + 成就状态 |
| `streak` | 连续天数 | 索引里的每日桶 |
| `vocab_count` / `translations` | 生词数 / 翻译次数 | 生词本 + 索引 |
| `library_books` | 书库里一共几本书 | 书库索引 |
| `words_read` | 累计读了多少字（**按行号区间去重**） | 成就状态 |
| `days_opened` / `early_open` | 打开过 werd 的天数 / 是否在清晨打开过 | 成就状态 |

字数口径：**中文一字算一个，英文一个词算一个**，标点与数字不计。同一段正文读第二遍不再累加
（靠每本书记下来的「已统计行区间」判断）。

**事件驱动**：各模块调用 `achievements.check_achievements(事件名, 数据)`，事件有
`daily_open`（每次启动 `werd`）、`session_end`（退出阅读，带时长与读过的行区间）、
`book_add`（`werd import`）、`progress_update`、`book_finish`、`word_add`、
`geo_change`（Phase 3）、以及不带任何累加的 `check`（只是"现在重算一遍"）。
已解锁的成就不会重复触发；整个「读状态 → 记事件 → 判定 → 写回」在**文件锁**下进行，
两个终端同时开也不会互相覆盖（Windows 没有 `flock`，退化成原子替换写入）。

"连续天数"的判定：一天阅读 ≥ 30 分钟才算有效；当天永远算数（因为它正要变成事实）。
解锁时会打印动画和横幅，`stats.achievement_sound = false` 可以关掉提示音。


---

## 项目结构

```
wreader/
├── pyproject.toml           打包配置（依赖、console script、LICENSE、[tool.pytest]、[tool.pyright]）
├── LICENSE                  MIT 许可证
├── README.md                中文说明（本文件）
├── README.en.md             English README
├── 使用指南.md               小白手把手教程（第一次用看这个）
├── install.sh               一键安装：建 venv、装依赖、配好 werd 别名（幂等）
├── tools/                   开发期校验脚本：文档锚点/数字对拍/折行/绘制/配色（见 tools/README.md）
├── .vscode/settings.json    把 Pylance / 终端指向 .venv 解释器
├── wreader/
│   ├── __init__.py          __version__ 和模块地图（19 行）
│   ├── achievements.py      成就引擎：事件记录、状态文件、解锁判定与文件锁（768 行）
│   ├── cli.py               argparse 定义 + 各子命令处理函数（1266 行）
│   ├── config.py            settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁（1007 行）
│   ├── library.py           txt/epub 导入、编码识别、书名解析、索引与模糊搜索（1159 行）
│   ├── reader.py            curses 分页阅读器：视图、搜索、书签、状态栏、滚轮/触摸、标记与笔记（3342 行）
│   ├── translator.py        章节缓存 / 分批 / 段落映射 + 引擎适配层（1199 行）
│   ├── vocab.py             生词本：增删查、复习、Anki 导出（436 行）
│   ├── stats.py             统计指标、热力图、成就判定与庆祝动画（785 行）
│   ├── toc.py               目录：章节提取、epub nav 解析、可重建缓存（474 行）
│   ├── translate/           可插拔翻译引擎（每个厂商一个模块；行数见 memory-bank）
│   │   ├── __init__.py      引擎注册表 + 工厂：按名字造引擎
│   │   ├── base.py          Translator 抽象基类：translate() 契约与凭证检查
│   │   ├── google.py        Google（deep-translator，免费免密钥，默认引擎）
│   │   ├── baidu.py         百度通用翻译 API V2（MD5 签名）
│   │   ├── youdao.py        有道智云 v3（SHA-256 签名）
│   │   ├── tencent.py       腾讯云 TMT（TC3-HMAC-SHA256 签名）
│   │   ├── deepseek.py      DeepSeek chat completions（流式 SSE）
│   │   └── local.py         本地 Argos Translate（离线，可选依赖）
│   └── data/
│       └── achievements.json  28 个成就的定义（198 行）
└── tests/                   683 项测试，全部离线运行（见下方「运行测试」）
    ├── conftest.py          共享 fixture：隔离的 $WREADER_HOME、假翻译后端、epub 构造器
    ├── test_achievements.py 35 项 —— 字数口径、行区间去重、事件累加、状态文件、文件锁、解锁判定
    ├── test_config.py       51 项 —— 默认值、类型校验、旧配置迁移、数据目录搬迁、目录解析
    ├── test_library.py      119 项 —— 编码、章节、epub、导入去重、书名解析、模糊搜索、最近在读
    ├── test_reader.py       192 项 —— 分页数学、Pager、状态栏、按键、会话落库、折行、滚轮、目录浮层、标记与笔记面板
    ├── test_stats.py        70 项 —— 指标、连续天数、热力图、定义加载、报告
    ├── test_translator.py   77 项 —— 语言识别、分批、章节缓存、引擎适配、错误映射
    ├── test_translate.py    49 项 —— 引擎注册表、各厂商签名/请求构造、错误与参数校验
    ├── test_vocab.py        31 项 —— 生词本读写、刷新不重复、复习、Anki 导出
    ├── test_toc.py          18 项 —— 章节提取、epub nav/ncx 解析、自定义正则、缓存失效与重建
    └── test_cli.py          41 项 —— 参数解析、各子命令输出、退出码、翻译引擎配置向导
```

分层约定：除了 `wreader/reader.py` 的 curses 前端和 `wreader/cli.py` 的输出渲染，
其余模块都是**纯函数 + 普通数据**，不依赖终端，所以分页数学、章节边界、统计指标、
成就条件都可以脱离 TTY 单独测试或复用。

---

## 开发说明

```bash
# 装好（可编辑模式，改完代码直接生效）
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 跑命令
werd --help
werd list

# 不污染真实数据地做实验：换一个数据目录即可
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
werd import /tmp/my-test-books
```

调试建议：

- **想清空重来**：删掉 `$WREADER_HOME`（默认 `~/.wreader`）和小说目录即可，`werd` 下次运行会重新生成默认设置。
- **想单独调前端逻辑**：`wreader/reader.py` 里 `Pager`、`chapter_bounds`、`read_lines`、`reading_streak`
  都不需要 curses，可以直接 `from wreader.reader import Pager` 在 REPL 里玩。
- **IDE**：仓库里的 `.vscode/settings.json` 已经把解释器指向 `.venv/bin/python`。
  如果 Pylance 报 `无法解析导入 "rich.console"`，执行一次 `Developer: Reload Window`
  或手动 `Python: Select Interpreter` 选 `.venv/bin/python`。

静态类型检查：配置写在 `pyproject.toml` 的 `[tool.pyright]` 里（`venvPath` / `venv` 指到 `.venv`，
所以不需要额外参数就会从虚拟环境解析 `rich` 等第三方库）：

```bash
npx pyright                 # 或者装一次 pyright 后直接 pyright
```

当前状态是 **0 errors / 0 warnings**（`wreader/` 与 `tests/` 都纳入检查）。
注意 `[tool.pyright]` 只对 pyright CLI 生效，VS Code 里的 Pylance 读的是 `.vscode/settings.json`
（两者都指向同一个 `.venv`）。

### 运行测试

```bash
pip install -e ".[dev]"     # 装上 pytest
pytest                      # 545 项，约 5 秒
pytest -q tests/test_reader.py            # 只跑一个文件
pytest -k "streak or heatmap" -q          # 按名字筛选
```

测试遵循几条约定，改代码时可以顺着走：

- **绝不碰真实数据**：`tests/conftest.py` 里的 autouse fixture 会把 `$WREADER_HOME` / `$WREADER_NOVELS_DIR`
  指到 `tmp_path`，并清掉 `wreader.config` 的缓存与 `wreader.translator` 的全局后端，所以每个测试都是干净的。
- **绝不联网**：翻译全部走 conftest 里的 `RecordingBackend`（用 `set_backend` 注入），
  Google / DeepSeek 只测到构造参数、请求体和 SSE 解析这一层。想确认的话，用假代理跑一遍即可：
  ```bash
  HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 pytest
  ```
- **不需要终端**：阅读器用 `tests/test_reader.py` 里的 `FakeStdscr`（实现了阅读器真正用到的那部分
  curses API）；需要输入的地方 monkeypatch `wreader.reader._prompt` / `_confirm`。
  唯一"注定失败"的路径是 `open_reader` 的 tty 检查，正好拿来断言那条报错。

### 其它校验脚本

`tools/` 下还有几个开发期用的检查（**不参与打包**）。改完对应代码顺手跑一下：

```bash
python tools/check_docs.py            # 文档锚点与代码围栏（改过 README / 使用指南 之后）
python tools/check_doc_numbers.py     # README 里的行数、测试项数是否还和代码一致
python tools/check_comments.py        # 注释覆盖情况（默认只报告；加 --strict 才是门禁）
python tools/verify_wrap.py           # 折行属性（期望 OK: 40077 checks passed）
python tools/verify_draw.py           # 绘制不越界（期望 OK: 420 draw checks passed）
script -q /dev/null python tools/verify_colors.py   # 配色（需要 pty）
```

它们都自己推算仓库根目录，所以**在哪个目录下运行都行**；退出码 0 = 通过、1 = 有问题。
详见 [tools/README.md](tools/README.md)。

---

## 常见问题

**Q：新开终端后敲 `werd` 提示 command not found？**
这是最常见的报错，**不是装坏了**：`werd` 装在项目自己的 `.venv` 里，而 `.venv/bin` 默认不在 `PATH` 上。
用 `./install.sh` 装的话别名已经写好了 —— 先 `source ~/.zshrc`（bash 换成 `~/.bashrc`）或重开终端；
还是不行就说明当初用了 `--no-alias` 或手动装的，见[新开一个终端后怎么用 werd](#新开一个终端后怎么用-werd)。
临时也可以用 `<项目路径>/.venv/bin/werd`、先 `source .venv/bin/activate`，
或者干脆把 `werd xxx` 写成 `python -m wreader.cli xxx`。

**Q：升级后我原来的书库去哪了？**
`werd` 第一次运行时会把 `~/.nr` 整体搬到 `~/.wreader`，不用你动手。如果两个目录都存在，
`werd` 只用 `~/.wreader`、不碰 `~/.nr`——确认新目录没问题后可以自己删掉它。

**Q：导入时说 `path does not exist` / `no .txt/.epub file found under ...`？**
路径写错了，或者那个目录里确实没有 `.txt` / `.epub`。`werd import` 是递归扫描的，直接给上层目录也行。

**Q：中文书导入后是乱码？**
编码按 BOM（UTF-8 / UTF-16 / UTF-32）→ chardet → UTF-8 → GB18030 依次尝试。BOM 只说明文件"想"是什么编码
（UTF-32 的 BOM 以 UTF-16 的 BOM 开头，损坏的 UTF-16 文件里也可能有非法 surrogate），所以带 BOM 的文件解码失败时
会用替换字符降级导入，并在编码名后面标 `(replaced)`，而不是让整次导入崩掉。真遇到这种文件，用编辑器另存为
UTF-8 再重新 `werd import` 就能拿到干净正文。
如果仍不正常，先用编辑器把源文件另存为 UTF-8，再重新 `werd import`。

**Q：同一本书导入了两次？**
不会。书号是正文的 SHA-1，第二次会显示为 `skipped 1 duplicate(s)`。
注意：换书名再导入仍会被认出来（内容没变），但**改过内容**就会被当成新书。

**Q：按了 `t` 却没有译文？**
`t` 只翻译当前屏幕，且**不缓存**；如果它提示 `当前视图就是原文，无需翻译`，说明你要的正是这本书的原文语言。
想永久保存译文请按 `T`（整章缓存），或者先在命令行跑一次 `werd translate <book_id>`。

**Q：翻译报错 `翻译不可用: ...`？**
Google 后端需要联网；DeepSeek 后端需要 API key（`werd config translator.deepseek_api_key sk-xxx`
或 `export DEEPSEEK_API_KEY=...`）。国内网络下 Google 可能不通，建议换 deepseek。

**Q：`werd read` 报 `needs an interactive terminal`？**
阅读器要在真终端里跑，不能 `| less`、不能重定向、也不能在 CI 里跑。
（`werd list` / `werd stats` 这些可以随便重定向。）

**Q：退出后统计没变？**
检查两处：`reader.store_history` 是否为 `true`；以及这次会话是否保存成功（磁盘只读或数据目录不可写会静默跳过）。

**Q：时间不长，为什么"连续天数"已经是 1 了？**
当天永远算数——因为它正要变成事实。真正的门槛是"某天累计 ≥ 30 分钟"。

**Q：想要安静地读书，不要统计、不要响铃？**
```bash
werd config reader.store_history false
werd config stats.achievement_sound false
werd config stats.show_heatmap false
```

**Q：怎么把生词导进 Anki？**
```bash
werd vocab --export anki > deck.txt
```
然后 Anki → 文件 → 导入，字段选"制表符分隔"，三列分别是 单词 / 释义 / 例句。

**Q：书删了，索引还在？**
命令行目前没有删除命令。删掉 `library.json` 里 `books` 下对应的那个 id 即可
（`werd list` 会立刻不再显示它）；或用 Python：
```python
from wreader import library
library.remove_book("3e027c4de949")   # 同时删掉 ~/novels 里的 UTF-8 正文
```

**Q：`settings.toml` 改坏了怎么办？**
`werd config --reset` 恢复全部默认；或者删掉文件让它重新生成。删单行则只回落到该行的默认值。

---

## 已知问题

这些是当前版本真实存在的限制，写出来比藏着好：

- **`reader.theme` 还没实现**，改了没有任何效果。
- **加标签没有命令行入口**。`books[].tags` 和 `werd search '#tag'` 都支持，但目前只能手改 `library.json`。
- **EPUB 解析有取舍**：没装 Calibre 的 `ebook-convert` 时用内置提取器，只取正文文本，
  图片、脚注、复杂排版会丢失；能装 Calibre 建议装上。
- **`werd read` 只能在真终端里用**（见上方 FAQ）。
- **Windows 需要额外依赖** `windows-curses`（`pip install -e ".[windows]"`）。
- **`library.json` 里 `progress` 的数值不做类型强制转换**：手写成字符串（`"current_line": "12"`）
  也能正常读，因为消费方都用 `int(...)` 兜住了，但它不会被自动改回数字。
- **笔记只存在内存里**：`m` 标记 + `o` 笔记面板已经可用，但 `Ctrl+S` 存下的笔记随阅读会话结束
  一起消失，**还没有落盘**（后续版本会写到 `~/.wreader/` 下的纯文本文件）。
- **笔记编辑区以英文 / 拼音为主**：编辑区基于 `curses.textpad.Textbox`，中文输入依赖系统 IME；
  并且面板里的 `Ctrl+S` 要求终端没开 XON/XOFF 流控（阅读器启动时会尝试自动关掉 `IXON`，关不掉时保存键会到不了程序）。

已经解决、不再属于已知问题的十条（留个记录，免得又被当成待办）：

- ~~没有 LICENSE~~ → 已加 MIT（`LICENSE` + `pyproject.toml` 的 `license = "MIT"`）。
- ~~`translator.__all__` 里有不存在的 `chapter_paragraphs`~~ → 已移除该名字，
  换成真实存在的 `TranslatorCallable`；此前 `from wreader.translator import *` 会直接抛 `AttributeError`。
- ~~`library.py` / `stats.py` / `translator.py` / `vocab.py` 还有约 10 条类型告警~~ → 已全部修掉，
  `pyright` 现在是 0 errors / 0 warnings。
- ~~没有自动化测试~~ → 已补 **545 项 pytest**（`tests/`），全程离线、不碰真实数据。
- ~~中译英时源语言短码会让默认后端直接报错~~ → 已修（补测试时发现的）：
  `detect_language()` 返回的是 `zh`，而 `deep-translator` 只认 `zh-CN`，会在发请求前就抛
  `No support for the provided language`。现在三条翻译入口统一过一遍 `normalize_language()`，
  手写 `translator.source_language = "zh"` 也不会再踩坑。
- ~~带 BOM 的损坏文件会让整次导入崩掉~~ → 已修：BOM 认 UTF-8/16/32 且宽编码优先（UTF-32 的 BOM 以
  UTF-16 的 BOM 开头），解码失败就降级成 `(replaced)`；单个坏文件只会进 `failed`，不再中止整个 import。
- ~~下载站的 `《书名》（校对版全本）作者：某人.txt` 解析不出干净书名和作者~~ → 已支持，且尾部
  `（…）`/`(...)` 注释统一剥掉；只认**尾部**括号，所以 `书名（中）下册` 这类标题保持完整。
- ~~超长正文行在终端里被静默截断~~ → 已修：阅读器现在**按终端宽度自动折行**，且折行严格按
  **显示列数**算（汉字占 2 列、英文在空格处断词、Tab 展开成 4 空格、行尾空格丢弃）。
  一个源行可以占多条屏幕行，书签 `★` 只画在该源行的第一行。
- ~~状态栏 / 消息行 / 确认弹窗还在按字符数算宽度~~ → 已修：这些位置全部改用显示列数
  （`_text_width` / `_clip_line` / `_pad_line`），窄屏下不会再整行越界消失；
  `_addstr` 写入前还会再裁一次作安全网，即使某行超宽也只是被裁剪、不会整行不见。
- ~~正文背景被锁成不透明黑底，不跟随终端主题／透明~~ → 已修：`initscr()` 之后调用
  `start_color()` + `use_default_colors()`（**必须成对**，只调前者反而会把默认配色锁成黑底），
  全程不 `init_pair()`，所以 `A_REVERSE` / `A_BOLD` / `A_DIM` 高亮不受影响。

---

## 许可

本项目采用 **MIT License**，完整文本见 [LICENSE](LICENSE)。

可以自由使用、修改、分发（包括商用），只需保留版权声明和许可证文本。
版权行目前写的是 `Copyright (c) 2026 wreader contributors`——如果这是你个人的项目，
把 `LICENSE` 里那一行改成你的名字或组织即可（一行改动，不影响其他内容）。

---

## 相关文档

- **[使用指南.md](使用指南.md)** —— 完全零基础的手把手教程：装 Python、建环境、导入第一本书、
  用按键读书、查生词、看统计，附报错急救表。
- **[README.en.md](README.en.md)** —— English version of this file.





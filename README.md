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
- [新开一个终端后怎么用 wreader](#新开一个终端后怎么用-wreader)
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

---

## 特性

| 功能 | 说明 |
| --- | --- |
| 📚 导入 | 递归扫描目录，认 `.txt` / `.epub`；自动识别编码（BOM 认 UTF-8/UTF-16/UTF-32 → chardet → UTF-8 → GB18030），统一转成 UTF-8 存好，之后再也不碰编码问题 |
| 🆔 去重 | 书号是正文的 SHA-1，同一本书重复导入直接跳过，不会出现两份 |
| 🔖 章节 | 导入时自动识别章节标题（`第一章`、`Chapter 1` 等），之后可以按章跳转 |
| 🔍 搜索 | 模糊搜索书库：标题、作者、标签都认，还能首字母跳跃匹配（`hptr` 找得到 *Harry Potter*） |
| 📖 阅读器 | curses 分页阅读：跳行、跳章、搜索高亮、书签、状态栏、自动保存进度；按终端宽度自动折行（汉字按 2 列算），配色跟随终端主题与透明背景 |
| 🌍 三种视图 | `中文` / `英文` / `双语对照`，按 `l` 循环切换；本来就是中文的书看中文视图不需要翻译，离线也能读 |
| 🈶 翻译 | 章节级翻译 + 磁盘缓存，译一次永久复用；支持 Google（免密钥）和 DeepSeek（OpenAI 兼容接口） |
| 📝 生词本 | 阅读中按 `v` 查词并收录，阅读器里自动给生词加下划线；支持搜索、复习、删除、导出 Anki |
| 📊 统计 | 总时长 / 今日 / 本周 / 本月 / 每日目标 / 连续天数 / 30 天热力图；`--json` 输出给脚本用 |
| 🏆 成就 | 10 个成就（开卷有益、深夜书虫、七日不断……），命令行显示进度条，解锁时有动画和提示音 |
| ⚙️ 配置 | 一个 `settings.toml` 管全部，`wreader config` 读写并带拼写纠错提示；旧版 `config.json` 自动迁移 |

---

## 环境要求

- **Python 3.11 或更高**（用到了标准库 `tomllib`）
- **macOS / Linux**：`curses` 是 Python 自带的，开箱即用
- **Windows**：需要额外装 `windows-curses`（见安装一节）
- 终端需要支持 UTF-8（读中文书必备；macOS 自带终端、iTerm2、Windows Terminal 都可以）
- 用 Google 翻译或 `wreader translate` 时需要联网；只想本地读书的话全程离线可用

运行时会用到这几个第三方库，安装时会自动装好：
`rich`（表格和进度条）、`chardet`（编码识别）、`deep-translator`（Google 翻译）、`requests`（DeepSeek 翻译）。

---

## 安装

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

装完之后，**在当前这个终端窗口里**就有了 `wreader` 命令：

```bash
wreader --version
# wreader 0.1.0
```

### 新开一个终端后怎么用 wreader

`wreader` 装在**项目自己的 `.venv`** 里，而 `.venv/bin` 默认不在系统的 `PATH` 上，
所以**关掉终端再新开一个窗口，直接敲 `wreader` 会报 `command not found`**——
这很正常，不代表装坏了。三种办法，任选一种：

| 办法 | 每次要敲什么 | 说明 |
| --- | --- | --- |
| **① 配一次别名**（推荐） | `wreader read <id>` | 配一次，此后**所有新终端**都能直接用 |
| **② 用完整路径** | `<项目路径>/.venv/bin/wreader read <id>` | 不改任何配置文件 |
| **③ 每次激活虚拟环境** | `cd <项目路径>` → `source .venv/bin/activate` → `wreader ...` | 顺手，但每个新窗口都要来一遍 |

办法①在 macOS / Linux（zsh）下就是往 `~/.zshrc` 追加一行（把路径换成你的实际位置）：

```bash
echo 'alias wreader="$HOME/Downloads/wreader/.venv/bin/wreader"' >> ~/.zshrc
source ~/.zshrc                       # 立刻生效；或者干脆重开一个窗口
wreader --version                     # 验证：应输出 wreader 0.1.0
```

用 bash 的话把 `~/.zshrc` 换成 `~/.bashrc`；Windows PowerShell 则在 `$PROFILE` 里定义一个同名函数。

> ⚠️ **不要把 `.venv/bin` 前置进 `PATH`**（`export PATH=".../.venv/bin:$PATH"`）。
> 那样 `wreader` 确实能用了，但新终端里的 `python3` 和 `pip` 也会一起变成这个虚拟环境的版本，
> 会干扰你在其它 Python 项目上的工作；别名只多一条命令，没有这个副作用。

> **只是临时用一下？** 也可以完全不配置，直接把 `wreader xxx` 换成
> `python -m wreader.cli xxx`——本文档里两种写法等价。
> 面向新手的详细版（含 Windows 写法、以及"为什么书和进度不会丢"）见
> [使用指南.md](使用指南.md) 的「关掉终端之后」一节。

### 从旧版 `nr` 升级

这个工具以前叫 `nr`。装过旧版的人**不需要手动搬数据**：第一次运行 `wreader` 时，如果 `~/.wreader`
还不存在而 `~/.nr` 存在，老的整个目录会被搬过去——设置、书库索引、生词本、译文缓存都在里面——
老目录随即消失。几个老名字的兼容情况：

| 老名字 | 现在 | 兼容方式 |
| --- | --- | --- |
| 命令 `nr` | `wreader` | 重新 `pip install -e .`，旧命令随旧发行版一起卸载 |
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
wreader import ~/Downloads/books

# ③ 看看书库里有什么，把 id 记下来
wreader list

# ④ 开读（把 id 换成上一步看到的）
wreader read 3e027c4de949
```

`wreader import` 的真实输出长这样：

```
imported 2 book(s), skipped 0 duplicate(s), 0 failed
  + ab912556b66b  《Nameless》 unknown · 7 行 · 12 字 · ascii · 2 章
  + 3e027c4de949  《三体》 刘慈欣 · 281 行 · 2000 字 · utf-8 · 41 章
```

`wreader list` 的真实输出长这样：

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
| `wreader import <路径>` | 扫描文件或目录，把 txt/epub 导入书库 |
| `wreader list` | 列出书库里的书 |
| `wreader search <关键词>` | 模糊搜索书名 / 作者 / 标签 |
| `wreader read <book_id>` | 打开分页阅读器 |
| `wreader translate <book_id>` | 把整本书逐章翻译并缓存 |
| `wreader vocab` | 生词本：列表 / 复习 / 搜索 / 删除 / 导出 |
| `wreader stats` | 阅读统计 + 热力图（`--json` 给脚本用） |
| `wreader achievements` | 成就清单与解锁进度 |
| `wreader config` | 查看 / 修改设置 |

退出码约定：成功 `0`；参数有误、找不到东西（`no book matches ...`）、
或翻译出现失败章节时返回 `1`（`Ctrl-C` 中断是 `130`）。
所有错误都以 `error: ...` 的形式打印，不会甩出 Python traceback。

### `wreader import <路径>`

```bash
wreader import ~/Downloads/books        # 递归扫描整个目录
wreader import ~/Downloads/三体.txt     # 也可以直接导入单个文件
```

- 只认 `.txt` 和 `.epub`，隐藏文件（macOS 的 `._xxx`、`.DS_Store`）自动跳过。
- `.epub` 优先调用系统里的 `ebook-convert`（Calibre）或 `epub2txt`；都没有时用内置解析器（标准库 `zipfile` + `ElementTree`，按 spine 顺序读正文）。
- 标题和作者从文件名猜，支持 `作者-书名`、`[作者] 书名`、`《书名》（校对版全本）作者：某人`、以及单纯的书名；
  文件名结尾的 `（校对版全本）` / `(annotated)` 这类括号注释会自动剥掉，猜不出来时作者记为 `unknown`。
- 转换后的 UTF-8 正文写进小说目录（`~/novels/<书名>_utf8.txt`），同名自动加 `(2)` 后缀。
- 重复导入同一本书会显示 `skipped N duplicate(s)`，不会重复占地方。

### `wreader list`

```bash
wreader list
```

表格里的 `progress` 是阅读进度百分比，`words` 是按中文习惯格式化的字数（`5.7万`、`1.2亿`）。
书库为空时会告诉你索引文件和小说的目录在哪。

### `wreader search <关键词>`

```bash
wreader search 三体          # 中文关键词
wreader search tolkien       # 作者名，大小写无所谓
wreader search hptr          # 首字母跳跃匹配 → Harry Potter
wreader search '#fantasy'    # 带 # 前缀表示只搜标签
```

匹配优先级：完全相等 > 前缀 > 包含（越靠前分越高）> 子序列匹配。书名权重是作者的 2 倍。
没找到就返回 `1` 并提示 `no book matches ...`。

### `wreader read <book_id>`

整本书的核心体验，详细按键见[阅读器快捷键](#阅读器快捷键)。

- 打开时自动检测书的语言，中文书默认进中文视图，英文书默认进英文视图（检测靠 CJK 字符占比，离线纯本地计算）。
- 每 60 秒自动保存一次阅读位置（可关），退出时再完整保存一次。
- 退出时把这次会话的时长、读过的行数写进统计，并检查有没有达成新成就。
- **需要真正的交互式终端**，重定向或管道里跑会报错：
  `error: wreader read needs an interactive terminal (a tty on stdin and stdout)`

### `wreader translate <book_id>`

```bash
wreader translate 3e027c4de949
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

### `wreader vocab`

不带参数时列出笔记（每页 20 条，新的在前）：

```bash
wreader vocab                          # 查看（第 1 页）
wreader vocab --page 2 --per-page 50    # 翻页，调整每页条数
wreader vocab --search 公认             # 按含义反查单词（词 / 释义 / 例句都会搜）
wreader vocab --review                  # 复习模式：打乱顺序，先看单词再按回车核对释义
wreader vocab --remove ephemeral        # 删掉一个词
wreader vocab --export anki > deck.txt  # 导出 Anki 制表符格式，可直接导入 Anki
```

`--review` 在真终端里是交互式的（回车看释义，`q` 停）；如果输出被重定向，它会降级成"一次性把所有词和释义都打印出来"。
`--export anki` 刻意不走 rich，用纯 `stdout` 输出，保证制表符不会被美化掉。

### `wreader stats`

```bash
wreader stats          # 人类可读的表格 + 热力图
wreader stats --json   # 同一个 dict 的原始 JSON，给脚本/看板用
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

### `wreader achievements`

```bash
wreader achievements
```

真实输出：

```
已解锁 1/10
  🏆 📖 开卷有益 第一次打开一本书  解锁于 2026-09-21T16:13:43

进行中
  ░░░░░░░░░░░░░░  ⏱️ 初窥门径 0分钟/1小时  累计阅读满1小时
  ██████░░░░░░░░  🔥 七日不断 3/7  连续7天每天阅读30分钟
```

### `wreader config`

```bash
wreader config                            # 打印全部设置（值 / 默认值 / 来源文件）
wreader config --path                     # 只打印设置文件路径
wreader config reader.page_height         # 读一项
wreader config reader.page_height 30      # 写一项（立即存盘）
wreader config --reset                    # 全部恢复默认
```

真实交互：

```
$ wreader config reader.page_height
reader.page_height = 24

$ wreader config reader.page_height 30
reader.page_height = 30 (saved)

$ wreader config reader.pag_height 20
error: unknown setting 'reader.pag_height' (did you mean 'reader.page_height'?)
```

设置用**点分路径**（`reader.page_height`），旧版 `config.json` 里的扁平名字（`page_height`、`novels_dir`……）依然能用，会自动迁移到对应 section。
写错名字会给出拼写建议，而不是把错键写进文件。类型不匹配（比如给布尔项写 `abc`）也会报错并保持原样。

---

## 阅读器快捷键

阅读器**底部提示栏默认就写着这排按键**（有临时消息时才临时被替换掉），所以不用背：

```
q退出 j/space翻页 g跳行 [/]章节 /搜索 n下一个 b书签 v生词 l语言 t翻屏 T翻章 c中文
```

| 按键 | 作用 |
| --- | --- |
| `q` / `Q` / `Ctrl-C` | 退出阅读器（会保存进度、书签、本次时长） |
| `j` / `空格` / `回车` / `↓` / `PageDown` | 往下翻页（翻页量由 `reader.page_scroll_step` 决定） |
| `k` / `↑` / `PageUp` | 往上翻页 |
| `g` | 跳到指定行号（提示 `跳到行号 (1-281):`，输入数字回车；`Esc` 取消） |
| `G` | 跳到全书最后一行 |
| `[` | 跳到上一章开头 |
| `]` | 跳到下一章开头 |
| `/` | 搜索关键词（中文也能输；命中后自动跳到第一个匹配并高亮） |
| `n` | 跳到下一个匹配（循环） |
| `b` | 在当前行加 / 删书签，状态栏显示书签数量 |
| `l` | 循环切换视图：`中文` → `英文` → `双语对照` → `中文`…… |
| `c` | 直接切到中文视图（英文书常用：边读边看中文） |
| `t` | 只翻译**当前屏幕**上的段落，**不写缓存**（适合随手瞄一眼） |
| `T` | 翻译并缓存**整章**，带进度条；下次再进这一章直接读缓存，不花钱 |
| `v` | 查一个单词并收进生词本（输入框会预填当前行最长的英文单词） |

几个实用细节：

- **底部两行是状态栏**：倒数第二行由 `reader.status_bar_format` 拼成（反色显示），
  最后一行是提示栏——平时显示按键清单，有临时消息（"已加入生词本：xxx = 承认"之类）时优先显示消息。
- **每行最左边一列是书签栏**：有书签的行显示 `★`，其余行留空。
- **搜索高亮**：当前跳到的命中行是反色，同一批的其他命中行是加粗。
- **生词会有下划线**（`vocab.highlight_in_reader = true` 时）；关闭后就不打扰阅读。
- **按 `v` 之后**：如果 `vocab.auto_add_on_mark = true`，查完直接收进生词本；设为 `false` 则会弹一个小窗问你 `[y] 加入生词本　其他键 取消`。
- **读到很慢的章节**（同一章停留超过 30 分钟），提示栏会顺手建议你按 `c` 看看中文。
- **中途 Ctrl-C** 不会丢进度：退出前同样会保存位置和本次时长。

---

## 设置项

设置都在 `~/.wreader/settings.toml` 里，分 5 个 section。可以直接用编辑器改，也可以用 `wreader config <section.key> <value>` 改。
**删掉任意一行都会回落到默认值**，所以不用担心改坏。

### `[reader]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `page_scroll_step` | `1` | 每次翻页滚几屏。`0.5` = 半屏（更细腻），`2` = 两屏 |
| `status_bar_format` | 状态栏显示 `time`、`chapter`、`duration` 三段 | 选状态栏显示哪几段，多段用竖线分隔（详见下表） |
| `auto_save_interval` | `60` | 自动保存进度间隔（秒），`0` = 关闭 |
| `page_height` | `24` | 每屏显示的行数（也是翻页量的基准） |
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
| `backend` | `"google"` | `google`（免密钥）或 `deepseek`（需要 API key） |
| `batch_size` | `3000` | 每次请求的字符数上限 |
| `cache_dir` | `"~/.wreader/cache"` | 译文缓存目录；默认跟随数据目录（所以 `$WREADER_HOME` 也管用） |
| `deepseek_api_key` | `""` | 留空则读环境变量 `DEEPSEEK_API_KEY` |
| `auto_translate_chapter` | `false` | 进入新章节时自动翻译整章（真·懒人模式） |
| `source_language` | `"auto"` | 原文语言，`auto` = 自动识别 |
| `target_language` | `"zh-CN"` | 译文语言 |
| `deepseek_model` | `"deepseek-chat"` | DeepSeek 模型名 |
| `deepseek_url` | `"https://api.deepseek.com/v1/chat/completions"` | 接口地址（兼容 OpenAI 协议的服务也能填这里） |

两个后端的差别：

- **google**：走 `deep-translator` 的 `GoogleTranslator`，免费、免注册，但每次请求之间有 1 秒节流，整本翻译比较慢；网络不通就报 `翻译不可用`。
- **deepseek**：POST 到 OpenAI 兼容的 `/v1/chat/completions`，`temperature` 0.3、开启流式输出，按章整段翻译质量更连贯；必须先给 key：
  ```bash
  wreader config translator.backend deepseek
  wreader config translator.deepseek_api_key sk-你的密钥
  # 或者更安全的做法（不写进文件）：
  export DEEPSEEK_API_KEY=sk-你的密钥
  ```

### `[stats]`

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `daily_goal_minutes` | `60` | 每日阅读目标（分钟），`0` = 不显示目标 |
| `show_heatmap` | `true` | `wreader stats` 里是否显示 30 天热力图 |
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

---

## 文件位置

| 内容 | 路径（macOS / Linux） | 可被覆盖 |
| --- | --- | --- |
| 设置 | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| 书库索引 | `~/.wreader/library.json` | `$WREADER_HOME` |
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
- `tags` 目前由 `wreader search '#tag'` 使用，命令行还没有加标签的入口，需要手改索引。

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

定义在 `wreader/data/achievements.json`，一共 10 个。条件是简单的 `指标 比较符 数字` 表达式，可以自己加。

| 成就 | 名称 | 条件 |
| --- | --- | --- |
| `first_book` | 📖 开卷有益 | 第一次打开一本书 |
| `first_hour` | ⏱️ 初窥门径 | 累计阅读满 1 小时 |
| `ten_hours` | 🎓 学富五车 | 累计阅读满 10 小时 |
| `night_owl` | 🌙 深夜书虫 | 凌晨 0-4 点阅读超 1 小时 |
| `streak_7` | 🔥 七日不断 | 连续 7 天每天阅读 30 分钟 |
| `streak_30` | 🗿 铁血读者 | 连续 30 天每天阅读 |
| `book_finished` | 🏁 完本达人 | 读完第一本书 |
| `vocab_100` | 📝 词汇积累 | 生词本满 100 个 |
| `translator` | 🌍 双语者 | 首次使用翻译功能 |
| `marathon` | 🧘 专注模式 | 单次连续阅读超 2 小时 |

条件里可用的指标：`books_read`、`total_time`、`night_time`、`streak`、`finished`、
`vocab_count`、`translations`、`single_session`（时间类指标单位是**秒**）。

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
├── .vscode/settings.json    把 Pylance / 终端指向 .venv 解释器
├── wreader/
│   ├── __init__.py          __version__ 和模块地图（18 行）
│   ├── cli.py               argparse 定义 + 各子命令处理函数（1006 行）
│   ├── config.py            settings.toml 读写、类型校验、旧配置迁移、数据目录搬迁（985 行）
│   ├── library.py           txt/epub 导入、编码识别、书名解析、索引与模糊搜索（1077 行）
│   ├── reader.py            curses 分页阅读器：视图、搜索、书签、状态栏（1948 行）
│   ├── translator.py        Google / DeepSeek 后端 + 章节缓存（1305 行）
│   ├── vocab.py             生词本：增删查、复习、Anki 导出（436 行）
│   ├── stats.py             统计指标、热力图、成就判定与庆祝动画（849 行）
│   └── data/
│       └── achievements.json  10 个成就的定义（62 行）
└── tests/                   494 项测试，全部离线运行（见下方「运行测试」）
    ├── conftest.py          共享 fixture：隔离的 $WREADER_HOME、假翻译后端、epub 构造器
    ├── test_config.py       49 项 —— 默认值、类型校验、旧配置迁移、数据目录搬迁、目录解析
    ├── test_library.py      116 项 —— 编码、章节、epub、导入去重、书名解析、模糊搜索
    ├── test_reader.py       115 项 —— 分页数学、Pager、状态栏、按键、会话落库、折行与显示宽度
    ├── test_stats.py        76 项 —— 指标、连续天数、热力图、成就解锁、报告
    ├── test_translator.py   74 项 —— 语言识别、分批、章节缓存、两个后端、SSE
    ├── test_vocab.py        31 项 —— 生词本读写、刷新不重复、复习、Anki 导出
    └── test_cli.py          33 项 —— 参数解析、各子命令输出、退出码
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
wreader --help
wreader list

# 不污染真实数据地做实验：换一个数据目录即可
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
wreader import /tmp/my-test-books
```

调试建议：

- **想清空重来**：删掉 `$WREADER_HOME`（默认 `~/.wreader`）和小说目录即可，`wreader` 下次运行会重新生成默认设置。
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
pytest                      # 494 项，约 5 秒
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

---

## 常见问题

**Q：新开终端后敲 `wreader` 提示 command not found？**
这是最常见的报错，**不是装坏了**：`wreader` 装在项目自己的 `.venv` 里，而 `.venv/bin` 默认不在 `PATH` 上。
推荐在 `~/.zshrc` 里配一行别名一劳永逸，见[新开一个终端后怎么用 wreader](#新开一个终端后怎么用-wreader)；
临时也可以用 `<项目路径>/.venv/bin/wreader`、先 `source .venv/bin/activate`，
或者干脆把 `wreader xxx` 写成 `python -m wreader.cli xxx`。

**Q：升级后我原来的书库去哪了？**
`wreader` 第一次运行时会把 `~/.nr` 整体搬到 `~/.wreader`，不用你动手。如果两个目录都存在，
`wreader` 只用 `~/.wreader`、不碰 `~/.nr`——确认新目录没问题后可以自己删掉它。

**Q：导入时说 `path does not exist` / `no .txt/.epub file found under ...`？**
路径写错了，或者那个目录里确实没有 `.txt` / `.epub`。`wreader import` 是递归扫描的，直接给上层目录也行。

**Q：中文书导入后是乱码？**
编码按 BOM（UTF-8 / UTF-16 / UTF-32）→ chardet → UTF-8 → GB18030 依次尝试。BOM 只说明文件"想"是什么编码
（UTF-32 的 BOM 以 UTF-16 的 BOM 开头，损坏的 UTF-16 文件里也可能有非法 surrogate），所以带 BOM 的文件解码失败时
会用替换字符降级导入，并在编码名后面标 `(replaced)`，而不是让整次导入崩掉。真遇到这种文件，用编辑器另存为
UTF-8 再重新 `wreader import` 就能拿到干净正文。
如果仍不正常，先用编辑器把源文件另存为 UTF-8，再重新 `wreader import`。

**Q：同一本书导入了两次？**
不会。书号是正文的 SHA-1，第二次会显示为 `skipped 1 duplicate(s)`。
注意：换书名再导入仍会被认出来（内容没变），但**改过内容**就会被当成新书。

**Q：按了 `t` 却没有译文？**
`t` 只翻译当前屏幕，且**不缓存**；如果它提示 `当前视图就是原文，无需翻译`，说明你要的正是这本书的原文语言。
想永久保存译文请按 `T`（整章缓存），或者先在命令行跑一次 `wreader translate <book_id>`。

**Q：翻译报错 `翻译不可用: ...`？**
Google 后端需要联网；DeepSeek 后端需要 API key（`wreader config translator.deepseek_api_key sk-xxx`
或 `export DEEPSEEK_API_KEY=...`）。国内网络下 Google 可能不通，建议换 deepseek。

**Q：`wreader read` 报 `needs an interactive terminal`？**
阅读器要在真终端里跑，不能 `| less`、不能重定向、也不能在 CI 里跑。
（`wreader list` / `wreader stats` 这些可以随便重定向。）

**Q：退出后统计没变？**
检查两处：`reader.store_history` 是否为 `true`；以及这次会话是否保存成功（磁盘只读或数据目录不可写会静默跳过）。

**Q：时间不长，为什么"连续天数"已经是 1 了？**
当天永远算数——因为它正要变成事实。真正的门槛是"某天累计 ≥ 30 分钟"。

**Q：想要安静地读书，不要统计、不要响铃？**
```bash
wreader config reader.store_history false
wreader config stats.achievement_sound false
wreader config stats.show_heatmap false
```

**Q：怎么把生词导进 Anki？**
```bash
wreader vocab --export anki > deck.txt
```
然后 Anki → 文件 → 导入，字段选"制表符分隔"，三列分别是 单词 / 释义 / 例句。

**Q：书删了，索引还在？**
命令行目前没有删除命令。删掉 `library.json` 里 `books` 下对应的那个 id 即可
（`wreader list` 会立刻不再显示它）；或用 Python：
```python
from wreader import library
library.remove_book("3e027c4de949")   # 同时删掉 ~/novels 里的 UTF-8 正文
```

**Q：`settings.toml` 改坏了怎么办？**
`wreader config --reset` 恢复全部默认；或者删掉文件让它重新生成。删单行则只回落到该行的默认值。

---

## 已知问题

这些是当前版本真实存在的限制，写出来比藏着好：

- **`reader.theme` 还没实现**，改了没有任何效果。
- **加标签没有命令行入口**。`books[].tags` 和 `wreader search '#tag'` 都支持，但目前只能手改 `library.json`。
- **EPUB 解析有取舍**：没装 Calibre 的 `ebook-convert` 时用内置提取器，只取正文文本，
  图片、脚注、复杂排版会丢失；能装 Calibre 建议装上。
- **`wreader read` 只能在真终端里用**（见上方 FAQ）。
- **Windows 需要额外依赖** `windows-curses`（`pip install -e ".[windows]"`）。
- **`library.json` 里 `progress` 的数值不做类型强制转换**：手写成字符串（`"current_line": "12"`）
  也能正常读，因为消费方都用 `int(...)` 兜住了，但它不会被自动改回数字。

已经解决、不再属于已知问题的十条（留个记录，免得又被当成待办）：

- ~~没有 LICENSE~~ → 已加 MIT（`LICENSE` + `pyproject.toml` 的 `license = "MIT"`）。
- ~~`translator.__all__` 里有不存在的 `chapter_paragraphs`~~ → 已移除该名字，
  换成真实存在的 `TranslatorCallable`；此前 `from wreader.translator import *` 会直接抛 `AttributeError`。
- ~~`library.py` / `stats.py` / `translator.py` / `vocab.py` 还有约 10 条类型告警~~ → 已全部修掉，
  `pyright` 现在是 0 errors / 0 warnings。
- ~~没有自动化测试~~ → 已补 **494 项 pytest**（`tests/`），全程离线、不碰真实数据。
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





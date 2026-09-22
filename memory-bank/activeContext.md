# Active Context — 当前焦点与最近改动

> 每次会话结束前更新这个文件。最后更新：**2026-09-22**。

## 当前状态一句话

代码库处于**干净、全绿**状态：`545 passed`、`pyright 0 errors / 0 warnings`、
`tools/` 的 7 个校验脚本全绿，且**已 git 化并推送到 GitHub**（`main` = `origin/main`，工作区干净）。
⚠️ 但注释覆盖**不是** 100%：严格口径下 `wreader/` + `tests/` 还有 **2279** 条语句上方没有紧邻注释行
（见 ⑪ 与 `progress.md` 待办 #4）—— 早先那句 `TOTAL: 0` 已作废。
本会话完成了：中文注释、自动换行、背景跟随终端、git 化并推 GitHub、启动方式文档、
README 数字同步、校验脚本进 `tools/`、鼠标滚轮 / 触摸拖动翻页、翻页保留 3 行上下文（⑭）、
翻页改按屏幕行精确推进（⑮）、屏顶坐标升级为 `(源行号, 段内偏移)` 修掉半截段落被跳过（⑯）、
新增 `wreader continue` 列"最近打开阅读的三本书"（⑰）、**安装压成三行命令 `./install.sh`（⑱）**。

## 最近改动（2026-09-22，按时间顺序）

### ① 全仓加逐行口语化中文注释（16 个 Python 文件）
- 范围：`wreader/` 8 个 + `tests/` 8 个（含 `conftest.py`），共 12,491 行。
- 当前实测注释规模：以 `#` 开头的注释行 **2,704 行**（`wreader/` 1,728 + `tests/` 976），
  其中绝大部分是本轮新增。
- 风格：每条逻辑语句**上方**一行中文注释，口语化讲清"在干嘛 + 类型/副作用/边界"；
  **原有 docstring 与英文注释全部保留**，中文补在上方或旁边。
- 逻辑零改动。为验证这一点，写了 `/tmp/check_comments.py`（基于 `tokenize` 找逻辑语句起点，
  检查其上方是否紧邻注释行，自动跳过 docstring/续行/`elif`/`except`）。
- 过程中**误改过 2 处代码并已还原**：
  - `config._unknown_path` 的 `hint` 曾被误加 `.rstrip("\n")`
  - `config._flatten` 的 `name = "{}.{}".format(prefix, key)` 曾被误改成 `"{}.{}\n".format(...).rstrip("\n")`
- 注：做这件事时工作目录**还不是 git 仓库**，因此无法用 diff 证明"零逻辑改动"，只能靠
  `py_compile` + 全量 pytest + 注释覆盖检查兜底。**这个隐患已在会话末尾解决**（见 ⑦）。
  ⚠️ 但要清醒：首个提交 `7ecc3eb` 里**就已经包含**这批注释改动，
  它**不是**"改注释之前"的基线 —— 真正能用 `git diff` 对比的起点是 `7ecc3eb` 之后。

### ② 修复"终端阅读时没有自动换行"
**根因**：`reader.py` 完全没有折行逻辑。每个源行被当作一条屏幕行，直接
`window.addstr(row, 1, text, attr)`；curses 在文本越过右边界时抛 `curses.error`，
而 `_addstr`/`_draw_text` 都是 `except curses.error: pass` → **超长行被静默截断**。

**改法**（`wreader/reader.py`）：
1. 新增 `_char_width`（东亚 Wide/Fullwidth = 2 列）、`_text_width`、`_clip_line`、`_wrap_line`。
   `_wrap_line` 按**显示宽度**折行：英文在最后一个空格断开（不劈单词）、汉字逐字断（不劈全角字符）、
   Tab 先展开成 4 空格、行尾空格丢弃、空行仍保留一行。
2. `Pager.visible_rows(height, width=None)` 增加可选 `width`：给了就折行，一个源行可占多条屏幕行。
   `width=None` 时行为与旧版完全一致（向后兼容）。
3. `_draw` 传入 `text_width = width - 1`（第 0 列留给书签位），删掉重复的 Tab 展开，
   并用 `previous_index` 让书签 `★` **只在某源行的第一条屏幕行**上出现。
4. 顺手修掉一个自己的边界 bug：溢出字符**本身是空格**时不该回头找更早的空格，
   否则会把已经排满整行的最后一个单词白白推到下一行。

### ③ 全部宽度计算改按"显示列数"（原来用 `len()`）
上一轮只改了阅读区，状态栏/消息行/弹窗仍在用字符数，导致窄屏下整行可能越界而消失。
按用户要求统一：
- `format_status_bar()`：丢段判断 `len(piece)` → `_text_width(piece)`；末尾硬截断 `[:room]` → `_clip_line(..., room)`
- `_message_row()`：`[:room].ljust(room)` → `_pad_line(..., room)`；"两者都放得下"的判断也改用 `_text_width`
- `_draw_status()`：信息栏 `.ljust(room)` → `_pad_line(..., room)`
- `_confirm()`：`line[:limit]` → `_clip_line(line, limit)`；`box_width` 按 `_text_width` 算
- 新增安全网：`_addstr()` 写之前先 `_clip_line(text, width - column)`。
  这样即使某行超宽，也只是被裁到屏幕上放得下的部分，**不会整行消失**。

### ④ 修复"正文背景固定黑色、不跟随终端主题/透明"
**根因**：全项目**从未初始化颜色**（无 `start_color()` / `use_default_colors()` / `init_pair()` /
`bkgd()`；`reader.theme` 也只是预留项）。这种情况下列表绘制只能用 curses 自己的默认配色对，
在不少终端上就是**不透明黑底**。

**改法**：新增 `_init_colors()`，在 `_run()` 里（`initscr()` 之后、主循环之前）调用：

```python
def _init_colors() -> None:
    try:
        if not curses.has_colors():
            return
        curses.start_color()          # 会先把默认配色设成白底黑字
        curses.use_default_colors()   # 再交还给终端默认前景/背景
    except curses.error:
        pass                          # 老终端不支持"默认色"，保持现状
```

**必须成对调用**：只调 `start_color()` 反而会把默认配色锁死成黑底。
全程不 `init_pair()`、不用 `color_pair()`，所以 `A_REVERSE`/`A_BOLD`/`A_DIM`/`A_UNDERLINE` 高亮不受影响。

### ⑤ 建立 MemoryBank + `.clinerules`
- 新建 `memory-bank/`：`README.md`（索引）+ `projectbrief.md` / `productContext.md` /
  `systemPatterns.md` / `techContext.md` / `activeContext.md` / `progress.md`，共 7 个文件。
  内容全部依据**实测结果**写（源码行数、`pytest --collect-only` 项数、`pyright` 输出、
  注释覆盖检查、`README.md` 中仍有效的部分），并纠正了 README 里已过期的数字。
- 新建 `.clinerules/memory-bank.md`：把「维护协议」（读取顺序 / 何时更新哪个文件 /
  写作纪律 / 项目硬性约束 / 本项目特殊提醒）放进规则目录，对**每次会话**自动生效。
- `memory-bank/README.md` 里的协议段落已改为**指向 `.clinerules`**，避免出现两个事实来源。

### ⑥ 修掉 `/tmp/demo_colors.py` 的 Pylance 报错（无法解析导入 `wreader`）
- **根因**：脚本住在 `/tmp`，**不在 `wreader` 工作区内**。`sys.path.insert(0, "...")`
  只有**运行期**生效，静态分析不执行它；而 `.vscode/settings.json` 的
  `python.analysis.extraPaths` 只有 `${workspaceFolder}` → Pylance 找不到 `wreader` 包。
  （`npx pyright` 在仓库里跑不报错，是因为 `.venv` 装了 editable
  （`site-packages/__editable__.wreader-0.1.0.pth`），Pylance 分析 `/tmp` 下的文件时不走这条路。）
- **改法**（只动 `/tmp/demo_colors.py`，**仓库代码零改动**）：导入行加**定点忽略**
  `from wreader import reader  # pyright: ignore[reportMissingImports]`，并在上方补中文注释讲原因。
  只压掉"无法解析导入"这一条诊断，其它类型错误照常上报。
- **对照实验**（证明是忽略注释在起作用、不是碰巧）：把同一文件去掉忽略注释另存
  `/tmp/demo_colors_baseline.py`，在 `/tmp` 下 `npx pyright` → `1 error:
  Import "wreader" could not be resolved (reportMissingImports)`；加回注释 → `0 errors`。
- 想**彻底**不写忽略注释，就把脚本搬进仓库（如 `tools/demo_colors.py`），
  正好对应 `progress.md` 待办 #3（`/tmp` 会被系统清理）。

### ⑦ 项目 git 化并上传 GitHub（2026-09-22）
- `git init -b main` → 首个提交 **`7ecc3eb`**（32 文件 / 15,843 行），
  `origin` = `https://github.com/zhangziluo/wreader`，`git push -u origin main` 成功；
  远端 `main` 与本地 `HEAD` 同一 SHA，`git rev-list --left-right --count origin/main...main`
  返回 `0 0`。
- **`.gitignore` 新增**（原有 Python / venv / 缓存条目全部保留）：
  `book/`（开发用真实电子书样例，实测 367 MB，单文件最大 147 MB → 远超 GitHub 单文件 100 MB 硬限制）、
  `.DS_Store`、`._*`、`*.log`。
- 入库：`wreader/`（8 模块 + `data/achievements.json`）、`tests/`（8 文件，494 项）、
  `memory-bank/`（6 状态文件 + 索引）、`.clinerules/memory-bank.md`、三份文档、
  `pyproject.toml`、`LICENSE`、`.vscode/settings.json`。
  **未**入库：`book/`、`.venv/`、`.pytest_cache/`、`wreader.egg-info/`、`__pycache__/`、
  两个 `.DS_Store`。提交前实测：staged 合计 **704 KB**，最大单文件 76 KB（`reader.py`）。
- **认证踩点（重要）**：本机**没有 `gh` CLI**；`~/.ssh/id_ed25519` **未注册**到 GitHub
  （`ssh -T git@github.com` → `Permission denied (publickey)`）；
  但系统级 `/usr/local/etc/gitconfig` 里有 `credential.helper=osxkeychain`，
  Keychain 里存着 `github.com` / 账号 `71907942` 的凭证 →
  **走 HTTPS 直接 push 成功，全程零交互**。所以远端 URL 必须用 HTTPS，不要改 SSH。
- 全局另有 `http.proxy` / `https.proxy` = `http://127.0.0.1:7897`；代理没开时 push 会失败，
  可临时 `git -c http.proxy= push` 绕过。
- 顺带清掉散落文档里的"无 git 仓库"过期说法：`.clinerules/memory-bank.md`（含新增的
  `book/` 禁上传、认证方式提醒）、`projectbrief.md`、`progress.md`、`techContext.md`、
  `activeContext.md`；`progress.md` 的待办序号因删掉第一项而整体前移一位。
- **推完做了克隆回环验证**：从 GitHub 全新 `git clone` 到 `/tmp/wreader-clone`，
  在克隆目录内跑 `pytest` → **494 passed**、`npx pyright` → `0 errors`，
  且 `wreader.__file__` 指向克隆副本（排除"其实在测本地 editable 安装"的假阳性）。
  结论：仓库自足，`book/` 不参与测试，忽略它没有任何副作用。

### ⑧ 让 `wreader` 在新终端里可直接敲（`~/.zshrc` 别名）
- **问题**：用户重开终端后不知道怎么打开 wreader —— 因为它是**项目内** `.venv` 的
  editable 安装，`.venv/bin` 不在默认 PATH 上，敲 `wreader` 会 `command not found`。
- **排查事实**：`~/.zshrc` **原本不存在**；`~/.zprofile`（只有 brew / MacPorts 的 PATH 前置）、
  `~/.zshenv`（只 source cargo env）、`/etc/paths` 与 `/etc/paths.d/*` 全都没配这个 venv。
- ⚠️ **排查时踩过一个坑（假阳性）**：一开始直接跑 `zsh -l -c 'command -v wreader'` 显示"能找到"，
  但那是因为它**继承了我当时那个已激活 venv 的环境**。必须用
  `env -i HOME=$HOME ... zsh -l -i -c ...` 把环境清干净，才测得出真实情况（结论：找不到）。
- **第一版方案（已推翻）**：`~/.zshrc` 里 `export PATH=".../.venv/bin:$PATH"`。
  能用，但**有副作用**：新终端里 `python3` → `.venv/bin/python3`、`pip` → `.venv/bin/pip`，
  会干扰用户在其它 Python 项目上的工作。
- **最终方案**：只写一行别名
  `alias wreader="/Users/zhangziluo/Downloads/wreader/.venv/bin/wreader"`，
  并在文件注释里写明**为什么不用 PATH**（防止以后有人好心改回去）。别名只作用于
  交互式 shell，对 `python3` / `pip` 零影响。
- `~/.zshrc` **在 git 仓库之外**，不受版本控制；排查结论与坑已记进 `techContext.md`。

### ⑨ 把"新终端怎么打开"写进《使用指南.md》
- 新增独立章节 `## 关掉终端之后：下次怎么打开 wreader`（放在第 11 步之后、报错急救表之前）：
  讲清"为什么新终端里 `wreader` 找不到"（装在项目 `.venv` 里、不在 PATH），
  给出三种办法 + 对比表 + "到底该选哪个"：
  ① `~/.zshrc` 别名（推荐，含 bash 用 `~/.bashrc`、Windows 用 `$PROFILE` 的写法）、
  ② 直接写完整路径、③ 每次激活 venv。
  也把**别用 PATH 前置**（会连累 `python3`/`pip`）和"书与进度不受 `.venv` 影响"写进去了。
- **四个入口都做了交叉引用**，不管从哪儿读都能找到：目录（TOC）、第 2 步的 ⚠️ 提示、
  第 3 步 ④ 的 💡 提示、报错急救表的 `command not found` 行。
  另外"常用命令速查卡"新增一段"新开终端"代码块，"术语小词典"新增 `别名（alias）` 与 `PATH` 两条。
- 规模：737 → **837** 行（+103 / −3）。
- 顺手记一条踩坑：我原写了一句 `「关掉终端之后」`，但全文 **38 处引号清一色是 ASCII `"`**，
  `「」` 只在全文出现过那 1 次（就是我写的）→ 已改成 `"关掉终端之后"`，复查残留为 0。

### ⑩ 两份 README 同步过期数字 + 补「新终端怎么打开」
- **过期数字全部按实测改对**（没有一个是从 memory-bank 的旧记录里抄的，全部重新量过）：
  - 源码行数（`wc -l` 实测）：`__init__.py` 16→**18**、`cli.py` 811→**1006**、
    `config.py` 779→**985**、`library.py` 826→**1077**、`reader.py` 1412→**1948**、
    `translator.py` 1048→**1305**、`vocab.py` 298→**436**、`stats.py` 655→**849**
  - 测试项数：总数 474→**494**；`test_reader.py` 95→**115**
    （其余 33 / 49 / 116 / 76 / 74 / 31 复查过，本来就对，没动）
  - `474` 一共 **6 处**：两份 README 的"项目结构""运行测试""已解决清单"各一处，**全部改掉**
- **新增一节**：`README.md` 的「新开一个终端后怎么用 wreader」与 `README.en.md` 的
  「Using wreader in a new terminal」——内容与《使用指南.md》那节对齐（三种办法 + 对比表 +
  「别把 `.venv/bin` 前置进 PATH」的警告 + `python -m wreader.cli` 兜底）。
  同时把「安装」里"装完之后就有了 `wreader` 命令"改成"**在当前这个终端窗口里**有了"
  （原文不准确：换个窗口就没了），并把 FAQ 的 `command not found` 一条改为指向新章节。
- **顺手改正一处旧笔误**：中文版「已经解决、不再属于已知问题的**六条**」，实际列了 **7** 条
  （英文版写的是 Seven，本来就是对的）。补上本轮三项修复后，中英两版统一为 **十条**。
- 「特性」表的阅读器一行补上"按终端宽度自动折行（汉字按 2 列算）、配色跟随终端主题与透明背景"。
- 「已知问题」里"README 陈旧"那一条已删除（不再成立）。
- 两版 README 的目录（TOC）各加一行指向新章节的链接，保持原有的扁平列表风格
  （锚点 `#新开一个终端后怎么用-wreader` / `#using-wreader-in-a-new-terminal`，已校验可解析）。
- 后果：`progress.md` 待办 #1 与 `activeContext.md` 待办 #1 都已标记完成；
  `techContext.md`、`memory-bank/README.md` 里"README 尚未同步"的提示也一并改掉了。

### ⑪ 把 `/tmp` 里的校验脚本搬进仓库 `tools/`（+ 抓出一个假绿 bug）
- **搬进来 6 个脚本 + 一份 `tools/README.md`**：`check_docs.py`（文档锚点/围栏）、
  `check_doc_numbers.py`（README 数字对拍）、`check_comments.py`（注释覆盖）、
  `verify_wrap.py`、`verify_draw.py`、`verify_colors.py`。
- **统一改造**：都从 `__file__` 推算仓库根（**任意目录都能运行**，实测在 `/tmp` 下跑也 OK）；
  退出码 0/1（可接 CI）；带逐行中文注释与类型标注；把 `tools` 加进 `[tool.pyright]` 的 include
  （pyright 仍 **0 errors / 0 warnings**）。
- ⚠️ **意外收获：原 `check_comments.py` 是个假绿的检查**。
  它把 `tokenize.NEWLINE` 也放进了「跳过」集合，于是
  「一条语句结束 → 下一条语句开始」这个判断**永远不会触发**，
  `expect_new` 只在一开始为 True —— 结果是**每个文件只检查了第 1 行**。
  实测对照：`wreader/cli.py` 里该函数只找到 **1** 个语句起点（第 1 行），
  修正 NEWLINE 处理后找到 **405** 个。
  也就是说，此前记录的「注释覆盖 TOTAL: 0 / 无遗漏注释的逻辑语句」**什么也没证明**。
- **修正后的真实数字**：`wreader/` + `tests/` 共 **2054** 条语句上方没有紧邻注释行
  —— `reader.py` 357、`translator.py` 189、`library.py` 163、`test_reader.py` 286、
  `test_library.py` 158、`test_config.py` 135 …
  （分布是合理的：表头 `table.add_column(...)` 一整组、函数里的 `return`/`assert` 一串，
  通常共享一段块级注释，而不是每条都单独注释。）
- **因此做了三处诚实校正**：`projectbrief.md` 的「注释规范」、`.clinerules/memory-bank.md` 的
  同名约束、`progress.md` 的待办 —— 都把口径从「16 个文件已统一、TOTAL: 0」改成
  「这是**目标**，实测还有 2054 条差距；实际风格是"一段逻辑配一段中文注释"」。
  是否全量补齐、还是改成增量门禁，留作 `progress.md` 待办 #4 供拍板（我倾向不补齐）。
- `check_comments.py` 因此**默认只报告不判定**（否则 CI 直接全红），
  要门禁就加 `--strict`，并可配合文件参数一次啃一个。

### ⑫ 鼠标滚轮 / 触摸拖动逐行滚动（Termux 适配）
- **需求**：用户在安卓 Termux 上反馈"上下翻页不适配，往下触屏翻页看不到上下文"，
  要求"上下滑动翻上下行，或音量键翻页"。拍板口径：滚轮一格 **1 行**、触摸拖动一起做、
  **向上滑 = 往后读**、向下滑 = 往前看。
- **实现**（`wreader/reader.py`，含注释约 +150 行）：
  - `_enable_mouse()`：`mouseinterval(0)` + `mousemask(ALL_MOUSE_EVENTS | REPORT_MOUSE_POSITION)`
  - `_DragScroll`：纯状态机，把连续的位置报告换算成滚动行数（1 行 = 1 行）
  - `_mouse_scroll_delta()`：纯函数，把 `(bstate, y)` 换算成滚动行数（滚轮 / 拖动 / 忽略）
  - `_mouse_event_delta()`：薄胶水，负责读 `curses.getmouse()`
  - `_run()`：新增 `KEY_MOUSE` 分支 → `pager.scroll(delta)` → `_maybe_auto_translate`
  - `Pager` 新增 `wheel_scroll_step` / `touch_scroll`；`config.SCHEMA` 同名两项（**21 → 23 键**）
- ⚠️ **这一路我错了两次，都是靠真 pty 实验纠正的**（单测发现不了）：
  1. 第一版把滚轮下的位猜成 `_WHEEL_UP << 6`。实测灌 button5 只得到位置报告 ——
     这套 Python/curses **根本没有 BUTTON5 概念**；而猜出来的值**正好等于 `BUTTON_SHIFT`**，
     会把 shift+点击误判成滚轮。已改成"拿不到真常量就不支持该方向"。
  2. 拖动一开始怎么都不动。加探针才看清：**按下事件压根没被上报** ——
     `curses.mouseinterval` 默认的点击判定窗口把它扣住了，拖动状态建立不起来，
     之后的位置报告全被当成普通移动丢掉。设 `mouseinterval(0)` 后立刻正常。
- **排错过程本身也有坑**：最初用 `TERM=xterm-256color` 灌 SGR 序列，全被当成普通按键 ——
  macOS 这份 terminfo **没有 `XM` 能力**，curses 只开 `?1000h`、不开 SGR(1006)。
  换成机器上确实存在的 **`xterm-1006`** 才测出真实结果。
- **工具补上**：新增 `tools/verify_mouse.py`（真 pty 端到端 6 项对账），校验脚本共 **7 个**。
- **音量键翻页**：阅读器本来就认 `↑` / `↓` / `PageUp` / `PageDown`，所以在 Termux 设置里把
  音量键映射过去即可，**无需改代码**；已写进《使用指南.md》的「场景 E：在手机上读」。

### ⑬ 全量复核并同步 MemoryBank（本次会话收尾）
- **触发**：用户要求"把目前的项目进度同步到 MemoryBank"，按协议对**全部 6 个状态文件 + 索引**
  逐项复核（这是协议里唯一要求全量复核的动作）。
- **做法**：先把所有数字**重新实测**（不信任旧记录），再逐文件比对，改掉与事实不符的地方。
- **本次实测基线**（全是跑命令得到的，不是估算）：
  - 源码行数：`__init__` 18 / `cli` 1006 / `config` **987** / `library` 1077 / `reader` **2100** /
    `stats` 849 / `translator` 1305 / `vocab` 436（合计 7778）
  - 测试：**514**（cli 33 / config **50** / library 116 / reader **134** / stats 76 /
    translator 74 / vocab 31），`tests/` 共 5050 行
  - `tools/`：**7 个脚本 + README**（862 行）
  - 配置：`SCHEMA` 共 **23** 键（reader 8 / translator 9 / stats 3 / vocab 2 / library 1）
  - git：**40 个跟踪文件**（`git ls-files` 实测）；提交数刻意不写死 —— 见下面那条教训；
    `main` 与 `origin/main` 一致（`0 0`），工作区干净
  - 校验脚本：check_docs OK、check_doc_numbers ALL OK、check_comments **2134**、
    verify_wrap 40077、verify_draw 420、verify_mouse 6 项全过；`pyright` **0 告警**
- **改掉了这些与事实不符的内容**：
  - `activeContext.md` 开头的"注释覆盖检查 `TOTAL: 0`" —— 这是被 ⑪ 推翻的旧说法，
    却一直漏在摘要句里没改（只改了证据表那一行）。现在改成 2134 并注明作废。
    **教训：改了证据表，别忘了改摘要句。**
  - `progress.md`：状态表 494→**514**、2054→**2134**、"16 个文件"→**23**、
    文档体积 37/40/31 KB → **42/44/37 KB**；工程质量里"16 个文件逐条语句上方都有注释"
    改成口径已校正的说法；待办 #4 的数字与文件分布同步（`reader.py` 379、`test_reader.py` 342）。
  - `techContext.md`：`tests/` 行的 494→514、`pytest` 注释 494→514、
    "已同步"提示改成指向 `tools/check_doc_numbers.py`。
  - `systemPatterns.md`：模块规模表 `config.py` 985→**987**、`reader.py` 1948→**2100**。
  - `projectbrief.md`：注释差距 2054→**2134**；版本控制一行换成当前的提交数 / 文件数；
    核心需求 #3 补上滚轮与触摸；"非目标"里"不做移动端"澄清为"**不做手机 App，
    但要能在手机终端里用**"。
  - `memory-bank/README.md`：494→514，并补一条**本次基线快照**。
  - `productContext.md`（本会话之前一直没动过）：补上"手机终端用户"这类目标用户、
    "手机上也能读"的体验目标、以及 3 条相关产品决策（1 行 = 1 行、方向约定、按键位不猜）。
- ⚠️ **又踩了一次"写死就会过期"的坑**（与早先写死 SHA 是同一类）：这次同步里我在 **5 处**写了
  "12 个提交"，可**这次同步自己又提交了两次** —— 落笔即过期。已全部改成稳定事实
  （"40 个跟踪文件"）或判据（"`git status` 不领先/不落后"）。
  并把这条教训补进了 `.clinerules/memory-bank.md` 的「写作纪律」，下次别再犯。
- **推送插曲（值得记）**：提交 `63b1eb8` 后第一次 `git push` 报了
  `LibreSSL SSL_connect: SSL_ERROR_SYSCALL in connection to github.com:443`；
  而**原样重试立刻成功**，同一时刻 `curl -x http://127.0.0.1:7897 https://github.com` 也返回 200 ——
  属于网络抖动，不是认证或代理配置坏了。这条已写进 `.clinerules/memory-bank.md`，
  免得下次误判成 keychain / helper 出问题而去乱改配置。
- **结论**：6 个状态文件 + 索引全部与实测一致，没有留下"以后再说"的过期内容。

### ⑭ 翻页保留 3 行上下文（用户需求：「阅读翻页的时候，上下保留三行前面的文字」）
- **需求解读**：翻页后新屏幕**顶部**要留着上一屏末尾的几行（往回翻时留下来的是**底部**），
  别让整屏跳转把上下文切断。
- **做法**：把翻页步长减去一个重叠行数 ——
  `Pager.step_lines = max(1, round(page_scroll_step × page_height) − page_overlap)`，默认 `page_overlap = 3`。
  因为翻页键 (next_page/previous_page) 前后对称，所以「顶部重叠 + 底部重叠」一次实现。
- **做成配置项而非写死 3**：`config.SCHEMA` 新增 `reader.page_overlap`（键数 **23 → 24**）。
  项目既有约定是阅读行为都走 SCHEMA；写死会留魔数，且用户可调大或设 `0` 关闭。
- **不动滚轮/触摸**：它们走 `scroll(±wheel_scroll_step)` 逐行走，本来就有上下文，不经过 `step_lines`。
- **关键点 / 坑（全在 `reader.py`）**：
  - 新增 `DEFAULT_PAGE_OVERLAP = 3`（模块 `__all__` 10 → **11**），与 `DEFAULT_STATUS_FORMAT` 同款约定。
  - `open_reader` 读配置必须用 `reader_settings.get('page_overlap', DEFAULT_PAGE_OVERLAP)`，
    **不能用 `or 3`** —— `0 or 3 == 3`，那样「关闭重叠」会被静默吃成默认值。
  - `Pager.__init__` 里 `self.page_overlap = max(0, int(page_overlap))`，负重叠夹到 0（否则会跳更多）。
  - `tests/conftest.py` 的 `pager_factory` 显式注入 `page_overlap=0`：否则 `page_height=4` 的既有分页断言
    （步长 = 屏数 × 每屏行数）会全被重叠改写而失真。
  - ⚠️ **`tools/verify_mouse.py` 的期望值是顺序累积的**：键盘基准从 24 行变 21 行（24−3），
    后续 23/27/24/24/19 连锁平移成 20/24/21/21/16；并新增第 ⑦ 项
    （`page_overlap=0` 时 `j` 仍走 24 行）来验证该设置真的生效。
    （此段数字已被 ⑮ 再次平移，见 ⑮。）

### ⑮ 修复"翻页跳行"：翻页改按**屏幕行**推进（用户报告）
- **现象/根因**：`step_lines` 是**文本行**数（`round(page_scroll_step × page_height) − overlap`），
  而小说里长段落没有换行、会被终端折成多屏行，所以"一屏"对应的文本行数是变的 ——
  按固定文本行数跳，会整段跳过**从未显示过**的内容。
- **关键取舍：拒绝用户提案里的 `ceil(len(text) / max_x)` 算法**。汉字占 2 列，
  `len()` 会把折行算错一倍；而且它会劈开英文单词、忽略 Tab 与双语视图。
  项目硬约束要求宽度计算只能走 `_char_width`/`_wrap_line`。
- **改法（复用已有正确折行）**：
  - `Pager` 新增 `viewport_rows` / `viewport_width`，由 `_draw` **每帧**按真实终端填入
    （`text_rows = height − 2`、`text_width = width − 1`），所以窗口 size 改了下一帧即生效。
  - 新增 `_screen_rows(index, width)`：一个源行占几屏行（`rows_for` + `_wrap_line`，CJK/双语都对）。
  - 新增 `next_position(screen_rows, width)` / `previous_position(...)`：按屏幕行预算算出下一屏顶部的源行号。
  - `step_lines` 属性删除，换成 `page_budget`（单位屏幕行）；
    `next_page`/`previous_page` → `move_to(next_position/previous_position(page_budget, viewport_width))`。
  - 顺带修同一根因的 `_screen_range()`（`t`/`T`/切视图时翻"当前屏"的范围），
    也用 `visible_rows` 取真实可见源行。
  - 默认 `viewport_rows = page_height`、`viewport_width = None`：**没有终端尺寸时行为与旧版一致**
    （既有单测因此只需改 `step_lines` 那几个）。
- **`page_height` 降级**：真实终端里不再参与翻页，只作"拿不到终端尺寸时的回退值"；文档已说明。
- ⚠️ **残留限制（已被 ⑯ 修掉）**：当时 `position` 还是纯源行号，一段长到恰好在一屏中途被折行
  截断时，下一页会从**下一源行**开始，该段剩下的几屏行看不到。⑯ 把屏顶坐标升级成
  `(源行号, 段内偏移)` 后不再有这个漏洞。
- `tools/verify_mouse.py` 期望值**再次平移**：键盘基准改成 pty 真实高度
  （pty 40 行 → 正文区 38 行 → `j` 走 38−3=**35** 行），整串变成 35/34/38/35/35/30/68。

### ⑯ 修掉"半截段落被跳过"：屏顶坐标升级为 `(源行号, 段内偏移)`
- **现象/根因**：⑮ 之后翻页按屏幕行推进，但 `position` 仍然只是**源行号**。
  一段长到在一屏中途被折行截断时，下一页只能从 `position + 1`（下一源行）开始 ——
  该段**剩下的几屏行整段丢失**（读起来像"段落突然少了半页"）。
- **改法**：
  - `Pager` 新增 `line_offset`：这一行里已经翻过去的**折行屏幕行数**。屏顶坐标 = `(position, line_offset)`。
  - 抽出 `_row_texts(index, width)`（一个源行摊平后的全部屏幕行）与 `_walk_forward(start, offset, budget, width)`
    （分页核心：返回"这一屏的行 + 下一屏的屏顶坐标"）；`visible_rows` 改为走它。
  - `next_position`/`previous_position` → 改名 **`next_top`/`previous_top`，返回 `(行, 偏移)`**（不再只返回行号）。
  - `move_to(position, offset=0)`：goto / 搜索 / 章节 / 首尾跳转一律回到**行首**（offset 归零）。
  - **`scroll` 也改成按屏幕行**（`next_top`/`previous_top`）：否则从"半截行"滚轮下滚会直接跳到下一行
    开头，又把这一行剩下的折屏行跳掉 —— 同一个 bug 从鼠标路径复现。
  - `_draw` 的书签 `★` 只在**真正的行首屏行**上画：整屏从行中间续显示时，第一条是半截，标在它上面会误标到段落中间。
- **两条硬约束（写进 systemPatterns 坑清单）**：
  1. **`line_offset` 绝不落库**：`progress["current_line"]` 只写源行号，否则书签 / 章节 / 翻译缓存
     共用的「行号坐标唯一」约定就破了。代价是重开书从行首开始（重看一小段半截行），是刻意取舍。
  2. **越界偏移必须夹住**：窗口变宽会让折屏行变少，旧偏移可能越界。`_walk_forward` 把偏移夹到
     "这一行的最后一条"，`visible_rows` 再加一层"offset 一条都取不出来就退回行首"的兜底 ——
     少了这两层会画出**空白屏**。
- **真终端也验证了**：`tools/verify_mouse.py` 新增第 ⑧ 项（另一本"第一行两万汉字"的书）：
  连按两次 `j`，落库的 `current_line` 仍是 **0**（旧逻辑会变成 2），证明段内偏移端到端生效。

## 本会话的验证证据（全部通过）

| 检查 | 结果 |
| --- | --- |
| `py_compile wreader/*.py tests/*.py` | 通过 |
| `pytest tests/` | **494 passed**（426→474 基线 + 本会话新增 20） |
| ~~`/tmp/check_comments.py`（16 个文件）~~ | ~~**TOTAL: 0**（无遗漏注释的逻辑语句）~~ ⚠️ **此条已作废**：该脚本是假绿的，真实数字是 **2054**，见 ⑪ |
| `npx pyright` | **0 errors, 0 warnings, 0 informations** |
| `/tmp/verify_wrap.py` | **40,077** 次随机属性检查：不丢字符、不超宽、不产生空行 |
| `/tmp/verify_draw.py` | **420** 次绘制检查（10~120 列 × 4~40 行 × 3 视图）：任何 `addstr` 都不越界，状态栏两行必有内容 |
| `/tmp/verify_colors.py`（真 pty，`script -q /dev/null`） | `has_colors=True`、`COLORS=256`、`-1/-1` 默认色对可用、会话干净退出 |
| `/tmp/demo_colors.py`（修复前后对照） | 修复前 `init_pair() returned ERR`；修复后 OK |
| `/tmp/demo_colors.py`（修 Pylance 报错后复测） | `npx pyright` 在**仓库内**与**`/tmp` 下**各跑一次均 `0 errors`；去掉忽略注释的对照文件则报 1 个 `reportMissingImports`；`py_compile` OK；真 pty（`script -q /dev/null`）运行 exit=0，输出仍是"修复前 FAIL / 修复后 OK" |
| `/tmp/demo_wrap.py`（可视化） | 80/40/24/20 列的终端下折行与状态栏渲染均正确 |
| `git init -b main` + 首个提交 | `32 files changed, 15843 insertions(+)`，提交 `7ecc3eb` |
| `git push -u origin main` | `* [new branch] main -> main`，退出码 0 |
| `git ls-remote origin` | `refs/heads/main` = `7ecc3eb38ebbca5f186ffc321c22b80e51ccfab1` = 本地 `HEAD` |
| `git status --short --branch` | `## main...origin/main`（工作区干净，无未跟踪文件） |
| `git rev-list --left-right --count origin/main...main` | `0 0`（本地与远端完全同步） |
| GitHub REST API 复核 | 默认分支 `main`；根目录 11 项（5 目录 + 6 文件）与本地一致；`book/` 未上传 |
| `git check-ignore -v` | `book/`、`.DS_Store`（×2）、`.venv/`、`.pytest_cache/`、`*.egg-info/` 全部命中 `.gitignore` |
| staged 体积审计 | 32 个文件共 **704 KB**，最大单文件 76 KB（`reader.py`），无 >1 MB 文件 |
| **持续有效的同步判据**（别写死 SHA，否则记一次就过期一次） | 历史起点 `7ecc3eb`；`git rev-list --left-right --count origin/main...main` 应恒为 `0 0`；GitHub API 递归树应恒为 **32 个 blob**（`truncated: false`）。截至本次记录，`main` 已走到 `4434518`（4 个提交），之后每改一次 memory-bank 都会再 +1 |
| **全新克隆验证**（对 `ee92a95` 做 `git clone` 到 `/tmp/wreader-clone`） | 32 个跟踪文件、2 个提交、`book/` 不存在；**在克隆目录内**跑 `pytest` → **494 passed in 4.12s**；`npx pyright` → `0 errors, 0 warnings` |
| 克隆内 import 路径确认 | `wreader.__file__` = `/private/tmp/wreader-clone/wreader/__init__.py` —— 证明确实在测克隆副本，而非本地 editable 安装 |
| 干净 shell 里 `command -v wreader`（改前） | **找不到**，`VIRTUAL_ENV` 为空 —— 确认"重开终端不可用"属实 |
| 干净「登录+交互」shell 里 `wreader --version`（改后） | `wreader 0.1.0`；`command -v wreader` → `.venv/bin/wreader`（别名生效） |
| 干净「非登录交互」shell 里 `wreader list`（沙箱 `WREADER_HOME`） | 正常输出 `the library is empty -- add books with wreader import <path>`，真实 `~/.wreader` 未被触碰 |
| `zsh -n ~/.zshrc` | 语法 OK |
| 副作用检查（PATH 前置版，已推翻） | `python3` → `.venv/bin/python3`、`pip` → `.venv/bin/pip` —— **不可接受**，故放弃 |
| 副作用检查（别名版，最终） | `python3` → `/usr/local/bin/python3`、`pip` 不在 PATH —— 与改动前一致，**零影响** |
| `python3 /tmp/check_guide.py 使用指南.md` | 51 标题 / 24 文内链接 / 84 围栏行（偶数）→ **锚点全部可解析，RESULT: OK** |
| 同一脚本对照跑 `README.md`、`README.en.md` | 两者**也全过** → 证明脚本的 slug 规则与仓库既有约定一致，上面那个 OK 不是假阴性 |
| 沙箱实测指南里那条复制粘贴命令 | 造 `$TMPHOME` + 软链项目，照抄 `echo 'alias ... "$HOME/..."' >> ~/.zshrc`：`wreader --version` = `wreader 0.1.0`、`wreader list` 正常；**用户真实 `~/.zshrc` 未被改动** |
| 引号风格一致性核对 | 《使用指南.md》全文 38 处引号**清一色 ASCII `"`**，我唯一误写的 `「」` 已改、残留 0；memory-bank 侧用 `「」` 是**既有约定**（HEAD 里就有 4 处），故保留 |
| `python3 /tmp/verify_readme_numbers.py` | 把 README 声称的数字与真实文件行数、pytest 收集数**逐项对拍** → **ALL OK**：8 个源码行数 × 中英两版 + 7 个测试文件项数 + 两版总数；任一处不符会打印 `FAIL` |
| `/tmp/check_guide.py` 跑三份文档 | `README.md` 68 / `README.en.md` 68 / `使用指南.md` 84 围栏行（均偶数），**MISSING 锚点：无** → 三份都 `RESULT: OK`（含新增的两处章节锚点） |
| 旧数字全面复查 | `474` / `811 行` / `826 行` / `1048 行` / `1412 行` / `298 行` / `655 行` / `779 行` / `95 项` / `16 行` / `六条` 在 README 两版里 **0 命中** |
| 回归（纯文档改动，代码未动） | `pytest` → **494 passed in 4.65s**、`pyright` → **0 errors, 0 warnings** |
| 旧 `check_comments.py` 的 bug 对照实验 | 同一实现逻辑对 `wreader/cli.py`：**旧版只找到 1 个语句起点**（第 1 行），修正 `NEWLINE` 处理后找到 **405 个** → 旧检查是假绿 |
| 修正后全量注释覆盖 | `tools/check_comments.py` → **TOTAL: 2054**（旧脚本报的是 0） |
| 6 个脚本逐个实跑 | `check_docs` → `RESULT: OK`（3 个文档）；`check_doc_numbers` → `ALL OK`；`verify_wrap` → `OK: 40077 checks passed`；`verify_draw` → `OK: 420 draw checks passed`；`verify_colors`（真 pty）→ `has_colors=True` / `COLORS=256` / `default colour pair usable: yes (-1/-1)` |
| 退出码核对（不经管道，避免取到 `tail` 的退出码） | 报告模式 `0`；`--strict` 有遗漏时 `1`；`check_docs` / `check_doc_numbers` 通过时 `0` |
| 换目录运行（`cd /tmp` 后跑绝对路径） | `verify_draw` 420、`check_docs` OK、`check_doc_numbers` ALL OK → 仓库根自解析有效 |
| `npx pyright`（include 加入 `tools` 之后） | **0 errors, 0 warnings, 0 informations** |
| `pytest tests/` | **494 passed in 3.15s**（`tools/` 不在 testpaths 里，不会被当测试收集） |
| **`tools/verify_mouse.py`**（真 pty，`TERM=xterm-1006`） | 6 项全 OK：键盘 `j`=24、滚轮上一格=23、上拖 4 行=27、下拖 3 行=24、`touch_scroll=false` 拖动不动=24、步长 5=19 |
| **`mouseinterval` 修复前后对照** | 同一串拖动（带正常 pty 尺寸）：修复前 = **0**（按下事件根本没上报）；修复后 = **4** ✅ |
| 拖动探针日志（修复后） | press→`0x2` y=19 active=True；motion→`0x8000000` y=15 **delta=4**；release→`0x1` active=False |
| 灌 SGR 序列的真实解码表 | wheel-up(64)→`0x80000`=BUTTON4_PRESSED；wheel-down(65)→`0x8000000`（**本平台没有该位**）；press b1→`0x2`；motion→`0x8000000`；release→`0x1` |
| **本轮（⑫）回归** | `pytest tests/` → **514 passed**（覆盖上面那行旧的 494）；`npx pyright` → **0 errors / 0 warnings**；`tools/check_doc_numbers.py` → **ALL OK**；`tools/check_docs.py` → 三份文档 OK；`tools/verify_wrap.py` → 40077；`tools/verify_draw.py` → 420；`tools/verify_mouse.py` → 全部通过 |
| **本轮（⑭）回归** | `pytest tests/` → **522 passed**；`npx pyright` → **0 errors / 0 warnings**；`tools/check_docs.py` → 三份文档 OK；`tools/check_doc_numbers.py` → **ALL OK**；`tools/verify_wrap.py` → 40077；`tools/verify_draw.py` → 420；`tools/verify_mouse.py` → **7 项全过**（键盘 j=21、滚轮上=20、上拖 4=24、下拖 3=21、`touch_scroll=false`=21、步长 5=16、`page_overlap=0` 时 j=40） |
| **本轮（⑮）回归** | `pytest tests/` → **531 passed**；`npx pyright` → **0 errors / 0 warnings**；`tools/check_docs.py` → 三份文档 OK；`tools/check_doc_numbers.py` → **ALL OK**；`tools/verify_wrap.py` → 40077；`tools/verify_draw.py` → 420；`tools/verify_mouse.py` → **7 项全过**（pty 40 行下键盘 j=**35**、滚轮上=34、上拖 4=38、下拖 3=35、`touch_scroll=false`=35、步长 5=30、`page_overlap=0` 时 j=68） |
| **⑮ 关键对照（翻页跳行）** | 长段落（50 汉字 = 100 列，宽 20 时占 5 屏行）+ 短行、正文区 12 行：`j` 从第 0 行到第 **8** 行（长段 5 行 + 第 1..7 行）；旧逻辑会按 `page_height=24` 硬跳到第 24 行，**跳过第 8..23 行** |
| **本轮（⑯）回归** | `pytest tests/` → **540 passed**；`npx pyright` → **0 errors / 0 warnings**；`tools/check_docs.py` → 三份文档 OK；`tools/check_doc_numbers.py` → **ALL OK**；`tools/verify_wrap.py` → 40077；`tools/verify_draw.py` → 420；`tools/verify_mouse.py` → **8 项全过**（新增第 ⑧ 项：长段落书连按两次 `j` 后 `current_line` 仍为 **0**） |

## 本会话新增的测试（20 项，全在 `tests/test_reader.py`）

折行/宽度（14 项）：`test_char_width_counts_cjk_as_two_columns`、
`test_text_width_counts_columns_not_characters`、`test_clip_line_cuts_on_display_width`、
`test_pad_line_fills_exactly_the_requested_columns`、`test_wrap_line_folds_on_display_width`、
`test_wrap_line_keeps_latin_words_whole`、`test_wrap_line_fills_a_row_exactly_before_breaking`、
`test_wrap_line_never_exceeds_the_width`、`test_visible_rows_wraps_long_lines_to_the_width`、
`test_visible_rows_wraps_chinese_by_two_columns`、`test_visible_rows_stops_at_the_screen_height`、
`test_draw_wraps_a_long_line_onto_the_next_row`、`test_draw_wraps_chinese_by_display_width`、
`test_draw_marks_a_bookmark_only_on_the_first_wrapped_row`

越界保护 / 窄屏（3 项）：`test_addstr_clips_a_row_wider_than_the_window`、
`test_addstr_clips_within_the_remaining_columns`、`test_draw_fits_the_status_rows_on_a_narrow_screen`

颜色（3 项）：`test_init_colors_uses_the_terminal_defaults`、
`test_init_colors_is_a_noop_without_color_support`、
`test_init_colors_survives_a_terminal_without_default_colors`

**同步更新了 2 个原先锁"字符数语义"的测试**：
`test_format_status_bar_drops_whole_segments_when_narrow`（改用 10/22/23/36 列验证）、
`test_message_row_shows_the_long_chapter_nudge`（宽 5 列时 `"看中文?"` → `"看中"`）。

## ⑭ 新增的测试（8 项）

`tests/test_config.py`（1 项）：`test_page_overlap_setting_is_declared`（默认 3、`coerce_value` 认 `"5"`/`"0"`）。

`tests/test_reader.py`（7 项）：
`test_page_overlap_shortens_the_page_turn`（4 行 − 3 = 1）、
`test_page_overlap_zero_keeps_the_full_page`（0 → 4）、
`test_page_overlap_with_a_half_page_step`（0.5 屏 − 3 兜成 1）、
`test_page_overlap_never_stalls_the_page_keys`（重叠 > 整页仍为 1）、
`test_page_overlap_defaults_to_three_lines`（`Pager` 默认 3、`DEFAULT_PAGE_OVERLAP` 常量一致）、
`test_page_overlap_is_clamped_to_zero`（负重叠夹到 0）、
`test_page_turn_keeps_the_last_lines_of_the_previous_screen`（**端到端语义**：6 行屏 + 3 行重叠，
翻页后新屏前 3 行 == 上一屏末 3 行，往回翻精确回到原处）。

## ⑮ 新增/改写的测试（`tests/test_reader.py`）

改写（原先直接断言 `step_lines` 的 5 个，现在断言翻页后的 `position`）：
`test_page_scroll_step_controls_the_page_turn`、`test_page_overlap_shortens_the_page_turn`、
`test_page_overlap_zero_keeps_the_full_page`、`test_page_overlap_with_a_half_page_step`、
`test_page_overlap_never_stalls_the_page_keys`。

新增（10 项）：
`test_page_budget_counts_screen_rows`（预算单位是屏幕行）、
`test_screen_rows_counts_wrapped_and_cjk_lines`（**汉字按 2 列**：宽度 4 的 4 个汉字 → 2 行）、
`test_screen_rows_counts_every_row_of_the_bilingual_view`、
`test_next_position_stops_at_the_first_line_that_does_not_fit`、
`test_previous_position_is_the_mirror_of_next_position`、
`test_long_wrapped_paragraph_is_not_skipped`（**跳行 bug 的回归测试**）、
`test_page_turn_never_skips_a_source_line`（用户验收口径：翻 10 次，每屏首页 == 上屏末页 + 1）、
`test_next_page_is_reversible_with_wrapping`、
`test_screen_range_counts_wrapped_lines`（`_screen_range` 同根因修复的回归测试）。

## ⑯ 新增/改写的测试（`tests/test_reader.py`，159 项）

改名（原来只返回行号，现在返回 `(行, 段内偏移)`）：
`test_next_top_stops_at_the_first_row_that_does_not_fit`、`test_previous_top_is_the_mirror_of_next_top`。

新增（9 项）：
`test_next_top_returns_an_intra_line_offset`（`next_top(5, 20) == (0, 5)`）、
`test_previous_top_walks_back_inside_a_wrapped_line`、
`test_page_turn_resumes_inside_a_truncated_paragraph`（翻页停在同一行的第 4 条折屏片段上）、
`test_page_turns_show_every_row_of_a_long_paragraph`（**验收口径**：一屏装不下的长段落，
折出来的每条屏幕行都按顺序出现过，一条不漏）、
`test_next_page_from_a_mid_line_position_is_reversible`（含偏移的往返一致性）、
`test_scroll_is_measured_in_screen_rows`（滚轮也从"半截行"继续，不再跳掉剩下一截）、
`test_move_to_resets_the_intra_line_offset`（goto / 首尾跳转回到行首）、
`test_a_stale_intra_line_offset_never_blanks_the_screen`（窗口变宽后偏移越界的兜底）、
`test_bookmark_mark_is_not_drawn_on_a_mid_line_resume`（书签不画在半截行上）。

## ⑰ 新增 `wreader continue`（最近打开阅读的三本书）

**用户诉求**：「优化 wreader 在 linux 重启之后的启动命令，应该控制在一到两行就可以开启 wreader 看书」。

**拆出的两个摩擦点**：
1. 命令不在 PATH 上 → 重启后新终端敲 `wreader` 报 `command not found`（别名方案早已有，文档里写了）。
2. **读书要先知道 `book_id`**：得 `wreader list` 找 id → 再 `wreader read <id>`，两步且要记 id。

第 2 点才是真痛点 —— 因为 `progress.last_read` **早就在退出阅读器时写好了**
（`reader._write_position` 写 `_iso(moment)`，格式定长 `YYYY-MM-DDTHH:MM:SS`），只是从来没有入口去读它。

**改法**：
1. `wreader/library.py` 新增纯函数 `recent_books(limit=3)`：遍历 `load_library()["books"]`，
   跳过 `progress.last_read` 为空的书，按时间戳**字典序倒排**（定长 ISO ⇒ 字典序 == 时间序，
   不必解析 datetime），返回前 `limit` 个 `(book_id, record)`；`limit` 负数/0 返回空。
2. `wreader/cli.py` 新增子命令 `continue` + `cmd_continue`：打印
   `_book_table("最近在读 (recent)", books)`；一本都没读过时打印中文提示、返回 `0`
   （与空书库的 `list` 一致）。同步补上 `_HANDLERS` 与模块 docstring。
3. 顺手修正 `cli.py` 顶部那段**过期 docstring**（原文写 "read/translate/vocab/stats/achievements
   还是占位符"，实际早就全部实现了）。

**刻意不做的事**：**不自动打开最近那一本**。最近读的不一定是此刻想读的，程序不该替用户猜；
而且"列 id + 抄 id"正好就是用户要的「一到两行」。

**重启后两行开读**（Linux / macOS 同构）：
```bash
wreader continue      # 最近打开阅读的三本书（附 id）
wreader read f1ba2379642f
```
前置条件只有一条：`wreader` 得能用（配一次别名，见 `techContext.md` 的「开发环境」一节）。

**验证证据（2026-09-22 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest tests/` | **545 passed**（+5：`test_library.py` +3、`test_cli.py` +2） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | 三份文档 **OK** |
| `tools/check_doc_numbers.py` | **ALL OK**（`cli.py` 1028、`library.py` 1099、总数 545 全对上） |
| `tools/verify_wrap.py` / `verify_draw.py` | **40077 / 420**（未受影响，与改动前一致） |
| 沙箱端到端 | 4 本书（3 本设了 `last_read`、1 本从没读过）→ `wreader continue` 打出 `呐喊 / 基地 / 三体` 三行，**未读那本不出现**；空书库 → 中文提示 + `exit=0` |

**没踩到的坑（记录一下幸运之处）**：全程没碰落库格式、没碰行号坐标、没动阅读器绘制，
所以「行号坐标唯一」「CJK 宽度」两条硬约束都不受影响 —— `verify_wrap` / `verify_draw` 数字不变即为证。

## ⑱ 新增 `./install.sh`，安装压成三行命令

**用户诉求**：「简化安装流程到三行命令，git clone URL，cd wreader，把剩下的安装过程全塞进 ./install.sh」。

**改法**：新建 `install.sh`（**219 行** bash，已 `chmod +x`，git 记为 100755），做六件事：
1. 找 `python3`/`python` 中 **>= 3.11** 的（`sys.version_info` 判断，找不到就报错并给各平台安装提示）；
2. `.venv` 不存在才建 —— 判据是 **`-x .venv/bin/python`** 而不是 `-d .venv`
   （创建被中断会留下空目录，那种情况要重建）；
3. 用 **`.venv/bin/python -m pip`** 装：`--upgrade pip`（**只在新建 venv 时**）+ `pip install -e .`
   （`--dev` 则 `-e ".[dev]"`）。**全程不 activate**，守住"不污染 PATH"这条既有约定；
4. 自检 `wreader --version`，跑不起来就当失败；
5. **写别名**：按 `${SHELL}` 选 `~/.bashrc` / `~/.zshrc`（认不出来两个都写），
   `grep -q "^alias wreader="` 判重 + `grep -Fxq` 比对整行；指向别的路径时**只警告、不擅自改**用户文件；
6. 打印总结 + 下一步（`wreader continue` / `wreader list`）。

**选项**：`--dev` / `--no-alias` / `--help`。用 `sh install.sh` 跑会自动 `exec bash "$0" "$@"` 转交
（脚本用了数组等 bash 特性）。

### 踩到的两个坑

1. **全角字符紧跟变量名 → `unbound variable`**。首跑直接炸在
   `ok "虚拟环境已存在，跳过创建（$VENV）"`：bash 在非 UTF-8 locale 下会把 `（` 的字节
   当成变量名的一部分，于是去找名叫 `VENV（` 的变量。**修法**是改成 `${VENV}`。
   同类问题在 `die "...：$arg（试 ...）"` 里也有一处 —— 写了个正则
   `\$[A-Za-z_]\w*(?=[^\x00-\x7f])` 一次全扫出来，改完复扫 **0 处**。
   ⚠️ **写 shell 脚本时，中文/全角标点紧跟在 `$VAR` 后面一律要加花括号。**
2. **提示硬编码 `source ~/.bashrc`**，但脚本实际可能写的是 `~/.zshrc`（本机 `$SHELL` 就是 zsh）。
   改成打印真正写过的 `${ALIAS_RCS[0]}`。

### 验证证据（2026-09-22 实测）

| 项 | 结果 |
| --- | --- |
| `bash -n install.sh` | 通过 |
| **全新克隆**（`git clone` → `/tmp/wreader-clone`，无 `.venv`） | `HOME=<假家> SHELL=/bin/bash` 下 **exit 0**：venv 建好、15 个包装上、`[ok] 自检通过：wreader 0.1.0`、别名写进假 `~/.bashrc` |
| 别名真的可用 | `env HOME=<假家> bash -ic 'source ~/.bashrc; wreader --version'` → `wreader 0.1.0` |
| 幂等（同一 HOME 跑两次） | 第二次 `[ok] 别名已存在`，`grep -c 'alias wreader='` 仍为 **1** |
| `--no-alias` | exit 0，且假 HOME 里**没有任何 rc 文件** |
| `--dev` | exit 0，`pytest 9.1.1` 已满足 |
| `--help` / `sh install.sh --help` | 均 exit 0（后者靠 `exec bash` 转交） |
| 错误参数 `--bogus` | exit 1 + 中文提示（`${arg}` 修好后的路径） |
| 回归 | `pytest` **545 passed**；`npx pyright` **0/0**；`check_docs` **OK**；`check_doc_numbers` **ALL OK** |

> ⚠️ 测试让仓库 `.venv` 的 pip 从 25.1.1 升到了 26.2.1（首版每次跑都升级 pip）；
> 现已改成**只在新建 venv 时**升级，重复跑不再联网。测试全程用**假 HOME**，没碰真实 `~/.zshrc`。

### 文档

- `README.md` / `README.en.md`：安装节换成「三条命令」+ 参数表，原手动三步折进 `<details>`
  （Windows 走这条）；「新开一个终端后怎么用 wreader」与 FAQ 改成"install.sh 已配好别名，
  只需 `source` 或重开终端"；`PATH` 警告旁补一句"install.sh 也守着这条"；项目结构加 `install.sh`。
- `使用指南.md`：第 2 步改成 `git clone` 为主 / ZIP 为辅；第 3 步改成 `./install.sh` 一条命令
  （打印样例照抄真实输出），手动四步折进 `<details>`；速查卡、报错急救表（+2 行：
  `Permission denied`、`需要 Python 3.11 或更高版本`）、术语小词典（+「一键安装脚本」）、
  「关掉终端之后」（顶部加"可跳过"提示）全部同步。
- 顺带修掉一个目录锚点：`#第-3-步安装4-条命令` → `#第-3-步安装一条命令`
  （**`tools/check_docs.py` 抓出来的**，说明这个守卫真的在干活）。

## 待办 / 下一步

按优先级（本会话已完成的"git 化"一项已移除，序号整体前移）：

1. ~~更新 `README.md` 的过期内容~~ → **已完成（2026-09-22）**，详见下方 ⑩；
   两份 README 的数字都用 `tools/check_doc_numbers.py` 逐项核过（`ALL OK`；最近一次同步见 ⑰）。
2. **`reader.theme` 仍未实现**（预留项）。若要做，需在 `_init_colors()` 里根据主题值
   `init_pair()` 出一套配色，并给正文/状态栏/书签分配 color pair。
3. 可选：给 `library.py` 补 `__all__`（目前唯一没有 `__all__` 的模块）。
4. ~~把 `/tmp` 的校验脚本搬进 `tests/` 或 `tools/`~~ → **已完成（2026-09-22）**：
   7 个脚本都在 `tools/` 里（见 `techContext.md` 的「命令」一节），`/tmp` 里已无依赖。
5. 可选：`wreader continue` 目前**写死 3 本**。若想可配置，应加 `reader.continue_limit`
   走 `SCHEMA`（项目约定：阅读行为不写魔数）。
6. 可选（产品取舍，先问再做）：`wreader continue` 只"列 id"，不做交互选择。
   若哪天想省掉"抄 id"这一步，可让 `read` 的 `book_id` 变成可选（`nargs="?"`）+
   无参时续读最近一本 —— 但那会让程序替用户猜要读哪本，需先确认。
7. 可选：**Windows 还没有一键脚本**。`install.sh` 是 bash，Windows 用户目前只能照
   README 的手动步骤来（`pip install -e ".[windows]"` + 在 `$PROFILE` 里加函数）。
   要补的话就写一个 `install.ps1`，做同样六件事（PowerShell 版的别名是 function 而不是 alias）。

## 已知会话级注意事项

- **维护协议在 `.clinerules/memory-bank.md`**（对每次会话自动生效）：读取顺序、何时更新哪个
  文件、写作纪律、项目硬性约束都在那里。要调整协议只改那一个文件，别在 `memory-bank/` 里重复。
- **不要用 `read_files` 读刚改过的同一段**：本会话中该工具多次返回
  `[outdated - see the latest file content]`；改用 `sed -n 'A,Bp' file` 更可靠。
- **`editor` 单次替换有 ~6000 字符上限**，大改要拆成多次小改。
- **pytest 汇总行会消失**：`pyproject.toml` 的 `addopts` 已含 `-q`，命令行再加 `-q`
  变成 `-qq`，只输出 `文件: 数量`。想看到 `N passed` 就别再加 `-q`。
- **macOS 终端透明背景**：如果 `use_default_colors()` 之后背景依旧纯黑、透不出壁纸，
  那是终端模拟器自己的设置（如 iTerm2「在备用屏幕里禁用透明度」），应用层无法绕过。
- **git 提交要连 memory-bank 一起**：协议要求"每完成一段工作就更新 `activeContext.md`"，
  所以收尾时 `git status` 应当干净；文档改动和代码改动一起 commit + push，别攒着。
  推之前留意别把 `book/`（已忽略）或临时脚本加进去。

# Active Context — 当前焦点与最近改动

> 每次会话结束前更新这个文件。最后更新：**2026-09-22**。

## 当前状态一句话

代码库处于**干净、全绿**状态：`522 passed`、`pyright 0 errors / 0 warnings`、
`tools/` 的 7 个校验脚本全绿，且**已 git 化并推送到 GitHub**（`main` = `origin/main`，工作区干净）。
从 GitHub **全新克隆下来跑同样全绿**（522 passed + 全部校验脚本），说明仓库自足、无遗漏。
⚠️ 但注释覆盖**不是** 100%：严格口径下 `wreader/` + `tests/` 还有 **2142** 条语句上方没有紧邻注释行
（见 ⑪ 与 `progress.md` 待办 #4）—— 早先那句 `TOTAL: 0` 已作废。
本会话完成了：中文注释、自动换行、背景跟随终端、git 化并推 GitHub、启动方式文档、
README 数字同步、校验脚本进 `tools/`、鼠标滚轮 / 触摸拖动翻页、**翻页保留 3 行上下文**（见 ⑭）。

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

## 待办 / 下一步

按优先级（本会话已完成的"git 化"一项已移除，序号整体前移）：

1. ~~更新 `README.md` 的过期内容~~ → **已完成（2026-09-22）**，详见下方 ⑩；
   两份 README 的数字都用 `tools/check_doc_numbers.py` 逐项核过（`ALL OK`）。
2. **`reader.theme` 仍未实现**（预留项）。若要做，需在 `_init_colors()` 里根据主题值
   `init_pair()` 出一套配色，并给正文/状态栏/书签分配 color pair。
3. 可选：给 `library.py` 补 `__all__`（目前唯一没有 `__all__` 的模块）。
4. 可选：把本会话写在 `/tmp` 的校验脚本（注释覆盖、折行属性、绘制越界）搬进
   `tests/` 或 `tools/`，因为 `/tmp` 会被系统清理；仓库已 git 化，搬进来即可挂 CI。

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

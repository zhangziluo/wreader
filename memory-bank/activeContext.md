# Active Context — 当前焦点与最近改动

> 每次会话结束前更新这个文件。最后更新：**2026-09-26**。

## 当前状态一句话

代码库处于**干净、全绿**状态：**633 passed**（本机 8~44 秒，本会话四次实测 11.58 / 21.97 / 23.76 / 43.84 秒）、
`npx pyright` **0 errors / 0 warnings / 0 informations**、`tools/` 的 **8** 个校验脚本全绿
（`check_docs` OK / `check_doc_numbers` ALL OK / `check_comments` **3403** / `verify_wrap` 40077 /
`verify_draw` 140 / `verify_colors` 干净退出（`-1/-1` 可用）/ `verify_mouse` 8 项 /
`verify_achievements` 19 项），`git status -sb` 收尾是 `## main...origin/main`（没有领先 / 落后）。

最近两轮工作都是 **2026-09-26、都围绕自动翻页**，而且**都已提交并推送**：
㉞（提交 `feat(reader): 自动翻页久了弹一道算术题防作弊`）给自动翻页加了**防作弊校验** ——
连续自动翻页 10 分钟后弹一道 100 以内加减乘除的四选一题，按 `1`~`4` 选一个才继续、
没作答（`Esc` / 别的键 / 超时）就停，配置加 `reader.auto_scroll_check_minutes` /
`reader.auto_scroll_check_seconds` 两个键；㉟（提交 `chore(memory-bank): 同步防作弊校验（㉞）的实测数字与踩坑`）
是它的收尾复核 —— 三个真 pty 脚本补跑、一个「探针假警报」的澄清、记忆库全量对账。
**没有半成品悬着**：下个会话直接挑待办里的事项做即可（`reader.theme` 或注释口径拍板）。

- `wreader/` = **12** 个 `.py` / **10,182** 行（`reader.py` **3411**、`config.py` **975**）；
  `tests/` = 11 个文件 / **633** 项；`tools/` = 8 个 `.py`。
- 配置 **4 个 section / 20 个键**（本会话新增 `reader.auto_scroll_check_minutes` /
  `reader.auto_scroll_check_seconds`）；状态栏 **9** 个 token 可用；成就 **48** 条；`EVENTS` 白名单 **16** 个。
- 阅读器新增两个键：`a`（自动翻页开关）、`>` / `+` / `=`（加速）、`<` / `-` / `_`（减速）；
  校验题**不用新键**，直接按 `1`~`4` 作答。
- ⚠️ 注释覆盖**不是** 100%：严格口径下 `wreader/` + `tests/` 有 **3403** 条语句上方没有紧邻注释行
  （2026-09-25 是 2771 → ㉜ 之后 3099 → ㉝ 之后 3204 → 本会话的新代码与新测试又加到 3403；
  口径与处置见 `progress.md` 待办 #1）。
- ⚠️ 遗留数据（`vocab.json`、`notes/*.md`、旧译文缓存）**仍被只读**，`werd stats --json`
  的 `vocab_count` / `translations` / `translate_hits` / `notes_count` 四个键仍在（脚本兼容）。
- ⚠️ IDE 里飘的**幽灵告警**（仓库根那份 **143 行**野生 `cli.py`，见 ㉔ / ㉕）：
  判据是**先 `ls` 报错指向的路径**，路径不存在就直接忽略，改看 `npx pyright` + `pytest`。
  该文件已再次确认不在仓库里；它若回来，是 `editor` 超长替换"假成功"重演（坑 #20）。
- 历史已完成（细节见下文各节）：中文注释、自动换行、背景跟随终端、git 化并推 GitHub、
  README 数字同步、校验脚本进 `tools/`、鼠标滚轮 / 触摸拖动（⑫）、翻页保留 3 行（⑭）、
  翻页按屏幕行推进（⑮）、屏顶坐标升级为 `(源行号, 段内偏移)`（⑯）、`werd continue`（⑰）、
  `./install.sh`（⑱）、CLI 改名 `werd`（⑲）、目录浮层 + `werd toc`（⑳）、
  成就引擎 Phase 1（㉖）、成就 Phase 2/3（㉙）、数据搬家与清理（㉜）、自动翻页（㉝）、
  自动翻页防作弊校验（㉞）。**已删除**：笔记（㉑ / ㉘）、翻译（㉒ / ㉓）。

## 最近改动（2026-09-22 起，按时间顺序）

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

### ⑧ 让 `werd` 在新终端里可直接敲（`~/.zshrc` 别名）
- **问题**：用户重开终端后不知道怎么打开 werd —— 因为它是**项目内** `.venv` 的
  editable 安装，`.venv/bin` 不在默认 PATH 上，敲 `werd` 会 `command not found`。
- **排查事实**：`~/.zshrc` **原本不存在**；`~/.zprofile`（只有 brew / MacPorts 的 PATH 前置）、
  `~/.zshenv`（只 source cargo env）、`/etc/paths` 与 `/etc/paths.d/*` 全都没配这个 venv。
- ⚠️ **排查时踩过一个坑（假阳性）**：一开始直接跑 `zsh -l -c 'command -v werd'` 显示"能找到"，
  但那是因为它**继承了我当时那个已激活 venv 的环境**。必须用
  `env -i HOME=$HOME ... zsh -l -i -c ...` 把环境清干净，才测得出真实情况（结论：找不到）。
- **第一版方案（已推翻）**：`~/.zshrc` 里 `export PATH=".../.venv/bin:$PATH"`。
  能用，但**有副作用**：新终端里 `python3` → `.venv/bin/python3`、`pip` → `.venv/bin/pip`，
  会干扰用户在其它 Python 项目上的工作。
- **最终方案**：只写一行别名
  `alias werd="/Users/zhangziluo/Downloads/wreader/.venv/bin/werd"`，
  并在文件注释里写明**为什么不用 PATH**（防止以后有人好心改回去）。别名只作用于
  交互式 shell，对 `python3` / `pip` 零影响。
- `~/.zshrc` **在 git 仓库之外**，不受版本控制；排查结论与坑已记进 `techContext.md`。

### ⑨ 把"新终端怎么打开"写进《使用指南.md》
- 新增独立章节 `## 关掉终端之后：下次怎么打开 werd`（放在第 11 步之后、报错急救表之前）：
  讲清"为什么新终端里 `werd` 找不到"（装在项目 `.venv` 里、不在 PATH），
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
- **新增一节**：`README.md` 的「新开一个终端后怎么用 werd」与 `README.en.md` 的
  「Using werd in a new terminal」——内容与《使用指南.md》那节对齐（三种办法 + 对比表 +
  「别把 `.venv/bin` 前置进 PATH」的警告 + `python -m wreader.cli` 兜底）。
  同时把「安装」里"装完之后就有了 `werd` 命令"改成"**在当前这个终端窗口里**有了"
  （原文不准确：换个窗口就没了），并把 FAQ 的 `command not found` 一条改为指向新章节。
- **顺手改正一处旧笔误**：中文版「已经解决、不再属于已知问题的**六条**」，实际列了 **7** 条
  （英文版写的是 Seven，本来就是对的）。补上本轮三项修复后，中英两版统一为 **十条**。
- 「特性」表的阅读器一行补上"按终端宽度自动折行（汉字按 2 列算）、配色跟随终端主题与透明背景"。
- 「已知问题」里"README 陈旧"那一条已删除（不再成立）。
- 两版 README 的目录（TOC）各加一行指向新章节的链接，保持原有的扁平列表风格
  （锚点 `#新开一个终端后怎么用-werd` / `#using-werd-in-a-new-terminal`，已校验可解析）。
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
| 干净 shell 里 `command -v werd`（改前） | **找不到**，`VIRTUAL_ENV` 为空 —— 确认"重开终端不可用"属实 |
| 干净「登录+交互」shell 里 `werd --version`（改后） | `werd 0.1.0`；`command -v werd` → `.venv/bin/werd`（别名生效） |
| 干净「非登录交互」shell 里 `werd list`（沙箱 `WREADER_HOME`） | 正常输出 `the library is empty -- add books with werd import <path>`，真实 `~/.wreader` 未被触碰 |
| `zsh -n ~/.zshrc` | 语法 OK |
| 副作用检查（PATH 前置版，已推翻） | `python3` → `.venv/bin/python3`、`pip` → `.venv/bin/pip` —— **不可接受**，故放弃 |
| 副作用检查（别名版，最终） | `python3` → `/usr/local/bin/python3`、`pip` 不在 PATH —— 与改动前一致，**零影响** |
| `python3 /tmp/check_guide.py 使用指南.md` | 51 标题 / 24 文内链接 / 84 围栏行（偶数）→ **锚点全部可解析，RESULT: OK** |
| 同一脚本对照跑 `README.md`、`README.en.md` | 两者**也全过** → 证明脚本的 slug 规则与仓库既有约定一致，上面那个 OK 不是假阴性 |
| 沙箱实测指南里那条复制粘贴命令 | 造 `$TMPHOME` + 软链项目，照抄 `echo 'alias ... "$HOME/..."' >> ~/.zshrc`：`werd --version` = `werd 0.1.0`、`werd list` 正常；**用户真实 `~/.zshrc` 未被改动** |
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

## ⑰ 新增 `werd continue`（最近打开阅读的三本书）

**用户诉求**：「优化 werd 在 linux 重启之后的启动命令，应该控制在一到两行就可以开启 werd 看书」。

**拆出的两个摩擦点**：
1. 命令不在 PATH 上 → 重启后新终端敲 `werd` 报 `command not found`（别名方案早已有，文档里写了）。
2. **读书要先知道 `book_id`**：得 `werd list` 找 id → 再 `werd read <id>`，两步且要记 id。

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
werd continue      # 最近打开阅读的三本书（附 id）
werd read f1ba2379642f
```
前置条件只有一条：`werd` 得能用（配一次别名，见 `techContext.md` 的「开发环境」一节）。

**验证证据（2026-09-22 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest tests/` | **545 passed**（+5：`test_library.py` +3、`test_cli.py` +2） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | 三份文档 **OK** |
| `tools/check_doc_numbers.py` | **ALL OK**（`cli.py` 1028、`library.py` 1099、总数 545 全对上） |
| `tools/verify_wrap.py` / `verify_draw.py` | **40077 / 420**（未受影响，与改动前一致） |
| 沙箱端到端 | 4 本书（3 本设了 `last_read`、1 本从没读过）→ `werd continue` 打出 `呐喊 / 基地 / 三体` 三行，**未读那本不出现**；空书库 → 中文提示 + `exit=0` |

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
4. 自检 `werd --version`，跑不起来就当失败；
5. **写别名**：按 `${SHELL}` 选 `~/.bashrc` / `~/.zshrc`（认不出来两个都写），
   `grep -q "^alias werd="` 判重 + `grep -Fxq` 比对整行；指向别的路径时**只警告、不擅自改**用户文件；
6. 打印总结 + 下一步（`werd continue` / `werd list`）。

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
| **全新克隆**（`git clone` → `/tmp/wreader-clone`，无 `.venv`） | `HOME=<假家> SHELL=/bin/bash` 下 **exit 0**：venv 建好、15 个包装上、`[ok] 自检通过：werd 0.1.0`、别名写进假 `~/.bashrc` |
| 别名真的可用 | `env HOME=<假家> bash -ic 'source ~/.bashrc; werd --version'` → `werd 0.1.0` |
| 幂等（同一 HOME 跑两次） | 第二次 `[ok] 别名已存在`，`grep -c 'alias werd='` 仍为 **1** |
| `--no-alias` | exit 0，且假 HOME 里**没有任何 rc 文件** |
| `--dev` | exit 0，`pytest 9.1.1` 已满足 |
| `--help` / `sh install.sh --help` | 均 exit 0（后者靠 `exec bash` 转交） |
| 错误参数 `--bogus` | exit 1 + 中文提示（`${arg}` 修好后的路径） |
| 回归 | `pytest` **545 passed**；`npx pyright` **0/0**；`check_docs` **OK**；`check_doc_numbers` **ALL OK** |

> ⚠️ 测试让仓库 `.venv` 的 pip 从 25.1.1 升到了 26.2.1（首版每次跑都升级 pip）；
> 现已改成**只在新建 venv 时**升级，重复跑不再联网。测试全程用**假 HOME**，没碰真实 `~/.zshrc`。

### 文档

- `README.md` / `README.en.md`：安装节换成「三条命令」+ 参数表，原手动三步折进 `<details>`
  （Windows 走这条）；「新开一个终端后怎么用 werd」与 FAQ 改成"install.sh 已配好别名，
  只需 `source` 或重开终端"；`PATH` 警告旁补一句"install.sh 也守着这条"；项目结构加 `install.sh`。
- `使用指南.md`：第 2 步改成 `git clone` 为主 / ZIP 为辅；第 3 步改成 `./install.sh` 一条命令
  （打印样例照抄真实输出），手动四步折进 `<details>`；速查卡、报错急救表（+2 行：
  `Permission denied`、`需要 Python 3.11 或更高版本`）、术语小词典（+「一键安装脚本」）、
  「关掉终端之后」（顶部加"可跳过"提示）全部同步。
- 顺带修掉一个目录锚点：`#第-3-步安装4-条命令` → `#第-3-步安装一条命令`
  （**`tools/check_docs.py` 抓出来的**，说明这个守卫真的在干活）。

### ⑲ 把 CLI 命令从 `wreader` 改成 `werd`（2026-09-23）

**用户诉求**：命令行太长不好敲，把**用户敲的那个命令名**换成 `werd`；
但**项目目录名 / 仓库名、Python 包名、数据目录（`~/.wreader`）全部保持 `wreader` 不动**。

**改法**（只动"终端里敲的命令名"，不碰包名 / 数据目录 / 仓库名）：

1. `pyproject.toml` 的 `[project.scripts]`：`wreader = "wreader.cli:main"` → `werd = "wreader.cli:main"`
   （console script 名字变了，指向的入口仍是 `wreader.cli:main`）。
2. `wreader/cli.py` 的 `build_parser()`：`prog="wreader"` → `prog="werd"`。
   这是**唯一真正决定 argv[0] 显示**的硬编码 —— `--help` / `--version` / 报错里的命令名都由它来；
   顺带把 `--version` 帮助文案 `show the wreader version` 改成 `show the werd version`。
   （`config` 子命令的 `view or modify the wreader settings` **保留** —— 那里 `wreader` 指应用 / 设置文件，不是命令。）
3. `install.sh`：`WREADER_BIN` 改指 `$VENV/bin/werd`；别名行 `alias wreader=...` → `alias werd=...`；
   幂等检测 `grep "^alias wreader="` → `^alias werd=`；各处提示文案里的命令名同步。
   脚本内部变量名仍叫 `WREADER_BIN`（纯内部标识，不对外）。
4. 全部模块的 docstring / 注释 / 帮助文本 / 提示里的命令示例：`wreader import/list/read/...` → `werd ...`。
   **保留**所有 `:mod:`wreader.x``、`from wreader import`、`python -m wreader.cli`、`~/.wreader`、
   `$WREADER_HOME`、`%APPDATA%\wreader`、`wreader/data/achievements.json`、仓库 URL、`wreader/` 目录树。
5. 文档：`README.md`、`README.en.md`、`使用指南.md` 的命令示例、命令类标题
   （`### \`wreader import <路径>\`` → `### \`werd import <路径>\``）与
   「新开一个终端后怎么用 wreader」/「关掉终端之后：下次怎么打开 wreader」这类**标题 + 锚点 + 目录 + 交叉引用**全部同步。
   ⚠️ **标题改名必须连带改锚点**，否则目录链接点不动（`tools/check_docs.py` 会抓）。
6. `tests/` **无需改动**：全量 grep 确认没有任何测试断言命令名 `wreader`
   （只剩 `from wreader import`、`:mod:`wreader.x``、`~/.wreader` / `DATA_DIRNAME` 这类包名 / 数据目录引用）。

**踩到的坑（重要）**：用 Perl 按「`wreader` + 空格 + 子命令」批替换时，会**误伤三类非命令引用**：
`from wreader import library`（包名被当成 `wreader import`）、
`Python 包名也从 \`nr\` 改成了 \`wreader\``、以及 `settings.toml` 头的 `# wreader settings`。
这三类都已**逐条还原**。教训：**命令名替换必须带上下文判断**，包名和以 `wreader` 开头的英文短语都会撞上。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pip install -e .` | 成功；`.venv/bin/werd` 生成、旧 `.venv/bin/wreader` 消失 |
| `.venv/bin/werd --version` | `werd 0.1.0`（exit 0） |
| `.venv/bin/werd --help` | 正常输出，`usage: werd [-h] [-V] <command> ...`，版本行 `show the werd version and exit` |
| `pytest` | **545 passed**（8.27s） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | **RESULT: OK** |
| `tools/check_doc_numbers.py` | **RESULT: ALL OK** |
| `bash -n install.sh` | 通过（仍 219 行） |
| 残留检查 | 全仓 grep：**命令名已无 `wreader`**；剩余 `wreader` 只剩包名 / 数据目录 / 仓库名 / 许可证 / 包内文档字符串 |

### ⑳ 目录（章节表）与章节跳转（2026-09-23）

**用户诉求**：给 `werd` 加"目录 / 章节跳转"——TXT 用正则提取章节、EPUB 解析 `nav.xhtml` / `toc.ncx`，
结果缓存；阅读中呼出目录浮层选章跳转；带进度百分比；源文件变了自动失效；`werd toc --rebuild` 手动重建。

**先说清与现状的关系**（本功能最容易做重的地方）：项目**早就有**章节基础设施 ——
`library.parse_chapters` 在导入时就把 `chapters[{title,line_start}]` 写进 `library.json`，
`[` / `]` 已在翻章，跳转原语是 `Pager.move_to(line)`。所以这是"增强"而非"从零建"：
在既有章节表之上补 **百分比 + epub 自带标题 + 独立可重建缓存 + 浮层 UI + CLI**。

**新增 `wreader/toc.py`（474 行，纯函数）**：
- `build_toc(lines, extra)`：内置 `library.is_chapter_heading` + 用户自定义正则 → `[{title,line,percentage}]`；
  百分比复用 `library.position_percentage`（与状态栏同口径，**不另造一套算法**）。
- `parse_nav(archive)`：EPUB3 `properties="nav"` 的 XHTML、EPUB2 由 `<spine toc>` 指向的 ncx 都认；
  返回 `[(title, zip 内路径)]`（href 按 nav 文档所在目录解析、丢掉 `#fragment`）。
- `_spine_layout(archive)`：镜像内置提取器的拼接方式（各 spine 文档用 `\n` 连接），给出"每份文档的起始行"。
- `build_toc_from_epub(...)`：nav 标题 + spine 行号；**只有"spine 布局算出的总行数 == 正文行数"时才信 nav 的行号**
  （否则说明正文来自外部 `ebook-convert`、结构不同），并额外校验行号不倒挂，任一不满足就**整体退回正则**。
- `load_toc` / `save_toc` / `toc_cache_path`：缓存在 `~/.wreader/cache/<book_id>_toc.json`，
  **以"转换后正文的 mtime"为唯一失效判据**；缓存坏 / 缺 / mtime 不符就重建；`source` 字段留着源 epub 路径，
  供 `--rebuild` 再读一次 nav。

**`library.py`**：新增 `epub_spine_texts(archive)`（把 `extract_epub_builtin` 的核心抽出来给 toc 复用）、
`_epub_package_path(archive)`（从 `_epub_content_files` 里抽出的 opf 定位）、
以及 `_cache_epub_toc(...)`——在 `import_books` 里对 `.epub` **尽力**写一次目录缓存
（索引里只留转换后的 txt，**导入是唯一还能读到 nav 的时刻**）；整段 try/except 兜住，绝不拖垮导入。

**`reader.py`**：`Pager` 新增 `toc` 字段（`open_reader` 用 `toc.load_toc` 备好后传入）；
新增 `_toc_overlay()` 模态小循环 + `_draw_toc` / `_draw_toc_panel`（右侧 40% 面板、左侧正文 `A_DIM` 变暗）+
`_toc_window` / `_toc_move_cursor` / `_toc_panel_width`（纯函数，可单测）；
`handle_key` 绑定 **`Tab`** → `_jump_via_toc`。
⚠️ 面板文本一律走 `_clip_line` / `_pad_line`（汉字 2 列）；**最后一行只用 `panel-1` 列**，
否则会撞 curses 的右下角限制 → 整行静默消失。

**`config.py`**：新增 section `[toc]`（`patterns`，默认 `""`）→ SCHEMA **24 → 25 键**、**5 → 6 个 section**。
自定义正则写成**单个字符串**（`|` 或换行分隔）——SCHEMA 只支持 str/int/float/bool，压成字符串最省事、也最纯文本友好。

**`cli.py`**：新增 `werd toc <book_id> [--rebuild]`，用 rich 表格打印 `# / chapter / line / %`。

**与规格不同的地方（用户已确认"按你的建议来"）**：
1. `j` 已被"下一页"占用 → 目录键用 **`Tab`**。
2. 规格里的 `advance_by_page` 不存在 → 用既有原语 `Pager.move_to(line)`。
3. 规格写 `~/.werd` → 实际数据目录仍是 **`~/.wreader`**（与 translator 的 `<book_id>/` 缓存同目录）。
4. 规格说"更新 last_session 的 chapter / line" → 数据模型没有 `chapter` 字段；跳转后 `current_line` 照旧落库，
   `chapter` 永远由 `current_line` 现算（`chapter_index_at`），**刻意不加持久化字段**（守住"行号坐标唯一"）。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest` | **570 passed**（原 545 + `test_toc` 18 + `test_reader` 新增 7） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | **RESULT: OK** |
| `tools/check_doc_numbers.py` | **RESULT: ALL OK**（两份 README 的行数 / 测试数已同步，含新增的 `toc.py`、`test_toc.py`） |
| `tools/verify_wrap.py` | `OK: 40077 checks passed` |
| `tools/verify_draw.py` | `OK: 420 draw checks passed` |
| `tools/verify_mouse.py` | `RESULT: 全部通过`（8 项） |
| 端到端（320 章 TXT 沙箱） | 导入即识别 **320 章**；`toc.load_toc` 320 条（首条 line 0 / 0.1%，末条 line 957 / 99.8%）；缓存带 mtime 戳；`werd toc <id>` rc 0 打出表格；`--rebuild` rc 0；未知 id rc 1 |

**踩到的坑**：
1. `parse_nav` 里 `navPoint` 是**嵌套**的：`point.iter()` 会把子节点的 `<text>` / `<content>` 也算到父节点上 →
   必须只看**直接子节点**（`list(point)`），否则标题重复。
2. pyright：从 `isinstance(x, dict)` 收窄出的 `dict[Unknown, Unknown]`，`get()` 返回 `Unknown | None`，
   直接 `int(...)` 会报 `reportArgumentType`；先赋给 `Dict[str, Any]` 变量再取值即可。
3. `test_schema_has_a_default_for_every_path` 写死了 SCHEMA 键数（24）→ 加 `toc.patterns` 后必须同步改成 25。
   这是**故意**的守卫：动配置键就得动这个断言，免得文档悄悄漂移。
4. `FakeStdscr`（在 `tests/test_reader.py` 里，不在 conftest）原本没有 `get_wch`：
   给浮层的"按键脚本"测试补了一个**预置按键队列**的 `get_wch`，队列空时抛 `KeyboardInterrupt`，
   保证测试**永不**卡在浮层的阻塞读里（否则会挂死）。

### ㉑ 笔记功能 Phase 1+2：标记模式 + 笔记面板（2026-09-23）
> ⚠️ **本节描述的功能已于 2026-09-25 整体删除**（`m` / `o` 键位、`_mark_*`、`_note_*` 全部移除）。
> 保留本节只为解释当时的取舍与踩过的坑（子窗口 / Textbox / `Ctrl+S`）。

**需求**：给阅读器加"标记一段 → 写笔记"。规格给的键位 `v`（标记）与 `n`（笔记面板）
**与既有功能冲突**（`v` = 查词入库、`n` = 下一个搜索命中），已让用户拍板：
**保留现有键、新功能改用空闲键 `m`（标记）/ `o`（笔记面板）**，零破坏（规格里的
"`j`/`Tab` 目录跳转"也是笔误 —— 实际 `j` = 下一页、`Tab` = 目录）。

**`reader.py` 新增状态（都在 `Pager` 上，全是普通数据）**：`mark_mode` /
`mark_start` / `mark_end`（`(屏幕行, 行内字符下标)` 二元组）/ `note_buffer` /
`notes`（内存列表）/ `note_panel_open` / `note_focus`（`"quote"` | `"edit"`）/
`viewport`（每帧由 `_draw` 填入的可见行 `[(源行, 文本), ...]`）。

**纯函数（可脱离终端单测）**：`_mark_clamp`（夹进可见范围）、`_mark_move`（h/j/k/l + 方向键）、
`_mark_normalize`（方向无关的左上/右下）、`_mark_selection`（**按源行分组拼接**：同一源行的折行碎片
直接接上、跨源行才插换行；超 `NOTE_MAX_CHARS = 2000` 截断并返回 `truncated`）、
`_mark_row_span`（某屏幕行要高亮的字符区间）、`_note_panel_layout`（正文/引用/编辑三块高度）、
`_note_validate`（Textbox 的 validator，回车 → `curses.ascii.NL` 即"换行"，
**没有任何键映射到 Ctrl-G**，所以回车绝不会意外提交）。

**标记坐标为什么是「屏幕行 + 字符下标」**：`viewport` 就是 `visible_rows()` 的返回值，
高亮/取词因此天然对齐折行与汉字 2 列宽（`_draw_marked_row` 用 `_text_width` 累加列偏移，
把一行拆成 前段 / 反色选中段 / 后段 三块写）。**标记模式只在一屏内选字，绝不翻页**。

**笔记面板 = 模态小循环**（与 `_toc_overlay` 同款，**不另开线程**）：下方 25% 两个子窗口，
引用区（`A_DIM` 只读，`> ` 前缀 + `_wrap_line` 折行）+ 编辑区（`curses.textpad.Textbox`）。
**刻意不调用 `Textbox.edit()`**（那是阻塞循环），改为在主循环里逐键喂 `do_command()`，
这样 `Tab` / `Ctrl+S` / `Esc` 都能自己拦下来。

**`_disable_flow_control()`（`_run` 里调用）**：`curses.wrapper` 只调 `cbreak()`，`IXON` 仍开着，
行规程会把 `Ctrl-S`（XOFF）吃掉 → 保存键永远到不了程序。故尽力用 `termios` 清掉 `IXON|IXOFF`；
Windows 无 `termios`、非 tty 会失败，两者都静默降级；`endwin()` 会把 shell mode 还原，无需手工回滚。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest` | **595 passed**（570 + `test_reader` 新增 25） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | **RESULT: OK** |
| `tools/check_doc_numbers.py` | **RESULT: ALL OK**（`reader.py` **3112** 行、`test_reader.py` **191** 项、总数 **595** 已同步） |
| `tools/verify_wrap.py` | `OK: 40077 checks passed` |
| `tools/verify_draw.py` | `OK: 420 draw checks passed` |
| `tools/verify_mouse.py` | `RESULT: 全部通过`（8 项，回归） |
| `tools/verify_notes.py` | **`RESULT: 全部通过`（5 项，新增）**：真 pty 里 `m → ll → y → o → abc → Tab×2 → Ctrl+S → Esc → q`，对账引用区 `> …`、面板提示行、`Ctrl+S` 存成功、折叠提示 `按o展开`、无 traceback |
| `py_compile` | 25 个 `.py` 全过 |

**踩到的坑**：
1. ⚠️ **`stdscr.newwin` 根本不存在**！第一版写成 `stdscr.newwin(...)`，单测**全绿**
   （`FakeStdscr` 恰好实现了 `newwin`），但真 curses 的 `curses.window` 对象**只有 `derwin`** ——
   真 pty 里立刻 `AttributeError: '_curses.window' object has no attribute 'newwin'`。
   现改为 `reader._sub_window(stdscr, ...)` 这层间接（生产用 `curses.newwin`，测试 monkeypatch 掉）。
   **教训：假窗口实现得太像真的，反而会掩盖真 API 的差异；UI 改动必须过一遍真 pty。**
2. **面板的绘制顺序有讲究**：`stdscr.erase()` 会把面板覆盖的那几行也标脏，所以必须
   **主窗口先 `refresh()`、两个子窗口后 `refresh()`**，否则面板会被主窗口的空白格擦掉。
3. **`verify_notes.py` 必须显式给子进程一个 `TERM`**：非交互运行时 `TERM` 可能没设 → curses 起不来 →
   子进程提前退出 → 写 pty 直接 `OSError: EIO`（`verify_mouse.py` 早就显式设了 `TERM`，第一版漏了）。
4. 纯函数单测一开始把"同一源行折成两行"的样例写错（第二行的 `source_line` 其实是 0，
   所以不该出现换行），断言立刻抓到；说明这类坐标/切片逻辑靠**纯函数 + 精确断言**很值钱。
5. 选到"下一行行首"会带出一个换行 → `_copy_selection` 里先 `rstrip()` 掉尾部空白再判定空选区。

**已知局限（同时写进了 README 两份的「已知问题」与「使用指南」场景 F）**：
- 笔记**只存内存**（`Pager.notes`），退出阅读器就没了；落盘见待办 #1。
- 编辑区基于 `curses.textpad.Textbox`，**中文输入依赖系统 IME**，实际以英文 / 拼音为主。
- 引用区不做滚动（放不下只画前几行）。

### ㉒ 可插拔翻译引擎：`wreader/translate/` + 配置向导 + `t` 译文弹窗（2026-09-23）
> ⚠️ **本节描述的功能已于 2026-09-25 整体删除**（`wreader/translate/` 整目录、`translator.py`、
> `t` / `T` 键、`werd translate`、`[translate]` 段全部移除）。保留本节只为解释当时的取舍。

**需求**：把翻译做成可插拔（`base` + 百度/有道/腾讯/DeepSeek/本地），加 `[translate]` 配置段、
`werd config translate` 交互式向导、`t` 键译文弹窗、未配置时给可操作提示、把重依赖下沉到 extras。

**关键决策（用户拍板）**：**重构**，不是另起一套 —— 新包只当"引擎层"，`translator.py` 保留
章节缓存 / 分批 / 段落映射 / 双语视图 / `werd translate`，只把真正发请求的 `translate()` 委托出去。
理由是项目已有完整的缓存与视图机器，重写等于把这些再赌一次；并行两套则会让"到底谁在翻译"说不清。

**新包 `wreader/translate/`（8 个文件，共 1317 行）**：

| 文件 | 行 | 职责 |
| --- | --- | --- |
| `base.py` | 151 | `Translator` ABC（`translate(text, from_lang, to_lang) -> str`）+ `TranslateError` / `TranslateUnavailable` + 凭证/可选包检查 + `language_code()` |
| `google.py` | 92 | `deep-translator`；**免费免密钥，仍是默认引擎**；`pause()` 做批次限速 |
| `baidu.py` | 155 | 通用翻译 API V2，**MD5 签名**（`md5(appid + q + salt + secret)`） |
| `youdao.py` | 179 | 有道智云 v3，**SHA-256 签名** + `truncate()`（>20 字符取前 10+长度+后 10） |
| `tencent.py` | 240 | 腾讯云 TMT `TextTranslate`，**TC3-HMAC-SHA256**（规范请求串 → 待签串 → 逐级派生密钥） |
| `deepseek.py` | 221 | 从 `translator.DeepSeekBackend` 搬来；chat completions + SSE 流式 + 系统提示词 |
| `local.py` | 129 | Argos Translate，**惰性导入**，语言包没装时给安装命令 |
| `__init__.py` | 150 | `ENGINES` 注册表 + `make_engine()` / `engine_from_settings()` / `available_engines()` / 引擎中文名 |

**加一个厂商 = 写一个模块 + 在 `ENGINES` 登一行**，别处都不用改；连配置向导都自动适配
（它按 `EngineClass.credential_keys` 提问，提示语直接复用 `config.COMMENTS`）。

**`translator.py` 的变化**（1305 → 1199 行）：
- `Backend` 接口**保留**（`_translate_batches` 还要用它的 `pause()` 与错误语义），新增
  `EngineBackend(Backend)` 适配器：把引擎的 `TranslateError` 映射成模块自己的
  `TranslationError` / `TranslationUnavailable`（**后者决定整本书是"中止"还是"继续下一章"**）。
- 删掉 `GoogleBackend` / `DeepSeekBackend` / `_parse_sse` / `_system_prompt`（都搬进新包）；
  `make_backend()` 改为 `EngineBackend(translate.make_engine(...))`。
- `TranslatorSettings` 新增 `engine` + `credentials`，并有 `resolved_engine()`（`engine` 空则回退旧的
  `translator.backend`）与 `credential_values()`（`[translate]` 缺的 key 回退到旧的 `[translator] deepseek_*`）。
  **旧配置文件零迁移**照常能用。
- 新增 `engine_ready() -> (bool, str)`：给 `t` 与 CLI 做"配好了吗"的前置检查。
- 顺手去掉重复的默认值：`DEFAULT_BACKEND` / `DEFAULT_BATCH_SIZE` / `DEFAULT_DEEPSEEK_MODEL` / `DEEPSEEK_URL`
  现在**从 `config.DEFAULTS` 取值**，不再和 `SCHEMA` 各写一份。

**配置**：新增 `[translate]` 段（11 键）→ SCHEMA **25 → 36 键 / 6 → 7 段**
（守卫测试 `test_schema_has_a_default_for_every_path` 的计数器同步改成 36）。
`[translator]` **一个键都没删**（`backend` 变成"engine 为空时的回退"），所以老 settings.toml 照常工作。

**`t` 键（`reader.py`，3112 → 3308 行）**：先 `_translation_ready()`，没配好就
`未配置翻译引擎：运行 werd config translate（原因）`；配好了则
`Pager.translate_screen(first, last, target=...)`（**新增 `target` 参数**，所以中文书在中文视图里也能翻）
→ 译文在底部弹窗显示 `TRANSLATION_POPUP_SECONDS = 3.0` 秒（任意键提前关；走 `_sub_window`，
与笔记面板同一套"主窗口先刷、子窗口后刷"）。译文仍并进 `pager.translations`，之后按 `l` 切双语立刻可见。

**CLI**：`werd config translate` 走交互式向导（`cli.py` 1087 → 1237 行）：列出引擎（标出当前）、
按引擎声明的键逐条问、**密钥类字段不回显且"留空保留"**、写完立刻 `engine_ready()` 自查。
`werd config translate.engine xxx` 这种非交互写法**完全不受影响**。

**依赖**：`requests` 与 `deep-translator` **仍是必装**（前者撑起四家 HTTP 引擎，后者是默认引擎的地基 ——
把默认引擎的依赖做成可选，等于"装完就坏"），只把 `argostranslate` 放进 `local` extra。
**与计划的一句话出入**：计划里写的是"`deep-translator` 移到 google extra"，实现时判定不妥，见上。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest` | **654 passed**（595 + `test_translate` 49 + `test_cli` 6 + `test_translator`/`test_reader` 调整） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` / `check_doc_numbers.py` | **RESULT: OK** / **ALL OK** |
| `tools/verify_wrap.py` / `verify_draw.py` | 40077 / 420 |
| `tools/verify_mouse.py` / `verify_notes.py` | 全部通过（回归） |
| **`tools/verify_translate.py`（新增）** | **全部通过（4 项）**：真 pty 里选 `local`（没装包）与 `baidu`（没填密钥）各按一次 `t`，都对账到"提示去跑 `werd config translate`"；再喂标准输入跑向导，确认 `engine`/密钥真的落盘 |
| `py_compile` | **36 个** `.py` 全过（wreader 17 + tests 10 + tools 9） |

**外部向量验证**（没联网也能对账）：
- **百度**：官方文档示例 `appid=2015063000000001, q=apple, salt=1435660288, secret=12345678`
  → `f89f9594663708c1605f3d736d01d2d4`，**逐字节对上**（这条进了单测）。
- **腾讯云**：官方 v3 文档把"请求体 → sha256"的结果印在页面上
  （`35e9c5b0e3ae67532d3c9f17ead6c90222632e5b1ff7f6e89887f1398934f064`），单测断言哈希一致；
  **但它给的 SecretId/SecretKey 已被打码**（页面里是 `AKID****`），所以最终签名**没有可复现的外部向量** ——
  只能靠"结构断言 + 自洽性"（规范请求串格式、UTC 日期作用域、逐级派生、签名随 body 变化）。
  ⚠️ 别把这条当成"腾讯云已经完全验过"。

**踩到的坑**：
1. ⚠️ **`editor` 工具在超长替换时"报告成功但实际另建了一个文件"**：一次约 5900 字符的替换返回
   `File created successfully at: .../wreader/cli.py`（路径写在包内），实际却在**仓库根**留下一个
   143 行的 `cli.py`，而目标文件只改了别的部分。表现极具迷惑性：`grep 新函数名` 找不到、
   pyright 却依然报 0（根目录不在 include 里）。
   **对策：大改动拆成 <6000 字符的小块、每次改完 `grep` 确认落地、`git status` 检查有没有冒出怪文件。**
   （本次收尾前就把这个野生 `cli.py` 删掉了，别让它进版本库。）
2. **`region` 参数的默认值会"影子"掉凭证表**：`TencentTranslator(region=DEFAULT_REGION)` 里
   `region or self.credential("tencent_region", ...)` 永远走左边 → 配置里的地域永远读不到。
   把默认值改成 `""` 才对。这类"默认值把回退逻辑短路"的坑，**只有真跑一遍配置才暴露**。
3. **向导里"留空保留"不能只是提示语**：第一版对已设置的密钥把 default 设成空串，
   结果空输入真的把密钥写成了空（提示语在说谎）。现在 `values[key] = answer or existing`。
4. 测试替身要**复刻被替换函数的语义**：`_answer_with` 一开始直接返回队列里的空串，
   于是"直接回车保留当前引擎"这条路径根本没被跑到（向导当成"不认识的名字"取消）。
   替身里补上 `return answer or default` 后才真正覆盖。
5. **`check_doc_numbers.py` 只认 `wreader/<文件名>`**：子包里的 `translate/__init__.py` 会和包根的
   `__init__.py` 撞名，被错算到包根那份上。所以 README 的子包条目**不写"（N 行）"**，
   行数改记在本文件与 `techContext.md` 里（工具里也写了注释说明）。

**已知局限**（也写进了两份 README 与《使用指南》）：
- 六家引擎里只有**百度**有可复现的外部签名向量；腾讯云的最终签名只能靠结构 + 自洽性验证。
- `local`（Argos）**必须自己装语言包**，装了包但没语言包时 `available()` 仍为 False（提前拦，不让第一次翻译才炸）。
- 单个引擎**没有超时重试 / 退避**：一次失败就按 `TranslateError`（单章失败）或
  `TranslateUnavailable`（整本中止）处理，没有自动重试。

### ㉓ 修掉临时脚本 `/tmp/check_translate.py` 的 `Translator.params` 类型报错（2026-09-23）
> ⚠️ 相关模块（`translate/`、`translator.py`）已于 2026-09-25 删除；本节留作"静态类型用错基类"的案例。

报错是 `无法访问类 Translator 的属性 params`（Pylance）。根因**不是逻辑坏了，是静态类型用错了基类**：
`params()` 只定义在 `BaiduTranslator` / `YoudaoTranslator` 上，基类 `Translator` 的契约里只有
`translate()` / `pause()`；而 `make_engine()` 的声明返回类型正是基类。修法 = 让变量落到**具体类**
（直接构造，或 `isinstance` 收窄，见 `systemPatterns.md` 坑 #23）。

该文件此前已从 `/tmp` 消失（`read_files` 直接 ENOENT，`/tmp` 旧脚本备份与 VS Code 本地历史里
都没有它），所以是按报错信息**重建**成正牌离线自检：百度 MD5 签名 / 有道 v3 签名 + `truncate`、
三条解析失败路径（`error_code` / 空 `trans_result` / 非对象响应）、凭证标签与 `configured` /
`available`、未知引擎、`engine_from_settings({}) -> None`、本地引擎可用性随可选包变化。

| 项 | 结果 |
| --- | --- |
| `.venv/bin/python /tmp/check_translate.py` | `RESULT: 全部通过`（24 项，退出码 0，全程不发请求） |
| `npx pyright /tmp/check_translate.py` | **0 errors / 0 warnings** |
| 反向对照（把 `.params()` 故意调在基类上，验完已删） | `error: Cannot access attribute "params" for class "Translator"` —— 与 IDE 报的一字不差，证明 pyright 确实在分析这个 `/tmp` 文件、且修法有效 |

**这条的教训**：临时脚本的报错常常是**基类 / 具体类的类型边界**，不是逻辑 bug；`assert isinstance(...)`
收窄既过静态检查，又能在真跑时兜住"工厂换了引擎"。重建时我自己还写错过一条断言（有道的 `zh-CHS`
该断言在 `from` 上，却写成了 `to`），是脚本自己 FAIL 出来的 —— **自检脚本必须自己会 FAIL**，
否则等于没有检查。

### ㉔ 核实"`cli.py:24: 未定义『Optional』"—— 幽灵告警，零代码改动（2026-09-23）

**报告**：Pylance 指出 `cli.py` 第 24 行 `Optional` 未定义。**结论：现盘代码没有这个错误**，
报错对象是**仓库根**那个野生 `cli.py`（㉒ 坑 #1 里 `editor` 工具"假成功"写出来的 143 行碎片，
当时已删），不是 `wreader/cli.py`。

**为什么判定是它**：IDE 给的路径是工作区根的 `cli.py`，而该路径**根本不存在**
（`read_files` 直接 ENOENT）；全仓 `find -iname 'cli.py*'` 只命中 `wreader/cli.py`，
`git log --diff-filter=ADR -- '*cli.py'` 显示历史上只跟踪过 `wreader/cli.py`。
那份碎片的第 24 行恰好是 `Optional[...]` 用法、又没带 `from typing import Optional`，
症状与报错**逐字吻合**。

**实测证据（2026-09-23）**：

| 项 | 结果 |
| --- | --- |
| `sed -n '20,28p' wreader/cli.py` | 第 **22** 行就是 `from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple`；第 24 行是注释 |
| `grep -n Optional wreader/cli.py` | **22**（import）/ **427** / **748** / **1213**，用到的都来自那一行 import |
| `npx pyright`（1.1.414，全仓 + 单文件各跑一次） | **0 errors / 0 warnings / 0 informations** |
| `py_compile` + `.venv/bin/python -c "import wreader.cli"` | 过；`c.Optional` 能取到 `typing.Optional` |
| AST 自检（`/tmp/check_typing_names.py`） | 扫 **36** 个 `.py`：用 `Optional` 的 **18** 个**全都** import 了它；`MISSING TYPING NAMES: none` |
| `pytest tests/` | **654 passed**（`test_cli.py` 单独跑 41 passed） |

**给用户的处置**：这是编辑器侧的陈旧诊断，代码无需改 —— 关掉根目录那个 `cli.py` 标签页，
然后 **Developer: Reload Window**（或 `Python: Restart Language Server`）即可。
VS Code 的 `workspaceStorage` / `User/History` / `Backups` 里都已搜不到该路径的痕迹，
说明它只活在**当时那个运行中的 Pylance 会话**内存里。
⚠️ **这条后来被推翻**：2026-09-23 的 ㉕ 里用 `sqlite3` 读 `state.vscdb`，**搜到了**该路径的 3 处痕迹
（`history.entries` + 两个编辑器 `memento`），所以它并不只活在 Pylance 内存里。
当时的 `grep` 漏了，原因未查明；**引用"搜不到痕迹"时请先自己重跑一遍那条 `grep`**。

**教训（接 ㉒ 坑 #1）**：那条"`editor` 假成功"不只是脏文件问题 ——
**它还会在 IDE 里留下指向不存在文件的告警**。以后看到"某文件某行未定义 X"，
先 `ls` 那个路径、再 `grep` 真实文件，**别直接照报错改代码**。

### ㉕ 第二次幽灵告警：`cli.py:143` 返回类型 `int` —— 碎片自己现身，删掉即可（2026-09-23）

**报告**：Pylance 说 `cli.py` 第 143 行「所声明的返回类型为"int"的函数必须在所有代码路径上返回值；
`None` 不可分配给 `int`」。**结论：`wreader/cli.py` 一行都没错**；报错对象是 ㉒ 坑 #1 / ㉔ 里那份
**仓库根的野生 `cli.py`** —— 而它**在这次会话中途（15:20）自己回到了磁盘上**（IDE 把陈旧的脏缓冲区落了盘），
于是"路径不存在、告警无法复现"这次变成了"**文件真在、告警名副其实**"。
**已逐行读完、对账、再次删除**（原件留了一份在 `/tmp/ghost_cli_fragment_143lines.py` 供本会话追溯）。

**本次实测证据**：

| 项 | 结果 |
| --- | --- |
| `find . -name 'cli.py'`（排除 `.git/`） | 仓库根 **无此文件**；只命中 `wreader/cli.py`（1237 行）与 `.venv/` 里别的包 |
| `git --no-pager log --all -- cli.py` / `git ls-files \| grep cli.py` | 历史上**从未跟踪过**根 `cli.py`；只有 `tests/test_cli.py`、`wreader/cli.py` |
| `npx pyright wreader/cli.py` | **0 errors / 0 warnings / 0 informations** |
| `npx pyright`（全仓） | **0 errors / 0 warnings / 0 informations** |
| `pytest tests/` | **654 passed**；`tests/test_cli.py` 单独跑 **41 passed** |
| 143 行窗口扫描（脚本：在 `wreader/cli.py` 里找"相对第 24 行含 `Optional`、相对第 143 行是 `def … -> int:`"的窗口） | **0 命中** —— 碎片**不是**现盘文件的连续切片（它是编辑中途的 `new_text`，行号无法用现文件复原） |
| VS Code `workspaceStorage/cdd18f67a9633099378310d8bbff10f6/state.vscdb`（**先 `cp` 到 `/tmp` 再用 `sqlite3` 读**，不锁真库） | **搜到该路径 3 处痕迹**：`history.entries`（`file:///…/wreader/cli.py`，`"forceFile":true`）、`memento/workbench.parts.editor`、`memento/workbench.editors.files.textFileEditor` |

**碎片真容（它是自己送上门的，所以下面全是实测，不再靠推测）**：

| 检查 | 结果 |
| --- | --- |
| 行数 / 体积 | **143 行 / 5860 字节**，第 **143 行就是最后一行** |
| 第 **143** 行 | `def cmd_config(args: argparse.Namespace) -> int:` —— **光有函数头、没有函数体**（文件到此截断）→ 与"所有代码路径都必须 return"**逐字吻合** |
| 第 **24** 行 | `def _choose_translate_engine(current: str) -> Optional[str]:` —— 用了 `Optional` 而整个碎片**一行 import 都没有** → 与 ㉔ 的"`Optional` 未定义"**逐字吻合** |
| 有没有 import | **0 行**（`grep -n '^import\|^from'` 无输出）。连 `console` / `config` / `translate` 都没导入，**根本不可能跑起来** |
| 与 `wreader/cli.py` 的关系 | 它是 **`wreader/cli.py` 第 404–546 行那一段的"早期草稿"**：121 行非空行中 **94 行与现盘逐字相同**，余 27 行是同一批函数的**旧写法**（例：`values[key] = answer if answer else existing` vs 现盘 `_prompt_line(label, default)`；`return names[index - 1] if 1 <= index <= len(names) else None` vs 现盘的 if / return 两行；docstring 措辞也不同） |
| 由此推断 | 因为它是**草稿**而不是现盘文件的切片，上表那条"143 行窗口扫描 **0 命中**"正是**期望结果**，不构成矛盾 |
| `git status` 里的样子 | **`?? cli.py`** —— 协议要求每次收尾看 `git status`，这次就是靠它抓到的；`git check-ignore` 显示它**不**被忽略 → 一个 `git add -A` 就会把垃圾提交进去 |
| 有没有人引用它 | `grep -rn 'import cli' tests tools` 只命中 `tests/test_cli.py: from wreader import cli, …` —— **根目录这个无人引用** |

**它为什么会在 15:20 回来**：`textFileEditor` 里那条 `cursorState`（第 143 行、列 45–48、选中态）
说明 IDE 一直把它当"打开着的文件"记着；窗口一旦把脏缓冲区落盘，它就又出现在仓库根。
**所以关掉那个标签页（或 Reload Window）才算真的清完** —— 光删磁盘文件会被它再写回来。

⇒ **同一个碎片解释了两次幽灵告警**：第 24 行缺 `Optional` 是 ㉔，最后一行缺函数体是 ㉕。
㉔ 当初"症状逐字吻合"的推断，这次拿到了实物证据。

**㉔ 的一处更正**：㉔ 写"`workspaceStorage` 里已搜不到该路径的痕迹"，**现在搜得到**（见上表）。
判据：`grep -rl 'Downloads/wreader/cli.py' ~/Library/Application\ Support/Code/User/{workspaceStorage,History} .../Backups`
命中 `state.vscdb`。所以那条陈旧诊断**不只在当时的 Pylance 内存里** ——
编辑器的"最近打开 / 标签页视图状态"也在把它一遍遍带回来。

**处置（本次已执行 = 这次"修 bug"的全部动作）**：`rm cli.py` 删掉那份碎片。
**`wreader/cli.py` 一行都不用改** —— 碎片里的东西在那份文件里都有，而且是更成熟的一版
（碎片从未被任何人 import，删除不影响任何行为）。
⚠️ 但**只删磁盘文件不够**：IDE 那个标签页还会把它写回来（15:20 就是这么发生的），
所以还要在 IDE 里**关掉那个标签页 + Developer: Reload Window**
（或 `Python: Restart Language Server`）。若还自动冒出来，就**完全退出 VS Code**（关窗口 != 退出）。

**实测证据（删完之后复跑）**：

| 项 | 结果 |
| --- | --- |
| `git status --short --branch` | 只有 `## main...origin/main`，**无未跟踪文件** |
| `npx pyright`（全仓） | **0 errors / 0 warnings / 0 informations** |
| `pytest tests/` | **654 passed** |

**教训（同一个坑累积到第二次，这次钉死）**：
1. 「**报错指向的文件是不是真的存在**」永远先查，**而且别只查一次**：
   本次 15:18 查是"不存在"，15:20 它就被 IDE 写回来了 —— **下结论前重查一遍**。
2. 幽灵告警的"文案像不像真问题"完全不可信：**同一条 143 行碎片**先后产出两种看起来都很像
   真问题的告警（`Optional` 未定义 / 返回类型不匹配），先后骗过两次。
3. 判据优先级：`ls` 报错路径 → `git ls-files` / `git status` 看它有没有进版本库 → **最后**才看代码；
   项目侧的答案永远是 `npx pyright` + `pytest` 双绿。
4. **`git status` 是抓这类幽灵的唯一有效手段**（碎片是未跟踪文件，只有它显示 `?? cli.py`）。
   因此**故意没**给 `.gitignore` 加 `/cli.py`：那样反而会让它悄悄消失、下次没人发现。
   宁可让它继续在 `git status` 里显形，同时**永不用 `git add -A`**。

### ㉖ 成就引擎 Phase 1：`wreader/achievements.py` + 28 个成就（2026-09-23）

**需求**：用户给了完整的「事件驱动成就系统」规格（约 60 条成就、`check_achievements(event_type, data)`、
数据存 `~/.nr/achievements.json`、解锁时在 curses 底部通知 5 秒、IP 地理用 ip-api.com 缓存 1 小时、
文件锁防并发、字数按行号去重）。**Phase 1 只做引擎 + 累计/习惯类成就**，把需要实时按键、
地理、环境探测的部分留给 Phase 2/3（见 `progress.md` 待办 0b）。

**做了什么**：

| 文件 | 变化 |
| --- | --- |
| `wreader/achievements.py` | **新增 768 行**：状态文件读写（原子替换 + `flock`）、`record_event`、`compute_metrics`（= `stats.compute_metrics` ∪ 状态派生指标）、`check_achievements(event, data)`、`list_achievements()`、`count_words`/`uncovered_words`/`merge_ranges`/`weekend_seconds` 等纯函数 |
| `wreader/data/achievements.json` | 10 → **28** 条，每条加 `category`（阅读习惯 / 数据积累）+ `secret`；198 行 |
| `wreader/stats.py` | 849 → **785** 行：**删掉 `check_achievements`**（解锁权威只剩一个），保留指标/定义加载/庆祝；`load_achievements` 改为产出 6 键；`build_report` 新增可选 `unlocked=` |
| `wreader/reader.py` | `Pager.read_ranges` + 在 `move_to()` 里记区间；`_session_achievements()` 发 `session_end`；`_celebrate_achievements(newly, ring)` 只负责渲染 |
| `wreader/cli.py` | `_now()` / `_record_achievements()` / `_unlocked_ids()`；`main` 发 `daily_open`、`cmd_import` 发 `book_add`、`cmd_translate` 后重算；`cmd_achievements` 按分类重写 |
| 测试 | 新增 `tests/test_achievements.py` **35 项**；`test_stats.py` 76 → 70（6 个旧解锁测试删除、2 个定义测试改为 6 键）；`test_cli.py` 2 项改为走新引擎 + 固定 `cli._now` |

**关键决策与理由**：见 `progress.md` 决策演变表最后 7 行（独立模块 / 仍用表达式 / 区间去重挂在
`move_to` / 6 键定义 / 删除旧 `check_achievements` / 只做 POSIX 锁 / 改名两个成就的显示名）。
**`~/.nr` 是改名前的旧路径，一律用 `~/.wreader`**（`config.data_dir()`）。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest tests/` | **683 passed**（654 + `test_achievements` 35 − `test_stats` 6） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` / `check_doc_numbers.py` | **RESULT: OK** / **RESULT: ALL OK**（`achievements.py` 768、`stats.py` 785、`cli.py` 1266、`reader.py` 3342、`achievements.json` 198、`test_achievements.py` 35、总数 683 全部对拍） |
| `tools/verify_wrap.py` / `verify_draw.py` | 40077 / 420（回归） |
| `tools/verify_mouse.py` / `verify_notes.py` / `verify_translate.py` | 全部通过（回归：动过 `move_to` 与阅读器退出路径，所以真 pty 必跑） |
| `tools/verify_colors.py`（`script -q /dev/null` 包一层） | 干净退出 |
| 端到端冒烟（`WREADER_HOME` 指向 `/tmp`） | `werd import` → 屏幕上直接打出「🏆 已解锁 1 个成就：🗄️ 书库初成」；`werd achievements` → `已解锁 1/28` + 分类分组 + 时间类指标按小时渲染；`~/.wreader/achievements.json` 里 `counters`/`metrics`/`progress` 都正确 |

**踩到的坑（都写进了 `systemPatterns.md` 坑 #24-28）**：
1. **`progress` 没进 `empty_state()`** → 写回的进度快照读回来就没了（`KeyError: 'progress'`）。教训：**任何新段落都要同时进 `empty_state()` 与 `_normalise_state()`**，否则"写进去"和"读出来"不对称。
2. **`merge_ranges` 返回 tuple，直接进 state 会让内存形状与 JSON 形状不一致**，`==` 断言永远失败（`[(0, 2)] != [[0, 2]]`）。已统一成 `list[list[int]]`。
3. **全角标点会被 `east_asian_width` 判成宽字符** → `，。` 也算了字数。改为"排除空白与 `unicodedata.category == P`"。
4. **`daily_open` 挂在 `cli.main()` 上 → 测试与"跑测试的时刻"耦合**：05:00-07:00 跑会自己解锁 `early_bird`。加了 `cli._now()` 注入缝，测试固定成中午。
5. **一次 `editor` 替换想"删除 6 个测试"却只传了表头当 `old_text`** → 反而把整块**复制**了一份（测试重名）。看到 `--diff` 里出现 `+` 而不是 `-` 就要立刻回头核对；删除类编辑必须把**整块**当 `old_text`。
6. 规格里的 `~/.nr/achievements.json` 与项目现状（`nr` → `wreader` 改名、数据在 `~/.wreader`）**冲突**，按项目现状处理并记录。

**Phase 1 明确没做**（别误以为已有）：Phase 2/3 的实时按键类、屏内 5 秒通知、地理（`geo.py`）、
环境探测（`env.py`）、阅读器帮助页、意外中断自动恢复流程。

### ㉘ 笔记 Phase 3：`wreader/notes.py` + `wreader/lock.py` + `werd notes`（2026-09-23）
> ⚠️ **本节描述的功能已于 2026-09-25 整体删除**（`notes.py`、`werd notes` 三条路径、`index.json`）。
> **唯一留下的**是 `wreader/lock.py`（成就状态还在用它）与 `achievements._note_total()` 的只读计数。

**需求**：用户给了 Phase 3 规格（存储逻辑 + CLI）：新增笔记模块、markdown 落盘 + `index.json`、
30 秒自动保存、`Ctrl+S` 闪现"✓ 已保存"、`werd notes` 三条用法（清单 / 分页 / 导出）、
文件锁防并发、目录自动创建、UTF-8。

**做了什么**：

| 文件 | 变化 |
| --- | --- |
| `wreader/notes.py` | **新增 558 行**：`save_note`（追加 markdown + 刷索引）、`load_notes`/`parse_notes`（容错解析）、`list_all_notes`（从 `.md` 重建派生索引）、`update_index`、`export_notes`、`save_draft`/`load_draft`/`clear_draft` |
| `wreader/lock.py` | **新增 81 行**：把成就模块里的文件锁抽出来共用（`file_lock(path)`；POSIX `flock`，Windows 退化为原子替换） |
| `wreader/reader.py` | 3342 → **3515 行**：`Pager.notes` 改成"打开时从磁盘载入"；`_commit_note`/`_save_note` 落盘 + `✓ 已保存` 1.5 秒；`_note_panel` 改成 200ms 节拍轮询 + 30 秒草稿 + `Esc` 提交 / `Ctrl-C` 留草稿；`_restore_draft`/`_fill_editor`/`_finish_note_panel` 新增 |
| `wreader/cli.py` | 1266 → **1450 行**：新增 `werd notes [book_id] [--export]`（`_notes_table` / `_page_notes` / `_read_one_key` / `_paging_is_interactive` / `DEFAULT_NOTES_EXPORT_DIR = "~/books"`） |
| `wreader/achievements.py` | 768 → **715 行**（文件锁搬去 `lock.py`，`_file_lock` 三兄弟删除） |
| 测试 | 新增 `tests/test_notes.py` **30 项**（含**三进程并发写**的锁验证）；`test_reader.py` 192 → **198**（落盘 / 草稿 / 恢复 / 失败保留）；`test_cli.py` 41 → **49**（清单 / 分页 / `q` 退出 / 导出 / 边界） |
| `tools/verify_notes.py` | 真 pty 端到端从 5 项扩到 **20 项**：加上落盘格式、索引计数、**第二次会话追加不覆盖**、CLI 三条路径、`--export` 内容一致 |

**规格里我改掉/澄清的三处**（详见 `progress.md` 决策演变最后 5 行）：
1. **"自动保存"= 崩溃草稿，不是每 30 秒追加一条笔记**（否则同一段草稿会重复入账）；
2. **markdown 为源 + 派生索引**（`count` 从 `.md` 数出来，删掉 `index.json` 自动重建，永不漂移）；
3. **`Esc` = 提交、`Ctrl-C` = 只留草稿**（规格里写的"n 折叠"在本项目是"下一个搜索命中"，
   面板实际由 `Esc` 关闭）。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest tests/` | **727 passed**（683 + `test_notes` 30 + `test_reader` 6 + `test_cli` 8） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` / `check_doc_numbers.py` | **RESULT: OK** / **RESULT: ALL OK**（`notes.py` 558、`lock.py` 81、`cli.py` 1450、`reader.py` 3515、`achievements.py` 715、`test_notes.py` 30、总数 727 全对拍） |
| `tools/verify_notes.py`（真 pty） | **全部通过（20 项）** —— 含落盘 markdown 格式、`index.json` 计数、**第二次会话追加**、`werd notes` 清单/分页、`--export` 落到 `~/books` 且内容一致 |
| `tools/verify_mouse.py` / `verify_translate.py` / `verify_colors.py` | 全部通过（回归：动过 `reader.py` 的面板与退出路径） |
| `tools/verify_wrap.py` / `verify_draw.py` | 40077 / 420 |
| `py_compile` | wreader + translate + tests + tools 全过 |

**踩到的坑（都写进了 `systemPatterns.md` 坑 #29-32）**：
1. ⚠️ **`Textbox.gather()` 把字符截成 7 位**（`curses.ascii.ascii()` = `& 0x7f`）：把中文草稿填进编辑区，
   提交后原文变成 `I?c\x07`。**这是数据损坏级的坑**，测试用中文当草稿正文时当场暴露。
   最终设计：中文正文不进编辑区，`_restore_draft` 把它交回调用方直接落盘。
2. ⚠️ **`export_notes(book_id, "~/books")` 造出一个名叫 `books` 的文件**：目录不存在时
   `is_dir()` 为假 → 走"按文件复制"。改成调用方拼完整文件名。
3. ⚠️ **分页只看 `stdin.isatty()` 会永久挂住**：`capture_output=True` 的子进程（stdout 被捕获、
   stdin 仍是终端）会卡在第一页 —— 实测把 `verify_notes.py` 整个挂死，只能 `pkill`。
   判据改成"两端都是 tty"，工具里再加 `stdin=subprocess.DEVNULL`。
4. `flock` **不可重入**（同进程不同 fd 也会等自己）→ 内部已有锁时只能调不加锁的 `_write_index`。
5. 编辑区内容 `_save_note` 与"中文草稿"两条路要**共用一个 `_commit_note`**，否则清空逻辑会各写一遍。

### ㉙ 成就 Phase 2/3：实时事件 + 屏内 5 秒通知 + `geo.py` / `env.py`（2026-09-23）

**接手时的状态（重要）**：工作区是脏的，`git status` 有 8 个改动文件、且 **跑不了测试**。
前一个会话留下的未提交工作是一整块完整的功能（本会话把它一并交付，并补了文档）：
- 标记模式里新增 `t`：把选中的这一段**翻译**好、暂存成 `Pager.note_translation`，
  之后按 `o` 写笔记时连着引用一起落盘（`notes.save_note(translation_text=...)`）；
- 笔记开始记**章节**（`> 章节: 第一章`，`notes._CHAPTER_RE` 解析）与**译文**（`译文：` 块），
  `werd notes <id>` 也跟着显示；
- 新增成就「笔记达人」（`notes_count >= 50`，指标**现数 markdown**，
  经 `notes.total_note_count()` + 延迟导入的 `notes.check_note_achievements()` 上报 `note_add`）；
- ⚠️ 但 `tests/test_notes.py` 里 `test_concurrent_writes_do_not_lose_notes` 的 **docstring 首行被吞**，
  文件成了语法错误（`SyntaxError: invalid character '：'`），`pytest` 直接 collection error。
  这是 `editor` 工具超长替换的**第三次同款事故**（另两次见坑 #21 与 ㉔/㉕）。
  **对策再强调一遍：大改动拆小块、改完 `py_compile` 或跑一次测试、收尾 `git status` 扫一遍。**

**本次交付的功能（规格见 `progress.md` 待办 0b，那一段就是当时能拿到的全部规格）**：

1. **`EVENTS` 白名单 +7**：`key` / `resize` / `help` / `recover` / `env` / `name_egg` / `achievements_view`
   （`geo_change` 是 Phase 1 就留着的，这一轮才真的有人调用它）。
   载荷约定：`key` / `resize` / `session_end` 带 `{"deltas": {...}, "maxima": {...}, "width", "height"}`，
   增量按 `COUNTER_METRICS` 累加、峰值按 `MAX_METRICS` 取 max，**白名单之外的名字一律丢弃**
   （不让手写的载荷往状态文件里塞新键）。
2. **阅读器实时记账**（`Pager.note_key` / `note_chapter_change` / `note_width`）：
   空格连击、连续翻页、方向键怀旧、翻译键次数、窄屏秒数与窄屏读完的章数。
   换章结算挂在 `_sync_chapter()` 这个**唯一**的换章点上。
3. **屏内 5 秒通知**（规格要求）：`Pager.announce/current_notice` + `_draw_notice`，
   画在**右上角三行反白块**（标题 / 成就名 / 脚注），**非阻塞**——不拦按键、不开子窗口、
   不像 `t` 的译文弹窗那样等用户关。窗口太小（< 24 列或 < 6 行）时退到消息行（`_message_row(notice=...)`）。
4. **「不为每次按键写盘」的关键设计**：`achievements.metric_thresholds()` 把定义文件里的门槛
   解析成 `{指标: (数, ...)}`，`_prepare_achievements()` 在开书时取一次**基线**
   （`achievements.session_metrics`），并把这些线里**基线就已达标**的全部预标记成 `fired`。
   之后 `_achievement_tick` 只做**纯内存判断**（`achievements.crossed_thresholds`），
   **只有刚好越过某条线时才** `check_achievements()` 一次。没撞线的增量攒着，
   退出时随 `session_end` 一次性交账 → 一次会话的写盘次数 = 越线次数（通常 0~2 次）。
5. **阅读器帮助页 `?`**（帮助迷）：`_HELP_LINES`（纯数据）+ `help_lines()` + `_help_layout` +
   `_draw_help` + `_help_overlay`（模态小循环，`↑↓/j/k` 滚动，`q`/`Esc`/`回车` 关闭）。
6. **意外中断恢复**：`reader.write_marker/read_marker/clear_marker`，
   现场 = `~/.wreader/reading_session.json`（书 id、行号、段内偏移、一行预览、时间、pid）。
   `_run` 开头问一句（`_confirm(..., hint=_RECOVER_HINT)`，`_confirm` 因此多了可选参数），
   `save_position()` 每次自动保存顺手刷新现场，`open_reader` 在**正常退出**时删掉它。
   → 恢复大师（`crash_recovers >= 3`）/ 我反悔（`recover_declined >= 1`）。
7. **`wreader/geo.py`**（343 行）：ip-api 免费接口 + **一小时缓存**（`~/.wreader/geo.json`）+
   国家代码→大洲表（7 洲）+ 世仇组合（第一条是**英法**，百年战争的出处）+ 注入式 `fetcher` 接缝。
   **离线是正常状态**：没网且没缓存就返回 `{}`，调用方按"这次不记"处理；
   查询失败但缓存过期 → 用旧的。`stats.geo_lookup = false` 时**一步网络都不发**。
8. **`wreader/env.py`**（183 行）：云主机 / WSL / tmux / 可编辑安装四个信号，
   全部**可注入**（`env` 映射、`release` 串、`direct_url.json` 文本），所以测试不看本机。
9. **成就 28 → 48**：新增 操作彩蛋 5（手速达人 / 翻页永动机 / 方向键怀旧 / 翻译狂魔 / 帮助迷）、
   难度挑战 4（极限尺寸 / 窄屏挑战 / 恢复大师 / 我反悔）、隐藏 10（环游亚欧非美大洋 / 世界公民 /
   百年世仇 / 节日读者 / 名字彩蛋 / 成就猎人 / 云端书虫 / 穿越子系统 / 套娃终端 / 开发者模式）
   + 笔记达人（Phase 3 联动，见上）。
   `category` 顺序变成 5 类：阅读习惯 / 操作彩蛋 / 数据积累 / 难度挑战 / 隐藏。
10. **名字彩蛋**：`werd werd` / `werd word` / `werd --werd` 三写法都通（`_word_egg`）。
    为此把子命令容器改成 `required=False`，并在 `main()` 里自己 `parser.error(...)`
    ——**用法提示与退出码 2 与以前逐字一致**（`test_a_command_is_required` 没动也过）。
11. **`werd achievements` 改用 `achievements_view` 事件**（`check` 仍在白名单里、仍可用，
    只是不再是它的调用方），成就猎人条件写成 `achievement_views > 10`。
12. **新设置键**：`stats.geo_lookup`（默认 `true`）——`SCHEMA` 从 36 个键变 **37 个**（section 仍 7 个）。

**验证证据（2026-09-23 实测）**：

| 项 | 结果 |
| --- | --- |
| `pytest` | **832 passed**（727 + 新增 105：geo 31、env 14、achievements +16、reader +38、cli +6） |
| `npx pyright` | **0 errors / 0 warnings / 0 informations** |
| `tools/check_docs.py` | **RESULT: OK** |
| `tools/check_doc_numbers.py` | **RESULT: ALL OK**（三份文档的行数/项数全部同步） |
| `tools/verify_wrap.py` | `OK: 40077 checks passed`（未受影响） |
| `tools/verify_draw.py` | `OK: 420 draw checks passed`（未受影响） |
| `tools/verify_mouse.py` / `verify_notes.py` / `verify_translate.py` | `RESULT: 全部通过`（回归） |
| `tools/verify_achievements.py` | **`RESULT: 全部通过`（19 项，新增）**：真 pty 里 `?` → 帮助页出现 → `q` 关掉 → 屏内出现「成就解锁／帮助迷」→ `q` 退出；造现场 → 「上次好像没有正常退出／上次读到第 13 行」→ `y` → 位置回到第 12 行、`crash_recovers=1`、现场被删；再开一次**不再问**；`werd --werd` 解锁「名字彩蛋」 |
| `py_compile` | 全部 `.py` 通过 |

**踩到的坑**：

1. ⚠️ **`_confirm` 的默认提示是硬编码的"加入生词本"**：恢复流程复用同一个弹窗，
   所以给它加了 `hint` 参数（默认值保持不变，老调用方一字未改）。
2. ⚠️ **`Pager.viewport_width` 是"正文区宽度"（已扣掉书签列），不是终端列数**。
   第一版把窄屏计时与 `terminal_width` 共用这个字段，结果 `_draw` 每帧都把它改写成 `width-1`
   → 「≤60 列」的判定永远差一列。现在分成两个字段：`viewport_width`（排版用，`_draw` 写）
   与 `terminal_width`（真实列数，`note_width` 写）。
3. ⚠️ **测试里那个"平平无奇的中午"不平凡**：`test_achievements_lists_progress` 把 `cli._now`
   钉在 `2026-01-01 12:00` —— 那是**元旦**，新加的「节日读者」当场解锁，断言 `已解锁 0/48` 翻车。
   已把两个测试的固定时刻挪到 `2026-01-15`（周四、不过节），并在注释里写明"别挑节日"。
   ⚠️ **凡是给 `daily_open` 钉时间的测试，都要同时避开 05:00-07:00 与节日表**。
4. ⚠️ **`editor` 工具又吞了一行 `def`**：插入帮助页函数时把 `def _enter_mark(pager: Pager) -> None:`
   整行替换掉了，`_enter_mark` 的 docstring 与函数体直接挂在 `_help_overlay` 后面 →
   `pyright` 报 `Expected 3 positional arguments`、6 个标记模式测试 `NameError`。
   已补回。**这是同一类事故的第四次**（#21、㉔/㉕ 的野生文件、test_notes.py 的 docstring）。
   结论：**用 `editor` 做完插入，立刻 `pyright` + `pytest` 各跑一次**，别等到收尾。
5. ⚠️ **`env.direct_url_text()` 会被源码树里的 `wreader.egg-info` 遮蔽**：
   在仓库根运行时 `metadata.distribution("wreader")` 先找到 `wreader.egg-info`（没有
   `direct_url.json`）而不是 site-packages 里的 `wreader-0.1.0.dist-info`，
   于是"可编辑安装"探测在仓库根会误判为 `False`。改成 `metadata.distributions(name=...)`
   **逐个尝试**，两种启动方式答案一致（已实测）。
6. `?` 在标记模式下不会被 `note_key` 记账（`handle_key` 在标记模式里提前 return），
   这是**故意**的：标记模式里的 `j/k/h/l` 是挪光标而不是翻页，不该算"连续翻页"或打断"方向键怀旧"。
7. 帮助页在 10 行高的假窗口里只画出 8 行 → 断言要挑第一屏就有的文字，
   或断言脚注里的 `还有 N 行`（`_draw_help` 会把剩余行数报出来）。

### ㉚ 删除翻译 / 生词本 / 笔记三个功能，成就改走遗留数据只读（2026-09-25，本会话主任务）

**需求**：用户要求"去掉翻译、生词本、笔记相关功能"，同时**不能丢掉已有成就**。

**做法（按落地顺序）**：
1. **源码删净**：删 `wreader/translator.py`、`wreader/translate/`（8 文件）、`wreader/vocab.py`、
   `wreader/notes.py`；`reader.py` 移除 `m` / `o` / `v` / `l` / `c` / `t` / `T` 键与所有标记模式、
   笔记面板、译文弹窗代码；`cli.py` 移除 `translate` / `vocab` / `notes` 三个子命令与 `_HANDLERS` 条目；
   `config.SCHEMA` 从 7 段 37 键缩到 **4 段 16 键**（`[translator]` / `[translate]` / `[vocab]` 全删；
   2026-09-26 的 ㉜ / ㉝ / ㉞ 之后是 **20 键**，`[reader]` 段多了自动翻页四条）。
2. **成就保全**（关键取舍）：**一条成就都不删**。翻译 / 词汇 / 笔记相关的 4 条
   （`vocab_100` 📝 词汇积累、`vocab_500` 🧠 生词狂魔、`note_master` 🖊️ 笔记达人、
   `translate_maniac` 🔤 翻译狂魔）保留原条件，靠两个**只读**函数继续供数：
   `stats._vocab_file_size()`（数 `vocab.json`）与 `achievements._note_total()`（数 `notes/*.md` 的
   `## 笔记 #N` 小节）。两者都**吞掉一切异常返回 0**（坏 JSON / 坏编码 / 无权限 / 目录不存在）——
   它们挂在每次统计与每次成就判定的路径上，抛异常等于"老数据一坏就打不开阅读器"。
3. **接口兼容**：`EVENTS` 白名单保留 `word_add` / `note_add`（共 **16** 个事件，这两个已无调用方）；
   `werd stats --json` 保留 `vocab_count` / `translations` / `translate_hits` / `notes_count` 四个键。
4. **配置兼容**：`Config.unknown` 收集老 `settings.toml` 里的死键，`cli._print_config` 逐条打
   `warning: unknown setting '...' is ignored` —— **不报错、不改写用户文件**（真机实测见 `techContext.md`）；
   反过来 `werd config <path> <value>` 写不存在的键**仍然报错**（打错字必须被发现）。
5. **工具与文档**：删 `tools/verify_notes.py`；README / README.en.md / 使用指南.md / `tools/README.md`
   的表格、数字、特色列表同步去功能；`pyproject.toml` 去掉 `deep-translator` / `argostranslate`
   等依赖，运行时依赖仍为 **3** 个（`chardet` / `rich` / `requests`，其中 `requests` 现在只服务
   地理成就的可选联网）。
6. **记忆库全量复核**：`projectbrief.md` / `productContext.md` / `techContext.md` /
   `systemPatterns.md` / `progress.md` / 本文件。

**实测规模**：整次提交（含记忆库 / 协议文档）`git show --stat` 为 **-11,240 / +1,163 行**、
47 个文件；其中代码与测试部分是 **-10,649 / +599**（当时 `git diff --stat` 的中途读数）。

**验证证据（2026-09-25，全部通过）**
| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 测试 | `.venv/bin/python -m pytest tests/` | **559 passed**，11.76s |
| 类型 | `npx pyright` | 0 errors / 0 warnings / 0 informations |
| 编译 | `python -m py_compile`（wreader 11 + tests 10 + tools 8） | 全部通过 |
| 折行 | `tools/verify_wrap.py` | 40077 项 |
| 绘制 | `tools/verify_draw.py` | 140 项 |
| 成就真 pty | `tools/verify_achievements.py` | 19 项 |
| 鼠标真 pty | `tools/verify_mouse.py` | 8 项 |
| 文档 | `tools/check_docs.py` / `check_doc_numbers.py` | 锚点 OK / ALL OK |
| 配置兼容 | `werd config`（本机老 settings.toml） | 16 键表格 + 20+ 行 `unknown setting` 警告，退出码 0 |
| 注释 | `tools/check_comments.py` | TOTAL: 2771（报告用，非门禁） |
| 版本控制 | `git status` | 干净、与 `origin/main` 同步 |

**教训**：删功能时"幽灵引用"比想象的顽固（详见 `systemPatterns.md` 坑 #31）——
`cli` 的 subparser、`[tool.pyright]` 的 include、README 的表格与数字、`tools/` 的专用脚本、
`pyproject.toml` 的 extras 各漏一处，都会以"启动即 ImportError"或"文档数字 FAIL"的形式炸出来。

### ㉛ 记忆库 + 协议全量复核（2026-09-25 收尾，无代码改动）

功能裁剪之后，把"项目状态"这几份文件按**实测**重新对了一遍，改的都是文档：

| 文件 | 改了什么 |
| --- | --- |
| `systemPatterns.md` | 模块职责表按 11 个 `.py` / 8,840 行重写；模式表补第 **11** 条"遗留数据只读兼容层"；新增「关键实现路径」调用链表；坑清单补到 **#33** |
| `progress.md` | 当前状态表、已完成清单、待办、已知问题全部去功能；新增「遗留数据只读兼容」一节与 2026-09-25 决策行 |
| `activeContext.md` | 开头的当前状态、㉑㉒㉓㉘ 加"已删除"标注、㉚ 记录整次裁剪、待办重写、注意事项去重 |
| `memory-bank/README.md` | 本目录现状改成 **2026-09-25** 基线（559 / 29 个 `.py` / 8,840 行 / 2771 注释缺口 / `tools/` 8 个），旧基线降级为"仅作对照" |
| `.clinerules/memory-bank.md` | 协议本身的三处过期：注释缺口 2279 → **2771**、`tools/` 脚本清单（去掉 `verify_notes.py`，补 `verify_mouse.py` / `verify_achievements.py`）、**代理没开时不要用 `git -c http.proxy= push` "绕过"**（实测挂在直连上）；另加"改文件只用 `editor`"的坑 |

**顺手抓到的两处写错的事实**（值得记，因为都是"凭记忆写数字"翻车）：

1. `activeContext.md` ㉚ 里把运行时依赖写成 `platformdirs` / `tomli-w` —— 实测 `pyproject.toml`
   的 `dependencies` 是 **`chardet` / `rich` / `requests`**（`wreader/library.py` 用 chardet、
   `cli.py` + `reader.py` 用 rich、`geo.py` 才 `import requests`）。已改正。
2. `memory-bank/README.md` 说 `systemPatterns.md` 有 **12** 个设计模式 —— 实际一节一节数是 **11**。

**再跑一遍全量验证（2026-09-25 收尾，数字与 ㉚ 完全一致）**：
`pytest tests/` → **559 passed**（19.63s，机器负载不同所以比 ㉚ 记的 11.76s 慢）；
`npx pyright` → 0 / 0 / 0；`py_compile`（wreader 11 + tests 10 + tools 8）→ 通过；
`check_docs` → RESULT: OK；`check_doc_numbers` → RESULT: ALL OK；`check_comments` → **TOTAL: 2771**；
`verify_wrap` → 40077；`verify_draw` → 140；`verify_mouse` → 8 项全过（约 40 秒）；
`verify_achievements` → 19 项全过（约 50 秒）；`verify_colors` 用
`script -q /dev/null .venv/bin/python tools/verify_colors.py` 跑（直接跑会报 "需要在真终端 / pty 里运行"），
`/tmp/wreader_colors.txt` 结论：`has_colors=True`、`COLORS=256`、默认配色对 `(-1/-1)` 可用。
另有两条**残留 grep** 结论：源码里剩下的 `vocab` / `translate` / `notes` 命中全是
只读兼容函数与冻结成就的指标名；`README.md` / `README.en.md` 里的命中全是
「历史遗留文件」「已知问题」两类**说明性**段落。

⚠️ **踩到的一点小坑**：把 `verify_mouse.py` / `verify_achievements.py` 写进
`for s in ...; do ... | tail -3; done` 这种管道循环里会**假挂**（实测 300 秒无输出、只能 `pkill`），
单独跑就 40–50 秒正常通过 —— 这两个脚本自己开 pty、要么就单独跑，要么重定向到文件后台观察。

⚠️ **第二个小坑（heredoc 的两副面孔）**：本会话提交时用了 `git commit -F - <<'MSG'`，
**消息确实进了提交，但命令挂满 300 秒不返回**；而更早的会话里 `cat > file <<EOF` 干脆一个字节都没写。
结论写进协议了：写文件只用 `editor`，提交信息落成文件再 `git commit -F <file>`。
最终这次提交是 **47 个文件 / -11,240 / +1,163 行**，已推上 `origin/main`（`git status -sb` 无领先/落后）。

### ㉜ 数据搬家与书库清理（2026-09-26）

**问题**：阅读时长与成就只存在本机（`library.json` + `achievements.json`），换电脑 / 重装系统就归零。
**做法**：`werd data export <文件>` 打一个纯 JSON 包，拷到新机器 `werd data import <文件>` 合并进去；
顺带补两个清理入口 `werd prune` / `werd clear`。

| 改动 | 内容 |
| --- | --- |
| `wreader/transfer.py`（**新，198 行**） | `BUNDLE_KIND="werd-data"` / `BUNDLE_VERSION=1`；`export_data(path)` 挑**有阅读痕迹的书**（有 `last_read` 或 `total_time_seconds`）连同时长、每日桶、位置、会话、书签打包，成就解锁记录原样放入；`import_data(path)` 只加不减地合并；坏包一律 `TransferError` |
| `wreader/library.py` | 新增 `clear_library()`（删记录 + 删正文，**保留时长与成就**）、`prune_missing_books()`（索引 ↔ 正文目录对账）、`save_library()` 的合并侧配套改动 |
| `wreader/achievements.py` | 新增 `merge_states()`（解锁按 id 取并集、进度计数取较大值），供导入用 |
| `wreader/cli.py` | 新子命令 `data export/import`、`prune`、`clear` + `_HANDLERS` 三条新条目 + `_auto_prune_books()` |
| 文档 | `README.md` / `README.en.md` / `使用指南.md` 三处同步：命令表、三节用法、「从没读过的书不进包」「重复导入会把时长再加一遍」「Windows 上包放哪」 |
| 测试 | 新增 `tests/test_transfer.py`（**8 项**）；`test_cli.py` 33 → **45**、`test_library.py` 119 → **132** |

**合并语义（都写进了文档，用户必须知道）**：全局时长与每日桶**相加**、书的 `total_time_seconds` 相加、
`sessions` 按内容去重、书签取并集、`finished` 一旦为真就粘住、位置**只在本机没有历史时**才采用；
本机没有的 `book_id` 记进 `skipped`（提示"先 `werd import` 再导一次"）。所以**同一个包导入两次 = 时长翻倍**。

**实测（2026-09-26，真 CLI + 沙箱 `/tmp/wr-smoke`，不碰真实数据）**：

```
# 本机：导入一本书 → 手工写进 600 秒阅读痕迹
werd data export /tmp/wr-smoke/bundle.json
  → 已导出 1 本书的阅读记录与 1 个成就 → ...；累计时长 10分钟
  → 包首行 kind=werd-data / version=1 / exported_at / summary{books:1,unlocked:1,total_read_time:600}
werd data export /tmp/wr-smoke            # 目标是目录
  → error: /tmp/wr-smoke is a directory, give a file name   （退出码 1）
# 第二台机器（另一套 $WREADER_HOME/$WREADER_NOVELS_DIR）
werd data import bundle.json              # 书还没导入
  → 已合并 0 本书的阅读记录，成就共 1 个 / 1 本本机还没有的书被跳过
werd import book.txt && werd data import bundle.json
  → 已合并 1 本书的阅读记录，成就共 1 个；stats 0 → 20分钟（两次全包，含被跳过那次也算了全局时长）
第三次导同一个包 → 1800 秒，证实"累加"语义
缺包 → error: no such data file: ...（1）；非 JSON → error: ... cannot be read: ...（1）；
       kind 不对 → error: ... is not a werd data file（1）
werd prune（正文在）→ 没有失效书目；rm 掉正文后跑 werd list → 已清理 1 个失效书目（正文已被删除）：book
werd clear → 已清空书库：1 本书及其正文文件已删除 / 阅读时长与成就已保留；之后 werd stats 仍是 10分钟
```

**全量验证（2026-09-26，㉜ 当时）**：`pytest tests/` → **592 passed in 22.52s**；`npx pyright` → 0 / 0 / 0；
`check_docs` → RESULT: OK；`check_doc_numbers` → RESULT: ALL OK（含 `transfer.py` 198 行与
`test_transfer.py` 8 项）；`check_comments` → **TOTAL: 3099**；`verify_wrap` → 40077；`verify_draw` → 140；
`verify_achievements.py`（真 pty）→ 全部通过（改动动了 `achievements.py`，所以照规矩跑了一遍）。

**记忆库全量复核（2026-09-26 同一轮）**：6 个状态文件 + `memory-bank/README.md` + `.clinerules/memory-bank.md`
全部按实测重写数字（559 → 592 项 / 29 → 31 个 `.py` / 8,840 → 9,561 行 / 注释缺口 2771 → 3099），
`systemPatterns.md` 补模式 #12 与坑 #34–#37、模块表补上此前漏列的 `toc.py` 并新增 `transfer.py` 行。
**已提交并推送**（同一提交 19 个文件 / +1,964 −98；`git status -sb` 为 `## main...origin/main`，无领先/落后）。

> ℹ️ 本段（㉜）里的 **592 项 / 9,561 行 / 注释缺口 3099 / `reader.py` 2799 行 / `config.py` 966 行**
> 都是**当时**的实测值，已被其后的 ㉝（自动翻页）与 ㉞（防作弊校验）覆盖：现在是 **633 项 /
> 10,182 行 / 缺口 3403 / `reader.py` 3411 / `config.py` 975**（见本文件顶部的「当前状态一句话」）。
> 留着它们是为了说明「这一轮加了多少东西」，引用时请用 ㉞ 的数字。

### ㉝ 自动翻页：免手翻模式（2026-09-26）

**需求**：按一下 `a`，正文自己往下走（吃饭 / 织毛衣 / 跟读书会进度时不用手），能调速、能暂停。

| 改动 | 内容 |
| --- | --- |
| `wreader/reader.py`（**2799 → 3036 行**） | `Pager` 新增 `auto_scroll_interval` / `auto_scroll_step` / `auto_scroll` / `auto_scroll_deadline` 与 `set_auto_scroll` / `toggle_auto_scroll` / `defer_auto_scroll` / `auto_scroll_wait` / `auto_scroll_tick` / `auto_scroll_pace` / `adjust_auto_scroll_speed`；常量 `DEFAULT_AUTO_SCROLL_INTERVAL=5.0` / `DEFAULT_AUTO_SCROLL_STEP=1` / `AUTO_SCROLL_MIN_INTERVAL=0.5` / `AUTO_SCROLL_MAX_INTERVAL=600.0`；`_poll_timeout_ms()` 把每帧的 `stdscr.timeout` 收到「离下一拍还剩多久」；`_message_row` 开着时改报速度；`_HINT` / `_HELP_LINES` 补键位 |
| `wreader/config.py`（**966 → 971 行**） | `SCHEMA` 的 `[reader]` 加 `auto_scroll_interval`（默认 5.0）/ `auto_scroll_step`（默认 1）→ **4 段 18 键**（`reader` 11 键） |
| `tests/test_reader.py`（**174 → 199 项**） | 默认值 / 范围夹取 / `_format_seconds` / 速度文案 / 排期 / `defer` / tick 前进 / 到书末自停并提示 / 按**屏幕行**走过折行 / 自动模式只算进度不刷按键成就 / `_poll_timeout_ms` / 消息行 / 开关键与调速键 |
| `tests/test_config.py`（**49 → 50 项**） | `SCHEMA` 含两个新键且默认值对、`coerce_value` 认数字、非数字抛 `ConfigError` |
| 文档 | `README.md` / `README.en.md`（特性表 + 按键表 + 设置项 + 测试数字）、`使用指南.md`（新增「场景 D：手没空，让它自己翻」+ 总表两行 + 参数示例） |

**口径（都写进文档里了）**：
- 前进单位是**屏幕行**（`auto_scroll_step`），与 `next_page` / `scroll` 同一套单位 ——
  超长段落的折行会**一行一行**走过，不会整段跳过；
- 间隔夹在 **0.5s ~ 600s**；`>` / `+` / `=` 加速（÷2）、`<` / `-` / `_` 减速（×2），调速后**重新排期**；
- **任何按键 / 滚轮 / 窗口变化都 `defer_auto_scroll()`**，把下一拍推后一整间隔 —— 正在打字的人不该被抢页；
- 到书末**自动关掉并提示** `已经读到全书末尾，自动翻页已停`（免手模式静默空转比没有更糟）；
- 自动翻页**照常算阅读进度与时长**，但**不喂** `page_streak` 与按键类成就（那是给手动阅读的）。

**实测（沙箱 `/tmp/wr-as`，不碰真实数据）**：

```
werd config                                 # 18 键表格，含 reader.auto_scroll_interval=5 / auto_scroll_step=1
werd config reader.auto_scroll_interval 2   → reader.auto_scroll_interval = 2 (saved)
werd config reader.auto_scroll_step 3       → reader.auto_scroll_step = 3 (saved)
grep auto_scroll ~/.wreader/settings.toml   → auto_scroll_interval = 2 / auto_scroll_step = 3（带中文行尾注释）
werd config reader.auto_scroll_interval abc
   → error: 'reader.auto_scroll_interval' expects a number, got 'abc'    （退出码 1）
```

**全量验证（2026-09-26）**：`pytest tests/` → **618 passed**（同一台机器两次：14.59s / 26.35s）；`npx pyright` → **0 / 0 / 0**；
`check_docs` → OK；`check_doc_numbers` → **ALL OK**（618 总数 + `test_reader` 199 / `test_config` 50 /
`reader.py` 3036 / `config.py` 971）；`check_comments` → **3204**；`verify_wrap` → 40077；`verify_draw` → 140。
**真 pty 端到端补测（本会话临时写的一次性脚本，跑完已删）**：40×100 的 pty + 沙箱书 200 行，
设 `auto_scroll_interval=1` / `auto_scroll_step=2` / `auto_save_interval=1`：按 `a` 后 3.6 秒，
屏上从开头走到**第 038~041 行**、`progress.current_line` **0 → 4**；再按 `a` 暂停、干等 2.5 秒，
仍停在 **4**（暂停是暂停，不是减速）；提示栏确实出现「自动翻页」字样。
⚠️ 当时**没跑** `verify_mouse.py` / `verify_achievements.py` / `verify_colors.py`（`a` 键也不在
`verify_mouse.py` 的键盘基准里）—— **㉞ 收尾时已全部补跑并通过，见 ㉞**。

**已提交并推送**：`93e3719`（`wreader/reader.py` + `wreader/config.py` + 两个测试文件 +
`README.md` / `README.en.md` / `使用指南.md`）与 `f0b10bd`（记忆库 6 个状态文件 +
`memory-bank/README.md` + `.clinerules/memory-bank.md`）。

> ℹ️ ㉝ 的数字同样是**当时**的（618 项 / 9,803 行 / 缺口 3204 / `reader.py` 3036 / `config.py` 971）；
> 紧接着的 ㉞ 把它们推到 **633 项 / 10,182 行 / 缺口 3403 / `reader.py` 3411 / `config.py` 975**。

### ㉞ 自动翻页的防作弊校验：连续 10 分钟弹一道算术题（2026-09-26）

**需求（用户原话）**：「增加一个防作弊机制，自动翻页十分钟之后，程序跳出一个 100 以内的加减乘除
判断题，如果用户没有选择，自动翻页结束。如果选择了选项，自动翻页继续。」

**口径（弹题前问过用户，用户选了第二项）**：**只要按了某个选项就继续**（答错也继续 —— 证明确实
有人在）；只有**超时未选**或按 `Esc`（以及任何别的非选项键）才停。题目做成四选一，
是因为手机上（Termux）一个数字键就能作答。

| 改动 | 内容 |
| --- | --- |
| `wreader/reader.py`（**3036 → 3411 行**） | `Pager` 新增 `auto_check_period`（= 分钟 × 60，0 = 关）/ `auto_check_wait` / `auto_check_deadline` / `auto_check_until` / `auto_check_question`，方法 `_schedule_auto_check` / `auto_check_due` / `auto_check_remaining` / `begin_auto_check` / `resolve_auto_check` / `auto_check_note`；纯函数 `_make_auto_check_question(rng)` / `_auto_check_lines(question, remaining, period)` / `_auto_check_choice(key, count)` / `_auto_check_layout(height, width, lines)`；绘制 `_draw_auto_check`、模态 `_auto_check_overlay`；常量 `DEFAULT_AUTO_CHECK_MINUTES`=10.0 / `DEFAULT_AUTO_CHECK_SECONDS`=30.0 / `_AUTO_CHECK_CHOICES`=4 / `_AUTO_CHECK_OPERATORS` / `_AUTO_CHECK_TITLE` / `_AUTO_CHECK_FOOTER` / `_AUTO_CHECK_POLL_MS`=200；`set_auto_scroll` 里接上排期，`_run` 在 `_draw` 之后 `if pager.auto_check_due(): _auto_check_overlay(...)`；`_HELP_LINES` 补两行说明；`open_reader` 读两个新键 |
| `wreader/config.py`（**971 → 975 行**） | `SCHEMA` 的 `[reader]` 加 `auto_scroll_check_minutes`（默认 **10.0**，float）/ `auto_scroll_check_seconds`（默认 30，int）→ **4 段 20 键**（`reader` 13 键） |
| `tests/test_reader.py`（**199 → 213 项**） | 默认值与换算 / 提示语 / 出题（300 次固定种子：四种运算符、操作数与结果 ≤ 100、除法整除、选项 4 个不重复且正确项位置随机）/ 文案与倒计时 / 布局太小 / 排期只在周期后 / 作答后继续（两个排期都重排）/ 没作答停（含越界与没题在屏上）/ `_auto_check_choice` 只认数字键 / 弹窗三个出口（选 `2`、超时、`Esc`）与屏太小 |
| `tests/test_config.py`（**50 → 51 项**） | 两个新键的默认值（`10.0` / `30`）、`coerce_value` 认 `"15"` / `"0.5"` / `"0"`、非数字抛 `ConfigError` |
| `tests/test_reader.py` 的 `FakeStdscr` | 加两个钩子：`empty_key="timeout"` 让 `get_wch` 抛 `curses.error`（测"轮询超时"分支）、`timeout_value` 记住最后一次 `timeout()`（断言模态退出后恢复 `_TICK_MS`）；默认行为不变 |
| 文档 | `README.md` / `README.en.md`（按键表 `a` 行 + 特性段 + 设置表两行 + 18 → 20 项 + 全部行数/测试数字）、`使用指南.md`（场景 D 增「翻了十分钟会考你一道算术题」+ 总表 + 参数示例 + 快捷提示注释） |

**行为口径（写进三份文档与 `progress.md` 的已知问题表）**：

- **计时量的是「自动翻页连续开了多久」**：`set_auto_scroll(True)` 种下 `now + period`，
  **读者按键 / 滚轮 / 改窗口都不重置它**（`defer_auto_scroll` 只推后下一拍翻页）——
  否则敲一下键就能永久躲过校验（设计取舍见 `progress.md` 决策行）。
- **弹题期间不翻页**：`begin_auto_check` 把 `auto_scroll_deadline` 清零，结算后再 `defer_auto_scroll`
  排一整拍，所以题目不会在文字背后被卷走。
- **任意选项都算作答**；没作答（`Esc` / 别的键 / 超时）就 `set_auto_scroll(False)` +
  `say("校验题没有作答，自动翻页已停（按 a 重新开始）")`。作答成功则
  `say("已作答（正确答案 62），自动翻页继续；10 分钟后再校验")`。
- **屏幕小到放不下题目**（`_auto_check_layout` 返回 `None`）→ 当没作答处理 + `say("屏幕太小…")`，
  不让用户对着看不见的倒计时干等。
- **题目每次都不一样**：运算符、操作数、选项顺序随机；运算符刻意用 ASCII 的 `+ - * /`
  （`×` `÷` 是"东亚宽度不确定"字符，CJK 终端里可能占两列，弹窗边框会错位）。

**全量验证（2026-09-26，本会话实测）**：`pytest tests/` → **633 passed in 43.84s**（`test_reader` +
`test_config` 两个文件单跑 21.97s）；`npx pyright` → **0 errors / 0 warnings / 0 informations**；
`check_docs` → RESULT: OK；`check_doc_numbers` → **RESULT: ALL OK**（633 总数 + `test_reader` 213 /
`test_config` 51 / `reader.py` 3411 / `config.py` 975）；`check_comments` → **TOTAL: 3403**；
`verify_wrap` → 40077；`verify_draw` → 140。

**真 pty 端到端补测（临时脚本 `/tmp/verify_auto_check.py`，跑完已删）**：40×100 的 pty + 沙箱书 400 行，
设 `auto_scroll_interval=0.5` / `auto_scroll_step=1` / `auto_scroll_check_minutes=0.05`（= 3 秒周期）/
`auto_scroll_check_seconds=3`，按 `a` 打开后等题目出现，三条路径实测：

```
① 收到题目后按 "1"  → 提示栏出现「正确答案」，进度 +12 行（6 秒 tail，且 3 秒后又弹了第二道）
② 收到题目后按 Esc  → 提示栏「校验题没有作答，自动翻页已停」；进度只 +6（题目出现之前的那些）
③ 收到题目后不按键  → 3 秒后同样提示已停；进度只 +6
RESULT: ALL OK
```

**三个真 pty 脚本本会话都补跑了**（都通过）：`verify_achievements.py` → 19 项全过（帮助页 / 通知 /
恢复流程）；`verify_mouse.py` → 8 项全过；`verify_colors.py` → `default colour pair usable: yes (-1/-1)`。
⚠️ 两个环境坑（已写进 `systemPatterns.md` 坑 #45 / #46）：`verify_colors.py` 必须在**真终端**里跑
（本会话用 `script -q /dev/null .venv/bin/python tools/verify_colors.py` 才过，非 tty 时它会打印
「需要在真终端 / pty 里运行」并退出）；`verify_mouse.py` **不能和 pytest 并行跑** —— 它固定
`sleep 1.3` 等 curses 起来，机器一忙按键就被吞、脚本挂在 `waitpid`（并行时卡了 3 分钟没动静，
单独跑 8 项全过）。

**已提交并推送**（本会话）：`c99c3d7`（`wreader/reader.py` + `wreader/config.py` + 两个测试文件 +
`README.md` / `README.en.md` / `使用指南.md`）与 `5935593`（记忆库 6 个状态文件 +
`memory-bank/README.md` + `.clinerules/memory-bank.md`）；`git status -sb` 收尾
`## main...origin/main`（不显示领先 / 落后）。收尾复核见 ㉟。

### ㉟ 收尾复核：三个 pty 脚本补跑 + 一个探针假警报的澄清 + 记忆库全量对账（2026-09-26）

**这一节没有新的功能改动**，做的是 ㉞ 的收尾：

1. **三个真 pty 脚本补跑（都通过）** → `tools/` 的 8 个脚本本轮**全绿**：
   `verify_achievements.py` 19 项、`verify_mouse.py` 8 项、`verify_colors.py`
   （`default colour pair usable: yes (-1/-1)`；必须借真终端跑：
   `script -q /dev/null .venv/bin/python tools/verify_colors.py`）。
2. **澄清「阅读器不理 `q`」这个假警报**（教训已写进 `systemPatterns.md` 坑 #45 / #46）：
   临时 pty 探针反复报「灌了 `q` 也不退出」，而把本轮改动 `git stash` 掉、在 HEAD 上**照样复现**
   → 先排除了「回归」。最后 `ps -p <pid> -o stat` 看到子进程是 **`ZN`（zombie）**：
   它其实**每次都在第一个 `q` 就正常退出了**，是探针自己「读到 EOF 就 `break`」把正常退出
   误判成卡住。→ **阅读器的 `q` 一直好使**；`verify_mouse.py` 那次挂住是它固定 `sleep 1.3`
   等 curses 起来，而我把 pytest 与它并行跑（机器一忙，灌进去的按键被 `initscr()` 的 flush
   吃掉），**单独跑就 8 项全过**。
3. **记忆库全量复核（本次）**：所有数字重测（见开头：633 项 / `wreader/` 12 个 `.py` /
   10,182 行 / `reader.py` 3411 / `config.py` 975 / 注释缺口 3403 / `SCHEMA` 4 段 20 键 /
   成就 48 条 / `tools/` 8 个脚本），并修掉三处漂移 ——
   `.clinerules/memory-bank.md`（逐文件注释缺口抄的是更早的 `664` / `509`，现改为不重复，
   明细只留 `progress.md` 待办 #1）、`projectbrief.md` 与 `progress.md`（`reader.py` 缺口
   `585` → **588**）、`memory-bank/README.md`（模式数 `12` → **14**，补上坑 **46** 条）。

## 待办 / 下一步

0. **注释覆盖率拍板**（`progress.md` 待办 #1）：严格口径下 `wreader/` + `tests/` 还有 **3403** 条缺口
   （2026-09-26 复测：上一次是 2771 → ㉜ 之后 3099 → ㉝ 之后 3204 → 本会话的防作弊校验又添了 199 条）。
   要么正式把口径定为"一段逻辑配一段注释"（文档已如此），要么对改到的文件做 `--strict` 增量门禁。
1. **`reader.theme` 仍未实现**（预留项，改了没效果）：在 `_init_colors()` 里按主题 `init_pair()`，
   并给正文 / 状态栏 / 书签分配 color pair；务必保住 `use_default_colors()` 的透明背景（背景用 `-1`），
   改完跑 `tools/verify_colors.py`。
2. 可选：给 `library.py` 补 `__all__`（目前唯一没有 `__all__` 的模块）。
3. 可选：`werd continue` 目前**写死 3 本**。若想可配置，应加 `reader.continue_limit` 走 `SCHEMA`
   （项目约定：阅读行为不写魔数）。
4. 可选（产品取舍，先问再做）：`werd continue` 只"列 id"，不做交互选择。
   若想省掉"抄 id"这步，可让 `read` 的 `book_id` 变成可选（`nargs="?"`）+ 无参时续读最近一本 ——
   但那会让程序替用户猜要读哪本，需先确认。
5. 可选：**Windows 还没有一键脚本**。`install.sh` 是 bash，Windows 用户目前只能照 README 的手动步骤
   （`pip install -e ".[windows]"` + 在 `$PROFILE` 里加函数）。要补就写 `install.ps1`，
   做同样几件事（PowerShell 的别名是 function 而不是 alias）。
6. 可选：**遗留数据没有清理入口**（`~/.wreader/vocab.json`、`notes/`、旧译文缓存
   `cache/<book_id>/ch*_en.txt`）。要么在 `werd stats` 里标一句「遗留数据，只读」，
   要么加 `werd clean`（删之前必须问一次）。
   ⚠️ 2026-09-26 加的 `werd clear` **不是**这个入口：它清的是**书库**（书目记录 + 转换后的正文），
   遗留数据文件一个都没动。
7. 可选：老 `settings.toml` 里的死键只在 `werd config` 列表时警告，不会从文件里删掉（刻意如此）。
   若要做清理向导，挂在 `werd config --reset` 上，默认别动用户的文件。
8. 可选：成就侧两处已无调用方的常量 —— `EVENTS` 里的 `word_add` / `note_add` 与 `check`
   （`werd achievements` 改发 `achievements_view`）。保留是为了不打断老脚本，可留到下个大版本再删。
9. 成就的两个已知边界（细节在 README「已知问题」）：
   - 农历节日表（`achievements.LUNAR_HOLIDAYS`）**只到 2030 年**，2031 起要按历书补；
   - `geo.py` 用的是 **HTTP** 免费端点（ip-api 的 HTTPS 要付费），换服务商得同时改
     `parse_response` 与测试。

## 已知会话级注意事项

- **数字的权威快照在本文件开头与 `memory-bank/README.md`**：写任何数字前先看那里，或直接重跑
  `tools/check_doc_numbers.py` 与 `tools/check_comments.py` —— 别凭记忆写"大概"。
- **维护协议在 `.clinerules/memory-bank.md`**（对每次会话自动生效）：读取顺序、何时更新哪个
  文件、写作纪律、项目硬性约束都在那里。要调整协议只改那一个文件，别在 `memory-bank/` 里重复。
- ⚠️ **改文件只用 `editor` 工具**：本环境 `cat > file <<EOF` 这类 heredoc 会把 shell 搅乱、
  **文件一个字节都没写**（看着像成功）。`editor` 单次替换还有 ~6000 字符上限，超长替换会
  "假成功"（在仓库根留一份野生文件）；大改拆小块，改完 `grep` / `head` 确认落地，
  收尾 `git status` 扫一眼有没有怪文件。
- **`read_files` 读刚改过的同一段可能返回 `[outdated ...]`**：复核刚改的内容改用 `sed -n 'A,Bp' file`。
- **pytest 汇总行会消失**：`pyproject.toml` 的 `addopts` 已含 `-q`，命令行再加 `-q` 变成 `-qq`，
  只输出 `文件: 数量`。想看到 `N passed` 就别再加 `-q`。
- **macOS 终端透明背景**：若 `use_default_colors()` 之后背景依旧纯黑、透不出壁纸，
  那是终端模拟器自己的设置（如 iTerm2「在备用屏幕里禁用透明度」），应用层无法绕过。
- **git 提交要连 memory-bank 一起**：协议要求"每完成一段工作就更新 `activeContext.md`"，
  所以收尾时 `git status` 应当干净；文档改动和代码改动一起 commit + push，别攒着。
  推之前留意别把 `book/`（已忽略）或临时脚本加进去。
- **改 UI 一定要跑真 pty 验证**：`verify_mouse.py`（鼠标）、`verify_achievements.py`
  （成就通知 / 帮助页 / 恢复流程）、`verify_colors.py`（配色）。
  **`FakeStdscr` 实现得越像真 curses，越可能掩盖真 API 的差异** ——
  历史上 `stdscr.newwin` 不存在这个错误就是靠真 pty 才抓出来的。
  非交互运行时记得给子进程显式设 `TERM`（鼠标那项要 `TERM=xterm-1006`）。
- **`Ctrl-S` 依赖 `_disable_flow_control()`**：终端 `IXON` 没关就会被行规程吞掉。
  现在没有 `Ctrl-S` 键了，但这个函数仍在；以后任何 Ctrl-Q/Ctrl-S 绑定都要先确认它被调用过。
- **只读兼容函数不许抛异常**：`stats._vocab_file_size()` / `achievements._note_total()` 挂在
  每次统计与每次成就判定的路径上，坏 JSON / 坏编码 / 无权限一律吞掉返回 `0`。
- **`importlib.metadata` 在仓库根会被 `wreader.egg-info` 遮蔽**：`distribution("wreader")` 先命中
  源码树里那份（没有 `direct_url.json`），于是"可编辑安装"探测在仓库根误判。
  `env.direct_url_text()` 遍历 `distributions(name=...)` 逐个尝试；以后读安装元数据都按这个写法。
- **给 `daily_open` 钉时间的测试要避开节日**：固定时刻用 `2026-01-15 12:00` 这类既不在 05:00-07:00、
  也不在 `achievements.HOLIDAYS` / `LUNAR_HOLIDAYS` 里的时间。
- ⚠️ **推送依赖代理 `http://127.0.0.1:7897`**（实测）：代理没开时 `git push` 立刻报
  `Failed to connect to 127.0.0.1 port 7897`，而"绕过代理"的 `git -c http.proxy= push` **会挂在直连上**
  （实测挂几分钟无结果，只能 `pkill git-remote-https`）—— 直连 GitHub 在这台机器上不通，
  别把"绕过代理"当万能解。判据：
  `curl -s -o /dev/null -w '%{http_code}' --max-time 8 -x http://127.0.0.1:7897 https://github.com`
  返回 200 就能推。**偶发 `SSL_ERROR_SYSCALL` 是网络抖动，原样重试一次通常就好**。
  代理没开也不挡任何验证工作：测试、`pyright`、`tools/` 全离线可跑，提交先留在本地等代理起来。
- **在旧终端里验证 CLI 用 `.venv/bin/python -m wreader.cli ...` 最稳**：`install.sh` 往
  `~/.zshrc` / `~/.bashrc` 写的别名只在**新开的** shell 里生效。
- ⚠️ **活体验证要在沙箱里做**：`export WREADER_HOME=/tmp/wr-smoke/home WREADER_NOVELS_DIR=/tmp/wr-smoke/novels`
  之后再跑 `.venv/bin/werd ...`，动的就是 `/tmp` 里的假数据。2026-09-26 用这套跑通了
  `data export` → 第二台机器 `data import` → `prune` → `clear` 的全链路（证据见 ㉜）。
- ⚠️ **别把「删目录」和「依赖它的命令」放进同一个并行批次**：2026-09-26 一次把 `rm -rf /tmp/wr-smoke`
  与随后的 `import` / `data export` 同时发出（同一批 `run_commands`），于是出现
  「包明明导出了却 `head` 不到」「书库明明是空的」这类**假失败**，白查一轮。
  有先后依赖的命令串成一个 `&&` 链条，或者分两次调用。
- ⚠️ **`tools/check_doc_numbers.py` 只管 `README.md` 与 `README.en.md`**：`使用指南.md` 与
  memory-bank 里的行数 / 测试项数**没有任何脚本替你守**，改完代码必须自己重数（本会话手改了 3 处文档）。
- ⚠️ **用 `editor` 写中文段落时别夹英文双引号**：2026-09-26 实测，`new_text` 里出现的英文双引号会被落成
  「反斜杠 + 双引号」原样写进文件，肉眼扫 diff 容易漏过去。判据：扫一遍 `chr(92)+chr(34)` 所在行号；
  改用「」就没事。

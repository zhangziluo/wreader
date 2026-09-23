# tools/ —— 开发期的校验脚本

这些脚本**不参与打包**（`[tool.setuptools.packages.find]` 只收 `wreader*`），也不需要额外安装。
用项目虚拟环境里的 Python 跑就行：

```bash
source .venv/bin/activate       # 或者直接用 .venv/bin/python 调
python tools/check_docs.py
```

它们都从 `__file__` 推算仓库根目录，所以**在哪个目录下运行都可以**。
除 `verify_colors.py` 需要 pty（退出码含义见下）外，其余脚本统一是
**0 = 通过、1 = 发现问题**，可以直接接到 CI 上。

| 脚本 | 检查什么 | 退出码 |
| --- | --- | --- |
| `check_docs.py` | Markdown 的文内锚点能否解析、代码围栏是否配对 | 0 / 1 |
| `check_doc_numbers.py` | README 里写的源码行数、测试项数是否与真实情况一致 | 0 / 1 |
| `check_comments.py` | 有没有「上方没有紧邻注释行」的逻辑语句（默认只报告） | 见下 |
| `verify_wrap.py` | `reader._wrap_line` 折行：不超宽、不丢字符、不产空行（约 4 万次属性检查） | 0 / 1 |
| `verify_draw.py` | `reader._draw` 的每次写入都不越界（4 种正文 × 7 宽 × 5 高 × 3 视图 = 420 组） | 0 / 1 |
| `verify_colors.py` | 真 pty 里 `_init_colors()` 的效果（默认色 `-1` 可用 ⇒ 背景能跟随终端主题） | 0 / 1 |
| `verify_mouse.py` | 真 pty 里灌 SGR 鼠标序列，验证滚轮 / 触摸拖动真的翻滚页（8 项对账） | 0 / 1 |
| `verify_notes.py` | 真 pty 里走一遍「标记 + 笔记面板」：引用区、Ctrl+S、折叠提示都对账（5 项） | 0 / 1 |
| `verify_translate.py` | 真 pty 里验证 `t` 的未配置提示，外加 `werd config translate` 落盘（4 项） | 0 / 1 |
| `verify_achievements.py` | 真 pty 里验证帮助页、屏内 5 秒成就通知、意外中断恢复、名字彩蛋（19 项） | 0 / 1 |

## 逐个说明

### `check_docs.py`

```bash
python tools/check_docs.py              # 检查仓库根下所有 .md
python tools/check_docs.py README.md    # 只检查一个文件
```

锚点规则照 GitHub：小写 → 丢掉标点（保留字母 / 数字 / 下划线 / 连字符 / CJK）→ 空格换连字符。
新增章节、改标题之后顺手跑一下，就不会留下点不动的目录链接。

### `check_doc_numbers.py`

```bash
python tools/check_doc_numbers.py
```

把 `README.md` / `README.en.md` 的「项目结构」里写的「（N 行）」与「N 项」，
跟**真实文件行数**、**pytest 实际收集数**逐项对拍。改了代码就顺手跑一次，防止文档悄悄过期。

> 注意：它内部会调用 pytest 来数测试项，所以**不要**把它放进 `tests/` 当测试跑（会递归）。

> ⚠️ **子包里的文件不在它的校验范围内**。行数那条规则只认 `wreader/<文件名>`，
> 而 `wreader/translate/` 这类子包的文件名会跟包根撞车（两边都有 `__init__.py`），
> 光看文件名分不清是哪一个。所以 README 的子包条目**不写"（N 行）"**，
> 这些数字记在 `memory-bank/techContext.md` 里。

### `check_comments.py`

```bash
python tools/check_comments.py              # 只报告 wreader/ 与 tests/
python tools/check_comments.py --strict     # 有遗漏就返回退出码 1
python tools/check_comments.py --strict wreader/vocab.py   # 限定文件，适合逐个改善
```

项目约定「每条逻辑语句上方都要有一行口语化中文注释」，但**这是个很严的字面规则**：
2026-09-22 实测 `wreader/` + `tests/` 仍有 **2260** 条语句上方没有紧邻注释行
（`test_reader.py` 447、`reader.py` 399、`translator.py` 189 …）。
所以默认模式**只报告、不判定**；要拿它当门禁就加 `--strict`，并配合文件参数一次啃一个。

> ⚠️ 历史坑：这个脚本早先的版本把 `tokenize.NEWLINE` 也放进了「跳过」集合，
> 于是「一条语句结束」这个信号永远不会触发，**每个文件只检查了第 1 行**，
> 却一直输出 `TOTAL: 0` —— 一个假绿的检查。2026-09-22 修正后才看到真实数字。

### `verify_wrap.py`

```bash
python tools/verify_wrap.py     # 期望输出：OK: 40077 checks passed
```

固定随机种子的属性检查（约 4 万次），专治「汉字占 2 列」这类宽度 bug。
断言里带着原文与宽度，出问题能原地复现。

### `verify_draw.py`

```bash
python tools/verify_draw.py     # 期望输出：OK: 420 draw checks passed
```

用记录型假窗口接住每次 `addstr`，断言「起始列 + 显示宽度 ≤ 终端宽度」。
真实 curses 对越界写入会报错、而阅读器会把错误吞掉 —— 后果是**整行文字静默消失**，
所以这条断言很值钱。改 `_draw` / 状态栏 / 折行之后务必跑它。

### `verify_colors.py`

```bash
script -q /dev/null python tools/verify_colors.py && cat /tmp/wreader_colors.txt
```

必须借 `script` 开一个 pty（macOS / Linux 自带；Windows 请另找办法），
结果写进文件是为了不让终端转义序列污染输出。它验证「背景跟随终端主题 / 透明」的前提：
`_init_colors()` 不抛异常、`use_default_colors()` 之后 `-1` 默认色对可用、`A_NORMAL` 不带颜色位。

### `verify_mouse.py`

```bash
python tools/verify_mouse.py     # 期望：RESULT: 全部通过
```

鼠标这套东西**单元测试盖不到底**：「终端有没有把事件送进来」取决于 curses / terminfo /
终端模拟器三者。所以这个脚本自己开一个真 pty、跑一次阅读器、灌标准 SGR 鼠标序列，
再读 `library.json` 里的进度对账 —— 键盘基准、滚轮上一格、向上拖 4 行、向下拖 3 行、
`touch_scroll=false` 拖动无效、步长=5、`page_overlap=0` 时键盘翻整屏、**长段落里翻页停在原行**，
共 **8 项**。
⚠️ 各项是**顺序累积**的：上一项退出的位置就是下一项的起点，所以改翻页步长 / 重叠时，
后面所有期望值都要跟着平移。
⚠️ 键盘翻页的基准是**pty 的真实高度**（40 行 → 正文区 38 行），不是 `reader.page_height`：
翻页现在按屏幕行算。改 pty 尺寸或改成按屏幕行推进的逻辑，① 及之后全部期望值都要重算。
⚠️ 第 ⑧ 项用另一本**第一行两万汉字**的书，验证"一屏装不下的长段落会停在段内继续翻"：
段内偏移只影响显示、**不落库**，所以两次 `j` 之后 `current_line` 仍然是 **0**（旧逻辑会变成 2）。

> ⚠️ 两个前提，别随便改：
> 1. 它固定用 **`TERM=xterm-1006`**。实测：macOS 上 `xterm-256color` 的 terminfo **没有 `XM` 能力**，
>    curses 只开 `?1000h`，SGR 序列会被当成普通按键收进来 —— 换别的 TERM 会**假失败**。
> 2. 必须给 pty 设一个正常尺寸（不设就是 0x0）。
>
> 它的价值已经被验证过：抓出了一个"拖动完全失效"的真 bug —— `curses.mouseinterval` 默认的
> 点击判定窗口会把**按下事件扣住**，导致拖动状态建立不起来。单测发现不了这个。

### `verify_notes.py`

```bash
python tools/verify_notes.py     # 期望：RESULT: 全部通过
```

笔记面板会真的建两个 curses 子窗口、跑 `curses.textpad.Textbox`，还要靠
「主窗口先刷、子窗口后刷」的刷新顺序才不会被 `stdscr.erase()` 擦掉 —— 这些用 `FakeStdscr`
的单元测试**盖不到底**（假窗口没有真正的 curses 叠窗语义）。所以这里开一个真 pty、
跑一次阅读器、按 `m` → `ll` → `y` → `o` → 打 `abc` → `Tab` → `Ctrl+S` → `Esc` → `q`，
再把终端输出读回来对账 **5 项**：引用区画出 `> …`、面板提示行、`Ctrl+S` 存成功
（顺带证明 `_disable_flow_control()` 真把 `IXON` 关掉了，否则 XOFF 会被行规程吞掉）、
折叠后提示行显示 `按o展开`、全程没有 traceback。

> ⚠️ 它的价值也已经被验证过：第一版把子窗口写成 `stdscr.newwin(...)`，
> 单测（假窗口正好实现了 `newwin`）全绿，但**真 curses 的 window 对象根本没有 `newwin` 方法**
> （只有 `derwin`）—— 一跑这个脚本就 `AttributeError`。现在代码走 `reader._sub_window()`
> 这层间接，生产用 `curses.newwin`，测试替换成假窗口。
>
> 另一个坑：脚本必须显式给子进程一个 `TERM`（非交互运行时 `TERM` 可能没设，
> curses 起不来，子进程会提前退出，写 pty 直接 `EIO`）。

### `verify_translate.py`

```bash
python tools/verify_translate.py     # 期望：RESULT: 全部通过
```

`t` 的译文弹窗要真的建子窗口、真的按"主窗口先刷、子窗口后刷"的顺序画；
但**翻译本身要联网**，而项目纪律是测试绝不联网。所以这里只验证**不联网也完全确定**的两条路径，
它们恰好是规格里最容易写错的两条：

1. **引擎没配好时按 `t`** 必须给出「运行 werd config translate」这种可操作提示 ——
   既不能偷偷发请求，也不能把后端报错甩给用户（分别用"选了 local 但没装 argostranslate"
   和"选了 baidu 但没填密钥"两种情况各验一次）；
2. **`werd config translate` 向导**真的把引擎名与密钥写进 `settings.toml`（喂标准输入，非交互跑）。

### `verify_achievements.py`

```bash
python tools/verify_achievements.py     # 期望：RESULT: 全部通过
```

成就 Phase 2/3 的链路里，有两件事**只有真进程能证明**：

1. **屏内 5 秒通知真的画在屏幕上**：它由 `_draw` 每帧画在右上角，靠 `Pager.current_notice()`
   的时间窗 —— `FakeStdscr` 只能说明"写进去过"，说明不了真 curses 里那一帧真的画出来了、
   也没把正文顶掉；
2. **意外中断恢复真的拦在开书时问一句**：要在真终端里弹 `_confirm`、等一个按键、再回到现场；
   而且现场文件必须**正常退出时才删掉**，否则下次开书会又问一遍 —— 这只有真进程能验。

脚本开一个真 pty，跑三个场景：`?` 打开帮助（顺便记一次"帮助迷"）→ 关掉 → 等通知画出来 → `q` 退出；
造一份"上次没正常退出"的现场 → `y` 接着读 → `q`；再干净地开一次，确认**不再问**。
对账 19 项：终端输出里的帮助页 / 通知 / 恢复提示，加上落盘的 `achievements.json`
（`help_opens`、`crash_recovers`、解锁 id、`eggs`）与 `library.json`（恢复后的行号）。

> 沙箱里第一件事就是把 `stats.geo_lookup` 设成 `false`：这个工具**不该依赖网络**，
> 顺便也就验证了那个开关真的第一步就把联网挡掉了。

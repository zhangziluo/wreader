# Active Context — 当前焦点与最近改动

> 每次会话结束前更新这个文件。最后更新：**2026-09-22**。

## 当前状态一句话

代码库处于**干净、全绿**状态：`494 passed`、`pyright 0 errors / 0 warnings`、
注释覆盖检查 `TOTAL: 0`。本会话完成的三件事（中文注释、自动换行、背景跟随终端）都已落地并验证。

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
- 注：工作目录**不是 git 仓库**，因此无法用 diff 证明"零逻辑改动"，只能靠
  `py_compile` + 全量 pytest + 注释覆盖检查兜底。

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
  正好对应 `progress.md` 待办 #5（`/tmp` 会被系统清理）。

## 本会话的验证证据（全部通过）

| 检查 | 结果 |
| --- | --- |
| `py_compile wreader/*.py tests/*.py` | 通过 |
| `pytest tests/` | **494 passed**（426→474 基线 + 本会话新增 20） |
| `/tmp/check_comments.py`（16 个文件） | **TOTAL: 0**（无遗漏注释的逻辑语句） |
| `npx pyright` | **0 errors, 0 warnings, 0 informations** |
| `/tmp/verify_wrap.py` | **40,077** 次随机属性检查：不丢字符、不超宽、不产生空行 |
| `/tmp/verify_draw.py` | **420** 次绘制检查（10~120 列 × 4~40 行 × 3 视图）：任何 `addstr` 都不越界，状态栏两行必有内容 |
| `/tmp/verify_colors.py`（真 pty，`script -q /dev/null`） | `has_colors=True`、`COLORS=256`、`-1/-1` 默认色对可用、会话干净退出 |
| `/tmp/demo_colors.py`（修复前后对照） | 修复前 `init_pair() returned ERR`；修复后 OK |
| `/tmp/demo_colors.py`（修 Pylance 报错后复测） | `npx pyright` 在**仓库内**与**`/tmp` 下**各跑一次均 `0 errors`；去掉忽略注释的对照文件则报 1 个 `reportMissingImports`；`py_compile` OK；真 pty（`script -q /dev/null`）运行 exit=0，输出仍是"修复前 FAIL / 修复后 OK" |
| `/tmp/demo_wrap.py`（可视化） | 80/40/24/20 列的终端下折行与状态栏渲染均正确 |

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

## 待办 / 下一步

按优先级：

1. **没有 git 仓库**：建议 `git init` 并做一次初始提交，否则今后再也无法用 diff 证明
   "只加注释、不动逻辑"，也无法回退。这是目前最大的工程风险。
2. **更新 `README.md` 的过期内容**：
   - "项目结构"一节的源码行数（`cli.py` 811→1006、`reader.py` 1412→1948 等）
   - 测试数量 474 → **494**，以及 `test_reader.py` 95 → 115
   - "已知问题"里可以补一条：状态栏/弹窗宽度已改为按显示列数（原为字符数）
3. **`reader.theme` 仍未实现**（预留项）。若要做，需在 `_init_colors()` 里根据主题值
   `init_pair()` 出一套配色，并给正文/状态栏/书签分配 color pair。
4. 可选：给 `library.py` 补 `__all__`（目前唯一没有 `__all__` 的模块）。
5. 可选：把本会话写在 `/tmp` 的校验脚本（注释覆盖、折行属性、绘制越界）搬进
   `tests/` 或 `tools/`，因为 `/tmp` 会被系统清理。

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

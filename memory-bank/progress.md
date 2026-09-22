# Progress — 已完成 / 待办 / 已知问题

> 项目整体进度与决策演变。最后更新：**2026-09-22**。

## 当前状态

| 维度 | 状态 |
| --- | --- |
| 版本 | `0.1.0`（Pre-Alpha，`Development Status :: 2 - Pre-Alpha`） |
| 测试 | **494 passed**，全离线、不碰真实数据，约 4~7 秒 |
| 类型检查 | `npx pyright` → **0 errors, 0 warnings, 0 informations** |
| 注释覆盖 | `tools/check_comments.py` 实测：`wreader/` + `tests/` 仍有 **2054** 条语句上方没有紧邻注释行（口径与处置见待办 #4） |
| 文档 | `README.md`（中文主文档，37 KB）、`README.en.md`（40 KB）、`使用指南.md`（31 KB） |
| 版本控制 | **git 仓库**，`main` 跟踪 `origin/main`（GitHub: `zhangziluo/wreader`），首个提交 `7ecc3eb` |
| CLI 冒烟 | `wreader --version` → `wreader 0.1.0` |
| 编译 | `py_compile` 全部 16 个文件通过 |

## 已完成（可用的功能）

### 书库与导入
- 递归导入 txt / epub；`chardet` 探测编码，BOM 认 UTF-8/16/32 且**宽编码优先**
  （UTF-32 的 BOM 以 UTF-16 的 BOM 开头），解码失败降级为 `(replaced)` 而不崩。
- 有 Calibre 的 `ebook-convert` 就用它，没有则用内置提取器（只取正文文本）。
- 文件名解析：支持 `《书名》（校对版全本）作者：某人.txt`，只剥**尾部**括号注释
  （`书名（中）下册` 保持完整）；全角/半角冒号都认。
- 去重：`book_id` = 正文 SHA-1 前 12 位；坏文件只进 `failed` 列表，不中止整批。
- 章节识别：`parse_chapters`（`第一章/第1章/卷X·…` 等），起点写入 `chapters[].line_start`。

### 阅读器（curses）
- 三种视图：中文 / 英文 / 双语对照（`l` 循环、`c` 直达中文）；切视图时按需翻译，原文语言零成本。
- 按键：`q Q Ctrl-C` 退出、`j/空格/回车/↓/PageDown` 下翻、`k/↑/PageUp` 上翻、`g` 跳行、
  `G` 到末尾、`[` `]` 章节跳转、`/` 搜索、`n` 下一个命中、`b` 书签、`l` 视图、`c` 中文、
  `t` 翻当前屏（不缓存）、`T` 翻整章（写缓存）、`v` 查词入库。
- 状态栏两行：倒数第二行由 `reader.status_bar_format` 拼接（12 个可用 token，未知 token 跳过），
  最后一行是消息/快捷键提示；屏幕最左一列是书签栏（`★`）。
- **按终端宽度自动换行**（2026-09 新增），CJK 按 2 列宽计算，英文按词断行。
- **配色跟随终端主题与透明背景**（2026-09 新增）。
- 生词下划线、搜索高亮（当前命中反色、其它命中加粗）、章节超 30 分钟提醒看中文。
- 进度落库：`q`/`Ctrl-C` 都保存位置、书签、本次时长；`auto_save_interval` 默认 60 秒兜底。

### 翻译
- 两个后端：`google`（deep-translator）、`deepseek`（HTTP + SSE 流式）。
- 三个入口：单句/单词（`translate_text`）、视口（`translate_viewport`）、整章（`translate_chapter`）。
- 按章缓存到 `cache/<book_id>/ch{N}_en.txt` + `ch{N}_bilingual.txt`，二次访问零成本、可断点续翻。
- `normalize_language()`：`zh` → `zh-CN` 等归一化，避免 deep-translator 在发请求前就报错。
- 段落（而非行）为翻译单位，双语视图能一段对一段。

### 生词本
- `add_word` 对同词是**刷新**而非重复插入；`book`/`chapter`/`context`/`date_added` 完整记录。
- 兼容旧 `{"words": [...]}` 包装与 `book_title`/`created` 旧字段名。
- 模糊搜索（拼写/释义/例句）、分页、`--review` 乱序复习、`--export anki` 制表符导出。
- 阅读器内 `v` 查词；`auto_add_on_mark=false` 时弹确认小窗。

### 统计与成就
- 指标：总时长、今日/本周/本月、夜间阅读（含跨午夜重叠计算）、单次最长、连续天数。
- 连续天数规则：一天 ≥ 30 分钟才算有效；**当天永远算数**（它正要变成事实）。
- 热力图（`heatmap` 单元格 + `heatmap_weeks` 整周对齐）与 ASCII 进度条。
- 10 个成就，条件为 `指标 比较符 数字` 表达式，定义在 `wreader/data/achievements.json`，
  可被 `$WREADER_HOME` 下的同名文件覆盖；解锁时播动画横幅，`stats.achievement_sound` 可静音。

### 配置
- `settings.toml`，5 个 section / 21 个键，由 `SCHEMA` 单一事实来源驱动（默认值、类型、写序、行尾注释）。
- `wreader config <section.key> [value]`、`--path`、`--reset`；类型不合法会明确报错。
- 旧扁平 `config.json` 自动折叠进 section 并备份为 `config.json.bak`。
- 旧数据目录 `~/.nr` 首次运行时整体搬迁到 `~/.wreader`。

### 工程质量
- 474 → **494** 项自动化测试（全离线、每测试独立 `tmp_path`）。
- pyright 0 告警；`.vscode/settings.json` 与 `[tool.pyright]` 双轨配置。
- 16 个 Python 文件**逐条逻辑语句上方都有口语化中文注释**（2026-09）。
- 校验脚本已从 `/tmp` 搬进 **`tools/`**（2026-09-22）：`check_docs.py`、`check_doc_numbers.py`、
  `check_comments.py`、`verify_wrap.py`、`verify_draw.py`、`verify_colors.py` + `tools/README.md`。
  统一从 `__file__` 推算仓库根（任意目录可跑）、退出码 0/1（可接 CI），并纳入 `[tool.pyright]`。
- **已 git 化并推送到 GitHub**（2026-09-22）：首个提交 `7ecc3eb`，32 文件 / 15,843 行，
  `main` 跟踪 `origin/main`；`book/`（367 MB 真实电子书样例）被 `.gitignore` 挡在版本控制之外。
  从此"只加注释、不动逻辑"这类改动可以用 `git diff` 直接证明。

## 待办

### 高优先级
1. ~~更正 `README.md` / `README.en.md` 的过期信息~~ → **已完成（2026-09-22）**：
   8 个源码文件的行数、测试总数 **494**、`test_reader.py` **115** 全部按实测改对；
   「已知问题」里补记了自动换行 / 按显示列数 / 配色跟随终端 三项修复；
   两份 README 都新增了「新开一个终端后怎么用 wreader / Using wreader in a new terminal」一节。
   顺手改正一处旧笔误：那份"已解决"清单原文写"六条"，实际列了 7 条
   （英文版写的是 Seven，是对的），现已扩成 **十条**，中英两版一致。
   同性质的守卫见 #3（把校验脚本搬进仓库，以后改代码就能自动查出这类数字漂移）。

### 中优先级
2. **实现 `reader.theme`**（当前是预留项，改了没效果）：在 `_init_colors()` 之后
   按主题 `init_pair()`，并把正文/状态栏/书签/高亮的属性改为 `color_pair(N) | A_*`。
   注意保持 `use_default_colors()` 带来的透明背景能力（正文背景建议用 `-1`）。
3. ~~把 `/tmp` 里的校验脚本搬进仓库~~ → **已完成（2026-09-22）**：6 个脚本住进 `tools/`
   （`check_docs.py` / `check_doc_numbers.py` / `check_comments.py` /
   `verify_wrap.py` / `verify_draw.py` / `verify_colors.py`），外加 `tools/README.md`。
   全部改成从 `__file__` 推算仓库根（任意目录可运行）、退出码 0/1（可接 CI），
   并把 `tools` 加进了 `[tool.pyright]` 的 include。
   ⚠️ 过程中发现一个**旧脚本的 bug**，见 #4。

### 低优先级
4. **决定「注释覆盖率」怎么处理**（2026-09-22 新发现，需要拍板）：
   严格按「每条逻辑语句上方一行注释」测，`wreader/` + `tests/` 仍有 **2054** 条不满足
   （`reader.py` 357、`translator.py` 189、`library.py` 163 …）。三个选项：
   (a) 把约定口径改成"一段逻辑配一段中文注释"，不再声称 100%
   —— **文档已按 (a) 校正**（`projectbrief.md` / `.clinerules` / 本条）；
   (b) 用 `tools/check_comments.py --strict <文件>` 做**增量门禁**，碰到哪个文件就让它达标；
   (c) 全量补齐 2054 处 —— 工作量极大，且大量只是给 `return` / `assert` 补一句废话，不建议。
5. 给 `library.py` 补 `__all__`（目前唯一没有的模块）。
6. **标签的命令行入口**：`books[].tags` 与 `wreader search '#tag'` 都已支持，
   但只能手改 `library.json` 才能加标签。
7. `progress` 数值不做类型强制转换（手写成 `"current_line": "12"` 也能读，
   因为消费方都用 `int(...)` 兜住），但不会被自动改回数字。可考虑在 `save_library` 时规整。
8. 译文缓存文件名固定 `_en` 后缀是历史包袱（容器里装的是 `target_language` 的结果），
   未来若加 `zh-CN` 以外目标语言可考虑改名为 `ch{N}_<lang>.txt`，但需要迁移逻辑。

## 已知问题（当前版本真实限制）

| 问题 | 影响 | 备注 |
| --- | --- | --- |
| 样例书 `book/` 不在版本控制里 | 新克隆下来没有现成的样书可导入 | 实测 367 MB、单文件最大 147 MB，超 GitHub 单文件 100 MB 硬上限，已 `.gitignore` |
| `reader.theme` 未实现 | 改了没效果 | 文档已标注"预留" |
| 无 CLI 加标签入口 | 只能手改 `library.json` | 搜索已支持 `#tag` |
| EPUB 内置提取器有损 | 图片/脚注/复杂排版丢失 | 装了 Calibre 则用 `ebook-convert` |
| `read` 只能真 TTY | 重定向即报错 | 报错文案已测 |
| Windows 需 `windows-curses` | 多一个可选依赖 | `pip install -e ".[windows]"` |
| `progress` 数值不强制转型 | 字符串值也能读但不会自动改回数字 | 消费方已用 `int()` 兜底 |
| 终端自身限制透明 | 若终端在备用屏幕禁用透明度，应用无法绕过 | 属终端设置，非应用缺陷 |

## 决策演变（记录为什么变成现在这样）

| 时间 | 决策 | 原因 |
| --- | --- | --- |
| 早期（`nr`） | 工具叫 `nr`，数据在 `~/.nr`，配置是扁平 `config.json` | — |
| 改名 `wreader` | 数据目录一次性搬迁到 `~/.wreader`，旧配置折叠进 `settings.toml` 并备份 | 不丢用户数据；旧环境变量留作兜底 |
| 配置重构 | 改为 `SCHEMA` 驱动的 section + TOML | 可读性、类型校验、加项成本最低 |
| 引入双语视图 | 一个源行可占多条屏幕行（原文 + 译文） | 段落级对照比行级对照好读得多 |
| 翻译缓存以章为单位 | 而非整本或每屏 | 省钱、可续翻，又不必整本翻完才能读 |
| 补测试前置重构 | `reader.py` 拆出 `Pager` 与纯函数；`translator` 变可注入后端 | 让分页/翻译逻辑脱离 TTY 与网络可测 |
| 上一轮修已知问题 | 修掉 `translator.__all__` 幽灵名字、`zh`→`zh-CN` 归一化、BOM/宽编码、文件名解析、pyright 告警 | 都是补测试时暴露出来的 |
| **2026-09-22** | 全仓加逐行中文注释 | 提升可读性与可维护性；逻辑零改动 |
| **2026-09-22** | 阅读区自动换行，宽度全部改按显示列数 | 窄终端/长句原先被静默截断；CJK 用 `len()` 一定算错 |
| **2026-09-22** | 加 `_init_colors()`（`start_color` + `use_default_colors`） | 原先从未初始化颜色，正文背景被锁成不透明黑底 |
| **2026-09-22** | `git init -b main` + 首个提交 `7ecc3eb`，推送到 GitHub `zhangziluo/wreader` | 补上版本控制：注释改造这类大范围改动此后可用 `git diff` 证明，并具备回退能力 |
| **2026-09-22** | `.gitignore` 忽略 `book/` | 367 MB 真实电子书样例，单文件最大 147 MB 超 GitHub 单文件 100 MB 上限，且不属于分发包 |
| **2026-09-22** | 远端走 HTTPS 而非 SSH | 本机 SSH key 未注册到 GitHub，而 Keychain 里已有 `github.com` 凭证，HTTPS 零交互可推 |
| **2026-09-22** | 校验脚本从 `/tmp` 搬进 `tools/`，并纳入 `[tool.pyright]` | `/tmp` 会被系统清理；进仓库才可能挂 CI、也才有人看得见 |
| **2026-09-22** | 把"注释全覆盖"从**事实**改成**目标**（口径：一段逻辑配一段中文注释） | 严格测量发现 `wreader/`+`tests/` 还有 2054 条差距；早先的 `TOTAL: 0` 是脚本 bug 造成的假绿，留着旧说法会误导下个会话 |
| **2026-09-22** | 文档（README / 使用指南）开始有**自动守卫**：锚点、数字都有脚本对拍 | 手写数字必然漂移，这次就一次抓到 6 处陈旧数字 |

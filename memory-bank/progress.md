# Progress — 已完成 / 待办 / 已知问题

> 项目整体进度与决策演变。最后更新：**2026-09-23**。

## 当前状态

| 维度 | 状态 |
| --- | --- |
| 版本 | `0.1.0`（Pre-Alpha，`Development Status :: 2 - Pre-Alpha`） |
| 测试 | **683 passed**，全离线、不碰真实数据，约 4~25 秒 |
| 类型检查 | `npx pyright` → **0 errors, 0 warnings, 0 informations**（`wreader/`、`tests/`、`tools/` 都纳入） |
| 注释覆盖 | `tools/check_comments.py` 实测：`wreader/` + `tests/` 仍有 **3405** 条语句上方没有紧邻注释行（口径与处置见待办 #4） |
| 文档 | `README.md`（中文主文档，44 KB）、`README.en.md`（46 KB）、`使用指南.md`（38 KB）；数字由 `tools/check_doc_numbers.py` 自动对拍 |
| 版本控制 | **git 仓库**，`main` 跟踪 `origin/main`（GitHub: `zhangziluo/wreader`），**54 个跟踪文件**（提交数每次提交都会变，故不写死） |
| CLI 冒烟 | `werd --version` → `werd 0.1.0` |
| 编译 | `py_compile` 全部 **36 个** .py 通过（wreader 17 + tests 10 + tools 9） |
| 开发期校验 | `tools/` 全绿：文档锚点 OK、数字对拍 ALL OK、折行 40077、绘制 420、鼠标 8 项、笔记 5 项、翻译 4 项 |

## 已完成（可用的功能）

### 书库与导入
- 递归导入 txt / epub；`chardet` 探测编码，BOM 认 UTF-8/16/32 且**宽编码优先**
  （UTF-32 的 BOM 以 UTF-16 的 BOM 开头），解码失败降级为 `(replaced)` 而不崩。
- 有 Calibre 的 `ebook-convert` 就用它，没有则用内置提取器（只取正文文本）。
- 文件名解析：支持 `《书名》（校对版全本）作者：某人.txt`，只剥**尾部**括号注释
  （`书名（中）下册` 保持完整）；全角/半角冒号都认。
- 去重：`book_id` = 正文 SHA-1 前 12 位；坏文件只进 `failed` 列表，不中止整批。
- 章节识别：`parse_chapters`（`第一章/第1章/卷X·…` 等），起点写入 `chapters[].line_start`。
- **`werd continue`**（2026-09-22 新增）：按 `progress.last_read` 倒序列出**最近打开阅读的三本**书，
  表格复用 `_book_table`（带 id），把 id 抄给 `werd read` 就能续读；一本都没读过时给提示并返回 `0`。
  纯函数在 `library.recent_books(limit=3)`：跳过 `last_read` 为空的书，时间戳是定长 ISO 字符串，
  所以直接按字典序倒排（不解析 datetime）。

### 目录 / 章节跳转（2026-09-23 新增）
- `wreader/toc.py`：章节提取（内置正则 + `toc.patterns` 自定义）、epub `nav.xhtml` / `toc.ncx` 解析、
  百分比、可重建缓存（`~/.wreader/cache/<book_id>_toc.json`，按转换后正文的 mtime 失效）。
- 阅读器按 `Tab` 呼出**目录浮层**（右侧 40%、左侧正文变暗）：`↑↓` / `j` / `k` 选章、`回车` 跳转、
  `/` 实时过滤、`q` / `Esc` 关闭。
- `werd toc <book_id> [--rebuild]`：命令行查看 / 强制重建目录。
- 跳转仍走 `Pager.move_to(line)`（与 `g` / 搜索 / `[` `]` 同一套行号坐标）。

### 阅读器（curses）
- 三种视图：中文 / 英文 / 双语对照（`l` 循环、`c` 直达中文）；切视图时按需翻译，原文语言零成本。
- 按键：`q Q Ctrl-C` 退出、`j/空格/回车/↓/PageDown` 下翻、`k/↑/PageUp` 上翻、`g` 跳行、
  `G` 到末尾、`[` `]` 章节跳转、`/` 搜索、`n` 下一个命中、`b` 书签、`l` 视图、`c` 中文、
  `t` 翻当前屏（不缓存）、`T` 翻整章（写缓存）、`v` 查词入库、`m` 标记、`o` 笔记面板。
- 状态栏两行：倒数第二行由 `reader.status_bar_format` 拼接（12 个可用 token，未知 token 跳过），
  最后一行是消息/快捷键提示；屏幕最左一列是书签栏（`★`）。
- **按终端宽度自动换行**（2026-09 新增），CJK 按 2 列宽计算，英文按词断行。
- **配色跟随终端主题与透明背景**（2026-09 新增）。
- **翻页按「屏幕行」精确推进**（2026-09-22 修跳行 bug + 段内偏移）：步长 = `round(page_scroll_step × 正文区行数) − page_overlap`，
  单位是**屏幕行**；长段落被终端折成多行时，翻页跟着实际占用的屏幕行算。
  屏顶坐标是 `(源行号, 段内偏移)`，所以**一屏装不下的长段落会分多屏读完**，
  下一页从段落中间接着显示（既不跳过也不重复）。段内偏移是显示态、**不落库**。
  终端尺寸由 `_draw` 每帧填入 `Pager.viewport_rows/width`，窗口改了下一帧就生效。
  设 `page_overlap=0` 则一次翻满整屏（默认保留 3 行上下文）。
- **鼠标滚轮 / 触摸拖动逐行滚动**（2026-09-22 新增）：滚轮一格 1 行（`reader.wheel_scroll_step`）、
  手指拖动 1 行 = 1 行（`reader.touch_scroll` 可关）；向上滑往后读、向下滑往前看。
  为此在 `_run` 里开了鼠标上报，并把 `curses.mouseinterval` 设为 0。
  ⚠️ 逐行滚动不经过翻页路径，所以**不受翻页重叠影响**（它本来就是一行一行走，上下文天然连着）。
- 生词下划线、搜索高亮（当前命中反色、其它命中加粗）、章节超 30 分钟提醒看中文。
- 进度落库：`q`/`Ctrl-C` 都保存位置、书签、本次时长；`auto_save_interval` 默认 60 秒兜底。

### 笔记（标记模式 + 笔记面板，2026-09-23 新增，Phase 1+2 = 只有 UI）
- **标记模式** `m`：光标变成反色方块，`h/j/k/l` 或方向键扩展选区（`A_REVERSE` 高亮），
  `y` 把选中的文字复制进引用缓冲区（超 2000 字截断并提示），`Esc` 取消。
  **只在一屏内选字、绝不翻页**；坐标是 `(屏幕行, 行内字符下标)`，进 `Pager.viewport`。
- **笔记面板** `o`：占屏幕下方 25%（正文区相应缩小），两个 `curses.newwin` 子窗口 ——
  引用区（只读、`A_DIM`、`> ` 前缀）显示 `y` 复制的内容，编辑区是 `curses.textpad.Textbox`
  （回车换行、退格、左右光标）；`Tab` 切焦点、`Ctrl+S` 保存、`Esc` 关闭。
  折叠时底部提示行显示 `📝 N条笔记 | 按o展开`。
- 实现要点：模态小循环（与目录浮层同款、不另开线程）；**不调用阻塞的 `Textbox.edit()`**，
  逐键喂 `do_command()`；`_note_validate` 把回车映射成 `NL`（换行）而非 `Ctrl-G`（提交）；
  `_run` 里 `_disable_flow_control()` 尽力关掉 `IXON`（否则 `Ctrl+S` 被行规程吞掉）。
- ⚠️ **笔记只存内存**（`Pager.notes`），退出即失；落盘是下一步（见待办高优先级 #1）。
- ⚠️ 编辑区中文输入依赖 IME（`do_command` 只认 `curses.ascii.isprint`），实际以英文 / 拼音为主。

### 翻译（2026-09-23 重构为可插拔引擎）
- **引擎层在 `wreader/translate/`**：每个厂商一个模块，共 8 个文件 1317 行 ——
  `base.py`（`Translator` ABC + 凭证/可选包检查）、`google.py`（默认，免密钥）、`baidu.py`（MD5）、
  `youdao.py`（SHA-256）、`tencent.py`（TC3-HMAC-SHA256）、`deepseek.py`（chat completions + SSE）、
  `local.py`（Argos，可选依赖）、`__init__.py`（注册表 + 工厂）。
  **加一个厂商 = 一个模块 + `ENGINES` 登一行**，连配置向导都会自动适配。
- **`translator.py` 变成"引擎之上的机器"**：保留 `Backend` 接口与
  `EngineBackend` 适配器（错误映射：引擎异常 → `TranslationError` / `TranslationUnavailable`），
  加上章节缓存 / 分批 / 段落映射 / 双语视图 / `werd translate`，以及新的 `engine_ready()` 前置检查。
- 三个入口不变：单句/单词（`translate_text`）、视口（`translate_viewport`）、整章（`translate_chapter`）；
  按章缓存 `cache/<book_id>/ch{N}_en.txt` + `ch{N}_bilingual.txt`，二次访问零成本、可断点续翻。
- `normalize_language()`：`zh` → `zh-CN` 归一化；每个引擎再用自己的 `language_codes`
  映射成厂商写法（百度 `zh`、有道 `zh-CHS`、Argos `zh`）。
- 段落（而非行）为翻译单位，双语视图能一段对一段。
- **配置**：新增 `[translate]` 段（`engine` + 各厂商密钥，11 键）；`werd config translate` 交互式向导
  （列引擎 → 逐条问密钥 → 落盘 → 当场自查）；旧的 `[translator] backend` 仍作为回退，**零迁移**。
- **阅读器 `t`**：翻译当前屏段落，译文在底部弹窗显示 3 秒（任意键提前关）；引擎没配好时
  只提示"运行 `werd config translate`"，不发请求。
- **依赖**：`argostranslate` 放进 `local` extra（模型动辄几百 MB）；`requests` / `deep-translator`
  仍是必装（默认引擎就靠后者）。

### 生词本
- `add_word` 对同词是**刷新**而非重复插入；`book`/`chapter`/`context`/`date_added` 完整记录。
- 兼容旧 `{"words": [...]}` 包装与 `book_title`/`created` 旧字段名。
- 模糊搜索（拼写/释义/例句）、分页、`--review` 乱序复习、`--export anki` 制表符导出。
- 阅读器内 `v` 查词；`auto_add_on_mark=false` 时弹确认小窗。

### 统计与成就
- 指标：总时长、今日/本周/本月、夜间阅读（含跨午夜重叠计算）、单次最长、连续天数。
- 连续天数规则：一天 ≥ 30 分钟才算有效；**当天永远算数**（它正要变成事实）。
- 热力图（`heatmap` 单元格 + `heatmap_weeks` 整周对齐）与 ASCII 进度条。
- **事件驱动成就引擎**（`wreader/achievements.py`，2026-09-23 Phase 1）：定义 **28** 条
  （`wreader/data/achievements.json`，可被 `$WREADER_HOME` 下的同名文件覆盖），条件是
  `指标 比较符 数字` 表达式；解锁记录写在 `~/.wreader/achievements.json`（纯 JSON + 文件锁，
  坏文件自动改名 `.broken` 重建）。事件：`daily_open`（每次启动）、`session_end`（退出阅读，
  带时长与读过的行区间）、`book_add`（`werd import`）、`progress_update`/`book_finish`/
  `word_add`/`geo_change`、以及纯重算的 `check`。
- **字数按行号区间去重**（中文一字=1、英文一词=1、标点不计），同一页读两遍不重复累加。
- 解锁时播动画横幅，`stats.achievement_sound` 可静音；`werd achievements` 按分类显示进度条。

### 配置
- `settings.toml`，5 个 section / 24 个键，由 `SCHEMA` 单一事实来源驱动（默认值、类型、写序、行尾注释）。
- `werd config <section.key> [value]`、`--path`、`--reset`；类型不合法会明确报错。
- 旧扁平 `config.json` 自动折叠进 section 并备份为 `config.json.bak`。
- 旧数据目录 `~/.nr` 首次运行时整体搬迁到 `~/.wreader`。

### 工程质量
- **一键安装脚本 `install.sh`**（2026-09-22 新增，**219 行** bash）：`git clone` → `cd` → `./install.sh`
  三条命令装完。脚本幂等（用 `-x .venv/bin/python` 判断 venv 是否可用，坏了会重建；别名按行判重不重复追加），
  全程用 `.venv/bin/python -m pip` 而**不 activate**（守住"不污染 PATH"这条约定），
  并自动往 `~/.bashrc` / `~/.zshrc` 写别名 —— 装完重启终端即可用。
  选项：`--dev`（多装 pytest）/ `--no-alias`（不碰 rc）/ `--help`；用 `sh install.sh` 跑会自动 `exec bash` 转交。
- **595** 项自动化测试（全离线、每测试独立 `tmp_path`）。
- pyright 0 告警；`.vscode/settings.json` 与 `[tool.pyright]` 双轨配置（`wreader/` + `tests/` + `tools/`）。
- `wreader/` 8 个 + `tests/` 8 个 Python 文件在 2026-09 大幅补过一轮口语化中文注释；
  ⚠️ 但**严格口径下没做到 100%**（`tools/check_comments.py` 实测还有 **2777** 条语句上方没有紧邻注释行），
  实际遵循的风格是"一段逻辑配一段中文注释"，详见待办 #4。
- 校验脚本已从 `/tmp` 搬进 **`tools/`**（现共 **8** 个）：`check_docs.py`、`check_doc_numbers.py`、
  `check_comments.py`、`verify_wrap.py`、`verify_draw.py`、`verify_colors.py`、`verify_mouse.py`、
  `verify_notes.py`（2026-09-23 新增，真 pty 验证笔记流程）+ `tools/README.md`。
  统一从 `__file__` 推算仓库根（任意目录可跑）、退出码 0/1（可接 CI），并纳入 `[tool.pyright]`。
- **已 git 化并推送到 GitHub**（2026-09-22）：首个提交 `7ecc3eb`，32 文件 / 15,843 行，
  `main` 跟踪 `origin/main`；`book/`（367 MB 真实电子书样例）被 `.gitignore` 挡在版本控制之外。
  从此"只加注释、不动逻辑"这类改动可以用 `git diff` 直接证明。

## 待办

### 高优先级
0. **笔记落盘（Phase 3）**——`m` 标记 + `o` 面板已可用，但 `Ctrl+S` 存的笔记只在
   `Pager.notes`（内存）里，退出即失。要做：新增 `wreader/notes.py`（纯函数 + 纯文本），
   存 `~/.wreader/notes/<book_id>.json`，字段 `{"line", "quote", "text", "created"}`；
   `open_reader` 加载、退出时写回。⚠️ **只写源行号**（屏幕行随终端宽度变化，不能当坐标）。
1. ~~更正 `README.md` / `README.en.md` 的过期信息~~ → **已完成（2026-09-22）**：
   8 个源码文件的行数、测试总数 **494**、`test_reader.py` **115** 全部按实测改对；
   「已知问题」里补记了自动换行 / 按显示列数 / 配色跟随终端 三项修复；
   两份 README 都新增了「新开一个终端后怎么用 werd / Using werd in a new terminal」一节。
   顺手改正一处旧笔误：那份"已解决"清单原文写"六条"，实际列了 7 条
   （英文版写的是 Seven，是对的），现已扩成 **十条**，中英两版一致。
   同性质的守卫见 #3（把校验脚本搬进仓库，以后改代码就能自动查出这类数字漂移）。

### 高优先级
0b. **成就引擎 Phase 2 / Phase 3**（用户给了完整 ~60 条规格，Phase 1 已完成 28 条）。
   - **Phase 2（操作彩蛋 / 难度挑战）**：需要**阅读器内的实时事件**——
     `key`（空格连击=手速达人、连续翻页=翻页永动机、全程方向键=方向键怀旧、`t` 连打=翻译狂魔）、
     `resize`（≤40 列并读满 5 分钟=极限尺寸、≤60 列读完一章=窄屏挑战）、
     以及 5 秒的**屏内通知**（现在解锁只在退出后的普通终端里庆祝）。
     另外要新增两个前置功能：阅读器**帮助页**（帮助迷）与**意外中断自动恢复**流程（我反悔 / 恢复大师）。
   - **Phase 3（地理 / 环境）**：`geo.py`（ip-api.com，1 小时缓存、**必须可注入且离线降级**）
     + `env.py`（云主机 / WSL / tmux / 可编辑安装探测）→ 环游亚欧非美大洋、世界公民、百年世仇、
     节日读者、名字彩蛋（`werd --werd` / `werd word`）、成就猎人（查看成就页 >10 次）。
   - 规格原文里的 `~/.nr/achievements.json` **是改名前的旧路径**，本项目一律用 `~/.wreader`（已定）。

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
   严格按「每条逻辑语句上方一行注释」测，`wreader/` + `tests/` 仍有 **2279** 条不满足
   （`test_reader.py` 447、`reader.py` 399、`translator.py` 189、`library.py` 165 …）。
   三个选项：
   (a) 把约定口径改成"一段逻辑配一段中文注释"，不再声称 100%
   —— **文档已按 (a) 校正**（`projectbrief.md` / `.clinerules` / 本条）；
   (b) 用 `tools/check_comments.py --strict <文件>` 做**增量门禁**，碰到哪个文件就让它达标；
   (c) 全量补齐 2279 处 —— 工作量极大，且大量只是给 `return` / `assert` 补一句废话，不建议。
5. 给 `library.py` 补 `__all__`（目前唯一没有的模块）。
6. **标签的命令行入口**：`books[].tags` 与 `werd search '#tag'` 都已支持，
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
| 笔记只存内存 | 退出阅读器后 `Ctrl+S` 存的笔记全部消失 | Phase 1+2 只做 UI，落盘见待办高优先级 #0；已写进两份 README 的「已知问题」 |
| 笔记编辑区中文输入受限 | 依赖系统 IME，实际以英文 / 拼音为主 | `curses.textpad.do_command` 只认 `curses.ascii.isprint`，宽字符被跳过 |
| 翻译引擎没有重试 / 退避 | 一次网络抖动就浪费一整章（Google 免费端点尤其明显） | 失败仍按 `TranslateError`（单章）/ `TranslateUnavailable`（整本中止）处理；要加需做成可配置，见 activeContext 待办 #8 |
| 只有百度有可复现的外部签名向量 | 腾讯云最终签名只能靠结构断言 + 自洽性验证，改动后无外部对拍 | 官方文档把 SecretId/SecretKey 打码了；有道/腾讯都没找到可复现的公开向量 |
| 本地引擎需自备语言包 | 选了 `local` 但没装语言包时不可用 | `available()` 会提前拦下并提示装包命令，不让它到第一次翻译才炸 |
| 终端自身限制透明 | 若终端在备用屏幕禁用透明度，应用无法绕过 | 属终端设置，非应用缺陷 |
| IDE 里有指向**仓库根 `cli.py`** 的幽灵告警（该文件不存在） | 会让人照报错去改 `wreader/cli.py`，白改 | 来源是 ㉒ 坑 #1 那份 143 行野生碎片；两次复现见 activeContext ㉔/㉕。**判据：报错路径 `ls` 不到 → 直接忽略，改看 `npx pyright` + `pytest`** |

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
| **2026-09-22** | 把"注释全覆盖"从**事实**改成**目标**（口径：一段逻辑配一段中文注释） | 严格测量发现 `wreader/`+`tests/` 还有 2054 条差距（后随代码增加涨到 **2279**）；早先的 `TOTAL: 0` 是脚本 bug 造成的假绿，留着旧说法会误导下个会话 |
| **2026-09-22** | 文档（README / 使用指南）开始有**自动守卫**：锚点、数字都有脚本对拍 | 手写数字必然漂移，这次就一次抓到 6 处陈旧数字 |
| **2026-09-22** | 加鼠标滚轮 + 触摸拖动逐行滚动（Termux 滑动原本完全没反应） | 用户反馈手机上翻页丢上下文；先在真 pty 里灌鼠标序列验证，才敢动代码 |
| **2026-09-22** | 滚轮下**不做位猜测**（拿不到 `BUTTON5_PRESSED` 就放弃该方向） | 猜出来的位正好撞上 `BUTTON_SHIFT`，会把 shift+点击误判成滚轮；宁可少一个方向 |
| **2026-09-22** | 翻页加"上下文重叠"：`step_lines` 减去 `reader.page_overlap`（默认 3），做成可配置项而非写死 3 | 用户要求"翻页时上下保留三行前面的文字"；项目既有约定是阅读行为都走 `SCHEMA` 配置，写死会留下魔数 |
| **2026-09-22** | 翻页改为**按屏幕行**推进（`viewport_rows` + `next_position`/`previous_position`，复用 `visible_rows`/`_wrap_line`） | 用户报告长段落翻页会跳行：原步长是"文本行数"，而长段落会被折成多屏行，一次翻页跳过的内容远超一屏。**拒绝**了"用 `ceil(len(text)/width)` 估算屏幕行"的提案 —— 汉字占 2 列，`len()` 必然算错，且会劈单词、漏掉双语视图 |
| **2026-09-22** | `reader.page_height` 降级为"拿不到终端尺寸时的回退值" | 翻页基准改成真实正文区高度后它不再参与真实路径；保留它是为了不破坏旧配置与既有测试，但文档必须讲清楚它已不是翻页基准 |
| **2026-09-22** | 屏顶坐标升级为 `(源行号, 段内偏移)`：`Pager.line_offset` 只作**显示态**，`current_line` 仍只写源行号 | 只记源行号时，一屏中途被折行截断的"半截段落"在下一页会被整个跳过（现象：段落突然少了半页）。改成两元组后长段落能被一屏一屏完整读完。**不落库**是为了守住「行号坐标唯一」这条硬约束（书签 / 章节 / 翻译缓存都依赖它），代价是重开书从行首开始 |
| **2026-09-22** | 新增 `werd continue` 列"最近打开阅读的三本书" | 用户诉求是「重启之后一到两行就能开 werd 看书」：原先必须 `werd list` 找 id 再 `werd read`。`progress.last_read` 其实**早就在退出阅读器时写好了**，缺的只是一个入口。**故意只"列 id"、不自动打开第一本** —— 最近读的不一定是此刻想读的，程序不该替用户猜；而且"列 id + 抄 id"正好就是用户要的「一到两行」 |
| **2026-09-22** | 新增 `./install.sh`，把安装压成「三行命令」（clone → cd → install.sh） | 用户诉求：简化安装流程。原先要 `venv` → `activate` → `pip install -e .` 三步，且"重启后能用 werd"还得**另外**配别名（散在两节文档里）。脚本把这些串成**一条幂等命令**。别名写入做成**自动但可跳过**（`--no-alias`），而不是不做 —— 用户明确选了"自动写入、装完重启即可用"；同时保留"手动安装"作为 Windows / 脚本跑不动时的退路 |
| **2026-09-23** | CLI 命令改名 `wreader` → `werd`（`pyproject.toml` 的 console script + `cli.py` 的 `prog` + `install.sh` 的别名与路径 + 全部文档示例）；**包名 / 仓库名 / 数据目录仍叫 `wreader`** | 用户诉求：命令行太长不好敲。刻意把"命令名"与"包名 / 数据目录"分开 —— 数据目录 `~/.wreader`、环境变量 `WREADER_HOME`、`python -m wreader.cli`、`from wreader import` 一律不动，换来的好处是**零数据迁移**、旧配置与既有测试照常可用；真正变的只有用户敲的那个词 |
| **2026-09-23** | **笔记键位用 `m`（标记）/ `o`（面板），而不是规格里的 `v` / `n`** | 规格给的 `v` 与 `n` **已被占用**（`v` = 查词入库、`n` = 下一个搜索命中），且都写在底部提示栏与三份文档里。让用户拍板后选**零破坏**：保留现有键，新功能用两个空闲键。规格里"`j`/`Tab` 目录跳转"同样是笔误（`j` = 下一页）—— **规格可能与现状不一致，动手前先对一遍现有键位** |
| **2026-09-23** | 标记坐标用 **`(屏幕行, 行内字符下标)`**，进 `Pager.viewport`（`_draw` 每帧刷新）；标记**只在一屏内选字、绝不翻页** | `viewport` 就是 `visible_rows()` 的返回值，所以高亮与取词天然对齐折行与汉字 2 列宽（列偏移用 `_text_width` 累加），不需要另造一套「屏幕 ↔ 源文」映射。限制在一屏内省掉了滚动时坐标失效的整类问题 |
| **2026-09-23** | 笔记面板做成**模态小循环**（同目录浮层），并**逐键调 `Textbox.do_command()` 而非 `Textbox.edit()`** | `edit()` 是阻塞循环，`Tab`/`Ctrl+S`/`Esc` 没法自己拦；逐键喂 `do_command` 既复用了 Textbox 现成的 Emacs 键绑定（退格/左右光标/回车换行），又把主循环控制权留在自己手里，且**不另开线程**（符合"面板渲染在主循环里"的要求）。`_note_validate` 把回车映射成 `NL` 而**不映射 `Ctrl-G`**，回车因此永远不会意外提交 |
| **2026-09-23** | `_run` 里新增 `_disable_flow_control()`（尽力关 `IXON`/`IXOFF`） | `curses.wrapper` 只调 `cbreak()`，`IXON` 仍开着 → 行规程把 `Ctrl-S`（XOFF）吃掉，保存键永远到不了程序。只在 POSIX 生效，Windows / 非 tty 静默降级；`endwin()` 负责还原，不需要手工回滚。**这是"真 pty 才验得出来"的那类问题**（单测不会经过行规程） |
| **2026-09-23** | 新增 `tools/verify_notes.py`（真 pty 端到端），并把子窗口创建抽成 `reader._sub_window()` | 第一版直接写 `stdscr.newwin(...)`，`FakeStdscr` 恰好也有 `newwin` 所以**单测全绿**，但真 curses 的 window 对象**只有 `derwin`** —— 真 pty 里立刻 `AttributeError`。抽出 `_sub_window()` 后生产用 `curses.newwin`、测试替换成假窗口。**教训：假窗口越像真的，越会掩盖真 API 的差异；UI 改动必须过真 pty** |

| **2026-09-23** | 翻译改成**可插拔引擎层** `wreader/translate/`（base + google/baidu/youdao/tencent/deepseek/local），`translator.py` 保留缓存/分批/段落/视图/CLI 只做委托 | 用户拍板"重构"而非另起一套或整体重写：项目已有完整的章节缓存与双语视图机器，重写等于把这些再赌一次；并行两套则会让"到底谁在翻译"说不清。**`translate/` 刻意不 import `config`/`translator`**（凭证由调用方传进来），既避免循环导入，也让工厂能脱离终端/网络单测 |
| **2026-09-23** | 新增 `[translate]` 段（engine + 各厂商密钥），`[translator] backend` 降级为"engine 为空时的回退" | 规格要求"新增 `[translate]` 配置段"。**一个键都没删**换来**零迁移**：老 settings.toml 里的 `backend` / `deepseek_*` 照常生效（`credential_values()` 会把没写的键回退到旧字段）。代价是两处能选引擎，所以文档明确写"`engine` 优先" |
| **2026-09-23** | `requests` 与 `deep-translator` **保持必装**，只把 `argostranslate` 放进 `local` extra | 计划里原本写"deep-translator 移到 google extra"，实现时判定不妥：**google 是默认引擎**，把它的依赖做成可选 = 装完就坏（`pip install wreader` 后按 `t` 直接报"没装包"）。extras 只该装"重且少数人才用"的东西，Argos 的几百 MB 模型正合适 |
| **2026-09-23** | `t` 从"只翻当前屏并提示已翻译 N 段"改成"**译文在底部弹窗显示 3 秒**"，并新增"未配置就走向导"的前置检查 | 规格明确要求弹窗；顺带修掉旧行为的反直觉之处——旧 `t` 只把译文塞进内存，用户按完看不到任何译文（得再按 `l`）。前置检查则是把"没配好"和"请求失败"分开：前者给可操作提示，后者才是错误 |
| **2026-09-23** | 新增 `tools/verify_translate.py`（真 pty，**不联网**） | 弹窗要真建子窗口/真按叠窗顺序刷；但翻译必须联网，而测试纪律不许联网。于是只验"不联网也确定"的两条：引擎不可用时 `t` 的提示、向导的落盘。**用 `local`（没装包）与 `baidu`（没填密钥）各打一次**，两条路都不需要网络 |
| **2026-09-23** | 成就引擎**独立成模块** `wreader/achievements.py`，解锁状态从 `library.json` 搬到 `~/.wreader/achievements.json`（第一次读状态时**自动迁移一次**） | 用户规格要求"事件驱动"。有些成就的条件根本**无法从索引派生**（打开过几天、周末读了多少秒、按行号去重后的字数），必须随事件记下来。"单一写入路径"避免"到底谁说了算"；一次性迁移保证老用户不丢解锁 |
| **2026-09-23** | 成就条件**仍是** `指标 比较符 数字` 表达式（而不是每种成就写一个判定函数） | 28 条里绝大多数本质是累计量。用"**事件累加 → 派生指标 → 表达式判定**"三件套：既满足"事件驱动 + 各模块调 `check_achievements`"，又保住"用户自己往 json 加一条成就"这个**已文档化的特性**（零代码扩展）。只有真正无法用指标表达的（实时按键、地理时间窗、环境探测）才留给 Phase 2/3 的专用判定器 |
| **2026-09-23** | 字数"按行号区间去重"由 `Pager.read_ranges` 承担，挂在 `move_to()` 这个**唯一位移入口** | 只记"读了多少行"换算不出字数；只记总字数又会因回翻重复计数。**行区间**是唯一同时满足"去重"与"行号坐标唯一"硬约束的表示；挂在 `move_to` 上则天然覆盖翻页/滚轮/跳转/搜索所有路径，不必逐个方法插桩 |
| **2026-09-23** | 定义文件加 `category` / `secret` 两个字段（**4 键 → 6 键**，旧定义自动补默认值） | 规格要求按分类展示成就、且有隐藏成就。代价是 `stats.load_achievements` 的规范化与 2 个测试同步更新；老式定义仍能加载（补 `DEFAULT_CATEGORY` 与 `secret=False`） |
| **2026-09-23** | **删除** `stats.check_achievements`（连同它的 6 个测试） | 解锁只能有一个写入路径。留着它 = 两套真相（一个写 `library.json`、一个写 `achievements.json`）。`stats` 从此只负责"指标 + 定义加载 + 庆祝动画" |
| **2026-09-23** | 文件锁只做 POSIX `flock`，Windows 退化为"原子替换、不串行化" | 主战场是 macOS / Linux / Termux。为 Windows 在**模块顶部** `import msvcrt` 会让 pyright 在 macOS 上报"无法解析"；改成函数内 `import fcntl` + `ImportError: return False`。这是明说的取舍（docstring 与两份 README 都写了） |
| **2026-09-23** | `marathon` / `book_finished` 的**显示名**改成规格里的「马拉松」「第一本」 | 用户规格明确给了名字。**id 不变** → 老用户的解锁记录与 `library.json` 里的旧数据照常有效（名字只是展示层，解锁记录里存的那份只是快照） |


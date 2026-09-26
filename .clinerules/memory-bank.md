# MemoryBank 协议

> 本规则对**每次会话**生效。`memory-bank/` 是项目的长期记忆，也是唯一可信的项目状态来源。

## 为什么需要它

我的记忆在会话之间会完全重置。所以"项目现在是怎样、为什么是这样、接下来要做什么"
必须全部落在 `memory-bank/` 的文件里。**只存在于对话里的结论，下个会话就等于不存在。**

## 文件职责

| 文件 | 内容 |
| --- | --- |
| `memory-bank/projectbrief.md` | 项目定位、核心功能需求、**硬性技术约束**、明确的非目标 |
| `memory-bank/productContext.md` | 为什么做、给谁用、体验目标、关键产品决策与理由、迁移兼容承诺 |
| `memory-bank/systemPatterns.md` | 分层架构、模块职责表、关键设计模式、关键调用链、必踩的坑 |
| `memory-bank/techContext.md` | 依赖、环境、环境变量、文件位置、配置项清单、常用命令、测试基础设施 |
| `memory-bank/activeContext.md` | **当前焦点**：最近改动、验证证据、待办优先级、会话级注意事项 |
| `memory-bank/progress.md` | 整体状态、已完成功能清单、待办、已知问题表、决策演变史 |

## 读取协议（任务开始时）

1. **任何任务开始前**：先读 `activeContext.md`，再读 `projectbrief.md`。
2. **着手改代码前**：加读 `systemPatterns.md`（架构 + 坑清单）与 `techContext.md`（命令 + 约束）。
3. **涉及需求取舍时**：加读 `productContext.md`。
4. **不要凭记忆假设项目状态**，文件里写下的才算数。
5. 发现文件与实际代码不符时：**先按实际代码工作，收尾时再修正文件**。

## 更新协议（何时更新哪个文件）

| 触发 | 要更新的文件 |
| --- | --- |
| 每完成一段工作（不论大小） | `activeContext.md` —— 写清改了什么、为什么改、怎么验证的 |
| 状态 / 已完成清单 / 待办 / 已知问题有变化 | `progress.md` |
| 做了方向性取舍 | `progress.md` 的"决策演变"表 |
| 架构、模块职责、设计模式、关键调用链有变化 | `systemPatterns.md` |
| 依赖、命令、配置项、测试规模有变化 | `techContext.md` |
| 项目定位或硬性约束真的变了 | `projectbrief.md`（谨慎，很少动） |
| 用户说 **"update memory bank"** | **全部 6 个文件逐一复核**（唯一要求全量复核的触发词） |

## 写作纪律

- **只写事实**。凡数字（源码行数、测试项数、版本、配置项个数）必须先**实测**再写，
  不许写"大概""应该"。确实只能估的，明确标为估值并尽量附上实测值。
  ⚠️ **别写会随每次操作变化的计数**（git 提交数、`HEAD` 的 SHA）—— 落笔那一刻就过期：
  2026-09-22 的同步里在 5 处写了"12 个提交"，而同一次会话自己又提交了两次。
  要写就写**稳定事实**（例如"40 个跟踪文件"）或**判据**（例如"`git status` 不显示领先/落后"）。
- **记录失败与坑**：踩过的坑、试过又放弃的方案、被回退的改动，比成功记录更值钱。
  例：`start_color()` 单独调用会把配色锁成黑底；`addstr` 越界被吞会让**整行**文字消失。
- **过期就改**：不要把"以后再说"当成已完成；过期内容会误导下个会话。
- **不制造第二个事实来源**：同一事实只写在最合适的那个文件里，别处只放链接。
- 中文为主、代码标识符用英文，与项目其余文档保持一致。

## 项目硬性约束（改代码前必读）

`projectbrief.md` 的「硬性技术约束」一节**不可违反**，摘要如下：

- 数据全部纯文本（JSON / TOML / UTF-8），用户随时能手改与备份。
- 行号坐标唯一：`正文.split("\n")` 的下标同时是 `current_line`、书签 `line`、
  `chapters[].line_start`；任何读正文的地方都必须先 `library.normalise_newlines()`。
- **CJK 宽度必须走** `reader._char_width` / `_text_width` / `_clip_line` / `_pad_line` / `_wrap_line`，
  **禁止用 `len()` 判断宽度**（汉字占 2 列）。
- 除 `reader.py` 的 curses 前端与 `cli.py` 的输出渲染外，模块保持**纯函数 + 普通数据**。
- 测试绝不联网、绝不碰真实数据；阅读器测试用 `FakeStdscr`，需要输入时 monkeypatch
  `reader._prompt` / `_confirm`。
- `npx pyright` 保持 **0 errors / 0 warnings**（`wreader/`、`tests/`、`tools/` 都纳入）。
- 每条逻辑语句上方保留一行**口语化中文注释**（讲清"在干嘛 + 类型/副作用/边界"），
  同时保留原有 docstring 与英文注释。
  ⚠️ **实测校正（2026-09-26 复测）**：这条是**目标**，不是既成事实 ——
  `tools/check_comments.py` 严格测出 `wreader/` + `tests/` 仍有 **3403** 条语句上方没有紧邻
  注释行（最多的是 `test_reader.py` 664、`reader.py` 509、`achievements.py` 256、
  `library.py` 233；2026-09-25 复测是 2771）。
  早先记录的 "TOTAL: 0" 是脚本 bug 造成的假绿，别再引用它。
  实务上遵循的是"一段逻辑配一段中文注释"的风格，别执行到每条 `return` / `assert` 都单独加。

## 本项目的特殊提醒

- **工作目录已是 git 仓库**（2026-09-22 起）：分支 `main`，远端 `origin` =
  `https://github.com/zhangziluo/wreader`。所以"这次只改了注释、没动逻辑"这类说法
  **必须用 `git diff` 证明**，别再靠 `py_compile` 猜；动手前先确认工作区干净
  （`git status`），做完及时 commit + push。`memory-bank/` 与 `.clinerules/` 都在版本控制内。
- **`book/` 永不上传**：那是开发用的真实电子书样例（367 MB，单文件最大 147 MB），
  已被 `.gitignore` 忽略，**不要 `git add -f`**——GitHub 单文件硬上限 100 MB，推上去必失败。
- **推送认证方式**：HTTPS + macOS Keychain（系统级 `/usr/local/etc/gitconfig` 里
  `credential.helper=osxkeychain`），`git push` 无需交互。`~/.ssh/id_ed25519` 这把钥匙
  **没有**注册到 GitHub 账号，改用 SSH 会 `Permission denied (publickey)`。
  全局另有 `http.proxy` / `https.proxy = http://127.0.0.1:7897`，**代理没开时 push 会失败**；
  ⚠️ 实测**不要**用 `git -c http.proxy= push` 去"绕过" —— 直连 GitHub 在这台机器上不通，
  会挂在直连上几分钟没结果（只能 `pkill git-remote-https`）。判据：`curl -x http://127.0.0.1:7897
  https://github.com` 返回 200 就能推，代理没开就先别推（测试 / `pyright` / `tools/` 全离线可跑）。
  自动化推送时设 `GIT_TERMINAL_PROMPT=0` 避免卡住。
  ⚠️ **偶发瞬时失败**：实测遇到过 `LibreSSL SSL_connect: SSL_ERROR_SYSCALL ... github.com:443`，
  而同一时刻 `curl -x http://127.0.0.1:7897 https://github.com` 返回 200 —— 是网络抖动，
  **先原样重试一次**（通常立刻成功），别急着当成认证/配置坏了去改 remote 或 helper。
- **pytest 汇总行会消失**：`pyproject.toml` 的 `addopts` 已含 `-q`，命令行再加 `-q` 会变成
  `-qq`，此时只输出 `文件: 数量`、不打印 `N passed`。想看到汇总就少加一个 `-q`。
- **改动必须先实测验证**：跑 `py_compile`、`pytest tests/`、`npx pyright`；
  涉及阅读器宽度/绘制时，还应跑 `tools/verify_wrap.py` 与 `tools/verify_draw.py`；
  动了鼠标 / 成就通知 / 帮助页 / 恢复流程 / 配色，跑 `tools/verify_mouse.py`、
  `tools/verify_achievements.py`、`tools/verify_colors.py`（后三个要真 pty / 真终端，
  见 `tools/README.md`）。
- **`tools/` 是开发期校验脚本的家**（不参与打包，共 **8** 个脚本 + `README.md`）：
  `check_docs.py`（文档锚点/围栏）、`check_doc_numbers.py`（README 数字对拍）、
  `check_comments.py`（注释覆盖，默认只报告）、`verify_wrap.py` / `verify_draw.py` /
  `verify_colors.py` / `verify_mouse.py` / `verify_achievements.py`。
  改完对应代码顺手跑一下，它们都自己推算仓库根，在哪个目录运行都行，退出码 0 = 通过。
  删功能时**连它的专用脚本一起删**（别留没人维护的死脚本）。
- **数据搬家与清理的既定行为**（2026-09-26 起）：`werd data export/import` 的包是**明文 UTF-8 JSON**
  （`kind=werd-data` / `version=1`），合并**只加不减** —— 时长与每日桶相加、会话按内容去重、
  书签取并集、`finished` 粘住、位置只在本机没有历史时才采用。
  ⚠️ **同一个包导两次，时长就翻倍，这是有意取舍，别当 bug 修**（理由见 `progress.md` 决策行与
  `systemPatterns.md` 模式 #12 / 坑 #34）。`werd clear` **只清书库、保留时长与成就**，且**没有二次确认**；
  `cli._auto_prune_books` 的自动对账会跳过 `clear` / `prune` 自己（坑 #35）。
- ⚠️ **改文件只用 `editor` 工具，提交信息也不要走 heredoc**：本环境对 heredoc 的处理不可靠 ——
  实测 `cat > file <<EOF` **文件一个字节都没写**（看着像成功），而 `git commit -F - <<MSG`
  消息虽然进了提交，命令却**挂到 300 秒以上**不返回。规矩：写文件用 `editor`，
  提交信息写成临时文件再 `git commit -F <file>` 或用 `-m`。
  `editor` 单次替换还有 ~6000 字符上限，超长替换会"假成功"
  （在仓库根留一份野生文件，并让 IDE 一直飘着指向它的幽灵告警）；大改拆小块，改完 `grep` /
  `head` 确认落地，收尾 `git status` 扫一眼有没有怪文件。
- 会话结束前务必让 `activeContext.md` 反映真实现状，好让下个会话无缝接手。

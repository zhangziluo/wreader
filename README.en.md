# wreader · a terminal novel reader

> Read txt / epub novels in your terminal: bilingual Chinese–English text, a vocabulary notebook, reading statistics and achievements.
> A pure Python CLI. Your books stay on your machine, and your progress, words and stats are remembered.

No mouse, no GUI. Drop your novels into a folder, type one command, and page through them in the terminal;
press a single key to look up a word you do not know and file it into your notebook; close the terminal and
the next launch resumes exactly where you stopped.

🌐 **中文**: [README.md](README.md) · **中文手把手教程**: [使用指南.md](使用指南.md) (Chinese only)

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Using wreader in a new terminal](#using-wreader-in-a-new-terminal)
- [Quick start](#quick-start)
- [Command reference](#command-reference)
- [Reader key bindings](#reader-key-bindings)
- [Settings](#settings)
- [File locations](#file-locations)
- [Data formats](#data-formats)
- [Achievements](#achievements)
- [Project layout](#project-layout)
- [Development](#development)
- [FAQ](#faq)
- [Known issues](#known-issues)
- [License](#license)
- [Related documents](#related-documents)

---

## Features

| Feature | Description |
| --- | --- |
| 📚 Import | Scans a directory recursively, accepts `.txt` / `.epub`; detects the encoding (a BOM for UTF-8/UTF-16/UTF-32 → chardet → UTF-8 → GB18030) and stores everything as UTF-8, so you never deal with encodings again |
| 🆔 Deduplication | A book's id is the SHA-1 of its text, so importing the same book twice is a no-op instead of a second copy |
| 🔖 Chapters | Chapter headings (`第一章`, `Chapter 1`, …) are detected at import time, which enables chapter navigation |
| 🔍 Search | Fuzzy library search over title, author and tags, with subsequence matching too (`hptr` finds *Harry Potter*) |
| 📖 Reader | A curses pager: line jumps, chapter jumps, highlighted search, bookmarks, a status bar and automatic progress saving; wraps to the terminal width (CJK counted as two columns) and follows the terminal theme / transparency |
| 🌍 Three views | `中文` / `英文` / `双语对照` (bilingual), cycled with `l`; a Chinese book read in the Chinese view needs no translation and works offline |
| 🈶 Translation | Chapter-level translation with an on-disk cache — translate once, reuse forever; Google (no API key) and DeepSeek (OpenAI-compatible endpoint) |
| 📝 Vocabulary | Press `v` while reading to look a word up and keep it; notebook words are underlined in the reader. List, search, review, remove and export to Anki |
| 📊 Statistics | Total / today / this week / this month / daily goal / streak / a 30-day heatmap; `--json` for scripts |
| 🏆 Achievements | 10 achievements (first book, night owl, seven-day streak, …) with progress bars, an unlock animation and a bell |
| ⚙️ Settings | One `settings.toml` for everything; `wreader config` reads and writes it with typo suggestions; the old `config.json` is migrated automatically |

---

## Requirements

- **Python 3.11 or newer** (the standard library `tomllib` is used)
- **macOS / Linux**: `curses` ships with Python, so nothing extra is needed
- **Windows**: install `windows-curses` as well (see Installation)
- A UTF-8 capable terminal (required for Chinese books; the macOS Terminal, iTerm2 and Windows Terminal all qualify)
- Network access only for Google translation and `wreader translate`; reading locally works entirely offline

These third-party libraries are installed automatically:
`rich` (tables and progress bars), `chardet` (encoding detection), `deep-translator` (Google translation)
and `requests` (DeepSeek translation).

---

## Installation

### Three commands (recommended)

You need **Python 3.11+** and `git`:

```bash
git clone https://github.com/zhangziluo/wreader.git
cd wreader
./install.sh
```

`./install.sh` takes care of everything else: it creates the `.venv` virtual environment,
installs the four dependencies, **sets up the `wreader` alias** (appended to `~/.bashrc` or
`~/.zshrc` — running it twice will not add a second line) and finally checks the version:

```bash
wreader --version        # wreader 0.1.0
```

Follow its last line (`source ~/.zshrc`, or simply open a new terminal) and you are done.

| Flag | What it does |
| --- | --- |
| `./install.sh --dev` | Also install `pytest` (only needed to hack on the code or run the tests) |
| `./install.sh --no-alias` | Leave `~/.bashrc` / `~/.zshrc` alone; use the full path instead |
| `./install.sh --help` | Show usage |

### Manual installation (if the script cannot run, or you prefer doing it yourself)

<details>
<summary><b>Expand for the manual steps (Windows users go here)</b></summary>

From the project root (the folder holding `pyproject.toml` and `wreader/`):

```bash
# 1. create a virtual environment (recommended; keeps your system Python clean)
python3 -m venv .venv

# 2. activate it
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows (PowerShell / CMD)

# 3. install in editable mode
pip install -e .
```

On Windows use:

```bash
pip install -e ".[windows]"
```

You now have the `wreader` command **in the current terminal window**:

```bash
wreader --version
# wreader 0.1.0
```

</details>

### Using wreader in a new terminal

`wreader` lives inside the project's own `.venv`, and `.venv/bin` is not on `PATH` by
default. So **after you close the terminal and open a new one, typing `wreader` fails
with `command not found`** — that is expected, and it does not mean the install is broken.

**If you installed with `./install.sh` you are already covered**: it wrote the alias into
`~/.bashrc` / `~/.zshrc` for you, so a new terminal simply works (the only thing you might
still need is `source ~/.zshrc`). The table below is for people who passed `--no-alias` or
installed by hand — pick whichever of the three you prefer:

| Option | What you type each time | Notes |
| --- | --- | --- |
| **① Add an alias** (recommended) | `wreader read <id>` | Do it once; works in **every** new terminal |
| **② Use the full path** | `<project>/.venv/bin/wreader read <id>` | Nothing to configure |
| **③ Activate the venv** | `cd <project>` → `source .venv/bin/activate` → `wreader ...` | Fine if you work in the project anyway |

Option ① on macOS / Linux (zsh) is one line appended to `~/.zshrc`
(put in your real project path):

```bash
echo 'alias wreader="$HOME/Downloads/wreader/.venv/bin/wreader"' >> ~/.zshrc
source ~/.zshrc                       # takes effect now; or simply open a new window
wreader --version                     # check: prints wreader 0.1.0
```

With bash, use `~/.bashrc` instead; on Windows PowerShell, define a function of the
same name in `$PROFILE`.

> ⚠️ **Do not prepend `.venv/bin` to `PATH`** (`export PATH=".../.venv/bin:$PATH"`).
> That does make `wreader` work, but it also turns `python3` and `pip` in every new
> terminal into this virtualenv's copies, which will confuse you in other Python
> projects. An alias adds one command and nothing else.
>
> `install.sh` follows the same rule: it always installs through `.venv/bin/python -m pip`
> and **never** adds `.venv/bin` to `PATH`.

> **Just passing through?** You can skip all of the above and write
> `python -m wreader.cli xxx` wherever this document says `wreader xxx` — the two are
> equivalent. A beginner-oriented version of this section (including the Windows form and
> why your books and progress are unaffected) is in [使用指南.md](使用指南.md) (Chinese).

### Upgrading from the old `nr`

The tool used to be called `nr`. Nobody has to move anything by hand: the first
time `wreader` runs, if `~/.wreader` does not exist yet and `~/.nr` does, the whole
old directory is moved into place — settings, library index, notebook and
translation cache included — and the old directory disappears.

| Old name | Now | Compatibility |
| --- | --- | --- |
| the `nr` command | `wreader` | re-run `pip install -e .`; the old command goes away with the old distribution |
| `python -m nr.cli` | `python -m wreader.cli` | the module name follows the package, so the old spelling is gone |
| `$NR_HOME` / `$NR_NOVELS_DIR` | `$WREADER_HOME` / `$WREADER_NOVELS_DIR` | the old variables are still read when the new one is unset |
| `~/.nr` | `~/.wreader` | adopted automatically on the first run (see above) |
| a hard coded `cache_dir = "~/.nr/cache"` | `"~/.wreader/cache"` | the old value still means "next to the data directory" instead of pointing at an abandoned path |

The Python package was renamed too: `from nr import library` is now
`from wreader import library`, and `pip show wreader` shows the new distribution.
To start over, delete `~/.wreader`.

---

## Quick start

Four steps from nothing to reading:

```bash
# (1) put your books somewhere (or point at a folder you already have)
#     naming files 「author-title.txt」 gives the best metadata, e.g. 刘慈欣-三体.txt

# (2) import them
wreader import ~/Downloads/books

# (3) see what is in the library and note the id
wreader list

# (4) start reading (replace the id with the one you just saw)
wreader read 3e027c4de949

# forgot which book you were on? this lists the three you opened most recently
wreader continue
```

Real `wreader import` output:

```
imported 2 book(s), skipped 0 duplicate(s), 0 failed
  + ab912556b66b  《Nameless》 unknown · 7 行 · 12 字 · ascii · 2 章
  + 3e027c4de949  《三体》 刘慈欣 · 281 行 · 2000 字 · utf-8 · 41 章
```

Real `wreader list` output:

```
                              library (2 book(s))
┏━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ # ┃ id           ┃ title    ┃ author  ┃ progress ┃ words ┃
┡━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ 1 │ ab912556b66b │ Nameless │ unknown │     0.0% │    12 │
│ 2 │ 3e027c4de949 │ 三体     │ 刘慈欣  │     0.0% │  2000 │
└───┴──────────────┴──────────┴─────────┴──────────┴───────┘
```

What you see after quitting the reader with `q`:

```
[双语对照 · 停在 120/281 行 (42.7%) · 本次 12:30 · 书签 2 个]
```

(Reader strings are Chinese: "bilingual view · stopped at line 120/281 (42.7%) · this session 12:30 · 2 bookmarks".)

---

## Command reference

At a glance:

| Command | What it does |
| --- | --- |
| `wreader import <path>` | Scan a file or directory and import txt/epub books |
| `wreader list` | List the books in the library |
| `wreader search <keyword>` | Fuzzy search over title / author / tags |
| `wreader read <book_id>` | Open the paged reader |
| `wreader continue` | The three books you opened most recently (with their ids) |
| `wreader translate <book_id>` | Translate and cache a whole book, chapter by chapter |
| `wreader vocab` | Vocabulary notebook: list / review / search / remove / export |
| `wreader stats` | Reading statistics and a heatmap (`--json` for scripts) |
| `wreader achievements` | Achievement list and unlock progress |
| `wreader config` | View or edit settings |

Exit codes: `0` on success; `1` for a bad argument, nothing found (`no book matches ...`) or a translation
with failed chapters (`Ctrl-C` gives `130`). Errors are always printed as `error: ...` — never as a raw traceback.

### `wreader import <path>`

```bash
wreader import ~/Downloads/books        # scan a whole directory recursively
wreader import ~/Downloads/三体.txt     # or import a single file
```

- Only `.txt` and `.epub` are accepted; hidden files (macOS `._xxx`, `.DS_Store`) are skipped.
- `.epub` prefers an external converter — `ebook-convert` (Calibre) or `epub2txt` — and falls back to the
  built-in extractor (standard library `zipfile` + `ElementTree`, reading the spine order).
- Title and author are guessed from the file name: `作者-书名`, `[作者] 书名`,
  `《书名》（校对版全本）作者：某人` and a plain `书名` all work, and a trailing `（校对版全本）` /
  `(annotated)` annotation is dropped from the title. When the author cannot be guessed it is `unknown`.
- The converted UTF-8 text is written to the novels directory (`~/novels/<title>_utf8.txt`),
  with a `(2)` suffix if a file of that name already exists.
- Importing the same book again reports `skipped N duplicate(s)` instead of storing a second copy.

### `wreader list`

```bash
wreader list
```

`progress` is the reading percentage; `words` is the word count formatted the Chinese way
(`5.7万` = 57k, `1.2亿` = 120M). An empty library tells you where the index and the novels directory live.

### `wreader search <keyword>`

```bash
wreader search 三体          # a Chinese keyword
wreader search tolkien       # an author, case insensitive
wreader search hptr          # subsequence match → Harry Potter
wreader search '#fantasy'    # a leading # searches tags only
```

Ranking: exact match > prefix > contains (earlier hits score higher) > subsequence. A title match is
weighted twice as heavily as an author match. No match returns `1` with `no book matches ...`.

### `wreader read <book_id>`

The heart of the tool; see [Reader key bindings](#reader-key-bindings) for every key.

- The book's language is detected on open (share of CJK characters, computed locally and offline), and the
  reader starts in the Chinese view for Chinese books and the English view for English ones.
- The reading position is saved every 60 seconds (configurable) and once more on exit.
- On exit, the session's duration and lines read are written to the statistics and achievements are checked.
- It **needs a real interactive terminal**; in a pipe or with redirected output you get:
  `error: wreader read needs an interactive terminal (a tty on stdin and stdout)`

### `wreader continue`

```bash
wreader continue        # the three books you opened most recently (with ids)
```

Sorted by `last_read` (the timestamp written when you leave the reader), listing only books you have
actually read, at most three:

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

Copy an `id` into `wreader read` to pick up where you stopped. When nothing has been read yet it tells
you to pick a book with `wreader list` (or import one) and still exits `0`.

> With the alias from [Using wreader in a new terminal](#using-wreader-in-a-new-terminal) in place,
> resuming after a reboot is two lines: `wreader continue` for the shortlist, `wreader read <id>` to open.

### `wreader translate <book_id>`

```bash
wreader translate 3e027c4de949
```

For "translate the whole book once, then flip between views freely". Real output:

```
translating 《三体》 · 41 chapter(s) · backend google · batch 3000 chars
translated 41, skipped 0 (already cached), 0 failed
cache: /Users/you/.wreader/cache/3e027c4de949
```

- Cache is **per chapter**, and already translated chapters are skipped — so re-running after a `Ctrl-C`
  simply resumes where it stopped.
- A single failing chapter does not abort the run; the chapter numbers are listed and the next run picks them up.
- A connectivity failure does abort, because retrying every remaining chapter would only waste time.

### `wreader vocab`

With no flags it lists the notebook (20 words per page, newest first):

```bash
wreader vocab                          # view (page 1)
wreader vocab --page 2 --per-page 50    # turn the page, change the page size
wreader vocab --search 公认             # reverse lookup by meaning (word / translation / context)
wreader vocab --review                  # review mode: shuffled, see the word then press Enter to check
wreader vocab --remove ephemeral        # delete a word
wreader vocab --export anki > deck.txt  # export Anki's tab separated format
```

`--review` is interactive in a real terminal (Enter reveals the meaning, `q` stops). If the output is
redirected it degrades to printing every word with its meaning in one go.
`--export anki` deliberately bypasses rich and writes to plain `stdout`, so the tabs survive redirection.

### `wreader stats`

```bash
wreader stats          # human readable table + heatmap
wreader stats --json   # the same data as raw JSON, for scripts and dashboards
```

Real output:

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

(In order: total reading time, today / this week / this month, the daily goal, the streak line,
then the 30-day heatmap with its legend.)

- Each heatmap **column** is one week (Monday on top, Sunday at the bottom); days outside the window are blank.
- `wreader stats --json` top-level keys: `generated_at`, `today`, `total_seconds`, `total`, `today_seconds`,
  `week_seconds`, `month_seconds`, `daily_goal_seconds`, `goal_met`, `streak_days`, `streak_min_seconds`,
  `books_read`, `finished_books`, `vocab_count`, `translations`, `night_seconds`,
  `longest_session_seconds`, `achievements`, `books`, `daily`, `heatmap`, `heatmap_grid`.
- The table and the JSON are rendered from the same dict, so the two can never disagree.

### `wreader achievements`

```bash
wreader achievements
```

Real output:

```
已解锁 1/10
  🏆 📖 开卷有益 第一次打开一本书  解锁于 2026-09-21T16:13:43

进行中
  ░░░░░░░░░░░░░░  ⏱️ 初窥门径 0分钟/1小时  累计阅读满1小时
  ██████░░░░░░░░  🔥 七日不断 3/7  连续7天每天阅读30分钟
```

(`1/10 unlocked`, the unlocked entry with its timestamp, then `进行中` = "in progress" with one progress bar per
remaining achievement.)

### `wreader config`

```bash
wreader config                            # print every setting (value / default / source file)
wreader config --path                     # print just the settings file path
wreader config reader.page_height         # read one setting
wreader config reader.page_height 30      # write one setting (saved immediately)
wreader config --reset                    # restore every default
```

Real interactions:

```
$ wreader config reader.page_height
reader.page_height = 24

$ wreader config reader.page_height 30
reader.page_height = 30 (saved)

$ wreader config reader.pag_height 20
error: unknown setting 'reader.pag_height' (did you mean 'reader.page_height'?)
```

Settings are addressed by **dotted path** (`reader.page_height`); the flat names of the old `config.json`
(`page_height`, `novels_dir`, …) still resolve and are migrated into the right section.
A typo produces a suggestion instead of being written to the file, and a type mismatch (say `abc` for a
boolean) is refused with the file left untouched.

---

## Reader key bindings

The hint bar **at the bottom of the reader shows this list by default** (a transient message temporarily
replaces it), so there is nothing to memorise:

```
q退出 j/space翻页 g跳行 [/]章节 /搜索 n下一个 b书签 v生词 l语言 t翻屏 T翻章 c中文
```

| Key | Action |
| --- | --- |
| `q` / `Q` / `Ctrl-C` | Quit (saves position, bookmarks and this session's duration) |
| `j` / `space` / `Enter` / `↓` / `PageDown` | Next page (measured in **screen rows**: a paragraph too long for one screen resumes **inside** the paragraph on the next page, so nothing is skipped or repeated; the distance comes from `reader.page_scroll_step`, keeping `reader.page_overlap` lines of context) |
| `k` / `↑` / `PageUp` | Previous page |
| Mouse wheel down · swipe up | Scroll **one line at a time** forward (lines per tick: `reader.wheel_scroll_step`) |
| Mouse wheel up · swipe down | Scroll **one line at a time** backwards |
| `g` | Jump to a line number (prompts `跳到行号 (1-281):`; `Esc` cancels) |
| `G` | Jump to the last line of the book |
| `[` | Jump to the start of the previous chapter |
| `]` | Jump to the start of the next chapter |
| `/` | Search (Chinese input works); jumps to the first hit and highlights all of them |
| `n` | Next hit (wraps around) |
| `b` | Toggle a bookmark on the current line; the status bar shows how many you have |
| `l` | Cycle the view: `中文` → `英文` → `双语对照` → `中文` … |
| `c` | Switch straight to the Chinese view (the usual key when reading an English book) |
| `t` | Translate **the current screen only**, **without caching** (for a quick peek) |
| `T` | Translate and cache **the whole chapter**, with a progress bar; revisiting it later is instant and free |
| `v` | Look a word up and file it in the vocabulary notebook (the prompt pre-fills the longest English word on the line) |

Useful details:

- **Reading on a phone (Termux and friends)**: press and drag up/down to scroll line by line —
  **swipe up to read on**, **swipe down to go back**; the distance per tick comes from
  `reader.wheel_scroll_step`, and `reader.touch_scroll false` turns dragging off.
  The wheel works the same way (down = forward, up = backward).
  ⚠️ One terminal limitation: terminals whose terminfo lacks the `XM` capability
  (**macOS's built-in Terminal** is one) can only report "wheel up" — wheel down never fires there.
  Use the arrow keys or dragging instead; nothing else is affected.
- **The bottom two rows are the status area**: the second-to-last row is assembled from
  `reader.status_bar_format` (drawn in reverse video); the last row is the hint bar — the key list normally,
  or a transient message such as `已加入生词本：xxx = 承认` ("added to notebook") when there is one.
- **The leftmost column of every text row is the bookmark gutter**: bookmarked lines show `★`, other rows are blank.
- **Search highlighting**: the hit you jumped to is in reverse video, the other hits in the same set are bold.
- **Notebook words are underlined** while `vocab.highlight_in_reader = true`; turn it off if the underlines distract you.
- **After pressing `v`**: with `vocab.auto_add_on_mark = true` the word is stored immediately; set it to `false`
  and a small popup asks `[y] 加入生词本　其他键 取消` ("press y to add, any other key cancels").
- **Slow chapters** (more than 30 minutes spent in one chapter) make the hint bar suggest pressing `c` for Chinese.
- **`Ctrl-C` mid-session loses nothing**: the position and the session duration are still saved on the way out.

---

## Settings

Everything lives in `~/.wreader/settings.toml`, split into 5 sections. Edit the file directly, or use
`wreader config <section.key> <value>`. **Deleting any line falls back to that setting's default**, so you cannot
really break it.

### `[reader]`

| Key | Default | Meaning |
| --- | --- | --- |
| `page_scroll_step` | `1` | How many screens the page keys move (a screen is the height of the text area). Paging counts **screen rows**: a paragraph too long for one screen is read across several, and the next page resumes **inside** the paragraph, so nothing is skipped or repeated. `0.5` = half a screen (finer), `2` = two screens |
| `page_overlap` | `3` | **Screen rows** of the previous screen kept at the top (and symmetrically at the bottom) on a page turn, so the text never jumps coldly; `0` turns the overlap off and each page is a clean screenful |
| `wheel_scroll_step` | `1` | Lines moved per mouse-wheel tick / per drag row (1–3 feels right on a phone) |
| `touch_scroll` | `true` | Drag the finger to scroll (mobile terminals); `false` keeps the wheel and keyboard only |
| `status_bar_format` | the `time`, `chapter`, `duration` segments | Which status bar segments to show, separated by a vertical bar (see the table below) |
| `auto_save_interval` | `60` | Seconds between automatic position saves; `0` disables |
| `page_height` | `24` | Fallback lines per screen when no terminal size is known (a real terminal pages by the actual height of the text area, so you normally leave this alone) |
| `theme` | `"default"` | Colour theme name (reserved, not implemented yet) |
| `store_history` | `true` | Record this session's duration into the statistics; `false` reads without counting time |

`status_bar_format` understands 12 segments, joined into `segment1 · segment2 · segment3`:

| Token | Shows |
| --- | --- |
| `time` | Current time, `21:34` |
| `book` | Book title |
| `chapter` | Current chapter title (`无章节` when the book has no chapters) |
| `position` | `行 120/281` (line 120 of 281) |
| `percent` | `42.7%` |
| `mode` | Current view: `中文` / `英文` / `双语对照` |
| `duration` | `本章 05:20` (time in this chapter) |
| `elapsed` | `本次 12:30` (time this session) |
| `streak` | `连续 3 天` (3-day streak) |
| `bookmarks` | `书签 2` (2 bookmarks) |
| `vocab` | `生词 128` (128 notebook words) |
| `translations` | `翻译 46` (46 translation actions) |

An unknown token is silently skipped rather than printed raw; if no segment resolves at all, the bar falls
back to showing just the clock.

### `[translator]`

| Key | Default | Meaning |
| --- | --- | --- |
| `backend` | `"google"` | `google` (no API key) or `deepseek` (needs a key) |
| `batch_size` | `3000` | Character limit per request |
| `cache_dir` | `"~/.wreader/cache"` | Translation cache directory; the default follows the data directory, so `$WREADER_HOME` applies too |
| `deepseek_api_key` | `""` | Empty falls back to the `DEEPSEEK_API_KEY` environment variable |
| `auto_translate_chapter` | `false` | Translate each chapter as it is entered (the lazy mode) |
| `source_language` | `"auto"` | Source language; `auto` detects it |
| `target_language` | `"zh-CN"` | Target language |
| `deepseek_model` | `"deepseek-chat"` | DeepSeek model name |
| `deepseek_url` | `"https://api.deepseek.com/v1/chat/completions"` | Endpoint (any OpenAI-compatible service works here) |

How the two backends differ:

- **google**: uses `deep-translator`'s `GoogleTranslator`. Free, no signup, but throttled with a one second
  pause between requests, so translating a whole book takes a while. Without connectivity you get
  `翻译不可用: Google translation failed`.
- **deepseek**: POSTs to the OpenAI-compatible `/v1/chat/completions` with `temperature` 0.3 and streaming
  enabled, which gives more coherent paragraph-level translations. It needs a key first:
  ```bash
  wreader config translator.backend deepseek
  wreader config translator.deepseek_api_key sk-your-key
  # or, without writing the key into a file:
  export DEEPSEEK_API_KEY=sk-your-key
  ```

### `[stats]`

| Key | Default | Meaning |
| --- | --- | --- |
| `daily_goal_minutes` | `60` | Daily reading goal in minutes; `0` hides the goal line |
| `show_heatmap` | `true` | Show the 30-day heatmap in `wreader stats` |
| `achievement_sound` | `true` | Ring the bell (`\a`) when an achievement unlocks; set `false` if your terminal is loud |

### `[vocab]`

| Key | Default | Meaning |
| --- | --- | --- |
| `highlight_in_reader` | `true` | Underline notebook words in the reader |
| `auto_add_on_mark` | `true` | File a looked up word immediately, without the confirmation popup |

### `[library]`

| Key | Default | Meaning |
| --- | --- | --- |
| `novels_dir` | `""` | Directory for the UTF-8 text; empty means `~/novels` |

---

## File locations

| What | Path (macOS / Linux) | Overridable by |
| --- | --- | --- |
| Settings | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| Library index | `~/.wreader/library.json` | `$WREADER_HOME` |
| Vocabulary notebook | `~/.wreader/vocab.json` | `$WREADER_HOME` |
| Translation cache | `~/.wreader/cache/<book_id>/ch0_en.txt`, `ch0_bilingual.txt` | `translator.cache_dir` |
| Book text (UTF-8) | `~/novels/<title>_utf8.txt` | `$WREADER_NOVELS_DIR`, `library.novels_dir` |

On Windows the data directory is `%APPDATA%\wreader`.

The three environment variables:

```bash
export WREADER_HOME=~/my-wreader-data    # move the whole data directory (tests / several profiles)
export WREADER_NOVELS_DIR=~/my-novels    # move the novels directory
export DEEPSEEK_API_KEY=sk-xxx           # DeepSeek key; the settings file wins over this
```

The pre-rename `$NR_HOME` / `$NR_NOVELS_DIR` still work, but only when the new name is unset.

The flat `config.json` written by older versions is folded into the matching sections the first time the
settings are loaded, and the old file is renamed to `config.json.bak`, so nothing is lost.

---

## Data formats

Everything is plain JSON / TOML / text, so you can always edit it by hand, back it up or script it.

### `~/.wreader/library.json` — the library index

Three top-level fields: `books`, `stats` and `achievements`.

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

Worth knowing:

- `book_id` is the first 12 hex digits of the SHA-1 of the converted text, which is why duplicates are always caught.
- `total_lines` and every `chapters[].line_start` are indexes into `text.split("\n")`. The reader's
  `current_line` and a bookmark's `line` use that same coordinate system, so they can never drift apart.
- `tags` is consumed by `wreader search '#tag'`, but there is no CLI command to add tags yet — edit the index by hand.

### `~/.wreader/vocab.json` — the vocabulary notebook

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

Looking the same word up twice **refreshes** the existing entry instead of adding a duplicate.
A notebook written by an older version (the `{"words": [...]}` wrapper with `book_title` / `created`) still loads.

### `~/.wreader/cache/<book_id>/` — the translation cache

```
ch0_en.txt          chapter 1's translation (one paragraph per line + blank lines) — always named _en,
                    even though it holds the text in translator.target_language
ch0_bilingual.txt   chapter 1 paired 中/英, which feeds the reader's bilingual view
```

The suffixes are fixed at `_en` and `_bilingual` (`_en` is a historical name for the "target language" file).
The cache is per chapter, so deleting the whole directory affects nothing else — it just means re-translating.

---

## Achievements

Defined in `wreader/data/achievements.json`; there are 10 of them. A condition is a simple
`metric comparison number` expression, so you can add your own.

| Achievement | Name | Condition |
| --- | --- | --- |
| `first_book` | 📖 开卷有益 | Open a book for the first time |
| `first_hour` | ⏱️ 初窥门径 | One hour of total reading |
| `ten_hours` | 🎓 学富五车 | Ten hours of total reading |
| `night_owl` | 🌙 深夜书虫 | More than an hour read between 00:00 and 04:00 |
| `streak_7` | 🔥 七日不断 | Seven days in a row with 30 minutes each |
| `streak_30` | 🗿 铁血读者 | Thirty days in a row of reading |
| `book_finished` | 🏁 完本达人 | Finish your first book |
| `vocab_100` | 📝 词汇积累 | 100 words in the notebook |
| `translator` | 🌍 双语者 | Use translation for the first time |
| `marathon` | 🧘 专注模式 | A single reading session longer than two hours |

Available metrics: `books_read`, `total_time`, `night_time`, `streak`, `finished`, `vocab_count`,
`translations`, `single_session` (time-based metrics are in **seconds**).

The streak rule: a day only counts once it reaches 30 minutes, but today always counts — it is about to
become a fact. Unlocking prints an animation and a banner; `stats.achievement_sound = false` silences the bell.

---

## Project layout

```
wreader/
├── pyproject.toml           packaging (dependencies, console script, LICENSE, [tool.pytest], [tool.pyright])
├── LICENSE                  MIT license
├── README.md                中文说明 (Chinese)
├── README.en.md             this file
├── 使用指南.md               step-by-step beginner guide (Chinese only)
├── install.sh               one-shot installer: venv, dependencies, wreader alias (idempotent)
├── tools/                   development-time checks: doc anchors, doc numbers, wrapping, drawing, colours (see tools/README.md)
├── .vscode/settings.json    points Pylance / the terminal at the .venv interpreter
├── wreader/
│   ├── __init__.py          __version__ and the module map (18 lines)
│   ├── cli.py               argparse definition + one handler per sub-command (1028 lines)
│   ├── config.py            settings.toml I/O, type checks, legacy migration, data dir adoption (989 lines)
│   ├── library.py           txt/epub import, encoding detection, file name parsing, index (1099 lines)
│   ├── reader.py            the curses pager: views, search, bookmarks, status bar, wheel/touch (2287 lines)
│   ├── translator.py        Google / DeepSeek backends + chapter cache (1305 lines)
│   ├── vocab.py             the notebook: add, remove, search, review, Anki export (436 lines)
│   ├── stats.py             metrics, heatmap, achievement checks, celebration (849 lines)
│   └── data/
│       └── achievements.json  the 10 achievement definitions (62 lines)
└── tests/                   545 tests, all offline (see "Running the tests" below)
    ├── conftest.py          shared fixtures: isolated $WREADER_HOME, recording back-end, epub builder
    ├── test_config.py       51 tests — defaults, type checks, legacy migration, data dir adoption
    ├── test_library.py      119 tests — encodings, chapters, epub, dedup, file names, search, recent books
    ├── test_reader.py       159 tests — paging maths, Pager, status bar, keys, sessions, wrapping, wheel
    ├── test_stats.py        76 tests — metrics, streaks, heatmap, unlock logic, the report
    ├── test_translator.py   74 tests — language detection, batching, cache, backends, SSE
    ├── test_vocab.py        31 tests — notebook I/O, refresh-not-duplicate, review, Anki export
    └── test_cli.py          35 tests — argument parsing, every sub-command's output, exit codes, continue
```

Layering: apart from the curses front end in `wreader/reader.py` and the output rendering in `wreader/cli.py`,
every module is **plain functions over plain data** and never touches a terminal. The paging maths, chapter
boundaries, statistics metrics and achievement conditions can therefore be tested or reused without a TTY.

---

## Development

```bash
# set up (editable, so code changes take effect immediately)
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# run it
wreader --help
wreader list

# experiment without touching your real data: point the environment elsewhere
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
wreader import /tmp/my-test-books
```

Debugging tips:

- **Starting over**: delete `$WREADER_HOME` (default `~/.wreader`) and the novels directory; the next run recreates the
  default settings. Imported books are re-importable from the originals.
- **Poking at the front-end logic**: `Pager`, `chapter_bounds`, `read_lines` and `reading_streak` in
  `wreader/reader.py` need no curses, so `from wreader.reader import Pager` works in a REPL.
- **IDE**: the repo's `.vscode/settings.json` already points the interpreter at `.venv/bin/python`. If Pylance
  reports `无法解析导入 "rich.console"` (unresolved import), run `Developer: Reload Window` once or pick
  `.venv/bin/python` through `Python: Select Interpreter`.

Static type checking is configured in the `[tool.pyright]` section of `pyproject.toml` (`venvPath` / `venv`
point at `.venv`, so third-party imports resolve without extra flags):

```bash
npx pyright                 # or install pyright once and call it directly
```

The current state is **0 errors / 0 warnings** (both `wreader/` and `tests/` are analysed). Note that
`[tool.pyright]` only affects the pyright CLI — the Pylance extension in VS Code reads
`.vscode/settings.json` instead (both point at the same `.venv`).

### Running the tests

```bash
pip install -e ".[dev]"     # pulls in pytest
pytest                      # 545 tests, a few seconds
pytest -q tests/test_reader.py            # one file
pytest -k "streak or heatmap" -q          # by name
```

A few conventions the suite follows, which are worth knowing before you change code:

- **It never touches your real data.** The autouse fixture in `tests/conftest.py` points
  `$WREADER_HOME` / `$WREADER_NOVELS_DIR` at a `tmp_path` and clears both the `wreader.config` cache and the
  `wreader.translator` global back-end, so every test starts clean.
- **It never reaches the network.** Translation goes through the `RecordingBackend` in conftest
  (installed with `set_backend`); Google and DeepSeek are only exercised down to their constructor
  arguments, request payload and SSE parsing. To prove it, run the suite behind a dead proxy:
  ```bash
  HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 pytest
  ```
- **It needs no terminal.** The reader is driven through `FakeStdscr` in `tests/test_reader.py`,
  which implements exactly the slice of the curses API the reader touches, and the keys that would
  prompt for input have `wreader.reader._prompt` / `_confirm` monkeypatched. The one path that *must*
  fail — `open_reader`'s tty check — is asserted as an error.

### Other check scripts

`tools/` holds a few development-time checks (**not shipped in the package**). Run the relevant
one after changing the matching code:

```bash
python tools/check_docs.py            # doc anchors and code fences (after editing README / 使用指南)
python tools/check_doc_numbers.py     # are the line/test counts in the READMEs still true?
python tools/check_comments.py        # comment coverage (report only; add --strict to gate)
python tools/verify_wrap.py           # wrapping invariants (expects OK: 40077 checks passed)
python tools/verify_draw.py           # nothing drawn past the edge (expects OK: 420 draw checks passed)
script -q /dev/null python tools/verify_colors.py   # colours (needs a pty)
```

Each one works out the repository root itself, so it can be run from any directory;
exit code 0 = pass, 1 = something to look at. See [tools/README.md](tools/README.md).

---

## FAQ

**Q: After opening a new terminal, `wreader` says command not found?**
The most common report — and **not** a broken install: `wreader` lives in the project's own `.venv`,
whose `bin` directory is not on `PATH` by default. If you installed with `./install.sh` the alias is
already in place, so just run `source ~/.zshrc` (or `~/.bashrc`) or open another terminal; if it still
fails you either passed `--no-alias` or installed by hand — see
[Using wreader in a new terminal](#using-wreader-in-a-new-terminal). Alternatively call
`<project>/.venv/bin/wreader` directly, run `source .venv/bin/activate` first, or simply write
`python -m wreader.cli xxx` instead of `wreader xxx`.

**Q: Where did my library go after upgrading?**
The first run of `wreader` moves `~/.nr` into `~/.wreader` for you. When both directories exist, `wreader`
only ever uses `~/.wreader` and leaves `~/.nr` alone — delete it yourself once you are happy with the new one.

**Q: `path does not exist` / `no .txt/.epub file found under ...` on import?**
Either the path is wrong, or the directory really holds no `.txt` / `.epub`. `wreader import` scans recursively,
so pointing at a parent folder is fine.

**Q: My Chinese book shows up as mojibake.**
The encoding is tried in order: a BOM (UTF-8 / UTF-16 / UTF-32) → chardet → UTF-8 → GB18030. A BOM only states
what the file *intends* to be — a UTF-32 document opens with the UTF-16 BOM bytes, and a damaged UTF-16 file can
carry an illegal surrogate — so a BOM'd file that fails to decode is imported with replacement characters and
labelled `(replaced)` instead of aborting the whole run. When you see that label, re-save the source file as
UTF-8 and import it again for clean text.

**Q: I imported the same book twice.**
You cannot. The id is the SHA-1 of the text, so the second one reports `skipped 1 duplicate(s)`.
Renaming the file does not help (the content is unchanged), but **editing** the content makes it a new book.

**Q: I pressed `t` and got no translation.**
`t` translates the current screen and deliberately does not cache. If it says `当前视图就是原文，无需翻译`
("this view is already the source text"), the language you asked for is the book's own. To keep a translation
permanently press `T` (caches the chapter) or run `wreader translate <book_id>` once from the shell.

**Q: Translation fails with `翻译不可用: ...`.**
The Google backend needs connectivity; the DeepSeek backend needs an API key
(`wreader config translator.deepseek_api_key sk-xxx` or `export DEEPSEEK_API_KEY=...`). Google is often unreachable
from mainland China — switch to DeepSeek there.

**Q: `wreader read` says `needs an interactive terminal`.**
The reader must run in a real terminal: no `| less`, no redirection, no CI.
(`wreader list` / `wreader stats` and friends are happy to be redirected.)

**Q: The statistics did not change after a session.**
Check two things: is `reader.store_history` still `true`, and was the session saved at all (a read-only disk
or an unwritable data directory fails silently).

**Q: The streak already says 1 after a short session.**
Today always counts — it is about to become a fact. The real threshold is 30 accumulated minutes on a day.

**Q: I want silent reading: no statistics, no bell.**
```bash
wreader config reader.store_history false
wreader config stats.achievement_sound false
wreader config stats.show_heatmap false
```

**Q: How do I get my words into Anki?**
```bash
wreader vocab --export anki > deck.txt
```
Then Anki → File → Import, choose "tab" as the field separator; the three columns are word / meaning / example.

**Q: I deleted a book file but the index still lists it.**
There is no CLI command for that yet. Delete the key under `books` in `library.json` (`wreader list` stops showing
it immediately), or use Python:
```python
from wreader import library
library.remove_book("3e027c4de949")   # also deletes the UTF-8 text under ~/novels
```

**Q: I broke `settings.toml`.**
`wreader config --reset` restores every default, or delete the file and it is regenerated. Deleting a single line
just reverts that one setting.

---

## Known issues

These are the limitations that genuinely exist today; better to write them down than to hide them:

- **`reader.theme` is not implemented** — changing it has no effect.
- **No CLI command to add tags.** `books[].tags` and `wreader search '#tag'` work, but for now you edit `library.json`.
- **EPUB parsing is a trade-off**: without Calibre's `ebook-convert` the built-in extractor only keeps body text,
  so images, footnotes and complex layout are lost. Installing Calibre is recommended.
- **`wreader read` only works in a real terminal** (see the FAQ above).
- **Windows needs the extra dependency** `windows-curses` (`pip install -e ".[windows]"`).
- **Numeric values under `progress` in `library.json` are not coerced**: a hand written string
  (`"current_line": "12"`) still works because every consumer wraps it in `int(...)`, but it is not
  turned back into a number for you.

Ten former issues that are now fixed, kept here so they are not mistaken for pending work:

- ~~No LICENSE~~ → MIT added (`LICENSE` plus `license = "MIT"` in `pyproject.toml`).
- ~~`translator.__all__` listed a non-existent `chapter_paragraphs`~~ → the name was removed and replaced by
  the real `TranslatorCallable`; before the fix `from wreader.translator import *` raised `AttributeError`.
- ~~About 10 type warnings in `library.py` / `stats.py` / `translator.py` / `vocab.py`~~ → all fixed;
  `pyright` now reports 0 errors / 0 warnings.
- ~~No automated tests~~ → 545 pytest tests in `tests/`, all offline, none of them touching your data.
- ~~A short source-language code made the default back-end refuse to translate~~ → fixed (found while
  writing the tests): `detect_language()` reports `zh`, while `deep-translator` only accepts `zh-CN` and
  fails with `No support for the provided language` *before* sending anything. All three translation entry
  points now pass the code through `normalize_language()`, so a hand written
  `translator.source_language = "zh"` works too.
- ~~A damaged file with a BOM aborted the whole import~~ → fixed: a BOM is read as UTF-8/16/32 with the
  wider encoding first (a UTF-32 BOM opens with the UTF-16 BOM bytes), and a family that fails to decode
  degrades to `(replaced)`; one bad file now lands in `failed` instead of killing the run.
- ~~Download-site names like `《Title》（校对版全本）作者：Someone.txt` parsed badly~~ → supported now, and a
  trailing `（…）` / `(...)` annotation is dropped from the title. Only *trailing* groups count, so a title
  such as `书名（中）下册` is left intact.
- ~~Overlong lines were silently truncated in the terminal~~ → fixed: the reader now **wraps to the
  terminal width** and measures in **display columns** (a CJK character counts as two, Latin text breaks
  at a space, tabs expand to 4 spaces, trailing spaces are dropped). One source line may occupy several
  screen rows, and the bookmark `★` is drawn only on that source line's first row.
- ~~The status bar / message row / confirm dialog still counted characters~~ → fixed: they now measure in
  display columns too (`_text_width` / `_clip_line` / `_pad_line`), so a narrow terminal no longer loses a
  whole row; `_addstr` additionally clips before writing, as a safety net.
- ~~The body background was locked to opaque black instead of following the terminal theme~~ → fixed by
  calling `start_color()` **and** `use_default_colors()` right after `initscr()` (they must be paired —
  `start_color()` on its own locks the default colours to black), and by never calling `init_pair()`, so
  `A_REVERSE` / `A_BOLD` / `A_DIM` highlighting keeps working.

---

## License

This project is released under the **MIT License**; the full text is in [LICENSE](LICENSE).

You may use, modify and redistribute it (commercially included) as long as the copyright notice and the
license text are kept. The copyright line currently reads `Copyright (c) 2026 wreader contributors` — if this is
your personal project, change that one line in `LICENSE` to your name or organisation; nothing else is affected.

---

## Related documents

- **[使用指南.md](使用指南.md)** — a from-zero, step-by-step walkthrough in Chinese: install Python, create the
  environment, import your first book, read with the keyboard, look up words, check the statistics, plus a
  troubleshooting table.
- **[README.md](README.md)** — the Chinese version of this file.









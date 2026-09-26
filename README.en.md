# wreader · a terminal novel reader

> Read txt / epub novels in your terminal: a fitted pager, a table of contents, search, bookmarks,
> reading statistics and 48 achievements.
> A pure Python CLI. Your books stay on your machine, and your progress and stats are remembered.

No mouse, no GUI. Drop your novels into a folder, type one command, and page through them in the terminal;
press `Tab` for the table of contents, `/` to search, `b` to bookmark a line; close the terminal and
the next launch resumes exactly where you stopped.

🌐 **中文**: [README.md](README.md) · **中文手把手教程**: [使用指南.md](使用指南.md) (Chinese only)

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Using werd in a new terminal](#using-werd-in-a-new-terminal)
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
| 🔖 Chapters | Chapter headings (`第一章`, `Chapter 1`, …) are detected at import time; press `Tab` while reading for a **table-of-contents overlay** (filter with `/`, jump with `Enter`), or list them with `werd toc <id>`; for epubs the book's own `nav` / `toc` titles win |
| 🔍 Search | Fuzzy library search over title, author and tags, with subsequence matching too (`hptr` finds *Harry Potter*) |
| 📖 Reader | A curses pager: line jumps, chapter jumps, highlighted search, bookmarks, a status bar and automatic progress saving; wraps to the terminal width (CJK counted as two columns) and follows the terminal theme / transparency |
| 📊 Statistics | Total / today / this week / this month / daily goal / streak / a 30-day heatmap; `--json` for scripts |
| 🏆 Achievements | **48** achievements (first book, night owl, hundred-day streak, weekend warrior, …) unlocked by **events**, with per-category progress bars, an unlock animation and a bell; press `?` inside the reader for the help page |
| ⚙️ Settings | One `settings.toml` for everything; `werd config` reads and writes it with typo suggestions; the old `config.json` is migrated automatically |
| 💾 Moving data | `werd data export` packs your reading time, progress, bookmarks and achievements into one JSON file, and `werd data import` merges it back on another machine (add-only); `werd prune` drops records whose text file is gone, `werd clear` empties the shelf (time and achievements stay) |

---

## Requirements

- **Python 3.11 or newer** (the standard library `tomllib` is used)
- **macOS / Linux**: `curses` ships with Python, so nothing extra is needed
- **Windows**: install `windows-curses` as well (see Installation)
- A UTF-8 capable terminal (required for Chinese books; the macOS Terminal, iTerm2 and Windows Terminal all qualify)
- **Fully offline by default**: nothing is sent anywhere, and the only optional network call is the
  geo lookup for the travel achievements (`stats.geo_lookup = false` turns even that off)

These third-party libraries are installed automatically:
`rich` (tables and progress bars), `chardet` (encoding detection) and `requests` (the optional geo lookup).

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
installs the dependencies, **sets up the `werd` alias** (appended to `~/.bashrc` or
`~/.zshrc` — running it twice will not add a second line) and finally checks the version:

```bash
werd --version        # werd 0.1.0
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

You now have the `werd` command **in the current terminal window**:

```bash
werd --version
# werd 0.1.0
```

</details>

### Using werd in a new terminal

`werd` lives inside the project's own `.venv`, and `.venv/bin` is not on `PATH` by
default. So **after you close the terminal and open a new one, typing `werd` fails
with `command not found`** — that is expected, and it does not mean the install is broken.

**If you installed with `./install.sh` you are already covered**: it wrote the alias into
`~/.bashrc` / `~/.zshrc` for you, so a new terminal simply works (the only thing you might
still need is `source ~/.zshrc`). The table below is for people who passed `--no-alias` or
installed by hand — pick whichever of the three you prefer:

| Option | What you type each time | Notes |
| --- | --- | --- |
| **① Add an alias** (recommended) | `werd read <id>` | Do it once; works in **every** new terminal |
| **② Use the full path** | `<project>/.venv/bin/werd read <id>` | Nothing to configure |
| **③ Activate the venv** | `cd <project>` → `source .venv/bin/activate` → `werd ...` | Fine if you work in the project anyway |

Option ① on macOS / Linux (zsh) is one line appended to `~/.zshrc`
(put in your real project path):

```bash
echo 'alias werd="$HOME/Downloads/wreader/.venv/bin/werd"' >> ~/.zshrc
source ~/.zshrc                       # takes effect now; or simply open a new window
werd --version                     # check: prints werd 0.1.0
```

With bash, use `~/.bashrc` instead; on Windows PowerShell, define a function of the
same name in `$PROFILE`.

> ⚠️ **Do not prepend `.venv/bin` to `PATH`** (`export PATH=".../.venv/bin:$PATH"`).
> That does make `werd` work, but it also turns `python3` and `pip` in every new
> terminal into this virtualenv's copies, which will confuse you in other Python
> projects. An alias adds one command and nothing else.
>
> `install.sh` follows the same rule: it always installs through `.venv/bin/python -m pip`
> and **never** adds `.venv/bin` to `PATH`.

> **Just passing through?** You can skip all of the above and write
> `python -m wreader.cli xxx` wherever this document says `werd xxx` — the two are
> equivalent. A beginner-oriented version of this section (including the Windows form and
> why your books and progress are unaffected) is in [使用指南.md](使用指南.md) (Chinese).

### Upgrading from the old `nr`

The tool used to be called `nr`. Nobody has to move anything by hand: the first
time `werd` runs, if `~/.wreader` does not exist yet and `~/.nr` does, the whole
old directory is moved into place — settings, library index and achievements state
included — and the old directory disappears.

| Old name | Now | Compatibility |
| --- | --- | --- |
| the `nr` command | `werd` | re-run `pip install -e .`; the old command goes away with the old distribution |
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
werd import ~/Downloads/books

# (3) see what is in the library and note the id
werd list

# (4) start reading (replace the id with the one you just saw)
werd read 3e027c4de949

# forgot which book you were on? this lists the three you opened most recently
werd continue
```

Real `werd import` output:

```
imported 2 book(s), skipped 0 duplicate(s), 0 failed
  + ab912556b66b  《Nameless》 unknown · 7 行 · 12 字 · ascii · 2 章
  + 3e027c4de949  《三体》 刘慈欣 · 281 行 · 2000 字 · utf-8 · 41 章
```

Real `werd list` output:

```
                              library (2 book(s))
┏━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ # ┃ id           ┃ title    ┃ author  ┃ progress ┃ words ┃
┡━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ 1 │ ab912556b66b │ Nameless │ unknown │     0.0% │    12 │
│ 2 │ 3e027c4de949 │ 三体     │ 刘慈欣  │     0.0% │  2000 │
└───┴──────────────┴──────────┴─────────┴──────────┴───────┘
```

What you see after quitting the reader with `q` (a dim summary line is printed in the ordinary terminal):

```
《三体》 · 停在 120/281 行 (42.7%) · 本次 12:30 · 书签 2 个
```

(Reader strings are Chinese: "title · stopped at line 120/281 (42.7%) · this session 12:30 · 2 bookmarks".)

---

## Command reference

At a glance:

| Command | What it does |
| --- | --- |
| `werd import <path>` | Scan a file or directory and import txt/epub books |
| `werd list` | List the books in the library |
| `werd search <keyword>` | Fuzzy search over title / author / tags |
| `werd read <book_id>` | Open the paged reader |
| `werd continue` | The three books you opened most recently (with their ids) |
| `werd stats` | Reading statistics and a heatmap (`--json` for scripts) |
| `werd achievements` | Achievement list and unlock progress |
| `werd werd` / `werd word` / `werd --werd` | The name easter egg (and the 名字彩蛋 achievement) |
| `werd toc <book_id>` | Show a book's table of contents (chapters + progress %); `--rebuild` re-parses it |
| `werd data export <file>` | Pack your reading time and achievements into one JSON file |
| `werd data import <file>` | Merge that bundle into this machine (add-only) |
| `werd prune` | Drop records whose converted text file no longer exists |
| `werd clear` | Empty the library (text files included; reading time and achievements are kept) |
| `werd config` | View or edit settings |

Exit codes: `0` on success; `1` for a bad argument or nothing found (`no book matches ...`)
(`Ctrl-C` gives `130`). Errors are always printed as `error: ...` — never as a raw traceback.

### `werd import <path>`

```bash
werd import ~/Downloads/books        # scan a whole directory recursively
werd import ~/Downloads/三体.txt     # or import a single file
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

### `werd list`

```bash
werd list
```

`progress` is the reading percentage; `words` is the word count formatted the Chinese way
(`5.7万` = 57k, `1.2亿` = 120M). An empty library tells you where the index and the novels directory live.

### `werd search <keyword>`

```bash
werd search 三体          # a Chinese keyword
werd search tolkien       # an author, case insensitive
werd search hptr          # subsequence match → Harry Potter
werd search '#fantasy'    # a leading # searches tags only
```

Ranking: exact match > prefix > contains (earlier hits score higher) > subsequence. A title match is
weighted twice as heavily as an author match. No match returns `1` with `no book matches ...`.

### `werd read <book_id>`

The heart of the tool; see [Reader key bindings](#reader-key-bindings) for every key.

- The book's language is detected on open (share of CJK characters, computed locally and offline), and the
  reader starts in the Chinese view for Chinese books and the English view for English ones.
- The reading position is saved every 60 seconds (configurable) and once more on exit.
- On exit, the session's duration and lines read are written to the statistics, and the
  `session_end` event goes to the achievements engine (the line ranges walked this session are
  folded into the word count with per-range deduplication, so re-reading a page adds nothing).
- Every `werd` start records a `daily_open` event (that is what "hundred-day streak" and "early
  bird" look at), and `werd import` records `book_add`.
- It **needs a real interactive terminal**; in a pipe or with redirected output you get:
  `error: werd read needs an interactive terminal (a tty on stdin and stdout)`

### `werd continue`

```bash
werd continue        # the three books you opened most recently (with ids)
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

Copy an `id` into `werd read` to pick up where you stopped. When nothing has been read yet it tells
you to pick a book with `werd list` (or import one) and still exits `0`.

> With the alias from [Using werd in a new terminal](#using-werd-in-a-new-terminal) in place,
> resuming after a reboot is two lines: `werd continue` for the shortlist, `werd read <id>` to open.

### `werd stats`

```bash
werd stats          # human readable table + heatmap
werd stats --json   # the same data as raw JSON, for scripts and dashboards
```

Real output:

```
总阅读时长 12小时34分钟
今日 45分钟 · 本周 5小时12分钟 · 本月 12小时34分钟
每日目标 1小时 · 今日 75% ✓
连续 3 天（每天 ≥30 分钟） · 读完 2 本
最近 30 天（2026-08-23 → 2026-09-21，每列一周，周一开始）
一   ░ · · ▒ ▓
二   · ▒ ░ · █
...
强度：·0 ░<20m ▒<40m ▓<1h █1h+
```

(In order: total reading time, today / this week / this month, the daily goal, the streak line,
then the 30-day heatmap with its legend.)

- Each heatmap **column** is one week (Monday on top, Sunday at the bottom); days outside the window are blank.
- `werd stats --json` top-level keys: `generated_at`, `today`, `total_seconds`, `total`, `today_seconds`,
  `week_seconds`, `month_seconds`, `daily_goal_seconds`, `goal_met`, `streak_days`, `streak_min_seconds`,
  `books_read`, `finished_books`, `night_seconds`, `longest_session_seconds`, `achievements`, `books`,
  `daily`, `heatmap`, `heatmap_grid`, plus two **legacy** keys — `vocab_count` (entries in an old
  `vocab.json`) and `translations` (the counter an old `library.json` kept). The reader no longer produces
  those two numbers, but they are still read and printed so existing dashboards keep working.
- The table and the JSON are rendered from the same dict, so the two can never disagree.

### `werd achievements`

```bash
werd achievements
```

Real output:

```
已解锁 1/48
  🏆 🗄️ 书库初成 书库里添加第 1 本书  解锁于 2026-09-21T16:13:43

进行中
  阅读习惯
    ░░░░░░░░░░░░░░  ⏱️ 初窥门径 0分钟/1小时  累计阅读满 1 小时
    ░░░░░░░░░░░░░░  🧱 百日筑基 3/100  连续 100 天打开 werd
    ...
  数据积累
    ██████░░░░░░░░  ✒️ 万字户 4200/10000  累计阅读 1 万字
    ...
```

(`1/48 unlocked` and the unlocked entries with their timestamps, then `进行中` = "in progress": the
remaining ones grouped by category, one progress bar each.)

### `werd config`

```bash
werd config                            # print every setting (value / default / source file)
werd config --path                     # print just the settings file path
werd config reader.page_height         # read one setting
werd config reader.page_height 30      # write one setting (saved immediately)
werd config --reset                    # restore every default
```

Real interactions:

```
$ werd config reader.page_height
reader.page_height = 24

$ werd config reader.page_height 30
reader.page_height = 30 (saved)

$ werd config reader.pag_height 20
error: unknown setting 'reader.pag_height' (did you mean 'reader.page_height'?)
```

Settings are addressed by **dotted path** (`reader.page_height`); the flat names of the old `config.json`
(`page_height`, `novels_dir`, …) still resolve and are migrated into the right section.
A typo produces a suggestion instead of being written to the file, and a type mismatch (say `abc` for a
boolean) is refused with the file left untouched.

### `werd toc <book_id>`

```bash
werd toc 3e027c4de949            # list the chapters, with their start line and progress %
werd toc 3e027c4de949 --rebuild  # ignore the cache, re-parse the text and rewrite it
```

- Chapters are found by **regex on the heading** (`第一章`, `Chapter 1`, `第N节`, `卷X`, …); for epubs the
  book's own `nav.xhtml` / `toc.ncx` titles are preferred (the regex is the fallback when no line mapping
  is available).
- The result is cached at `~/.wreader/cache/<book_id>_toc.json` and **rebuilt automatically whenever the
  converted text changes** (its mtime is the stamp), so there is nothing to clean up; use `--rebuild` to
  force it.
- Nothing detected, or a heading style the built-ins miss (`### 楔子`)? Add a regex in `[toc]`:
  ```bash
  werd config toc.patterns '^### |^第.+回'
  ```
- `Tab` in the reader opens the very same table of contents (plus a live filter).

### `werd data export <file>` / `werd data import <file>`

```bash
werd data export ~/werd-data.json     # pack reading time and achievements into one JSON file
# copy the file to the new machine (USB stick / cloud drive / scp), then run:
werd data import ~/werd-data.json     # merge it into this machine, add-only
```

The bundle carries your **reading record**: total and daily time, per-book progress (line, percentage,
time) and bookmarks, plus the achievement state and event counters. It contains **no book text and no
settings** — run `werd import` for the books themselves on the new machine.

- Merging is **add-only**: durations and event counters add up (importing the same bundle twice counts it
  twice — that is the "incremental merge" reading), sessions are deduplicated by content (a second import
  does not add a phantom session), bookmarks are unioned, a book's "finished" flag never flips back once
  true, and a reading position is adopted only when this machine has **no record at all** for that book.
- A book you imported but **never actually read** does not go into the bundle (there is no progress, time
  or bookmark to move), so the count inside the bundle can be lower than in `werd list`.
- A book is identified by `book_id` (the SHA-1 of its text), so **same text, same id**: run `werd import`
  on both machines and the records line up. Books that this machine does not have are skipped and counted,
  so you can import the books and run the command once more (the global time is merged either way, so the
  trip is not wasted).
- The bundle is plain UTF-8 JSON — readable at a glance and editable by hand:

```json
{
  "kind": "werd-data",
  "version": 1,
  "exported_at": "2026-09-26T21:03:11",
  "summary": { "books": 2, "unlocked": 7, "total_read_time": 43200 },
  "reading": {
    "total_read_time": 43200,
    "daily_read_time": { "2026-09-26": 3600 },
    "books": {
      "3e027c4de949": {
        "title": "三体",
        "total_time_seconds": 3600,
        "current_line": 120,
        "percentage": 42.7,
        "bookmarks": [120],
        "finished": false,
        "sessions": [{ "start": "2026-09-26T20:00:00", "end": "2026-09-26T21:00:00", "lines_read": 120 }]
      }
    }
  },
  "achievements": { "version": 1, "unlocked": [], "counters": {}, "metrics": {}, "books": {} }
}
```

- Importing the wrong file cannot break anything: a missing file, broken syntax, a file that is not a
  `werd` bundle, or a `version` newer than this build makes the command print one `error: ...` line and
  exit `1`, leaving your local data untouched.

### `werd prune`

```bash
werd prune
```

```
已清理 1 个失效书目（正文文件已被删除）：
  三体 3e027c4de949
```

(The output is Chinese: "pruned 1 dead record (its text file was deleted): 三体 3e027c4de949".)

`file_path` is a record's only evidence: once you delete the converted text from `~/novels` by hand, that
record can never be read again. `werd prune` drops those dead records from the index. In practice you
rarely need it — **every command reconciles the index first** and prints a one-line notice — so use it when
you want an explicit cleanup, or to see which titles went away.

### `werd clear`

```bash
werd clear
```

```
已清空书库：2 本书及其正文文件已删除
阅读时长与成就已保留（werd stats 仍然可用）
```

("Library emptied: 2 books and their text files were deleted. Reading time and achievements kept, so
`werd stats` still works.")

This empties the shelf: every book in the index goes, **and so do the converted text files** (the original
ebooks live wherever you keep them and are none of `werd`'s business). Total time, the daily buckets and
the achievement state all stay: what the command forgets is *which books you have*, not *how long you
read*.

---

## Reader key bindings

The hint bar **at the bottom of the reader shows this list by default** (a transient message temporarily
replaces it), so there is nothing to memorise:

```
q退出 j/space翻页 g跳行 [/]章节 Tab目录 /搜索 n下一个 b书签 ?帮助
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
| `Tab` | Open the **table-of-contents overlay** (right 40% of the screen): `↑↓` to move, `Enter` to jump, `/` to filter live, `q` / `Esc` to close; the text on the left dims but stays put |
| `/` | Search (Chinese input works); jumps to the first hit and highlights all of them |
| `n` | Next hit (wraps around) |
| `b` | Toggle a bookmark on the current line; the status bar shows how many you have |
| `?` | Open the **help page** (a centred overlay; `↑↓` / `j` / `k` scroll, `q` / `Esc` / `Enter` close): every key binding — paging, chapters, search, bookmarks — plus where the settings file lives |

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
  or a transient message such as `已加书签：第 42 行` ("bookmarked line 42") when there is one.
- **An unlock while reading flashes a plate in the top right corner** (`🏆 成就解锁 · <name>` plus a dim
  line), stays for **five seconds** and then disappears on its own: no key press is swallowed and nothing
  blocks the loop. ⚠️ On a terminal too small for it (narrower than 24 columns or shorter than 6 rows) the
  message drops to the hint row instead of vanishing.
- **An unexpected interruption (crash, power cut, `kill`)** makes the next start of the **same book** ask
  `上次好像没有正常退出 · 上次读到第 N 行`: `y` resumes at that line, any other key starts from the top.
  After a clean exit (`q` / `Ctrl-C`) the question never comes back. The marker lives in
  `~/.wreader/reading_session.json` and is refreshed on every `reader.auto_save_interval`; deleting it only
  costs you that one resume offer, never the position stored in the library index.
- **The leftmost column of every text row is the bookmark gutter**: bookmarked lines show `★`, other rows are blank.
- **Search highlighting**: the hit you jumped to is in reverse video, the other hits in the same set are bold.
- **`Ctrl-C` mid-session loses nothing**: the position and the session duration are still saved on the way out.

---

## Settings

Everything lives in `~/.wreader/settings.toml`, split into 4 sections (`reader` / `stats` / `library` / `toc`,
16 entries). Edit the file directly, or use `werd config <section.key> <value>`.
**Deleting any line falls back to that setting's default**, so you cannot really break it.

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

`status_bar_format` understands 9 segments, joined into `segment1 · segment2 · segment3`:

| Token | Shows |
| --- | --- |
| `time` | Current time, `21:34` |
| `book` | Book title |
| `chapter` | Current chapter title (`无章节` when the book has no chapters) |
| `position` | `行 120/281` (line 120 of 281) |
| `percent` | `42.7%` |
| `duration` | `本章 05:20` (time in this chapter) |
| `elapsed` | `本次 12:30` (time this session) |
| `streak` | `连续 3 天` (3-day streak) |
| `bookmarks` | `书签 2` (2 bookmarks) |

An unknown token is silently skipped rather than printed raw; if no segment resolves at all, the bar falls
back to showing just the clock. Segments are dropped **whole from the tail** when the line is too narrow,
never cut in half.

### `[stats]`

| Key | Default | Meaning |
| --- | --- | --- |
| `daily_goal_minutes` | `60` | Daily reading goal in minutes; `0` hides the goal line |
| `show_heatmap` | `true` | Show the 30-day heatmap in `werd stats` |
| `achievement_sound` | `true` | Ring the bell (`\a`) when an achievement unlocks; set `false` if your terminal is loud |
| `geo_lookup` | `true` | Look this machine's location up online (for the geography achievements). Set it to `false` to stay **fully offline**: the cache is not refreshed either, so those achievements simply stop moving |

### `[library]`

| Key | Default | Meaning |
| --- | --- | --- |
| `novels_dir` | `""` | Directory for the UTF-8 text; empty means `~/novels` |

### `[toc]`

| Key | Default | Meaning |
| --- | --- | --- |
| `patterns` | `""` | **Extra** chapter-heading regexes; separate several with `\|` (the built-ins always apply), for styles like `### 楔子` |
| `cache_dir` | `""` | Directory for the chapter cache; empty means `cache/` under the data directory (the cache file is `<book_id>_toc.json`) |

---

## File locations

| What | Path (macOS / Linux) | Overridable by |
| --- | --- | --- |
| Settings | `~/.wreader/settings.toml` | `$WREADER_HOME` |
| Library index | `~/.wreader/library.json` | `$WREADER_HOME` |
| Achievements state | `~/.wreader/achievements.json` | `$WREADER_HOME` |
| Reading session marker | `~/.wreader/reading_session.json` ("I am reading this book"; deleted on a clean exit, kept after a crash so the next start can ask whether to resume) | `$WREADER_HOME` |
| Location cache | `~/.wreader/geo.json` (the ip-api answer, cached for an hour; deleting it just means one more lookup) | `$WREADER_HOME` |
| Chapter cache | `~/.wreader/cache/<book_id>_toc.json` (the extracted chapters; rebuilt automatically as soon as the text changes) | `toc.cache_dir` |
| Book text (UTF-8) | `~/novels/<title>_utf8.txt` | `$WREADER_NOVELS_DIR`, `library.novels_dir` |

On Windows the data directory is `%APPDATA%\wreader`.

The file written by `werd data export` is **not** in there: it is an ordinary JSON file and you choose
where it goes on the command line (see `werd data export` / `werd data import` above).

Two environment variables:

```bash
export WREADER_HOME=~/my-wreader-data    # move the whole data directory (tests / several profiles)
export WREADER_NOVELS_DIR=~/my-novels    # move the novels directory
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
- `tags` is consumed by `werd search '#tag'`, but there is no CLI command to add tags yet — edit the index by hand.

### `~/.wreader/cache/<book_id>_toc.json` — the chapter cache

The extracted chapters (title + starting line) cached as one small JSON file.

- It is per book, deleting it affects nothing else, and it is rebuilt automatically the next time.
- **It is rebuilt as soon as the converted text's mtime changes**, so there is nothing to clean by hand;
  `werd toc <id> --rebuild` forces it now.
- Older versions may also have left a `cache/<book_id>/` directory behind (the old translation cache) —
  no code reads it any more, feel free to delete it.

### Legacy files: `vocab.json` and `notes/`

The vocabulary notebook (`~/.wreader/vocab.json`) and the notes (`~/.wreader/notes/*.md`) of older
versions are **no longer written by the program**, but the achievement engine still counts them
**read-only**:

- entries with a `word` in `vocab.json` → the `vocab_count` metric (`werd stats --json` still prints it);
- headings like `## 笔记 #N` in `notes/*.md` → the `notes_count` metric (that is what 「笔记达人」 watches).

So the words and notes you recorded earlier are **not wasted**: the files are there, the progress is
there, and sections you typed into the markdown by hand count too.
Both files can be deleted at any time (the metric drops to zero immediately; unlocked achievements stay unlocked).

The old format looked like this (this file is now only read, never rewritten):

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

Both old shapes are accepted when counting: a top-level array, or the `{"words": [...]}` wrapper; an
entry without a `word` does not count.

---

## Achievements

Defined in `wreader/data/achievements.json`; there are **48** of them (28 from Phase 1, one from the
notes phase, 19 from Phase 2/3), in five categories. A condition is a simple
`metric comparison number` expression, so you can add your
own. The **unlock records** live in `~/.wreader/achievements.json` (plain JSON, editable).

### Data (19)

| Achievement | Name | Condition |
| --- | --- | --- |
| `first_book` | 📖 开卷有益 | Open a book for the first time |
| `book_finished` | 🏁 第一本 | Finish your first book |
| `ten_books` | 📚 十本大关 | Finish 10 books |
| `fifty_books` | 🎯 半百 | Finish 50 books |
| `hundred_books` | 💰 百本富翁 | Finish 100 books |
| `thousand_books` | 🏛️ 千本富豪 | Finish 1000 books |
| `first_shelf` | 🗄️ 书库初成 | One book in the library |
| `collector` | 📦 藏书家 | 50 books in the library |
| `mobile_library` | 🚚 移动图书馆 | 100 books in the library |
| `words_10k` | ✒️ 万字户 | 10,000 words read |
| `words_100k` | ⛰️ 十万大山 | 100,000 words read |
| `words_1m` | 💵 百万富翁 | One million words read |
| `words_10m` | 🎩 千万俱乐部 | Ten million words read |
| `words_100m` | 👑 亿万富豪 | 100 million words read |
| `words_1b` | 🌌 十亿富豪 | A billion words read |
| `vocab_100` | 📝 词汇积累 | 100 entries in the old `vocab.json` (**read-only**: the reader no longer writes it) |
| `vocab_500` | 🧠 生词狂魔 | 500 entries in the old notebook (**read-only**) |
| `translator` | 🌍 双语者 | `stats.translations >= 1` in the old `library.json` (**read-only**, a historical record) |
| `note_master` | 🖊️ 笔记达人 | 50 notes in total (counted from `notes/*.md`, hand written ones included) |

### Reading habits (10)

| Achievement | Name | Condition |
| --- | --- | --- |
| `first_hour` | ⏱️ 初窥门径 | One hour of total reading |
| `ten_hours` | 🎓 学富五车 | Ten hours of total reading |
| `night_owl` | 🌙 深夜书虫 | More than an hour read between 00:00 and 04:00 |
| `streak_7` | 🔥 七日不断 | Seven days in a row with 30 minutes each |
| `streak_30` | 🗿 铁血读者 | Thirty days in a row of reading |
| `hundred_days` | 🧱 百日筑基 | Open werd on 100 days |
| `early_bird` | 🌅 清晨第一眼 | Open werd between 05:00 and 07:00 |
| `marathon` | 🏃 马拉松 | A single session longer than two hours |
| `ultra_marathon` | 🛌 超长待机 | A single session longer than four hours |
| `weekend_warrior` | ⚔️ 周末战士 | Three hours of weekend reading (Saturday or Sunday) |

### Key tricks (5)

| Achievement | Name | Condition | How |
| --- | --- | --- | --- |
| `space_combo` | 👏 手速达人 | `space_combo >= 100` | 100 consecutive **spaces** in a row (any other key breaks the run) |
| `page_streak` | 🌀 翻页永动机 | `page_streak >= 500` | 500 consecutive page turns (`j` / space / Enter / arrow keys / PgUp / PgDn) |
| `arrow_chapters` | 🕹️ 方向键怀旧 | `arrow_chapters >= 1` | A whole chapter paged with **arrow keys only** (at least five presses, no `j`/`k`/space/Enter/`[`/`]`/`Tab`) |
| `translate_maniac` | 🔤 翻译狂魔 | `translate_hits >= 100` | 100 presses of the translation keys in total (⚠️ the reader's `t` / `T` are gone, so this only counts what an older version left behind) |
| `help_fan` | ❓ 帮助迷 | `help_opens >= 1` | Open the help page with `?` |

### Tough ones (4)

| Achievement | Name | Condition | How |
| --- | --- | --- | --- |
| `tiny_terminal` | 🪡 极限尺寸 | `narrow_seconds >= 300` | Shrink the terminal to **≤ 40 columns** and read for five minutes in it |
| `narrow_chapter` | 📐 窄屏挑战 | `narrow_chapters >= 1` | Finish a chapter in a window of **≤ 60 columns** |
| `recovery_master` | 🧯 恢复大师 | `crash_recovers >= 3` | Be interrupted three times and pick `y` (resume) each time |
| `changed_mind` | 🙃 我反悔 | `recover_declined >= 1` | Decline the resume offer and start over |

### Hidden (10) — shown as "❓" until they fire

| Achievement | Name | Condition | How |
| --- | --- | --- | --- |
| `geo_continents` | 🌏 环游亚欧非美大洋 | `geo_continents >= 5` | Read on five continents (the location follows your IP) |
| `geo_citizen` | 🛂 世界公民 | `geo_countries >= 3` | Read in three or more countries or regions |
| `geo_feud` | 🏰 百年世仇 | `geo_feud >= 1` | Read in both Britain *and* France (other old feuds are listed in `geo.py`) |
| `holiday_reader` | 🎆 节日读者 | `holiday_opens >= 1` | Open werd on a holiday (New Year, Spring Festival, Christmas …) |
| `name_egg` | 🥚 名字彩蛋 | `easter_eggs >= 1` | Type `werd werd`, `werd word` or `werd --werd` |
| `achievement_hunter` | 🏹 成就猎人 | `achievement_views > 10` | Open `werd achievements` more than ten times |
| `env_cloud` | ☁️ 云端书虫 | `env_cloud >= 1` | Read on a cloud host (AWS / GCP / Alibaba Cloud …) |
| `env_wsl` | 🪟 穿越子系统 | `env_wsl >= 1` | Read inside Windows' WSL |
| `env_tmux` | 🧅 套娃终端 | `env_tmux >= 1` | Read inside tmux / screen |
| `env_editable` | 🧑‍💻 开发者模式 | `env_editable >= 1` | Read with a `pip install -e` checkout |

Available metrics:

| Metric | Meaning | Comes from |
| --- | --- | --- |
| `books_read` / `finished` | books read / books finished | the library index |
| `total_time` / `night_time` / `single_session` / `weekend_time` | total / night / longest session / weekend seconds | index + achievements state |
| `streak` | consecutive days | the daily buckets in the index |
| `vocab_count` / `translations` | notebook words / translation uses (**historical, read-only**: counted from the old `vocab.json` / `library.json`; the reader produces neither number any more) | notebook + index |
| `library_books` | books in the library | the library index |
| `words_read` | words read, **deduplicated by line range** | achievements state |
| `days_opened` / `early_open` | days werd was opened / whether it was opened at dawn | achievements state |
| `notes_count` | how many notes were written in total (counted from `notes/*.md`, **read-only**) | notes directory |
| `space_combo` / `page_streak` | longest run of spaces / longest run of page turns | achievements state (reported live by the reader) |
| `arrow_chapters` / `translate_hits` | chapters read with arrow keys only / translation key presses (no key can fire the latter any more, only the old count is kept) | achievements state (reported live by the reader) |
| `narrow_seconds` / `narrow_chapters` | seconds read in a ≤40 column window / chapters finished in a ≤60 column one | achievements state (reader) |
| `help_opens` | how often the help page was opened | achievements state |
| `crash_recovers` / `recover_declined` | times an interrupted session was resumed / restarted | achievements state |
| `achievement_views` | times `werd achievements` was opened | achievements state |
| `geo_countries` / `geo_continents` / `geo_feud` | countries / continents visited, whether a feud pair is complete | achievements state (location probe) |
| `holiday_opens` / `easter_eggs` | days opened on a holiday / easter eggs triggered | achievements state |
| `env_cloud` / `env_wsl` / `env_tmux` / `env_editable` / `env_flags` | whether you read on a cloud host / WSL / tmux / an editable install (each 0 or 1) plus the total | achievements state (environment probe) |

Word counting: **one Chinese character is one word, one English token is one word**; punctuation
and digits do not count. Reading the same passage twice adds nothing, because every book keeps the
line ranges that were already counted.

Unlocking is **event driven**: every module calls
`achievements.check_achievements(event, data)` with one of `daily_open` (every `werd` start),
`session_end` (leaving the reader: duration, the line ranges walked and the key/size counters
collected during the session), `book_add` (`werd import`), `progress_update`, `book_finish`,
`key` / `resize` (live key presses and terminal resizes in the reader),
`help`, `recover` (the crash recovery prompt), `geo_change` (location probe), `env` (environment
probe), `name_egg`, `achievements_view`, or a plain `check` (just re-evaluate now — old scripts still
use it). `word_add` / `note_add` (a vocabulary word / note was written) **stay on the whitelist** but
nothing calls them any more: they exist as a compatibility entry point for older scripts, and dropping
the names would break callers still using them.
An achievement never fires twice, and the whole
read-record-check-write cycle runs under a **file lock**, so two terminals cannot clobber each
other (Windows has no `flock`; there the write stays atomic but unlocked).

The reader does **not** write to disk on every keystroke: it keeps its own running totals
(`Pager.metric_values`) and only hands the deltas to the engine when it *just* crossed one of the
achievement thresholds — which is exactly when the in-screen notice belongs on screen. Whatever
never reached a threshold is handed over in one go with `session_end`, so nothing is lost. The
threshold table comes from the definitions themselves (`achievements.metric_thresholds`), so an
achievement **you** add fires live as well.

The streak rule: a day only counts once it reaches 30 minutes, but today always counts — it is about to
become a fact. Unlocking prints an animation and a banner; `stats.achievement_sound = false` silences the bell.
Unlocks that happen while reading first flash the in-screen notice (5 seconds, no key presses swallowed)
and are celebrated again with the full animation when you leave the reader.

---

## Project layout

```
wreader/
├── pyproject.toml           packaging (dependencies, console script, LICENSE, [tool.pytest], [tool.pyright])
├── LICENSE                  MIT license
├── README.md                中文说明 (Chinese)
├── README.en.md             this file
├── 使用指南.md               step-by-step beginner guide (Chinese only)
├── install.sh               one-shot installer: venv, dependencies, werd alias (idempotent)
├── tools/                   development-time checks: doc anchors, doc numbers, wrapping, drawing, colours (see tools/README.md)
├── .vscode/settings.json    points Pylance / the terminal at the .venv interpreter
├── wreader/
│   ├── __init__.py          __version__ and the module map (22 lines)
│   ├── achievements.py      the achievement engine: events, the state file, unlock checks, live thresholds, file lock (1250 lines)
│   ├── cli.py               argparse definition + one handler per sub-command (1004 lines)
│   ├── config.py            settings.toml I/O, type checks, legacy migration, data dir adoption (966 lines)
│   ├── env.py               environment probe: cloud host / WSL / tmux / editable install (183 lines)
│   ├── geo.py               location: ip-api lookup + a one hour cache, country → continent, feud pairs (343 lines)
│   ├── library.py           txt/epub import, encoding detection, file name parsing, index (1425 lines)
│   ├── lock.py              the cross-process file lock (flock; atomic writes only on Windows) (80 lines)
│   ├── reader.py            the curses pager: paging, search, bookmarks, status bar, wheel/touch, toc overlay, help page and notices (2799 lines)
│   ├── stats.py             metrics, heatmap, achievement definitions, celebration (817 lines)
│   ├── toc.py               table of contents: chapters, epub nav parsing, rebuildable cache (474 lines)
│   ├── transfer.py          the `werd data` bundle: export reading time + achievements to JSON, merge add-only (198 lines)
│   └── data/
│       └── achievements.json  the 48 achievement definitions (348 lines)
└── tests/                   592 tests, all offline (see "Running the tests" below)
    ├── conftest.py          shared fixtures: isolated $WREADER_HOME, library samples, epub builder
    ├── test_achievements.py 51 tests — word counting, range dedup, event accounting, state file, locking, unlock checks, live thresholds, geo/env metrics
    ├── test_cli.py          45 tests — argument parsing, every sub-command's output, exit codes, the achievement banner, the name egg
    ├── test_config.py       49 tests — defaults, type checks, legacy migration, data dir adoption, directory resolution
    ├── test_env.py          14 tests — cloud host / WSL / tmux / editable install probing (all injected)
    ├── test_geo.py          31 tests — country → continent, feud pairs, ip-api parsing, caching, offline fallback
    ├── test_library.py      132 tests — encodings, chapters, epub, dedup, file names, search, recent books, clear/prune, merging a bundle
    ├── test_reader.py       174 tests — paging maths, Pager, status bar, keys, sessions, wrapping, wheel, toc overlay,
    │                          help page, achievement notice, recovery flow
    ├── test_stats.py        70 tests — metrics, streaks, heatmap, definition loading, the report
    ├── test_toc.py          18 tests — chapter extraction, epub nav/ncx, custom regexes, cache invalidation
    └── test_transfer.py      8 tests — exporting a bundle, importing on a fresh machine, add-only merging, error cases
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
werd --help
werd list

# experiment without touching your real data: point the environment elsewhere
export WREADER_HOME=/tmp/wreader-sandbox WREADER_NOVELS_DIR=/tmp/wreader-sandbox/novels
werd import /tmp/my-test-books
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
pytest                      # 592 tests, about 15 seconds
pytest -q tests/test_reader.py            # one file
pytest -k "streak or heatmap" -q          # by name
```

A few conventions the suite follows, which are worth knowing before you change code:

- **It never touches your real data.** The autouse fixture in `tests/conftest.py` points
  `$WREADER_HOME` / `$WREADER_NOVELS_DIR` at a `tmp_path` and clears the `wreader.config` cache,
  so every test starts clean.
- **It never reaches the network.** The only thing that would go out is the location lookup behind the
  geography achievements, and every test injects a fake response (the request function in `wreader.geo`
  is monkeypatched); the real `ip-api` payload is only used for the offline parsing tests. To prove
  nothing slipped through, run the suite behind a dead proxy:
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
python tools/verify_draw.py           # nothing drawn past the edge (expects OK: 140 draw checks passed)
python tools/verify_mouse.py          # real pty: wheel / touch dragging (expects RESULT: 全部通过)
python tools/verify_achievements.py   # real pty: help page, the 5 second notice, crash recovery, the name egg
script -q /dev/null python tools/verify_colors.py   # colours (needs a pty)
```

Each one works out the repository root itself, so it can be run from any directory;
exit code 0 = pass, 1 = something to look at. See [tools/README.md](tools/README.md).

---

## FAQ

**Q: After opening a new terminal, `werd` says command not found?**
The most common report — and **not** a broken install: `werd` lives in the project's own `.venv`,
whose `bin` directory is not on `PATH` by default. If you installed with `./install.sh` the alias is
already in place, so just run `source ~/.zshrc` (or `~/.bashrc`) or open another terminal; if it still
fails you either passed `--no-alias` or installed by hand — see
[Using werd in a new terminal](#using-werd-in-a-new-terminal). Alternatively call
`<project>/.venv/bin/werd` directly, run `source .venv/bin/activate` first, or simply write
`python -m wreader.cli xxx` instead of `werd xxx`.

**Q: Where did my library go after upgrading?**
The first run of `werd` moves `~/.nr` into `~/.wreader` for you. When both directories exist, `werd`
only ever uses `~/.wreader` and leaves `~/.nr` alone — delete it yourself once you are happy with the new one.

**Q: `path does not exist` / `no .txt/.epub file found under ...` on import?**
Either the path is wrong, or the directory really holds no `.txt` / `.epub`. `werd import` scans recursively,
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

**Q: `t` used to translate and `v` used to save a word — where did they go?**
Translation, the vocabulary notebook and the notes panel have been **removed** from both the reader and
the command line (code, key bindings and sub-commands are gone). Data you recorded earlier is not
deleted: `~/.wreader/vocab.json` and `~/.wreader/notes/*.md` are still counted **read-only** by the
achievement engine, so the progress of 词汇积累 / 生词狂魔 / 双语者 / 笔记达人 survives. Delete those
two files to clear them out completely (already unlocked achievements stay unlocked).

**Q: `werd read` says `needs an interactive terminal`.**
The reader must run in a real terminal: no `| less`, no redirection, no CI.
(`werd list` / `werd stats` and friends are happy to be redirected.)

**Q: The statistics did not change after a session.**
Check two things: is `reader.store_history` still `true`, and was the session saved at all (a read-only disk
or an unwritable data directory fails silently).

**Q: The streak already says 1 after a short session.**
Today always counts — it is about to become a fact. The real threshold is 30 accumulated minutes on a day.

**Q: I want silent reading: no statistics, no bell.**
```bash
werd config reader.store_history false
werd config stats.achievement_sound false
werd config stats.show_heatmap false
```

**Q: I deleted a book file but the index still lists it.**
There is no CLI command for that yet. Delete the key under `books` in `library.json` (`werd list` stops showing
it immediately), or use Python:
```python
from wreader import library
library.remove_book("3e027c4de949")   # also deletes the UTF-8 text under ~/novels
```

**Q: I broke `settings.toml`.**
`werd config --reset` restores every default, or delete the file and it is regenerated. Deleting a single line
just reverts that one setting.

---

## Known issues

These are the limitations that genuinely exist today; better to write them down than to hide them:

- **`reader.theme` is not implemented** — changing it has no effect.
- **No CLI command to add tags.** `books[].tags` and `werd search '#tag'` work, but for now you edit `library.json`.
- **EPUB parsing is a trade-off**: without Calibre's `ebook-convert` the built-in extractor only keeps body text,
  so images, footnotes and complex layout are lost. Installing Calibre is recommended.
- **`werd read` only works in a real terminal** (see the FAQ above).
- **Windows needs the extra dependency** `windows-curses` (`pip install -e ".[windows]"`).
- **Numeric values under `progress` in `library.json` are not coerced**: a hand written string
  (`"current_line": "12"`) still works because every consumer wraps it in `int(...)`, but it is not
  turned back into a number for you.
- **Translation / the notebook / notes have been removed**: the `werd translate`, `werd vocab` and
  `werd notes` sub-commands are gone, as are the reader's `l` / `c` / `t` / `T` / `v` / `m` / `o` keys,
  and so are `wreader/translator.py`, `wreader/translate/`, `wreader/vocab.py` and `wreader/notes.py`.
  The old data files are still there, but only counted **read-only** for achievements (see the FAQ above
  and [Data formats](#data-formats)).
- **The geography achievements need the network** (one HTTP request, cached for an hour): they ask
  `ip-api.com` for the country / city / timezone only. Setting `stats.geo_lookup = false` keeps everything
  offline — those achievements simply stay locked, and nothing else changes. Being behind a captive portal,
  a proxy or no network at all just makes the probe skip silently.
- **The lunar holidays in “节日读者” are only tabulated up to 2030**: Spring Festival and Mid-Autumn fall on
  a different Gregorian date each year, and the table (`achievements.LUNAR_HOLIDAYS`) is written from the
  published calendars. From 2031 on the fixed-date holidays (New Year, Christmas, …) still work, but those
  two need somebody to add the new dates.
- **Crash recovery only ever offers the *same* book**: the marker records the book id, so opening another
  book simply overwrites it instead of jumping to somebody else's line. The marker is plain JSON
  (`~/.wreader/reading_session.json`) and safe to delete.

Ten former issues that are now fixed, kept here so they are not mistaken for pending work:

- ~~No LICENSE~~ → MIT added (`LICENSE` plus `license = "MIT"` in `pyproject.toml`).
- ~~`translator.__all__` listed a non-existent `chapter_paragraphs`~~ → that module was deleted along with
  the translation feature, so the problem no longer exists.
- ~~About 10 type warnings in `library.py` / `stats.py` / `translator.py` / `vocab.py`~~ → all fixed;
  `pyright` now reports 0 errors / 0 warnings (`translator.py` / `vocab.py` went away with the feature).
- ~~No automated tests~~ → 592 pytest tests in `tests/`, all offline, none of them touching your data.
- ~~A short source-language code made the default back-end refuse to translate~~ → that code path was
  removed together with the translation feature (the discovery back then, while writing the tests:
  `detect_language()` reports `zh`, while `deep-translator` only accepts `zh-CN`).
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
  environment, import your first book, read with the keyboard, check the statistics, plus a
  troubleshooting table.
- **[README.md](README.md)** — the Chinese version of this file.









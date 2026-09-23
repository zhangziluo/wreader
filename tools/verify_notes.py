# -*- coding: utf-8 -*-
"""在真 pty 里验证「标记模式 + 笔记面板」端到端真的能用。

为什么需要它：笔记面板会真的建两个 curses 子窗口、跑 ``curses.textpad.Textbox``，
而且**必须"主窗口先刷、子窗口后刷"**才不会被 ``stdscr.erase()`` 擦掉 ——
这些在 ``FakeStdscr`` 的单元测试里盖不到底（假窗口没有真正的 curses 叠窗语义）。
另外面板的 ``Ctrl+S`` 依赖 ``_disable_flow_control()`` 真的把 ``IXON`` 关掉，
否则终端会把 XOFF 吃掉、保存键永远到不了程序（单元测试也不会经过行规程）。

所以这个脚本开一个真 pty、跑一次阅读器、按一串键，再把终端输出读回来对账：
引用区画出了 ``> …``、Ctrl+S 真的存下了（顺带证明 IXON 关掉了）、
面板折叠后提示行显示笔记计数、整个过程没有 traceback。

用法：python tools/verify_notes.py
退出码：0 = 全部通过，1 = 有对不上的项（会打印期望的片段与实际输出尾巴）。
"""
import fcntl
import json
import os
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent
# 当前解释器（应该就是项目虚拟环境里的那个）
PY = sys.executable

# 第一行放一句好认的中文，方便断言"引用区把选中的文字画出来了"
FIRST_LINE = "第一章 测试开头"

# 失败项收集，最后统一报告
failures: list[str] = []


def build_sandbox() -> tuple[Path, dict[str, str], str]:
    """造沙箱数据目录 + 一本书并导入，返回 ``(目录, 环境变量, 书 id)``。"""
    # 独立的临时"家目录"，绝不碰真实数据
    home = Path(tempfile.mkdtemp(prefix="wreader-notes-"))
    novels = home / "novels"
    novels.mkdir(parents=True, exist_ok=True)
    # 一本小书：第一行是断言用的那句话，后面再补一些普通行
    book = novels / "笔记校验-测试作者.txt"
    lines = [FIRST_LINE] + ["第 {:03d} 行内容".format(i) for i in range(200)]
    book.write_text("\n".join(lines), encoding="utf-8")
    # 子进程环境：指向沙箱 + 让子进程能 import wreader
    env = dict(os.environ)
    env.update(
        {
            "WREADER_HOME": str(home),
            "WREADER_NOVELS_DIR": str(novels),
            # 非交互运行时 TERM 可能没设，curses 会起不来 —— 显式给一个
            "TERM": env.get("TERM") or "xterm-256color",
            "PYTHONPATH": str(ROOT),
        }
    )
    subprocess.run(
        [PY, "-m", "wreader.cli", "import", str(book)], env=env, capture_output=True
    )
    # 导入后索引里应该只有这一本
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    book_id = next(iter(document["books"]))
    return home, env, book_id


def drain(fd: int, sink: list[str], pause: float) -> None:
    """边等边把 pty 的输出读出来（不读会写满缓冲区把子进程卡住）。"""
    # 先歇一下，让子进程把这一帧画完
    time.sleep(pause)
    while True:
        # 0.1 秒没新数据就当这一轮读完了
        ready, _, _ = select.select([fd], [], [], 0.1)
        if not ready:
            return
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            return
        # 读到 EOF 说明子进程没了
        if not chunk:
            return
        # 终端里全是转义序列，解码时用 replace 兜住被截断的多字节字符
        sink.append(chunk.decode("utf-8", "replace"))


def run_notes_case(env: dict[str, str], book_id: str) -> str:
    """跑一次阅读器、走完整套笔记操作，返回读回来的终端输出。

    按键顺序：``m`` 进标记 → ``ll`` 向右选两个字 → ``y`` 复制 →
    ``o`` 开面板 → ``abc`` 打正文 → ``Tab`` ``Tab`` 来回切焦点 →
    ``Ctrl+S`` 保存 → ``Esc`` 关面板 → ``q`` 退出。
    """
    pid, fd = pty.fork()
    if pid == 0:
        # 子进程：换成沙箱环境后 exec 阅读器
        os.environ.clear()
        os.environ.update(env)
        os.execv(PY, [PY, "-m", "wreader.cli", "read", book_id])
    # 给 pty 一个正常尺寸（不设就是 0x0，行为不真实）
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
    # 收集终端输出
    sink: list[str] = []
    # 等 curses 起来并画出第一帧
    drain(fd, sink, 1.3)
    # 每一步按键之间都留出重绘时间，并把输出读走
    for payload in ["m", "l", "l", "y", "o", "a", "b", "c", "\t", "\t", "\x13", "\x1b"]:
        try:
            os.write(fd, payload.encode())
        except OSError:
            # 子进程提前没了：别在这里崩，让上层用收集到的输出对账并报错
            break
        drain(fd, sink, 0.35)
    # 退出阅读器（已经退出时忽略那次写失败）
    try:
        os.write(fd, b"q")
    except OSError:
        pass
    drain(fd, sink, 0.8)
    os.waitpid(pid, 0)
    os.close(fd)
    return "".join(sink)


def check(label: str, needle: str, blob: str) -> None:
    """断言 *blob* 里出现过 *needle*（终端输出里能看到画出来的文字）。"""
    ok = needle in blob
    if not ok:
        failures.append(label)
    print("  {} {}（找 {!r}）".format("OK  " if ok else "FAIL", label, needle))


def run_cli(env: dict[str, str], args: list[str]) -> str:
    """在同一个沙箱里跑一条 werd 子命令，返回它的输出（stdout + stderr）。

    ``stdin`` 必须显式断开：不然 ``werd notes <id>`` 会以为有人在按键，
    分页时一直等下去（子进程继承了本工具的终端）。
    """
    result = subprocess.run(
        [PY, "-m", "wreader.cli"] + args,
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return (result.stdout or "") + (result.stderr or "")


def main() -> int:
    """入口：跑一次笔记流程，逐项对账。"""
    home, env, book_id = build_sandbox()
    print("沙箱:", home)
    print("book_id:", book_id)
    print("== 端到端结果 ==")
    blob = run_notes_case(env, book_id)
    # ① 引用区应该把 y 复制的文字画出来（前缀 "> " 只有 _draw_quote 会写）
    check("① 引用区画出选中的文字", "> 第一章", blob)
    # ② 面板自己的提示行画出来了（说明面板确实展开过）
    check("② 面板提示行", "Tab 切换焦点", blob)
    # ③ Ctrl+S 真的触发保存（XOFF 没被行规程吞掉 => IXON 确实关掉了）
    check("③ Ctrl+S 保存成功", "已保存", blob)
    # ④ 关掉面板后底部提示行显示笔记计数与展开键
    check("④ 折叠后显示笔记计数", "按o展开", blob)
    # ⑤ 全程不该有 traceback
    if "Traceback" in blob:
        failures.append("⑤ 没有异常")
        print("  FAIL ⑤ 没有异常（输出里出现 Traceback）")
    else:
        print("  OK   ⑤ 没有异常")

    print("== 落盘结果（Phase 3：markdown + 索引）==")
    # ⑥ 笔记真的写进了 markdown：文件头 + 小节 + 引用 + 分界行 + 正文
    note_path = home / "notes" / "{}.md".format(book_id)
    landed = note_path.read_text(encoding="utf-8") if note_path.is_file() else ""
    check("⑥ 笔记文件已生成", "## 笔记 #1", landed)
    check("⑥ 写入了引用", "第一章", landed)
    check("⑥ 写入了正文", "abc", landed)
    check("⑥ 引用与正文的分界行", "我的想法：", landed)
    # ⑦ index.json 是派生索引：条数记对了
    index_path = home / "notes" / "index.json"
    index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    check("⑦ 索引里条数为 1", '"count": 1', index_text)
    check("⑦ 索引里带书籍 id", book_id, index_text)

    print("== 第二次会话：追加不覆盖 ==")
    # ⑧ 再进一次阅读器写第二条：文件里该有两条，第一条不能丢
    run_notes_case(env, book_id)
    second = note_path.read_text(encoding="utf-8") if note_path.is_file() else ""
    check("⑧ 第二条加在后面", "## 笔记 #2", second)
    check("⑧ 第一条还在（没被覆盖）", "## 笔记 #1", second)

    print("== CLI：werd notes ==")
    # ⑨ 列清单：带上书籍 id 与条数
    listed = run_cli(env, ["notes"])
    check("⑨ 清单里有这本书", book_id, listed)
    check("⑨ 清单表头有「条数」", "条数", listed)
    # ⑩ 翻单本：分隔线 + 序号 + 正文
    paged = run_cli(env, ["notes", book_id])
    check("⑩ 分页提示行", "空格看下一条", paged)
    check("⑩ 打出第一条", "#1", paged)
    check("⑩ 打出引用", "第一章", paged)
    # ⑪ 导出到临时目录（不碰真实 ~/books）
    export_dir = home / "export"
    export_dir.mkdir(parents=True, exist_ok=True)
    exported = subprocess.run(
        [PY, "-m", "wreader.cli", "notes", book_id, "--export"],
        env=dict(env, HOME=str(home)),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        cwd=str(export_dir),
    )
    # 导出目标是 ~/books：把 HOME 指到沙箱，于是落在 <home>/books
    exported_file = home / "books" / "notes_{}.md".format(book_id)
    check(
        "⑪ 导出成功",
        "已导出到",
        (exported.stdout or "") + (exported.stderr or ""),
    )
    check(
        "⑪ 导出的文件内容一致",
        "## 笔记 #1",
        exported_file.read_text(encoding="utf-8") if exported_file.is_file() else "",
    )

    print()
    print("RESULT:", "全部通过" if not failures else "失败项 {}".format(failures))
    if failures:
        # 出问题时把输出尾巴打出来，方便原地定位
        print("---- 终端输出末尾 1200 字符 ----")
        print(blob[-1200:])
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

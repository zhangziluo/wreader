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
    print()
    print("RESULT:", "全部通过" if not failures else "失败项 {}".format(failures))
    if failures:
        # 出问题时把输出尾巴打出来，方便原地定位
        print("---- 终端输出末尾 1200 字符 ----")
        print(blob[-1200:])
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""在真 pty 里验证鼠标滚轮 / 触摸拖动真的能翻滚页（端到端）。

为什么需要它：鼠标这套东西**没法用单元测试覆盖到底** —— 单元测试只能测我们自己的换算逻辑，
而"终端到底有没有把事件送进来"取决于 curses / terminfo / 终端模拟器三者。
这个脚本用真 pty 跑一次阅读器，往里灌标准 SGR 鼠标序列，再读 `library.json` 的进度对账。

关键前提（实测得出，别随便改）：
- **必须用 ``TERM=xterm-1006``**：terminfo 里带 `XM` 能力，curses 才会打开 SGR(1006) 鼠标模式。
  默认的 `xterm-256color` 在 macOS 上**没有** `XM`，curses 只开 ?1000h，
  于是 SGR 序列会被当成普通按键收进来，测试会假失败。
- 必须给 pty 设一个正常尺寸（不然是 0x0）。

用法：python tools/verify_mouse.py
退出码：0 = 全部通过，1 = 有对不上的项（会打印期望值与实际值）。
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

# SGR(1006) 鼠标序列：64 = 滚轮上、65 = 滚轮下、0 = 按下 button1、32 = 按住移动、小写 m = 抬手
WHEEL_UP = [("\x1b[<64;10;5M", 0.4)]
DRAG_UP_4 = [("\x1b[<0;10;20M", 0.3), ("\x1b[<32;10;16M", 0.3), ("\x1b[<0;10;16m", 0.3)]
DRAG_DOWN_3 = [("\x1b[<0;10;10M", 0.3), ("\x1b[<32;10;13M", 0.3), ("\x1b[<0;10;13m", 0.3)]

# 失败项收集，最后统一报告
failures: list[str] = []


def build_sandbox() -> tuple[Path, dict[str, str], str]:
    """造一个沙箱数据目录 + 一本 200 行的书并导入，返回 (目录, 环境变量, book_id)。"""
    home = Path(tempfile.mkdtemp(prefix="wreader-mouse-"))
    novels = home / "novels"
    novels.mkdir(parents=True, exist_ok=True)
    book = novels / "鼠标校验-测试作者.txt"
    book.write_text("\n".join("第 {:03d} 行内容".format(i) for i in range(200)), encoding="utf-8")

    env = dict(os.environ)
    env.update({
        "WREADER_HOME": str(home),
        "WREADER_NOVELS_DIR": str(novels),
        # 关键：带 XM 的 terminfo，curses 才会开 SGR
        "TERM": "xterm-1006",
        "PYTHONPATH": str(ROOT),
    })
    # 先导入，才有书可读
    subprocess.run([PY, "-m", "wreader.cli", "import", str(book)], env=env, capture_output=True)
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    return home, env, next(iter(document["books"]))


def current_line(home: Path, book_id: str) -> int:
    """读当前进度行号。"""
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    return int(document["books"][book_id]["progress"]["current_line"])


def set_config(env: dict[str, str], key: str, value: str) -> None:
    """改一项设置（走 CLI，和用户手动改等价）。"""
    subprocess.run([PY, "-m", "wreader.cli", "config", key, value], env=env, capture_output=True)


def run_case(home: Path, env: dict[str, str], book_id: str, label: str, events, expect: int) -> None:
    """跑一次阅读器：灌事件 → 按 q → 比对进度行号。"""
    pid, fd = pty.fork()
    if pid == 0:
        # 子进程：换成沙箱环境后 exec 阅读器
        os.environ.clear()
        os.environ.update(env)
        os.execv(PY, [PY, "-m", "wreader.cli", "read", book_id])
    # 给 pty 一个正常尺寸（不设就是 0x0，行为不真实）
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
    # 等 curses 起来
    time.sleep(1.3)
    for payload, pause in events:
        os.write(fd, payload.encode())
        time.sleep(pause)
        # 边灌边排空输出，免得子进程写满缓冲区卡住
        while True:
            ready, _, _ = select.select([fd], [], [], 0.1)
            if not ready:
                break
            try:
                if not os.read(fd, 65536):
                    break
            except OSError:
                break
    # 退出
    os.write(fd, b"q")
    time.sleep(0.8)
    while True:
        ready, _, _ = select.select([fd], [], [], 0.3)
        if not ready:
            break
        try:
            if not os.read(fd, 65536):
                break
        except OSError:
            break
    os.waitpid(pid, 0)
    os.close(fd)
    # 对账
    line = current_line(home, book_id)
    ok = line == expect
    if not ok:
        failures.append(label)
    print("  {} {}: 进度 {}（期望 {}）".format("OK  " if ok else "FAIL", label, line, expect))


def main() -> int:
    """入口：逐项验证键盘 / 滚轮 / 拖动 / 配置开关。"""
    home, env, book_id = build_sandbox()
    print("沙箱:", home)
    print("book_id:", book_id)
    print("== 端到端结果 ==")
    # ① 键盘翻页做基准：j 翻一整屏（正文区 38 行 = pty 40 - 状态栏 2，减去默认重叠 3 行 = 35 行）
    #    注意基准是**真实终端高度**，不再是页高配置 page_height（翻页现在按屏幕行算）
    run_case(home, env, book_id, "① 键盘 j 翻一整屏（38-3 行）", [("j", 0.5)], 35)
    # ② 滚轮上一格 = 往回 1 行（wheel_scroll_step 默认 1）
    run_case(home, env, book_id, "② 滚轮上一格", WHEEL_UP, 34)
    # ③ 手指上滑 4 行 = 往后 4 行
    run_case(home, env, book_id, "③ 向上拖 4 行", DRAG_UP_4, 38)
    # ④ 手指下滑 3 行 = 往回 3 行
    run_case(home, env, book_id, "④ 向下拖 3 行", DRAG_DOWN_3, 35)
    # ⑤ touch_scroll=false 时拖动应当无效
    set_config(env, "reader.touch_scroll", "false")
    run_case(home, env, book_id, "⑤ touch_scroll=false 拖动无效", DRAG_UP_4, 35)
    set_config(env, "reader.touch_scroll", "true")
    # ⑥ 步长改成 5：一格滚 5 行
    set_config(env, "reader.wheel_scroll_step", "5")
    run_case(home, env, book_id, "⑥ 步长=5 时滚轮上一格", WHEEL_UP, 30)
    # ⑦ 关掉翻页重叠：j 又翻满整屏 38 行（验证 page_overlap 真的生效）
    set_config(env, "reader.page_overlap", "0")
    run_case(home, env, book_id, "⑦ page_overlap=0 时 j 翻整屏 38 行", [("j", 0.5)], 68)
    print()
    print("RESULT:", "全部通过" if not failures else "失败项 {}".format(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

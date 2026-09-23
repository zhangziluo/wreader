# -*- coding: utf-8 -*-
"""在真 pty 里验证「成就 Phase 2/3」的端到端链路真的通。

为什么需要它（单元测试盖不到的两件事）：

1. **屏内 5 秒通知真的画在屏幕上**。它由 ``_draw`` 每帧画在右上角，靠的是
   ``Pager.current_notice()`` 的时间窗 —— ``FakeStdscr`` 只能证明"写进去过"，
   证明不了真 curses 里那一帧真的画出来了、也没把正文顶掉。
2. **意外中断恢复真的会拦在开书时问一句**。它要在真终端里弹 ``_confirm`` 弹窗、
   等一个按键、再回到现场；而且现场文件必须在**正常退出**时才被删掉 ——
   只有真进程才能证明"下次开书不再问"。

所以这个脚本开一个真 pty、按固定顺序按键，再把终端输出与落盘的 JSON 一起对账。
**不联网**：沙箱里先把 ``stats.geo_lookup`` 关掉（顺便验证这个开关真的生效）。

用法：python tools/verify_achievements.py
退出码：0 = 全部通过，1 = 有对不上的项（会打印期望片段与实际输出尾巴）。
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

# 失败项收集，最后统一报告
failures: list[str] = []


def run_cli(env: dict[str, str], args: list[str]) -> str:
    """跑一条 ``werd`` 子命令（不接键盘），返回它的输出。"""
    result = subprocess.run(
        [PY, "-m", "wreader.cli"] + args,
        env=env,
        capture_output=True,
        text=True,
        # stdin 必须显式断开，否则分页命令会一直等人按键
        stdin=subprocess.DEVNULL,
    )
    return (result.stdout or "") + (result.stderr or "")


def build_sandbox() -> tuple[Path, dict[str, str], str]:
    """造沙箱数据目录 + 一本书并导入，返回 ``(目录, 环境变量, 书 id)``。"""
    # 独立的临时"家目录"，绝不碰真实数据
    home = Path(tempfile.mkdtemp(prefix="wreader-achv-"))
    novels = home / "novels"
    novels.mkdir(parents=True, exist_ok=True)
    # 一本小书：10 章、每章 30 行，够翻几页
    lines: list[str] = []
    for chapter in range(1, 11):
        lines.append("第{:02d}章 测试章节".format(chapter))
        lines.extend("第 {:03d} 行内容".format(index) for index in range(30))
    book = novels / "成就校验-测试作者.txt"
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
    run_cli(env, ["import", str(book)])
    # 地理探测会联网：这个工具不该依赖网络（顺便验证这个开关真的生效）
    run_cli(env, ["config", "stats.geo_lookup", "false"])
    # 导入后索引里应该只有这一本
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    return home, env, next(iter(document["books"]))


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


def run_reader(env: dict[str, str], book_id: str, steps: list[tuple[str, float]]) -> str:
    """跑一次阅读器，按 *steps* 依次按键（键, 等待秒数），返回终端输出。"""
    pid, fd = pty.fork()
    if pid == 0:
        # 子进程：换成沙箱环境后 exec 阅读器
        os.environ.clear()
        os.environ.update(env)
        os.execv(PY, [PY, "-m", "wreader.cli", "read", book_id])
    # 给 pty 一个正常尺寸（不设就是 0x0，行为不真实）
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 100, 0, 0))
    sink: list[str] = []
    # 等 curses 起来并画出第一帧
    drain(fd, sink, 1.5)
    for payload, pause in steps:
        # 空串就是"只等一会儿、不按键"（给通知留出绘制时间）
        if payload:
            try:
                os.write(fd, payload.encode("utf-8"))
            except OSError:
                # 子进程提前退出了：下面靠输出对账就能看出来
                break
        drain(fd, sink, pause)
    # 收尾：把剩下的输出读完
    drain(fd, sink, 0.6)
    return "".join(sink)


def read_state(home: Path) -> dict:
    """读成就状态文件（不在就当空字典）。"""
    path = home / "achievements.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def unlocked_ids(state: dict) -> list[str]:
    """状态文件里的解锁 id 列表。"""
    return [str(entry.get("id")) for entry in state.get("unlocked") or []]


def check(label: str, needle: str, haystack: str) -> None:
    """对账一项：*haystack* 里应当包含 *needle*。"""
    if needle in haystack:
        print("  OK   {}".format(label))
        return
    failures.append(label)
    print("  FAIL {}（找不到 {!r}）".format(label, needle))


def check_true(label: str, condition: bool, detail: str = "") -> None:
    """对账一个布尔条件。"""
    if condition:
        print("  OK   {}".format(label))
        return
    failures.append(label)
    print("  FAIL {}{}".format(label, "（{}）".format(detail) if detail else ""))


def main() -> int:
    """入口：跑三个场景（帮助页 + 屏内通知、意外中断恢复、彩蛋），逐项对账。"""
    home, env, book_id = build_sandbox()
    print("沙箱:", home)
    print("book_id:", book_id)

    print("== ① 帮助页 + 屏内 5 秒通知 ==")
    # 按键顺序：? 打开帮助（顺手记一次"帮助迷"）→ q 关掉 → 停 2 秒让通知画出来 → q 退出
    blob = run_reader(env, book_id, [("?", 1.0), ("q", 1.0), ("", 2.0), ("q", 0.8)])
    check("① 帮助页画出来了", "快捷键一览", blob)
    check("① 帮助页里有翻页一节", "【翻页】", blob)
    # 通知是解锁后 5 秒内右上角那一块牌子：标题写的就是"成就解锁"
    check("① 屏内通知出现", "成就解锁", blob)
    check("① 通知里点名了成就", "帮助迷", blob)
    check_true("① 没有 traceback", "Traceback" not in blob)

    state = read_state(home)
    helped = state.get("metrics", {}).get("help_opens")
    check_true(
        "① 状态文件记下帮助页打开次数",
        helped == 1,
        "help_opens={}".format(helped),
    )
    check_true("① 帮助迷已解锁", "help_fan" in unlocked_ids(state))

    print("== ② 意外中断恢复 ==")
    # 造一份"上次没正常退出"的现场：同一本书、停在第 12 行
    marker = {
        "book_id": book_id,
        "title": "成就校验",
        "position": 12,
        "offset": 0,
        "preview": "第 011 行内容",
        "started": "2026-09-23T10:00:00",
        "pid": 4242,
    }
    (home / "reading_session.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # y = 接着上次读（恢复现场）→ 停 1 秒 → q 退出
    blob2 = run_reader(env, book_id, [("y", 1.2), ("", 1.0), ("q", 1.0)])
    check("② 弹出的恢复提示", "上次好像没有正常退出", blob2)
    check("② 提示里写了上次读到哪", "上次读到第 13 行", blob2)
    check("② 提示给了两个选项", "[y] 接着上次读", blob2)
    check_true("② 没有 traceback", "Traceback" not in blob2)

    state = read_state(home)
    recovered = state.get("metrics", {}).get("crash_recovers")
    check_true("② 恢复记了一次", recovered == 1, "crash_recovers={}".format(recovered))
    # 位置真的回到现场了（退出时 save_session 把它写进书库索引）
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    line = document["books"][book_id]["progress"]["current_line"]
    check_true("② 位置回到现场那一行", line == 12, "current_line={}".format(line))
    # 正常退出：现场文件必须被删掉，否则下次开书又会问一遍
    marker_path = home / "reading_session.json"
    check_true("② 正常退出后现场被清掉", marker_path.is_file() is False)

    print("== ③ 干净退出（不再问第二次）==")
    blob3 = run_reader(env, book_id, [("", 1.0), ("q", 0.8)])
    check_true("③ 没有再问恢复", "上次好像没有正常退出" not in blob3)
    # 第二次会话没有恢复可记：计数不变
    state = read_state(home)
    again = state.get("metrics", {}).get("crash_recovers")
    check_true("③ 恢复计数没被重复记", again == 1, "crash_recovers={}".format(again))

    print("== ④ 名字彩蛋（CLI）==")
    egg = run_cli(env, ["--werd"])
    check("④ 彩蛋打印出来了", "werd", egg)
    check("④ 彩蛋解锁成就", "名字彩蛋", egg)
    state = read_state(home)
    check_true("④ 状态文件记下彩蛋", state.get("metrics", {}).get("eggs") == ["werd"])

    print()
    print("RESULT:", "全部通过" if not failures else "失败项 {}".format(failures))
    if failures:
        # 出问题时把输出尾巴打出来，方便原地定位
        print("---- 第一次阅读的终端输出末尾 1500 字符 ----")
        print(blob[-1500:])
        print("---- 恢复场景的终端输出末尾 1500 字符 ----")
        print(blob2[-1500:])
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

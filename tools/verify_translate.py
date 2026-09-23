# -*- coding: utf-8 -*-
"""在真 pty 里验证「t 翻译」与「werd config translate」两条端到端路径。

为什么需要它：

* ``t`` 的译文弹窗要真的建子窗口、真的按"主窗口先刷、子窗口后刷"的顺序画，
  ``FakeStdscr`` 盖不到底（跟笔记面板同一个理由）；
* 但**翻译本身要联网**，而项目纪律是测试绝不联网 —— 所以这里只验证
  **不联网也完全确定**的两条路径，它们恰好就是规格里最容易写错的两条：

  1. 引擎没配好时按 ``t``，必须给出「运行 werd config translate」这种可操作提示，
     而不是把后端的报错（或者一次要联网的请求）甩给用户；
  2. ``werd config translate`` 向导真的把引擎名与密钥写进 ``settings.toml``。

用法：python tools/verify_translate.py
退出码：0 = 全部通过，1 = 有对不上的项。
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


def build_sandbox() -> tuple[Path, dict[str, str], str]:
    """造沙箱数据目录 + 一本书并导入，返回 ``(目录, 环境变量, 书 id)``。"""
    # 独立的临时"家目录"，绝不碰真实数据
    home = Path(tempfile.mkdtemp(prefix="wreader-translate-"))
    novels = home / "novels"
    novels.mkdir(parents=True, exist_ok=True)
    # 一本小书：正文随便写点中文，反正不会真的发翻译请求
    book = novels / "翻译校验-测试作者.txt"
    book.write_text(
        "\n".join(["第一章 测试开头"] + ["第 {:03d} 行内容".format(i) for i in range(40)]),
        encoding="utf-8",
    )
    # 子进程环境：指向沙箱 + 让子进程能 import wreader
    env = dict(os.environ)
    env.update(
        {
            "WREADER_HOME": str(home),
            "WREADER_NOVELS_DIR": str(novels),
            # 非交互运行时 TERM 可能没设，curses 会起不来
            "TERM": env.get("TERM") or "xterm-256color",
            "PYTHONPATH": str(ROOT),
        }
    )
    subprocess.run(
        [PY, "-m", "wreader.cli", "import", str(book)], env=env, capture_output=True
    )
    document = json.loads((home / "library.json").read_text(encoding="utf-8"))
    return home, env, next(iter(document["books"]))


def set_setting(env: dict[str, str], key: str, value: str) -> None:
    """改一项设置（走 CLI，与用户手改等价）。"""
    subprocess.run(
        [PY, "-m", "wreader.cli", "config", key, value], env=env, capture_output=True
    )


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


def press_t(env: dict[str, str], book_id: str) -> str:
    """跑一次阅读器：按 t（翻译当前屏）再按 q 退出，返回终端输出。"""
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
    # t：翻译当前屏幕（未配置时应当只出一条提示，不发请求）
    for payload in [b"t", b"q"]:
        try:
            os.write(fd, payload)
        except OSError:
            # 子进程提前退出：别在这里崩，让上层用收集到的输出对账
            break
        drain(fd, sink, 0.7)
    os.waitpid(pid, 0)
    os.close(fd)
    return "".join(sink)


def check(label: str, needle: str, blob: str) -> None:
    """断言 *blob* 里出现过 *needle*。"""
    ok = needle in blob
    if not ok:
        failures.append(label)
    print("  {} {}（找 {!r}）".format("OK  " if ok else "FAIL", label, needle))


def wizard_case(home: Path, env: dict[str, str]) -> None:
    """喂答案给 werd config translate，检查它真的写进了 settings.toml。"""
    # 2 = 百度（菜单顺序 google/baidu/youdao/tencent/deepseek/local）
    answers = "2\nverify-appid\nverify-secret\n"
    result = subprocess.run(
        [PY, "-m", "wreader.cli", "config", "translate"],
        env=env,
        input=answers.encode(),
        capture_output=True,
    )
    text = (home / "settings.toml").read_text(encoding="utf-8")
    ok = result.returncode == 0 and 'engine = "baidu"' in text and 'baidu_appid = "verify-appid"' in text
    if not ok:
        failures.append("③ 向导写入 [translate]")
    print(
        "  {} ③ 向导写入 [translate]（rc={}）".format("OK  " if ok else "FAIL", result.returncode)
    )


def main() -> int:
    """入口：逐项验证未配置提示与配置向导。"""
    home, env, book_id = build_sandbox()
    print("沙箱:", home)
    print("book_id:", book_id)
    print("== 端到端结果 ==")

    # ① 选了本地引擎但没装 argostranslate -> t 必须提示去跑向导
    set_setting(env, "translate.engine", "local")
    check(
        "① 引擎不可用时 t 给出向导提示",
        "werd config translate",
        press_t(env, book_id),
    )

    # ② 选了百度但没填密钥 -> 提示里要写清缺什么
    set_setting(env, "translate.engine", "baidu")
    blob = press_t(env, book_id)
    check("② 缺密钥时 t 提示去向导", "werd config translate", blob)
    check("② 提示里点名缺哪个凭证", "缺少", blob)

    # ③ 配置向导把引擎与密钥落盘
    wizard_case(home, env)

    print()
    print("RESULT:", "全部通过" if not failures else "失败项 {}".format(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

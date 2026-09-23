# -*- coding: utf-8 -*-
"""把文档里声称的数字与真实情况对一遍，防止「代码改了、文档没跟上」。

校验两类数字：
1. 源码行数：README「项目结构」里写的「（N 行）」/「(N lines)」 ←→ 文件真实行数
2. 测试项数：README 里写的「N 项」/「N tests」 ←→ pytest 实际收集到的数量

用法（在仓库任意目录都能跑）：
    python tools/check_doc_numbers.py
退出码：0 = 全部一致，1 = 有不一致（可直接接 CI）。
"""
import re
import subprocess
import sys
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent


def line_count(path: Path) -> int:
    """文件真实行数，口径与 `wc -l` 一致（数换行符）。"""
    return path.read_text(encoding="utf-8").count("\n")


def collected(test_file: str) -> int:
    """问 pytest：这个测试文件实际有多少项（含参数化展开后的数量）。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/" + test_file, "--collect-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    # 汇总行长这样：`115 tests collected in 0.16s`；注意别再加 -q，否则会被 -qq 吃掉
    found = re.search(r"^(\d+) tests? collected", result.stdout, re.M)
    return int(found.group(1)) if found else -1


def check(label: str, claimed: int, actual: int, failures: list[str]) -> None:
    """比对一项：打印结果，不一致就记进 failures。"""
    flag = "OK " if claimed == actual else "FAIL"
    if claimed != actual:
        failures.append(label)
    print("  [{}] {}: 文档={} 实际={}".format(flag, label, claimed, actual))


def main() -> int:
    """入口：返回 0 表示所有数字都对得上。"""
    failures: list[str] = []
    # 两份 README 都要读（中文版 + 英文版）
    readme_zh = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_en = (ROOT / "README.en.md").read_text(encoding="utf-8")

    print("== 源码行数 ==")
    # 中英两版各配一条正则：中文版是「（N 行）」，英文版是「(N lines)」
    for text, pattern in (
        (readme_zh, r"([a-z_]+\.py)\s+[^\n（]*?（(\d+) 行）"),
        (readme_en, r"([a-z_]+\.py)\s+[^\n(]*?\((\d+) lines\)"),
    ):
        for name, number in re.findall(pattern, text):
            target = ROOT / "wreader" / name
            # 只在包内目录里找得到的就是 wreader/ 的模块。
            # ⚠️ 子包（如 wreader/translate/）里的文件**故意不在这条校验范围内**：
            # 名字会撞车（两边都有 __init__.py），单看文件名分不清是哪一个，
            # 所以 README 的子包条目不写"（N 行）"，数字只写在 memory-bank 里。
            if target.is_file():
                check("wreader/" + name, int(number), line_count(target), failures)

    print("== 测试文件项数 ==")
    # 中英两版列的是同一批文件，用 seen 去重，避免同一个文件查两遍（查一遍要跑一次 pytest）
    seen: set[str] = set()
    for text, pattern in (
        (readme_zh, r"(test_[a-z_]+\.py)\s+(\d+) 项"),
        (readme_en, r"(test_[a-z_]+\.py)\s+(\d+) tests"),
    ):
        for name, number in re.findall(pattern, text):
            if name in seen:
                continue
            seen.add(name)
            check(name, int(number), collected(name), failures)

    print("== 测试总数 ==")
    # 总数只跑一次 pytest，两版 README 各比对一次
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only"],
        capture_output=True, text=True, cwd=ROOT,
    )
    total_found = re.search(r"^(\d+) tests? collected", result.stdout, re.M)
    total = int(total_found.group(1)) if total_found else -1
    for label, text, pattern in (
        ("README.md", readme_zh, r"└── tests/\s+(\d+) 项测试"),
        ("README.en.md", readme_en, r"└── tests/\s+(\d+) tests"),
    ):
        claimed = re.search(pattern, text)
        check(label + " 总数", int(claimed.group(1)) if claimed else -1, total, failures)

    print()
    print("RESULT:", "ALL OK" if not failures else "MISMATCH -> {}".format(failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())

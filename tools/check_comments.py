# -*- coding: utf-8 -*-
"""找出「上方没有紧邻注释行」的逻辑语句，用于守住项目的注释约定。

项目的硬性约定：**每条逻辑语句上方都要有一行口语化中文注释**。
本脚本用 tokenize 找出每条逻辑语句（logical line）的起始行，看它上面那行是不是注释。

用法（在仓库任意目录都能跑）：
    python tools/check_comments.py              # 只报告 wreader/ 与 tests/ 的覆盖情况
    python tools/check_comments.py --strict     # 有遗漏就退出码 1（给 CI 用）
    python tools/check_comments.py a.py b.py    # 只检查指定文件
默认模式**只报告、不判定**：因为“每条逻辑语句上方都要有一行注释”是很严的字面规则，
仓库目前并没有全量满足（见下方「现状」），把它当硬门禁会让 CI 直接全红。

> 现状（2026-09-25 实测，去掉翻译 / 生词本 / 笔记之后）：`wreader/` + `tests/` 合计 **2771** 条语句
> 上方没有紧邻注释行（`tests/test_reader.py` 591、`wreader/reader.py` 480、
> `wreader/achievements.py` 223、`wreader/library.py` 170、`tests/test_library.py` 165 …）。
> 所以那句“每条逻辑语句上方都有中文注释”更接近**目标**而不是**已达成的事实**。
> 想推进就逐个文件来：`python tools/check_comments.py --strict wreader/library.py`（目前 170 条）。

> 历史坑（2026-09-22 修）：早先的版本把 tokenize.NEWLINE 也放进了「跳过」集合，
> 于是“一条语句结束、下个 token 是新语句”这个判断永远不会触发，**每个文件只检查了第 1 行**，
> 于是永远输出 TOTAL: 0 —— 那是个假绿的检查。现在把 NEWLINE 单独处理。
"""
import io
import sys
import tokenize
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，再往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent

# 默认检查这两个目录下的所有 .py（这是文档里那条注释约定声明的范围：8 个包内模块 + 8 个测试文件）
# 想连 tools/ 一起看，就把路径显式传进来：python tools/check_comments.py tools
DEFAULT_DIRS = ("wreader", "tests")

# 这些 token 不是“一条逻辑语句的第一个 token”，遇到就跳过
# 注意：NEWLINE 不在这里 —— 它是“逻辑语句结束”的信号，要单独处理
SKIP_TOKENS = (
    tokenize.NL,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.COMMENT,
    tokenize.ENDMARKER,
)

# 这些开头的行自己不需要注释：
#   函数/类定义由紧随其后的 docstring 负责说明；
#   分支与异常承接行（elif/else/except/finally）语义上跟着上一行
SKIP_PREFIXES = ("def ", "class ", "@", "elif ", "else:", "except", "finally:")


def default_files() -> list[Path]:
    """没给命令行参数时，返回默认要检查的文件（按路径排序，输出稳定）。"""
    # 逐个目录收集 .py；rglob 会带上子目录，排序是为了让输出可复现
    found: list[Path] = []
    for name in DEFAULT_DIRS:
        directory = ROOT / name
        # 目录不存在就跳过（例如只 clone 了部分内容）
        if directory.is_dir():
            found.extend(sorted(directory.rglob("*.py")))
    return found


def statement_starts(src: str) -> list[int]:
    """返回每条逻辑语句的起始行号（1 起）。"""
    # starts 收行号；expect_new 为 True 表示“下一个非跳过 token 是新语句的第一个”
    starts: list[int] = []
    expect_new = True
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        # NEWLINE 表示一条逻辑语句到此结束，下个 token 就是新语句的开头
        if tok.type == tokenize.NEWLINE:
            expect_new = True
            continue
        # 其余结构性 token（缩进、续行 NL、注释等）直接忽略
        if tok.type in SKIP_TOKENS:
            continue
        # 只有每条语句的“第一个 token”才记行号，续行不再记
        if expect_new:
            starts.append(tok.start[0])
            expect_new = False
    return starts


def docstring_lines(src: str) -> set[int]:
    """返回所有独立 docstring 覆盖的行号（这些行不需要额外注释）。"""
    # 用 tokenize 认字符串，只收“该行以三引号开头”的，避免把普通字符串误判成 docstring
    lines: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.STRING and tok.line.strip().startswith(('"""', "'''")):
            for ln in range(tok.start[0], tok.end[0] + 1):
                lines.add(ln)
    return lines


def check_file(path: Path) -> list[tuple[int, str]]:
    """检查一个文件，返回 [(行号, 语句内容摘要), ...] 形式的遗漏列表。"""
    # 读不出来就跳过这个文件（不让一个坏文件把整轮检查打断）
    try:
        src = path.read_text(encoding="utf-8")
    except OSError as exc:
        print("SKIP", path, exc)
        return []
    # 正文按行切好；docstring 占用的行号先算出来
    lines = src.splitlines()
    doc_lines = docstring_lines(src)
    gaps: list[tuple[int, str]] = []
    for ln in statement_starts(src):
        # docstring 自己不用注释
        if ln in doc_lines:
            continue
        text = lines[ln - 1].strip()
        # 定义行、装饰器行、分支/异常承接行都不算
        if text.startswith(SKIP_PREFIXES):
            continue
        # 上一行 strip 后以 # 开头，就算这条语句被注释覆盖了
        prev = lines[ln - 2].strip() if ln >= 2 else ""
        if prev.startswith("#"):
            continue
        gaps.append((ln, text[:70]))
    return gaps


def main(argv: list[str]) -> int:
    """入口：报告覆盖情况；只有加 `--strict` 时才在存在遗漏的情况下返回 1。"""
    # 先把 --strict 开关摘出来，剩下的参数才是要检查的路径
    strict = "--strict" in argv
    paths = [arg for arg in argv if arg != "--strict"]
    # 给了路径就只查这些文件，否则查默认目录
    targets = [Path(arg) for arg in paths] if paths else default_files()
    total = 0
    for path in targets:
        gaps = check_file(path)
        total += len(gaps)
        # 能算相对路径就显示相对路径，输出短一些
        try:
            shown = path.resolve().relative_to(ROOT)
        except ValueError:
            shown = path
        print("{}: {} uncovered statement(s)".format(shown, len(gaps)))
        # 每个文件最多列 20 条，免得刷屏
        for ln, text in gaps[:20]:
            print("    L{}: {}".format(ln, text))
    print("TOTAL:", total)
    # 非 strict 模式恒返回 0：它默认是个报告工具，而不是门禁
    return 1 if (strict and total) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

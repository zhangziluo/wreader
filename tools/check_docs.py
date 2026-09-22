# -*- coding: utf-8 -*-
"""检查 Markdown 文档的结构：文内锚点能不能解析、代码围栏有没有配对。

锚点规则照 GitHub 来：标题转锚点 → 先小写，再丢掉标点（保留字母/数字/下划线/连字符/CJK），
最后把空格换成连字符。这样 `[文字](#某锚点)` 能不能点得动就能提前查出来。

用法（在仓库任意目录都能跑）：
    python tools/check_docs.py              # 检查仓库根下所有 .md
    python tools/check_docs.py README.md    # 只检查指定文件
退出码：0 = 全部通过，1 = 有问题（可直接接 CI）。
"""
import re
import sys
from pathlib import Path

# 仓库根目录：本文件住在 tools/ 里，往上一级就是仓库根
ROOT = Path(__file__).resolve().parent.parent


def slug(title: str) -> str:
    """把标题转成 GitHub 风格的锚点。"""
    # 先统一成小写并去掉首尾空白
    lowered = title.strip().lower()
    # 只保留字母/数字/下划线/连字符/空白/CJK，其余标点（含全角的：（）等）一律丢掉
    kept = re.sub(r"[^\w\s\u4e00-\u9fff-]", "", lowered)
    # 空白换成连字符
    return kept.replace(" ", "-")


def check_file(path: Path) -> list[str]:
    """检查一个文档，返回问题列表（空列表表示没问题）。"""
    # 读不出来就当作一个问题返回，不让编码异常打断整轮检查
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return ["SKIP {}: {}".format(path, exc)]
    # 抓出所有标题（去掉开头的 # 序列，以及结尾可能多写的 #）
    headings = [h.strip().rstrip("#").strip() for h in re.findall(r"^#{1,6}\s+(.+)$", text, re.M)]
    # 标题换算出来的锚点集合，用来判定链接
    slugs = {slug(heading) for heading in headings}
    # 文内链接形如 [文字](#锚点)
    links = re.findall(r"\]\(#([^)]+)\)", text)
    problems: list[str] = []
    # 逐个锚点判定；去重后报告，避免同一个坏锚点刷一屏
    for link in sorted(set(links)):
        if link not in slugs:
            problems.append("MISSING 锚点: #{}".format(link))
    # 代码围栏行数必须是偶数，奇数说明有 ``` 没闭合（会把后面整段文档吞进代码块）
    fences = [i + 1 for i, line in enumerate(text.splitlines()) if line.lstrip().startswith("```")]
    if len(fences) % 2:
        problems.append("代码围栏 {} 行（奇数），有未闭合的 ```，行号 {}".format(len(fences), fences))
    print("{}: {} 标题, {} 文内链接, {} 围栏行".format(path.name, len(headings), len(links), len(fences)))
    return problems


def main(argv: list[str]) -> int:
    """入口：返回 0 表示全部通过，1 表示有文档不合格。"""
    # 没给参数就检查仓库根下所有 .md（README.md / README.en.md / 使用指南.md …）
    targets = [Path(arg) for arg in argv] if argv else sorted(ROOT.glob("*.md"))
    total = 0
    for path in targets:
        problems = check_file(path)
        total += len(problems)
        # 有问题的逐条打出来
        for problem in problems:
            print("    " + problem)
    print("RESULT:", "OK" if total == 0 else "FAIL ({} 个问题)".format(total))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

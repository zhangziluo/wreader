#!/usr/bin/env bash
#
# werd 一键安装：建虚拟环境、装依赖、配好 werd 别名。
#
#   git clone https://github.com/zhangziluo/wreader.git
#   cd wreader
#   ./install.sh
#
# 脚本是**幂等**的：重复运行不会重建 venv，也不会把别名写第二遍。
# 只支持 macOS / Linux（POSIX shell）；Windows 请按 README 里的手动步骤走。

# 有人用 `sh install.sh` 跑的话，转交给 bash 重新执行（下面用了数组等 bash 特性）
if [ -z "${BASH_VERSION:-}" ]; then
  exec bash "$0" "$@"
fi

set -euo pipefail

# ---------------------------------------------------------------------------
# 输出小工具：有终端才上颜色，重定向到文件时保持纯文本
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"
  DIM="$(printf '\033[2m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  RED="$(printf '\033[31m')"
  RESET="$(printf '\033[0m')"
else
  BOLD=""; DIM=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

# 普通信息，直接原样打印
say() { printf '%s\n' "$*"; }
# 成功：绿色 [ok]
ok() { printf '%s  [ok]%s %s\n' "$GREEN" "$RESET" "$*"; }
# 提醒：黄色 [!!] 写 stderr，不中断安装
warn() { printf '%s  [!!]%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
# 致命错误：红色 [xx] 写 stderr 并以 1 退出
die() { printf '%s  [xx]%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

# 帮助文本
usage() {
  cat <<'EOF'
werd 一键安装

用法:
  ./install.sh              普通用户：建 venv、装依赖、配好 werd 别名
  ./install.sh --dev        开发者：额外装上 pytest
  ./install.sh --no-alias   不要动 ~/.bashrc / ~/.zshrc
  ./install.sh --help       显示这段帮助

装完之后，新开一个终端就能直接敲 werd。
EOF
}

# ---------------------------------------------------------------------------
# 解析参数
# ---------------------------------------------------------------------------
WITH_DEV=0
WITH_ALIAS=1
for arg in "$@"; do
  case "$arg" in
    --dev)      WITH_DEV=1 ;;
    --no-alias) WITH_ALIAS=0 ;;
    -h|--help)  usage; exit 0 ;;
    *)          die "无法识别的参数：${arg}（试 ./install.sh --help）" ;;
  esac
done

# ---------------------------------------------------------------------------
# 定位项目：脚本就住在仓库根，所以脚本所在目录就是项目目录
# ---------------------------------------------------------------------------
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
VENV="$PROJECT_DIR/.venv"
WREADER_BIN="$VENV/bin/werd"

say "${BOLD}werd 安装${RESET}"
say "${DIM}项目目录：$PROJECT_DIR${RESET}"

# ---------------------------------------------------------------------------
# 1. 找一个 >= 3.11 的 Python（项目用到 3.11 才有的标准库 tomllib）
# ---------------------------------------------------------------------------
PYTHON=""
for candidate in python3 python; do
  # 连命令都没有就试下一个
  if ! command -v "$candidate" >/dev/null 2>&1; then
    continue
  fi
  # 版本够新才用它，否则继续往下找
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
# 一个能用的都没找到：报错退出，并给出各平台的安装提示
if [ -z "$PYTHON" ]; then
  die "需要 Python 3.11 或更高版本。macOS: brew install python@3.13 ／ Debian/Ubuntu: sudo apt install python3 python3-venv"
fi
ok "Python：$("$PYTHON" --version 2>&1)"

# ---------------------------------------------------------------------------
# 2. 建虚拟环境（已存在就跳过，保证重复运行安全）
# ---------------------------------------------------------------------------
# 记住这次是不是新建的：只有新 venv 才值得升级 pip，重复运行就跳过
CREATED_VENV=0
# 用 bin/python 是否存在来判断"装好了"，而不是只看目录在不在
# （创建过程被打断会留下一个空 .venv 目录，那种情况要重建）
if [ -x "$VENV/bin/python" ]; then
  ok "虚拟环境已存在，跳过创建（${VENV}）"
else
  say "正在创建虚拟环境 .venv ..."
  # Debian/Ubuntu 缺 python3-venv 时这里会失败，提示里直接给解法
  "$PYTHON" -m venv "$VENV" \
    || die "创建虚拟环境失败。Debian/Ubuntu 可能需要先装：sudo apt install python3-venv"
  CREATED_VENV=1
  ok "已创建虚拟环境 $VENV"
fi

# ---------------------------------------------------------------------------
# 3. 装依赖 + 可编辑安装
#    注意：直接用 venv 里的 python 调 pip，**不 activate**。
#    这样不会把 .venv/bin 塞进 PATH，也就不会影响你其它项目的 python3 / pip。
# ---------------------------------------------------------------------------
say "正在安装依赖（需要联网，大约半分钟）..."
# 只有新建的 venv 才升级 pip：老 venv 重复跑就不联网、更快，幂等也更彻底
if [ "$CREATED_VENV" -eq 1 ]; then
  "$VENV/bin/python" -m pip install --upgrade pip || warn "pip 升级失败，用当前版本继续"
fi
# 开发者模式多装一个 pytest
if [ "$WITH_DEV" -eq 1 ]; then
  "$VENV/bin/python" -m pip install -e ".[dev]" || die "安装失败，请检查网络后重试"
else
  "$VENV/bin/python" -m pip install -e . || die "安装失败，请检查网络后重试"
fi
ok "werd 已安装（可编辑模式）"

# ---------------------------------------------------------------------------
# 4. 自检：能打印版本号就说明真的装好了
# ---------------------------------------------------------------------------
if ! "$WREADER_BIN" --version >/dev/null 2>&1; then
  die "安装完但 $WREADER_BIN 跑不起来，请把上面的输出发给开发者"
fi
ok "自检通过：$("$WREADER_BIN" --version)"

# ---------------------------------------------------------------------------
# 5. 配别名：让新终端 / 重启之后也能直接敲 werd
# ---------------------------------------------------------------------------
# 写进 rc 文件的整行内容（路径用双引号包住，含空格的路径也能用）
ALIAS_LINE="alias werd=\"$WREADER_BIN\""

# 把别名幂等地加进一个 rc 文件
add_alias_to() {
  # 目标 rc 文件的绝对路径
  local rc="$1"
  # 已经有 werd 别名了：只报状态，绝不重复追加
  if [ -f "$rc" ] && grep -q "^alias werd=" "$rc" 2>/dev/null; then
    # 同一行（同一个路径）就是"已配好"
    if grep -Fxq "$ALIAS_LINE" "$rc"; then
      ok "别名已存在：$rc"
    else
      # 指向别的路径（比如项目被挪走了）：不擅自改动用户文件，只提醒
      warn "$rc 里已有另一个 werd 别名，未改动；想换成新路径请手动编辑"
    fi
    return 0
  fi
  # rc 文件不存在就创建一个（不少 zsh 用户根本没有 ~/.zshrc）
  if [ ! -f "$rc" ]; then
    mkdir -p "$(dirname "$rc")"
    : > "$rc"
  fi
  # 追加一段带注释的别名
  {
    printf '\n# added by wreader/install.sh\n'
    printf '%s\n' "$ALIAS_LINE"
  } >> "$rc"
  ok "已写入别名：$rc"
}

if [ "$WITH_ALIAS" -eq 1 ]; then
  # 按登录 shell 决定写哪个 rc；认不出来就把两个都写
  ALIAS_RCS=()
  case "${SHELL:-}" in
    */zsh)  ALIAS_RCS+=("$HOME/.zshrc") ;;
    */bash) ALIAS_RCS+=("$HOME/.bashrc") ;;
    *)      ALIAS_RCS+=("$HOME/.bashrc" "$HOME/.zshrc") ;;
  esac
  # 逐个写；写不进去（只读文件系统等）只警告，安装本身已经成功
  for rc in "${ALIAS_RCS[@]}"; do
    add_alias_to "$rc" || warn "写入 $rc 失败，不影响安装；可手动加这一行：$ALIAS_LINE"
  done
fi

# ---------------------------------------------------------------------------
# 6. 收尾：告诉用户接下来敲什么
# ---------------------------------------------------------------------------
# 有别名就用短命令提示；没配就给完整路径
if [ "$WITH_ALIAS" -eq 1 ]; then
  HINT="werd"
else
  HINT="$WREADER_BIN"
fi

say ""
say "${BOLD}安装完成${RESET}"
say ""
say "命令位置        $WREADER_BIN"
if [ "$WITH_ALIAS" -eq 1 ]; then
  say "让别名生效      source \"${ALIAS_RCS[0]}\"   ${DIM}（或者干脆关掉终端、重开一个）${RESET}"
fi
say ""
say "${BOLD}接下来${RESET}"
say "  1. 导入你的书     $HINT import ~/Downloads/books"
say "  2. 看看书库       $HINT list"
say "  3. 接着上次读     $HINT continue   ${DIM}→ 把 id 抄给${RESET} $HINT read <id>"
say ""
say "${DIM}进度、生词本、统计都存在 ~/.wreader，和 .venv 无关，重装不会丢。${RESET}"


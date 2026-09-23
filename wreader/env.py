"""What kind of machine werd is running on (the environment achievements).

A handful of achievements are about *where the reader is*, not what they read:
a cloud host, WSL, a tmux/screen session, or a checkout installed with ``pip install -e``.
None of that is worth a network call -- it is all sitting in the environment, in
``platform.release()`` and in the ``direct_url.json`` that pip leaves behind.

Like :mod:`wreader.geo`, this module is written so that the answer can always be
*injected*: :func:`detect` takes the environment mapping, the ``uname`` release string
and that ``direct_url.json`` text as arguments, and only reads the real ones when they
are omitted.  That keeps the tests hermetic (they never look at the machine running
them) and lets ``werd`` report the truth on any platform.

Pure functions over plain data; the only I/O is :func:`direct_url_text`, which the
caller can bypass by passing the JSON in.
"""

# 延迟求值类型注解
from __future__ import annotations

# os.environ 是默认的探测输入
import os
# platform.release() 用来识别 WSL
import platform
# 只读一次 distribution 元数据
from importlib import metadata
# 解析 pip 留下的 direct_url.json
import json
# 类型注解
from typing import Any, Dict, List, Mapping, Optional, Tuple

# 模块对外暴露的名字
__all__ = [
    "ENV_LABELS",
    "SIGNALS",
    "SIGNAL_NAMES",
    "detect",
    "direct_url_text",
    "editable_from_direct_url",
    "flags",
    "label",
]

# 每个信号的中文名（成就描述与调试输出都用它，别在别处再写一遍）
ENV_LABELS: Dict[str, str] = {
    "cloud": "云主机",
    "wsl": "WSL",
    "tmux": "终端复用器（tmux/screen）",
    "editable": "可编辑安装（编辑器里跑着的源码）",
}

#: 全部信号名（顺序与 :func:`flags` 返回的一致）：成就引擎按它生成 ``env_<名字>`` 指标
#: Every signal name, in the order :func:`flags` returns them.
SIGNAL_NAMES: Tuple[str, ...] = ("cloud", "wsl", "tmux", "editable")

# 各个信号对应的环境变量标记：名字里出现下面任意一个（大小写不敏感）就算命中。
# 只有真正"不请自来"的变量才收进来 —— 比如 AWS_REGION 是用户自己写的，
# 而 AWS_EXECUTION_ENV / ECS_CONTAINER_METADATA_URI 是平台注入的。
SIGNALS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "cloud",
        (
            "AWS_EXECUTION_ENV",
            "ECS_CONTAINER_METADATA_URI",
            "AWS_LAMBDA_FUNCTION_NAME",
            "GOOGLE_CLOUD_PROJECT",
            "K_SERVICE",
            "FUNCTION_TARGET",
            "WEBSITE_INSTANCE_ID",
            "ALIBABA_CLOUD",
            "TENCENTCLOUD_REGION",
            "FLY_APP_NAME",
            "HEROKU_APP_ID",
            "DYNO",
            "RENDER",
            "RAILWAY_ENVIRONMENT",
            "VERCEL",
            "CODESPACES",
            "GITPOD_WORKSPACE_ID",
            "KUBERNETES_SERVICE_HOST",
            "CF_INSTANCE_INDEX",
        ),
    ),
    ("wsl", ("WSL_DISTRO_NAME", "WSL_INTEROP")),
    ("tmux", ("TMUX", "TMUX_PANE", "STY")),
)


def direct_url_text(package: str = "wreader") -> str:
    """Return the installed package's ``direct_url.json`` text, or ``""``.

    pip writes that file next to the metadata of anything installed from a path or a
    git URL, and it is the only reliable way to tell an editable install from a wheel
    (``wreader.__file__`` alone cannot: a wheel unpacks into site-packages too).  Any
    failure -- not installed, no metadata, unreadable file -- degrades to ``""``.

    ⚠️ Every distribution with that name is tried, not just the first: while the
    working directory **is** the source tree, its ``wreader.egg-info`` shadows the
    ``wreader-0.1.0.dist-info`` in site-packages for :mod:`importlib.metadata`, and
    the egg-info has no ``direct_url.json``.  Reading them in turn makes the answer
    the same whether werd is started from the checkout or from anywhere else.
    """
    try:
        # 同名发行版可能有两份（源码树里的 egg-info + site-packages 里的 dist-info）
        candidates = list(metadata.distributions(name=package))
    except Exception:  # pragma: no cover - 元数据目录坏得离谱时
        return ""
    for distribution in candidates:
        try:
            # 读安装元数据里的那一个文件（不存在会是 None 或抛 FileNotFoundError）
            text = distribution.read_text("direct_url.json")
        except OSError:
            # 这一份没有/读不了：看下一份
            continue
        if text:
            return text
    # 一份都没写这个文件（旧 pip / 手工装的）：看不出是不是可编辑安装
    return ""


def editable_from_direct_url(text: Any) -> bool:
    """Return ``True`` when a ``direct_url.json`` body describes an editable install."""
    # 空 / 非字符串：没有线索
    if not isinstance(text, str) or not text.strip():
        return False
    try:
        # pip 写的是 JSON
        raw = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(raw, Mapping):
        return False
    # PEP 610：可编辑安装的 dir_info 里会有 "editable": true
    info = raw.get("dir_info")
    return bool(isinstance(info, Mapping) and info.get("editable"))


def detect(
    env: Optional[Mapping[str, str]] = None,
    release: Optional[str] = None,
    direct_url: Optional[str] = None,
) -> Dict[str, bool]:
    """Return ``{"cloud": bool, "wsl": bool, "tmux": bool, "editable": bool}``.

    Every input can be injected so the answer never depends on the machine running the
    tests; the defaults read the real environment exactly once.
    """
    # 环境变量表（注入优先，否则读进程环境）
    variables = env if env is not None else os.environ
    # 变量名统一大写比较（Windows 上可能大小写不一）
    upper = {str(key).upper() for key in variables}
    # 内核版本串：WSL 的内核里带着 "microsoft" 字样
    kernel = release if release is not None else platform.release()
    result: Dict[str, bool] = {}
    for name, markers in SIGNALS:
        # 任何一个标记变量在环境里就算命中
        result[name] = any(marker.upper() in upper for marker in markers)
    # WSL 还有一条独立判据：连 /proc 都不读，只看内核串
    if "microsoft" in str(kernel).lower():
        result["wsl"] = True
    # 可编辑安装：pip 的 direct_url.json
    body = direct_url if direct_url is not None else direct_url_text()
    result["editable"] = editable_from_direct_url(body)
    return result


def flags(**kwargs: Any) -> List[str]:
    """Return the names of the signals that hit, in :data:`SIGNALS` order.

    ``flags()`` reads the real machine; ``flags(env=..., release=..., direct_url=...)``
    probes whatever the caller injected.  The order is stable so the achievement
    payload stays readable.
    """
    # 探测（参数原样透传给 detect，默认就是探本机）
    found = detect(**kwargs)
    # 按 SIGNAL_NAMES 的固定顺序输出，editable 永远排在最后
    return [name for name in SIGNAL_NAMES if found.get(name)]


def label(name: Any) -> str:
    """Return the Chinese label of one signal (unknown names come back as-is)."""
    # 认识就给中文名，不认识就原样返回（用户自己往定义里加信号时不会崩）
    return ENV_LABELS.get(str(name), str(name))

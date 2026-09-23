"""Tests for :mod:`wreader.env` — the environment probe behind the hidden achievements.

Every input is injected: the environment mapping, the ``uname`` release string and the
``direct_url.json`` text.  That keeps the answers reproducible on any machine (the test
never looks at the environment it is actually running in).
"""

# 延迟求值类型注解
from __future__ import annotations

# 类型注解
from typing import Any, Dict

# pytest.raises / parametrize
import pytest

# 被测模块
from wreader import env


# 一条 pip 写下的可编辑安装记录（PEP 610）
EDITABLE_JSON = '{"dir_info": {"editable": true}, "url": "file:///tmp/wreader"}'


def test_detect_reads_cloud_markers_from_the_environment() -> None:
    # 平台注入的变量（不是用户自己写的）才算"我跑在云上"
    found = env.detect(env={"AWS_EXECUTION_ENV": "AWS_ECS_FARGATE"}, release="", direct_url="")
    assert found["cloud"] is True
    assert found["wsl"] is False
    assert found["tmux"] is False
    assert found["editable"] is False


def test_detect_finds_tmux_and_wsl() -> None:
    # TMUX 是 tmux 自己塞进去的；WSL 还可以从内核串认出来
    found = env.detect(env={"TMUX": "/tmp/tmux-1000/default,1,0"}, release="", direct_url="")
    assert found["tmux"] is True
    # 内核版本串里带 microsoft 就是 WSL
    wsl = env.detect(env={}, release="5.15.90.1-microsoft-standard-WSL2", direct_url="")
    assert wsl["wsl"] is True
    # WSL 的环境变量标记同样认
    assert env.detect(env={"WSL_DISTRO_NAME": "Ubuntu"}, release="", direct_url="")["wsl"]


def test_detect_treats_a_plain_environment_as_nothing_special() -> None:
    found = env.detect(env={"HOME": "/home/me", "TERM": "xterm"}, release="6.8.0-generic", direct_url="")
    assert found == {"cloud": False, "wsl": False, "tmux": False, "editable": False}


@pytest.mark.parametrize(
    "text,expected",
    [
        (EDITABLE_JSON, True),
        ('{"dir_info": {"editable": false}}', False),
        ('{"url": "file:///tmp/x"}', False),  # 没有 dir_info
        ("[]", False),
        ("not json", False),
        ("", False),
        (None, False),
    ],
)
def test_editable_from_direct_url(text: Any, expected: bool) -> None:
    assert env.editable_from_direct_url(text) is expected


def test_flags_are_filtered_and_ordered() -> None:
    # 顺序固定：cloud → wsl → tmux → editable，空的那些不出现
    found = env.flags(env={"TMUX": "x"}, release="", direct_url=EDITABLE_JSON)
    assert found == ["tmux", "editable"]
    # 全部命中时四个都在
    everything = env.flags(
        env={"AWS_REGION": "x", "GOOGLE_CLOUD_PROJECT": "p", "STY": "1"},
        release="5.15-microsoft",
        direct_url=EDITABLE_JSON,
    )
    assert everything == ["cloud", "wsl", "tmux", "editable"]


def test_label_falls_back_to_the_raw_name() -> None:
    # 认识的名字给中文，不认识的（用户自己加的）原样返回，不抛异常
    assert env.label("cloud") == "云主机"
    assert env.label("nope") == "nope"


def test_signal_names_match_what_flags_can_return() -> None:
    # achievements 用 SIGNAL_NAMES 生成 env_* 指标，两边必须一致
    assert env.SIGNAL_NAMES == ("cloud", "wsl", "tmux", "editable")
    assert set(env.SIGNAL_NAMES) == set(env.ENV_LABELS)


def test_direct_url_text_reads_the_installed_metadata() -> None:
    # 真读一次安装元数据：本仓库是可编辑安装，所以应当拿到 JSON；读不到也必须是空串
    # （不写成 assert editable is True —— 有人用 wheel 装的话这里就没有 direct_url.json）
    text = env.direct_url_text()
    assert isinstance(text, str)
    if text:
        # 拿到东西就得是能解析的 JSON，且能被 editable_from_direct_url 读懂
        assert env.editable_from_direct_url(text) in (True, False)

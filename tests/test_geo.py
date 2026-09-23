"""Tests for :mod:`wreader.geo` — the location lookup behind the geography achievements.

Nothing here touches the network: every lookup goes through the *fetcher* argument (a
plain ``(url, timeout) -> parsed JSON`` callable), and every "did it go online?"
question is answered by counting that stub's calls.
"""

# 延迟求值类型注解
from __future__ import annotations

# 注入固定时间，让"缓存还新不新"可预测
from datetime import datetime, timedelta
# 类型注解
from typing import Any, Dict, List

# pytest.raises / parametrize
import pytest

# 被测模块
from wreader import geo


# 一份「接口正常返回」的样子（字段名按 ip-api 的写法）
OK_RESPONSE: Dict[str, Any] = {
    "status": "success",
    "country": "Japan",
    "countryCode": "JP",
    "city": "Tokyo",
    "timezone": "Asia/Tokyo",
}

# 测试用的固定时刻（当作"刚刚查过"）
NOW = datetime(2026, 9, 23, 12, 0, 0)


# 记录调用次数的假取数函数
class RecordingFetcher:
    """A fetcher stub that answers from a list and counts its calls."""

    def __init__(self, responses: List[Any]) -> None:
        # 每次调用按顺序取一个响应
        self.responses = list(responses)
        # 每次调用的 url（里面带着 fields 参数，可以断言请求长什么样）
        self.calls: List[str] = []

    def __call__(self, url: str, timeout: float) -> Any:
        # 记下这次调用
        self.calls.append(url)
        # 没有预置响应了就模拟"断网"
        if not self.responses:
            raise OSError("offline")
        # 预置项可以是字典，也可以是异常对象（用来模拟超时/HTTP 错误）
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ------------------------------------------------------------------ pure helpers
@pytest.mark.parametrize(
    "code,expected",
    [
        ("GB", "欧洲"),
        ("gb", "欧洲"),  # 大小写不敏感
        (" JP ", "亚洲"),
        ("US", "北美洲"),
        ("BR", "南美洲"),
        ("ZA", "非洲"),
        ("AU", "大洋洲"),
        ("AQ", "南极洲"),
        ("", geo.CONTINENT_UNKNOWN),
        (None, geo.CONTINENT_UNKNOWN),
        ("XX", geo.CONTINENT_UNKNOWN),  # 编造的国家代码
    ],
)
def test_continent_of_knows_every_continent(code: Any, expected: str) -> None:
    assert geo.continent_of(code) == expected


def test_every_continent_has_countries_and_no_code_is_in_two() -> None:
    # 七个大洲每个都得有国家，否则"环游亚欧非美大洋"永远解不开
    assert geo.CONTINENT_COUNT == 7
    listed = [code for _, codes in geo.CONTINENT_CODES for code in codes]
    assert len(listed) == len(set(listed))
    for name, codes in geo.CONTINENT_CODES:
        assert codes, name


def test_feud_hit_needs_both_sides() -> None:
    # 只有一边不算：百年世仇要的是两个国家都去过
    assert geo.feud_hit(["GB"]) is None
    assert geo.feud_hit(["GB", "FR"]) == "GB×FR"
    # 归一化大小写，也认列表里夹着的其它国家
    assert geo.feud_hit(["cn", "jp", "US"]) == "CN×JP"


def test_parse_response_derives_the_continent() -> None:
    location = geo.parse_response(OK_RESPONSE)
    # 大洲不是接口给的，是从国家代码推出来的
    assert location == {
        "country": "Japan",
        "country_code": "JP",
        "continent": "亚洲",
        "city": "Tokyo",
        "timezone": "Asia/Tokyo",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "fail", "message": "quota"},
        {"status": "success"},  # 没有国家代码
        {"status": "success", "countryCode": "  "},
        [1, 2, 3],
        "nope",
        None,
    ],
)
def test_parse_response_rejects_unusable_answers(payload: Any) -> None:
    # 只认 status=success 且有国家代码的响应，别的统一当成"查不到"
    assert geo.parse_response(payload) == {}


# ------------------------------------------------------------------- fetching
def test_fetch_never_raises_and_asks_for_the_documented_fields() -> None:
    fetcher = RecordingFetcher([OK_RESPONSE])
    assert geo.fetch(fetcher=fetcher)["country_code"] == "JP"
    # 请求里带上 fields，少取一点数据
    assert fetcher.calls[0].startswith(geo.ENDPOINT)
    assert "fields=" in fetcher.calls[0]
    # 断网 / 超时 / HTTP 错误：一律返回空字典
    assert geo.fetch(fetcher=RecordingFetcher([OSError("down")])) == {}
    assert geo.fetch(fetcher=RecordingFetcher([{"status": "fail"}])) == {}


def test_fetch_uses_the_default_fetcher_when_none_is_given(monkeypatch) -> None:
    # 默认取数函数是 _requests_json：这里把它换掉，证明走的确实是它
    marker: List[str] = []

    def fake_requests(url: str, timeout: float) -> Any:
        # 记下 url，并返回一份"正常"响应（测试绝不真的联网）
        marker.append(url)
        return OK_RESPONSE

    # 换掉模块里的默认实现
    monkeypatch.setattr(geo, "_requests_json", fake_requests)
    assert geo.fetch()["country"] == "Japan"
    assert len(marker) == 1


# ---------------------------------------------------------------------- cache
def test_cache_round_trip_keeps_chinese_readable(isolated_home) -> None:
    path = geo.cache_path()
    # 写盘（默认落在 $WREADER_HOME 里）
    geo.save_cached(geo.parse_response(OK_RESPONSE), now=NOW)
    assert path == isolated_home.data / geo.GEO_FILENAME
    # 文件是纯文本 JSON，中文可读（用户能手改、能删）
    text = path.read_text(encoding="utf-8")
    assert "亚洲" in text and "Japan" in text
    # 读回来
    cached = geo.load_cached()
    assert cached["fetched_at"] == NOW
    assert cached["location"]["country_code"] == "JP"


def test_load_cached_reports_a_broken_file(isolated_home) -> None:
    # 坏 JSON：明确报错（调用方自己决定要不要忽略）
    geo.cache_path().parent.mkdir(parents=True, exist_ok=True)
    geo.cache_path().write_text("{ not json", encoding="utf-8")
    with pytest.raises(geo.GeoError):
        geo.load_cached()
    # 结构不对（列表）同样报错
    geo.cache_path().write_text("[]", encoding="utf-8")
    with pytest.raises(geo.GeoError):
        geo.load_cached()


def test_load_cached_is_empty_when_there_is_nothing_yet(isolated_home) -> None:
    # 还没查过：空映射，但不是错误
    assert geo.load_cached() == {}


def test_load_location_does_not_look_up_again_while_the_cache_is_fresh(
    isolated_home,
) -> None:
    fetcher = RecordingFetcher([OK_RESPONSE])
    # 第一次：真的去查，并缓存下来
    assert geo.load_location(now=NOW, fetcher=fetcher)["country_code"] == "JP"
    assert len(fetcher.calls) == 1
    # 一小时之内：直接用缓存，一步网络请求都不发
    later = NOW + timedelta(minutes=30)
    assert geo.load_location(now=later, fetcher=fetcher)["country_code"] == "JP"
    assert len(fetcher.calls) == 1


def test_load_location_refreshes_once_the_cache_is_stale(isolated_home) -> None:
    fetcher = RecordingFetcher([OK_RESPONSE, dict(OK_RESPONSE, countryCode="FR")])
    geo.load_location(now=NOW, fetcher=fetcher)
    # 超过一小时：重新查一次
    later = NOW + timedelta(hours=2)
    assert geo.load_location(now=later, fetcher=fetcher)["country_code"] == "FR"
    assert len(fetcher.calls) == 2


def test_load_location_falls_back_to_a_stale_cache_when_offline(isolated_home) -> None:
    # 先成功查一次，把缓存种上
    geo.load_location(now=NOW, fetcher=RecordingFetcher([OK_RESPONSE]))
    # 过期后又断网：过期的旧数据也比没有强
    later = NOW + timedelta(hours=3)
    assert (
        geo.load_location(now=later, fetcher=RecordingFetcher([OSError("offline")]))[
            "country_code"
        ]
        == "JP"
    )


def test_load_location_is_quietly_empty_when_offline_without_a_cache(
    isolated_home,
) -> None:
    # 没有缓存 + 断网 = 空字典（地理成就保持锁定，阅读照常）
    assert geo.load_location(now=NOW, fetcher=RecordingFetcher([])) == {}


def test_load_location_can_be_told_never_to_look_up(isolated_home) -> None:
    fetcher = RecordingFetcher([OK_RESPONSE])
    # allow_fetch=False 且没有缓存：一步网络都不发
    assert geo.load_location(now=NOW, fetcher=fetcher, allow_fetch=False) == {}
    assert fetcher.calls == []
    # 但缓存里已有的（即使过期）照用：这是"关掉联网"时唯一的数据来源
    geo.save_cached(geo.parse_response(OK_RESPONSE), now=NOW)
    later = NOW + timedelta(days=9)
    assert (
        geo.load_location(now=later, fetcher=fetcher, allow_fetch=False)["country_code"]
        == "JP"
    )
    assert fetcher.calls == []


def test_load_location_ignores_a_broken_cache_and_asks_again(isolated_home) -> None:
    geo.cache_path().parent.mkdir(parents=True, exist_ok=True)
    geo.cache_path().write_text("broken", encoding="utf-8")
    fetcher = RecordingFetcher([OK_RESPONSE])
    # 坏缓存当成没有缓存：重新查一次（并把它覆盖成好的）
    assert geo.load_location(now=NOW, fetcher=fetcher)["country_code"] == "JP"
    assert len(fetcher.calls) == 1
    assert geo.load_cached()["location"]["country_code"] == "JP"

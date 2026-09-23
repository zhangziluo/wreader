"""Where in the world this copy of werd is being used (the geography achievements).

The achievements that need a location (环游亚欧非美大洋 / 世界公民 / 百年世仇) all boil
down to one question: *which country and continent is this terminal in?*  This module
answers it from a free IP lookup (ip-api.com, no key needed) and remembers the answer
in ``<data dir>/geo.json`` for an hour, so opening ten books does not mean ten lookups.

Design rules, all three of them about never getting in the reader's way:

* **offline is a normal state, not an error** -- :func:`load_location` returns ``{}``
  when there is no network, no cached answer and nobody injected a fetcher.  Every
  caller treats an empty mapping as "地理成就暂时不可用" and reads on,
* **degradable** -- a cached answer is still used when it is stale *and* the refresh
  fails (the country you were in an hour ago is a better guess than nothing),
* **injectable** -- the actual HTTP call lives behind the *fetcher* argument, so the
  tests pass a dict-returning stub and the test suite never opens a socket.

Everything except :func:`fetch` is a pure function over plain data: country code to
continent, which country pairs count as a 百年世仇, and what an ip-api response means.
"""

# 延迟求值类型注解
from __future__ import annotations

# 解析缓存文件
import json
# os.replace 做原子替换
import os
# 先写临时文件再替换
import tempfile
# 时间戳要跟当前时间比
from datetime import datetime
# 缓存文件路径
from pathlib import Path
# 类型注解：Callable 表示可注入的取数函数
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Tuple

# 同包引用：数据目录（缓存落在那里）
from . import config

# 模块对外暴露的名字
__all__ = [
    "CACHE_SECONDS",
    "CONTINENT_COUNT",
    "CONTINENT_UNKNOWN",
    "ENDPOINT",
    "FEUD_PAIRS",
    "GEO_FILENAME",
    "GeoError",
    "cache_path",
    "continent_of",
    "feud_hit",
    "fetch",
    "load_cached",
    "load_location",
    "parse_response",
    "save_cached",
]

# 缓存文件名（数据目录下面，与 settings.toml 平级）
GEO_FILENAME = "geo.json"
# 缓存有效期：一小时（规格要求；一天看几本书最多也就查一次）
CACHE_SECONDS = 3600
# 免费接口（ip-api 的 HTTPS 要付费，所以这里用 HTTP；只取国家/城市这类粗粒度信息）
ENDPOINT = "http://ip-api.com/json/"
# 要请求哪些字段：少取一点，响应更小
FIELDS = "status,message,country,countryCode,city,timezone"
# 网络超时（秒）：宁可放弃地理成就，也不能让开书的动作卡住
TIMEOUT = 2.0
# 查不到国家（离线 / 内网 / 接口挂了）时用的占位名
CONTINENT_UNKNOWN = "未知"


# 缓存文件坏到无法使用时抛这个异常（调用方通常直接忽略）
class GeoError(Exception):
    """Raised when the geo cache file cannot be read or written."""


# 亚洲
_ASIA = (
    "CN JP KR KP MN TW HK MO SG MY TH VN LA KH MM PH ID BN TL IN PK BD LK NP BT "
    "MV KZ KG TJ TM UZ AF IR IQ SY LB JO IL PS SA YE OM AE QA BH KW GE AM AZ TR RU"
).split()
# 欧洲
_EUROPE = (
    "GB IE FR DE NL BE LU CH AT IT ES PT AD MC SM VA LI MT DK NO SE FI IS EE LV LT "
    "PL CZ SK HU SI HR BA RS ME MK AL BG RO GR MD UA BY CY AX FO GI IM JE GG"
).split()
# 非洲
_AFRICA = (
    "EG LY TN DZ MA SD SS ET ER DJ SO KE TZ UG RW BI CD CG GA GQ CM CF TD NE NG BJ "
    "TG GH CI LR SL GN GW SN GM MR ML BF CV ST AO ZM ZW MW MZ BW NA SZ LS ZA MG KM "
    "YT RE MU SC"
).split()
# 北美洲（含中美洲与加勒比）
_NORTH_AMERICA = (
    "US CA MX GT BZ SV HN NI CR PA CU JM HT DO PR BS BB TT GD LC VC AG DM KN BQ CW "
    "AW SX BL MF GP MQ TC KY BM GL PM VI"
).split()
# 南美洲
_SOUTH_AMERICA = "BR AR CL PE CO VE EC BO PY UY GY SR GF FK".split()
# 大洋洲
_OCEANIA = (
    "AU NZ PG FJ SB VU NC PF WS TO TV KI NR FM MH PW GU MP AS CK NU TK NF WF"
).split()
# 南极洲（真有人从科考站读书的话）
_ANTARCTICA = ["AQ"]

#: 大洲名 -> 该洲的 ISO-3166 两位国家代码（顺序决定判定顺序：先出现的大洲优先）
#: Continent name to the ISO-3166 alpha-2 codes in it.
CONTINENT_CODES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("亚洲", tuple(_ASIA)),
    ("欧洲", tuple(_EUROPE)),
    ("非洲", tuple(_AFRICA)),
    ("北美洲", tuple(_NORTH_AMERICA)),
    ("南美洲", tuple(_SOUTH_AMERICA)),
    ("大洋洲", tuple(_OCEANIA)),
    ("南极洲", tuple(_ANTARCTICA)),
)

# 大洲总数（"环游亚欧非美大洋"要的就是把这里全走一圈）
CONTINENT_COUNT = len(CONTINENT_CODES)

# 「百年世仇」认的组合：两边都去过才算。第一条是它的出处 —— 英法百年战争；
# 后面几对是同一类历史宿敌，让这个成就别只认一个组合（用户也能自己加定义）。
#: Country pairs that count as an old feud, both sides required.
FEUD_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("GB", "FR"),
    ("CN", "JP"),
    ("KR", "JP"),
    ("IN", "PK"),
    ("RU", "UA"),
    ("IL", "PS"),
    ("US", "RU"),
    ("TR", "GR"),
)

# 国家代码 -> 大洲 的查表（模块加载时建一次，之后 O(1)）
_CODE_TO_CONTINENT: Dict[str, str] = {
    code: name for name, codes in CONTINENT_CODES for code in codes
}


def continent_of(country_code: Any) -> str:
    """Return the continent of *country_code*, or :data:`CONTINENT_UNKNOWN`."""
    # 大小写与空格都容错（缓存文件是用户能手改的纯文本）
    code = str(country_code or "").strip().upper()
    return _CODE_TO_CONTINENT.get(code, CONTINENT_UNKNOWN)


def feud_hit(country_codes: Iterable[Any]) -> Optional[str]:
    """Return the first feud pair both sides of which are in *country_codes*.

    ``("GB", "FR")`` means the reader has been seen in both Britain and France, so
    the 百年世仇 achievement has its two ends.  ``None`` means no pair is complete.
    """
    # 归一化成大写的集合，方便反复查询
    seen = {str(code or "").strip().upper() for code in country_codes}
    for left, right in FEUD_PAIRS:
        # 两边的国家都来过：命中
        if left in seen and right in seen:
            return "{}×{}".format(left, right)
    # 一对都没凑齐
    return None


def parse_response(payload: Any) -> Dict[str, str]:
    """Turn one ip-api response into wreader's flat location mapping.

    Returns ``{}`` for anything that is not a successful answer (``status != "success"``,
    a quota message, a non-mapping), so the caller only has to check for emptiness.
    The continent is *derived* from the country code here, because the endpoint does
    not report one.
    """
    # 结构不对（None、列表、字符串）都当失败
    if not isinstance(payload, Mapping):
        return {}
    # 接口自己说失败（比如查询额度用完了）
    if str(payload.get("status") or "") != "success":
        return {}
    # 国家代码是判定大洲与世仇的唯一依据，没有它就没法用
    code = str(payload.get("countryCode") or "").strip().upper()
    if not code:
        return {}
    return {
        "country": str(payload.get("country") or ""),
        "country_code": code,
        "continent": continent_of(code),
        "city": str(payload.get("city") or ""),
        "timezone": str(payload.get("timezone") or ""),
    }


def _requests_json(url: str, timeout: float) -> Any:
    """Fetch *url* and return the decoded JSON body (the default fetcher)."""
    # 延迟导入：离线运行时连 requests 都不必加载
    import requests

    response = requests.get(url, timeout=timeout)
    # 非 200 也交给 parse_response 兜底（它只看 status 字段）
    response.raise_for_status()
    return response.json()


def fetch(
    fetcher: Optional[Callable[[str, float], Any]] = None,
    timeout: float = TIMEOUT,
) -> Dict[str, str]:
    """Look the location up over the network; ``{}`` on *any* failure.

    *fetcher* is the seam the tests use: a callable ``(url, timeout) -> parsed JSON``.
    The default implementation imports ``requests`` lazily and asks for the fields in
    :data:`FIELDS`.  Nothing here raises -- "no network" is a normal answer, and the
    caller just keeps reading without the geography achievements.
    """
    # 取数函数：默认走 requests；注入假的就完全不碰网络
    get_json = fetcher if fetcher is not None else _requests_json
    try:
        payload = get_json("{}?fields={}".format(ENDPOINT, FIELDS), float(timeout))
    except Exception:
        # 断网 / DNS 失败 / 超时 / JSON 坏：一律当成"查不到"
        return {}
    return parse_response(payload)


def cache_path(path: Optional[Path] = None) -> Path:
    """Return the geo cache file, ``<data dir>/geo.json``."""
    # 显式给路径就用它（测试用），否则跟随数据目录
    return Path(path) if path is not None else config.data_dir() / GEO_FILENAME


def load_cached(path: Optional[Path] = None) -> Dict[str, Any]:
    """Return the cache as ``{"fetched_at": datetime, "location": {...}}``.

    A missing file is normal (nothing has been looked up yet) and yields an empty
    mapping; a corrupt one raises :class:`GeoError` so the caller can decide.
    """
    target = cache_path(path)
    # 还没查过：空的（不是错误）
    if not target.is_file():
        return {}
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeoError("{} is not usable: {}".format(GEO_FILENAME, exc)) from exc
    # 结构不对（手改成列表之类）也当坏文件
    if not isinstance(raw, Mapping):
        raise GeoError("{} must contain an object".format(GEO_FILENAME))
    # 时间戳解析：坏格式当"没有时间"，于是缓存一定被当成过期
    moment: Optional[datetime] = None
    try:
        moment = datetime.fromisoformat(str(raw.get("fetched_at") or ""))
    except ValueError:
        moment = None
    location = raw.get("location")
    return {
        "fetched_at": moment,
        "location": dict(location) if isinstance(location, Mapping) else {},
    }


def save_cached(
    location: Mapping[str, Any],
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Path:
    """Write *location* to the cache file (atomically) and return the path."""
    target = cache_path(path)
    # 目录可能还不存在（全新安装）
    target.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "fetched_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "location": dict(location),
        # 一句中文说明：用户打开这个文件就知道它是什么、删了会怎样
        "note": "地理位置缓存，删掉它下次阅读会重新查询（只用来解锁地理成就）",
    }
    # 同目录临时文件 + os.replace：读到的永远是完整的旧文件或新文件
    handle, temp_name = tempfile.mkstemp(prefix=GEO_FILENAME + ".", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            # ensure_ascii=False 让中文地名可读
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        # 原子替换
        os.replace(temp_name, target)
    except OSError:
        # 写失败：清掉临时文件，别在数据目录里留垃圾
        try:
            os.unlink(temp_name)
        except OSError:  # pragma: no cover - 临时文件已经不在了
            pass
        raise
    return target


def load_location(
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
    fetcher: Optional[Callable[[str, float], Any]] = None,
    max_age: float = CACHE_SECONDS,
    allow_fetch: bool = True,
) -> Dict[str, str]:
    """Return ``{country, country_code, continent, city, timezone}`` for this machine.

    Order of preference:

    1. a cache entry younger than *max_age* -- no network at all,
    2. a fresh lookup, cached when it succeeds,
    3. the stale cache entry, when the lookup failed but something is on disk,
    4. ``{}`` -- offline, and the geography achievements simply stay locked.

    ``allow_fetch=False`` (the ``stats.geo_lookup`` setting turned off) keeps the whole
    thing offline: only a fresh-enough cache entry is ever used.
    """
    moment = now or datetime.now()
    # 先看缓存：新鲜就直接用，一步网络请求都不发
    cached: Dict[str, Any] = {}
    try:
        cached = load_cached(path)
    except GeoError:
        # 缓存坏了：当作没有缓存（下一次成功查询会把它覆盖掉）
        cached = {}
    stored = cached.get("location") or {}
    fetched_at = cached.get("fetched_at")
    # 缓存够新（且不是"未来时间"）：直接返回
    if stored and isinstance(fetched_at, datetime):
        age = (moment - fetched_at).total_seconds()
        if 0 <= age < max_age:
            return dict(stored)
    # 关了地理查询：只用缓存，过期也不查（离线承诺）
    if not allow_fetch:
        return dict(stored) if isinstance(fetched_at, datetime) else {}
    # 真的去查一次（失败返回空字典，不抛异常）
    fresh = fetch(fetcher=fetcher)
    if fresh:
        try:
            save_cached(fresh, path, now=moment)
        except OSError:
            # 缓存写不了（目录只读）也不影响这次解锁
            pass
        return fresh
    # 查询失败：过期的旧数据也比没有强
    return dict(stored) if isinstance(fetched_at, datetime) else {}

"""有道智云（Youdao OpenAPI v3），签名用 SHA-256。

有道 v3 的签名是 ``sha256(appKey + 截断后的 q + salt + curtime + appSecret)``，
其中"截断"规则很特别：**超过 20 个字符时**取前 10 个 + 总长度 + 后 10 个字符。
这里的长度按**字符数**算（Python 的 ``len`` 正好就是字符数），不是终端显示列数。

请求与签名同样拆成可单测的纯函数；发请求走模块级 :func:`_http_get`。
"""

# 延迟求值类型注解
from __future__ import annotations

# SHA-256 签名
import hashlib
# 生成 salt
import random
# 当前时间戳（curtime）
import time
# 类型注解
from typing import Any, Dict, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, TranslateUnavailable, Translator

__all__ = ["YoudaoTranslator", "ENDPOINT", "truncate"]

# 有道开放平台的地址
ENDPOINT = "https://openapi.youdao.com/api"
# 单次请求超时（秒）
TIMEOUT = 30
# 超过这个字符数才需要"截断"参与签名
TRUNCATE_THRESHOLD = 20


def truncate(text: str) -> str:
    """Return the form of *text* that Youdao puts into its signature.

    Short input is used verbatim; longer input collapses to
    ``first 10 + character count + last 10`` characters.
    """
    # 未超阈值：原样参与签名
    if len(text) <= TRUNCATE_THRESHOLD:
        return text
    # 超阈值：前 10 + 长度 + 后 10
    return "{}{}{}".format(text[:10], len(text), text[-10:])


def _http_get(url: str, params: Dict[str, Any], timeout: int) -> Any:
    """GET *url* and return the decoded JSON body (tests replace this)."""
    # 延迟导入 requests
    import requests

    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _salt() -> str:
    """Return a random salt for one request."""
    # 有道只要求唯一/随机
    return str(random.randint(1, 2**31 - 1))


# 有道认的语言码：简体中文是 zh-CHS
LANGUAGE_CODES = {
    "zh": "zh-CHS",
    "cn": "zh-CHS",
    "zh-cn": "zh-CHS",
    "chinese": "zh-CHS",
    "en": "en",
    "eng": "en",
    "english": "en",
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "ko": "ko",
    "kr": "ko",
    "korean": "ko",
}


class YoudaoTranslator(Translator):
    """有道智云文本翻译（需要应用 ID 与应用密钥）。"""

    name = "youdao"
    required_credentials = (("youdao_appid", "应用 ID"), ("youdao_secret", "应用密钥"))
    credential_keys = ("youdao_appid", "youdao_secret")
    language_codes = LANGUAGE_CODES

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        timeout: int = TIMEOUT,
    ) -> None:
        # 收好 appKey / appSecret
        super().__init__(credentials)
        # 超时时间不能是 0
        self.timeout = int(timeout) or TIMEOUT
        # 发过多少次请求
        self.requests = 0

    def sign(self, text: str, salt: str, curtime: str) -> str:
        """Return ``sha256(appKey + truncate(text) + salt + curtime + secret)``."""
        # 顺序固定，q 用截断后的形式
        raw = "{}{}{}{}{}".format(
            self.credential("youdao_appid"),
            truncate(text),
            salt,
            curtime,
            self.credential("youdao_secret"),
        )
        # 十六进制小写 SHA-256
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def params(
        self,
        text: str,
        from_lang: str = "auto",
        to_lang: str = "en",
        salt: str = "",
        curtime: str = "",
    ) -> Dict[str, str]:
        """Return the query string of one request (exposed for the tests)."""
        # salt / curtime 没给就现生成（测试显式传，好断言签名）
        salt = salt or _salt()
        curtime = curtime or str(int(time.time()))
        return {
            "q": text,
            "from": self.language(from_lang, "auto"),
            "to": self.language(to_lang, "en"),
            "appKey": self.credential("youdao_appid"),
            "salt": salt,
            "sign": self.sign(text, salt, curtime),
            "signType": "v3",
            "curtime": curtime,
        }

    def parse(self, data: Any) -> str:
        """Pull the translation out of a Youdao response body."""
        # 响应必须是对象
        if not isinstance(data, dict):
            raise TranslateError("有道翻译返回了无法解析的响应")
        # errorCode 不为 "0" 就是失败
        code = str(data.get("errorCode") or "0")
        if code != "0":
            raise TranslateError(
                "有道翻译错误 {}：{}".format(code, data.get("error") or "")
            )
        # 正常结构是 translation: ["..."]，多行时多条
        pieces = [str(piece) for piece in (data.get("translation") or [])]
        # 一条都没有就当作失败
        if not pieces:
            raise TranslateError("有道翻译没有返回译文")
        # 多条之间用换行拼回去
        return "\n".join(pieces)

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate one chunk through Youdao."""
        # 空文本不发请求
        if not str(text or "").strip():
            return ""
        # 缺凭证就给可操作提示
        missing = self.missing_credentials(self.credentials)
        if missing:
            raise TranslateError(
                "有道翻译缺少 {}：运行 werd config translate 配置".format("、".join(missing))
            )
        # 计数 +1
        self.requests += 1
        try:
            # 发请求（签名在 params 里算好）
            data = _http_get(ENDPOINT, self.params(text, from_lang, to_lang), self.timeout)
        except Exception as exc:
            # 建连 / HTTP 状态码错误：归为"引擎不可达"
            raise TranslateUnavailable(
                "有道翻译请求失败：{}".format(str(exc) or exc.__class__.__name__)
            ) from exc
        # 再解析
        return self.parse(data)

"""Baidu 通用翻译 API（V2），签名用 MD5。

百度要求的签名是 ``md5(appid + q + salt + secret)`` —— 注意**待译文本原样参与签名**，
所以签名函数不能先 strip 或截断文本，否则服务端一定报 54001（Invalid Sign）。

请求与签名拆成纯函数（:meth:`BaiduTranslator.params` / :meth:`BaiduTranslator.sign` /
:meth:`BaiduTranslator.parse`），这样不联网也能把签名和解析测死；真正发请求的那一步
走模块级 :func:`_http_get`，测试可以替换掉它。
"""

# 延迟求值类型注解
from __future__ import annotations

# MD5 签名
import hashlib
# 生成随机 salt
import random
# 类型注解
from typing import Any, Dict, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, TranslateUnavailable, Translator

__all__ = ["BaiduTranslator", "ENDPOINT"]

# 通用翻译 API 的地址
ENDPOINT = "https://fanyi-api.baidu.com/api/trans/vip/translate"
# 单次请求超时（秒）
TIMEOUT = 30

# 百度认的语言码：中文是 zh（不是 zh-CN），日韩也有自己的写法
LANGUAGE_CODES = {
    "zh": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
    "en": "en",
    "eng": "en",
    "english": "en",
    "ja": "jp",
    "jp": "jp",
    "japanese": "jp",
    "ko": "kor",
    "kr": "kor",
    "korean": "kor",
}


def _http_get(url: str, params: Dict[str, Any], timeout: int) -> Any:
    """GET *url* and return the decoded JSON body.

    Kept as a module level function so tests can replace the network with a canned
    answer without touching :mod:`requests`.
    """
    # 延迟导入：本模块在没装 requests 的环境里也能被 import
    import requests

    # 让 requests 抛 4xx/5xx，交给调用方统一包装
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _salt() -> str:
    """Return a random salt for one request."""
    # 百度只要求"随机数"，取值范围没有硬性规定
    return str(random.randint(1, 2**31 - 1))


class BaiduTranslator(Translator):
    """百度通用翻译 API V2（需要 APPID 与密钥）。"""

    name = "baidu"
    required_credentials = (("baidu_appid", "APPID"), ("baidu_secret", "密钥"))
    credential_keys = ("baidu_appid", "baidu_secret")
    language_codes = LANGUAGE_CODES

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        timeout: int = TIMEOUT,
    ) -> None:
        # 收好 appid / secret
        super().__init__(credentials)
        # 超时时间不能是 0
        self.timeout = int(timeout) or TIMEOUT
        # 发过多少次请求
        self.requests = 0

    def sign(self, text: str, salt: str) -> str:
        """Return ``md5(appid + text + salt + secret)``."""
        # 顺序固定：appid、待译文本、salt、密钥
        raw = "{}{}{}{}".format(
            self.credential("baidu_appid"), text, salt, self.credential("baidu_secret")
        )
        # UTF-8 编码后取 MD5 十六进制串
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def params(
        self, text: str, from_lang: str = "auto", to_lang: str = "en", salt: str = ""
    ) -> Dict[str, str]:
        """Return the query string of one request (exposed for the tests)."""
        # salt 没给就现生成一个（测试会显式传，好断言签名）
        salt = salt or _salt()
        return {
            "q": text,
            "from": self.language(from_lang, "auto"),
            "to": self.language(to_lang, "en"),
            "appid": self.credential("baidu_appid"),
            "salt": salt,
            "sign": self.sign(text, salt),
        }

    def parse(self, data: Any) -> str:
        """Pull the translation out of a Baidu response body."""
        # 响应必须是对象
        if not isinstance(data, dict):
            raise TranslateError("百度翻译返回了无法解析的响应")
        # 有 error_code 就说明失败了（成功时不带这个字段）
        if data.get("error_code"):
            raise TranslateError(
                "百度翻译错误 {}：{}".format(data["error_code"], data.get("error_msg") or "")
            )
        # 正常结构是 trans_result: [{src, dst}]，多行时会有多条
        results = data.get("trans_result") or []
        pieces = [str(item.get("dst") or "") for item in results if isinstance(item, dict)]
        # 一条都没有就当作失败（避免把空串当成译文悄悄用掉）
        if not pieces:
            raise TranslateError("百度翻译没有返回译文")
        # 多行结果之间用换行拼回去
        return "\n".join(pieces)

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate one chunk through Baidu."""
        # 空文本不发请求
        if not str(text or "").strip():
            return ""
        # 缺凭证就给出可操作的提示
        missing = self.missing_credentials(self.credentials)
        if missing:
            raise TranslateError(
                "百度翻译缺少 {}：运行 werd config translate 配置".format("、".join(missing))
            )
        # 计数 +1
        self.requests += 1
        try:
            # 发请求（签名在 params 里算好）
            data = _http_get(ENDPOINT, self.params(text, from_lang, to_lang), self.timeout)
        except Exception as exc:
            # 建连 / HTTP 状态码错误：归为"引擎不可达"（整本书会因此中止）
            raise TranslateUnavailable(
                "百度翻译请求失败：{}".format(str(exc) or exc.__class__.__name__)
            ) from exc
        # 再解析
        return self.parse(data)

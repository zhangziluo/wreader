"""腾讯云机器翻译（TMT ``TextTranslate``），签名用 TC3-HMAC-SHA256。

腾讯云的签名分四步：拼规范请求串 → 拼待签串 → 逐级派生签名密钥 → 拼 ``Authorization``
头。步骤多但全是确定性的，所以整条链路都用 :class:`TencentTranslator` 的方法暴露出来
（:meth:`~TencentTranslator.canonical_request`、:meth:`~TencentTranslator.authorization`），
测试可以拿固定时间戳把签名逐字节验一遍；发请求走模块级 :func:`_http_post`。
"""

# 延迟求值类型注解
from __future__ import annotations

# 规范化请求串要用 JSON；HMAC-SHA256 与 SHA-256 用于签名
import hashlib
import hmac
import json
# 当前时间戳；UTC 日期要跟凭证作用域一致
import time
from datetime import datetime, timezone
# 类型注解
from typing import Any, Dict, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, TranslateUnavailable, Translator

__all__ = ["TencentTranslator", "ENDPOINT", "SERVICE", "VERSION"]

# TMT 的服务地址（规范 URI 就是 "/"）
ENDPOINT = "https://tmt.tencentcloudapi.com"
# 服务名与 API 版本，两个都要参与签名
SERVICE = "tmt"
VERSION = "2018-03-21"
ACTION = "TextTranslate"
# 默认地域
DEFAULT_REGION = "ap-beijing"
# 签名算法名与参与签名的头
ALGORITHM = "TC3-HMAC-SHA256"
SIGNED_HEADERS = "content-type;host;x-tc-action"
HOST = "tmt.tencentcloudapi.com"
# 单次请求超时（秒）
TIMEOUT = 30

# 腾讯云认的语言码
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
    "ko": "kr",
    "kr": "kr",
    "korean": "kr",
}


def _http_post(url: str, body: str, headers: Dict[str, str], timeout: int) -> Any:
    """POST *body* and return the decoded JSON body (tests replace this)."""
    # 延迟导入 requests
    import requests

    response = requests.post(
        url, data=body.encode("utf-8"), headers=headers, timeout=timeout
    )
    response.raise_for_status()
    return response.json()


def _hash_sha256(value: str) -> str:
    """Return the lowercase hex SHA-256 of *value*."""
    # 签名里所有的哈希都是对 UTF-8 字节算的
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hmac_sha256(key: bytes, value: str) -> bytes:
    """Return the raw HMAC-SHA256 of *value* under *key*."""
    # 派生签名密钥时用原始字节，最后一步才转十六进制
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


class TencentTranslator(Translator):
    """腾讯云 TMT 文本翻译（需要 SecretId 与 SecretKey）。"""

    name = "tencent"
    required_credentials = (
        ("tencent_secret_id", "SecretId"),
        ("tencent_secret_key", "SecretKey"),
    )
    credential_keys = ("tencent_secret_id", "tencent_secret_key", "tencent_region")
    language_codes = LANGUAGE_CODES

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        region: str = "",
        timeout: int = TIMEOUT,
    ) -> None:
        # 收好 SecretId / SecretKey
        super().__init__(credentials)
        # 地域也要参与签名（X-TC-Region）：关键字参数 > 凭证表 > 默认值。
        # ⚠️ region 的默认值必须是空串：写成 DEFAULT_REGION 的话，
        # `region or ...` 永远走左边，凭证表里的地域就永远读不到。
        self.region = str(region or self.credential("tencent_region", DEFAULT_REGION))
        # 超时时间不能是 0
        self.timeout = int(timeout) or TIMEOUT
        # 发过多少次请求
        self.requests = 0

    # -- 请求构造（纯函数，可单测）--------------------------------------
    def payload(
        self, text: str, from_lang: str = "auto", to_lang: str = "en"
    ) -> Dict[str, Any]:
        """Return the JSON body of one ``TextTranslate`` call."""
        # ProjectId 固定 0（默认项目）
        return {
            "SourceText": text,
            "Source": self.language(from_lang, "auto"),
            "Target": self.language(to_lang, "en"),
            "ProjectId": 0,
        }

    def body(self, payload: Mapping[str, Any]) -> str:
        """Serialise *payload* exactly the way it is hashed and sent."""
        # 紧凑且不做 ASCII 转义：中文原文按 UTF-8 出现，哈希与发送用的是同一串
        return json.dumps(dict(payload), ensure_ascii=False, separators=(",", ":"))

    def canonical_request(self, body: str) -> str:
        """Return the TC3 canonical request string for *body*."""
        # 规范头：小写头名、冒号后无空格、按头名排序，最后留一个换行
        canonical_headers = (
            "content-type:application/json; charset=utf-8\n"
            "host:{}\n"
            "x-tc-action:{}\n".format(HOST, ACTION.lower())
        )
        # 六段用换行连接：方法、URI、查询串、规范头、参与签名的头名、请求体哈希
        return "\n".join(
            ["POST", "/", "", canonical_headers, SIGNED_HEADERS, _hash_sha256(body)]
        )

    def string_to_sign(self, body: str, timestamp: int) -> str:
        """Return the TC3 string to sign for *body*."""
        # 日期取 UTC，和凭证作用域里的日期必须一致
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        # 凭证作用域：日期/服务/tc3_request
        scope = "{}/{}/tc3_request".format(date, SERVICE)
        # 四段：算法、时间戳、作用域、规范请求串的哈希
        return "\n".join(
            [ALGORITHM, str(timestamp), scope, _hash_sha256(self.canonical_request(body))]
        )

    def authorization(self, body: str, timestamp: int) -> str:
        """Return the ``Authorization`` header value for *body*."""
        # 日期与作用域
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
        scope = "{}/{}/tc3_request".format(date, SERVICE)
        # 逐级派生签名密钥：TC3+SecretKey -> 日期 -> 服务 -> tc3_request
        secret_date = _hmac_sha256(
            ("TC3" + self.credential("tencent_secret_key")).encode("utf-8"), date
        )
        secret_service = _hmac_sha256(secret_date, SERVICE)
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        # 最后一步对"待签串"做 HMAC 并转十六进制
        signature = hmac.new(
            secret_signing,
            self.string_to_sign(body, timestamp).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        # 拼成腾讯云要的那一行
        return (
            "{} Credential={}/{}, SignedHeaders={}, Signature={}".format(
                ALGORITHM,
                self.credential("tencent_secret_id"),
                scope,
                SIGNED_HEADERS,
                signature,
            )
        )

    def headers(self, body: str, timestamp: int) -> Dict[str, str]:
        """Return every HTTP header of one request."""
        return {
            "Authorization": self.authorization(body, timestamp),
            "Content-Type": "application/json; charset=utf-8",
            "Host": HOST,
            "X-TC-Action": ACTION,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": VERSION,
            "X-TC-Region": self.region,
        }

    def parse(self, data: Any) -> str:
        """Pull the translation out of a Tencent response body."""
        # 响应必须是对象，且带 Response
        if not isinstance(data, dict) or not isinstance(data.get("Response"), dict):
            raise TranslateError("腾讯云翻译返回了无法解析的响应")
        response = data["Response"]
        # Response 里有 Error 就是失败
        error = response.get("Error") or {}
        if error:
            raise TranslateError(
                "腾讯云翻译错误 {}：{}".format(
                    error.get("Code") or "", error.get("Message") or ""
                )
            )
        # 正常结构是 Response.TargetText
        text = str(response.get("TargetText") or "")
        if not text:
            raise TranslateError("腾讯云翻译没有返回译文")
        return text

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate one chunk through Tencent Cloud."""
        # 空文本不发请求
        if not str(text or "").strip():
            return ""
        # 缺凭证就给可操作提示
        missing = self.missing_credentials(self.credentials)
        if missing:
            raise TranslateError(
                "腾讯云翻译缺少 {}：运行 werd config translate 配置".format("、".join(missing))
            )
        # 请求体先序列化出来，签名与发送必须用同一串
        body = self.body(self.payload(text, from_lang, to_lang))
        # 时间戳由这里生成，签名与 X-TC-Timestamp 共用
        timestamp = int(time.time())
        # 计数 +1
        self.requests += 1
        try:
            # 发请求
            data = _http_post(ENDPOINT, body, self.headers(body, timestamp), self.timeout)
        except Exception as exc:
            # 建连 / HTTP 状态码错误：归为"引擎不可达"
            raise TranslateUnavailable(
                "腾讯云翻译请求失败：{}".format(str(exc) or exc.__class__.__name__)
            ) from exc
        # 再解析
        return self.parse(data)

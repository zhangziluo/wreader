"""DeepSeek（OpenAI 兼容的 ``chat/completions``），默认流式。

从 ``translator.DeepSeekBackend`` 搬过来的引擎实现。和其它引擎不同，DeepSeek 是**通用大模型**，
所以"翻译"靠一段系统提示词来定义风格；非流式的 ``translate()`` 就是把流式片段拼起来。
"""

# 延迟求值类型注解
from __future__ import annotations

# 读写环境变量（DEEPSEEK_API_KEY）与解析 SSE
import json
import os
# 类型注解
from typing import Any, Dict, Iterator, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, TranslateUnavailable, Translator

__all__ = [
    "DEEPSEEK_SYSTEM_PROMPT",
    "DEFAULT_MODEL",
    "DEFAULT_URL",
    "DeepSeekTranslator",
    "system_prompt",
]

# 默认模型与接口地址（与重构前一致）
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_URL = "https://api.deepseek.com/v1/chat/completions"
# temperature 调到 0.3：翻译要稳，不要发挥
TEMPERATURE = 0.3
# 大模型响应慢，超时给得比其它引擎宽
TIMEOUT = 120

# 给 DeepSeek 的系统提示词，决定翻译风格
DEEPSEEK_SYSTEM_PROMPT = (
    "你是一个专业的中译英翻译，擅长将中文网络小说翻译成流畅自然的英文，"
    "保留叙事节奏和人物情感。"
)


def system_prompt(target: str) -> str:
    """Return the system prompt for *target*.

    The Chinese-to-English prompt is the one the project was specified with; any
    other target gets an equivalent so that single word lookups still work.
    """
    # 目标语言是英文：用项目定制的那段提示词
    if target in ("en", "en-US", "en-GB"):
        return DEEPSEEK_SYSTEM_PROMPT
    # 其它目标语言：套一个通用模板
    return (
        "你是一个专业的翻译，请把用户给出的文本翻译成 {}，"
        "保留叙事节奏和人物情感，只输出译文。".format(target)
    )


def parse_sse(line: Any) -> Optional[str]:
    """Return the text carried by one SSE *line*.

    ``None`` means the stream is finished (``data: [DONE]``); an empty string
    means the frame carried no text at all.
    """
    # 空行（SSE 的心跳/分隔）：没带文本
    if not line:
        return ""
    # requests 给的是 bytes，先转字符串
    if isinstance(line, bytes):
        raw = line.decode("utf-8", errors="replace")
    else:
        raw = str(line)
    raw = raw.strip()
    # 不是 "data:" 开头的行（比如 event: 行）直接忽略
    if not raw or not raw.startswith("data:"):
        return ""
    # 去掉前缀 "data:"（5 个字符）
    body = raw[5:].strip()
    # [DONE] 表示流结束：返回 None 让调用方 break
    if body == "[DONE]":
        return None
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # 半截 JSON（不该发生）：当成空帧
        return ""
    # 收集这一帧里的文本片段
    pieces = []
    for choice in data.get("choices") or []:
        # 流式格式：delta.content
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            pieces.append(str(content))
        # 非流式格式：choice.text（仅在没有 delta 时才取）
        text = choice.get("text")
        if text and not delta:
            pieces.append(str(text))
    return "".join(pieces)


def _http_post(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int) -> Any:
    """POST *payload* and return the streaming response (tests replace this)."""
    # 延迟导入 requests
    import requests

    response = requests.post(url, json=payload, headers=headers, stream=True, timeout=timeout)
    response.raise_for_status()
    return response


class DeepSeekTranslator(Translator):
    """DeepSeek chat completions, streamed and joined back into one string."""

    name = "deepseek"
    required_credentials = (("deepseek_api_key", "API key"),)
    credential_keys = ("deepseek_api_key", "deepseek_model", "deepseek_url")

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        model: str = "",
        url: str = "",
        temperature: float = TEMPERATURE,
        timeout: int = TIMEOUT,
    ) -> None:
        # 基类收好凭证
        super().__init__(credentials)
        # 配置优先，其次环境变量
        self.api_key = self.credential("deepseek_api_key") or os.environ.get(
            "DEEPSEEK_API_KEY", ""
        )
        # 关键字参数优先（测试用），其次 [translate]，最后默认值
        self.model = str(model or self.credential("deepseek_model", DEFAULT_MODEL))
        self.url = str(url or self.credential("deepseek_url", DEFAULT_URL))
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        # 发过多少次请求
        self.requests = 0

    def available(self) -> bool:
        """Whether a key is present.

        The key may come from ``$DEEPSEEK_API_KEY`` instead of the settings file,
        so the base implementation (which only looks at the credential mapping)
        would wrongly report "not configured".
        """
        # 有 key 就能用（连不上是请求阶段的事）
        return bool(self.api_key)

    def payload(self, text: str, target: str = "en", stream: bool = True) -> Dict[str, Any]:
        """Return the JSON body sent to the API (exposed for the tests)."""
        # 标准的 chat completions 请求体：system 定风格，user 放待翻译文本
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt(target)},
                {"role": "user", "content": text},
            ],
            "temperature": self.temperature,
            "stream": bool(stream),
        }

    def headers(self) -> Dict[str, str]:
        """Return the HTTP headers, including the bearer token."""
        # 用 Bearer token 鉴权
        return {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }

    def stream(
        self, text: str, from_lang: str = "auto", to_lang: str = "en"
    ) -> Iterator[str]:
        """Yield the translation as the server streams it."""
        # 空文本不请求
        if not str(text or "").strip():
            return
        # 没 key 就给出可操作的提示
        if not self.api_key:
            raise TranslateUnavailable(
                "DeepSeek 需要 API key：运行 werd config translate 配置，"
                "或导出 DEEPSEEK_API_KEY"
            )
        # 计数 +1
        self.requests += 1
        try:
            # stream=True 让 requests 不把响应体一次读完
            response = _http_post(
                self.url,
                self.payload(text, self.language(to_lang, "en"), stream=True),
                self.headers(),
                self.timeout,
            )
        except Exception as exc:
            # 建连阶段失败：归为"引擎不可用"（会中断整本书的翻译）
            raise TranslateUnavailable(
                "DeepSeek request failed: {}".format(str(exc) or exc.__class__.__name__)
            ) from exc
        try:
            # 逐行读 SSE（不预先解码，交给 parse_sse 处理字节）
            for line in response.iter_lines(decode_unicode=False):
                piece = parse_sse(line)
                # None 表示流正常结束，停止读取
                if piece is None:
                    break
                # 空串表示这一帧没带文本（比如心跳）
                if piece:
                    yield piece
        except TranslateError:
            # 已经是我们的异常，原样上抛
            raise
        except Exception as exc:  # a connection that dies mid answer
            # 读到一半连接断了
            raise TranslateUnavailable(
                "DeepSeek stream failed: {}".format(str(exc) or exc.__class__.__name__)
            ) from exc

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Return the whole translation, joining the streamed pieces."""
        # 流式接口是核心，非流式就是把所有片段拼起来
        return "".join(self.stream(text, from_lang, to_lang))

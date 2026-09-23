"""Google, through the optional ``deep-translator`` package.

This is the free, **keyless** engine and therefore the default one: it needs no
signup, which is what makes ``werd`` translate out of the box.  It is also the only
engine that has to be throttled, hence the ``pause()`` override -- the translator
calls it between batches and the free endpoint starts refusing requests if you
hammer it.
"""

# 延迟求值类型注解
from __future__ import annotations

# 批次之间的限速等待
import time
# 类型注解
from typing import Any, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, Translator

__all__ = ["DEFAULT_BATCH_SLEEP_SECONDS", "GoogleTranslator"]

# 批次之间的默认等待秒数（跟重构前 translator.BATCH_SLEEP_SECONDS 一致）
DEFAULT_BATCH_SLEEP_SECONDS = 1.0

# deep-translator 认的语言码：中文要写成 zh-CN，其它基本与规范码一致
LANGUAGE_CODES = {
    "zh": "zh-CN",
    "cn": "zh-CN",
    "zh-cn": "zh-CN",
    "chinese": "zh-CN",
    "en": "en",
    "eng": "en",
    "english": "en",
}


class GoogleTranslator(Translator):
    """``deep_translator.GoogleTranslator`` wrapped as an engine."""

    name = "google"
    # 只有装了 deep-translator 才能用
    requires_package = "deep_translator"
    language_codes = LANGUAGE_CODES

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        sleep_seconds: float = DEFAULT_BATCH_SLEEP_SECONDS,
    ) -> None:
        # 基类先收好凭证（Google 不需要任何凭证，留个空表）
        super().__init__(credentials)
        # 等待时间不能为负
        self.sleep_seconds = max(0.0, float(sleep_seconds))
        # 发过多少次请求（测试会断言这个，也方便排查限流）
        self.requests = 0

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate one chunk through the free Google endpoint."""
        # 空文本不发请求，直接返回空
        if not str(text or "").strip():
            return ""
        try:
            # 延迟导入：没装 deep-translator 也能用别的引擎
            from deep_translator import GoogleTranslator as _GoogleTranslator
        except ImportError as exc:
            raise TranslateError(
                "deep-translator is not installed: pip install 'wreader[google]'"
            ) from exc
        # 计数 +1
        self.requests += 1
        try:
            # 真正调用；返回 None 时兜成空串
            return (
                _GoogleTranslator(
                    source=self.language(from_lang), target=self.language(to_lang)
                ).translate(text)
                or ""
            )
        except Exception as exc:  # rate limits, DNS failures, rejected codes
            # 限流、DNS、语言码被拒等统一归为引擎失败
            raise TranslateError(
                "Google translation failed: {}".format(
                    str(exc) or exc.__class__.__name__
                )
            ) from exc

    def pause(self) -> None:
        """Wait out the throttle between batches."""
        # 配了等待时间就真的睡一会儿；设 0 表示不限速
        if self.sleep_seconds:
            time.sleep(self.sleep_seconds)

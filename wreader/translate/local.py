"""Argos Translate：完全离线的本地引擎（需要 ``pip install argostranslate``）。

它和别的引擎不一样：不需要任何密钥，但**必须在本地先装好语言包**，否则第一次翻译会
触发模型下载（很大）或直接失败。所以这里：

* 只在真正调用时才 ``import argostranslate``（那个包很重，导入就要几秒）；
* 语言包没装时给出**可操作**的提示，而不是让底层抛一串栈；
* 语言码用两字母形式（Argos 用的是 ``zh`` / ``en``），与项目规范码做一次映射。
"""

# 延迟求值类型注解
from __future__ import annotations

# 类型注解
from typing import Any, List, Mapping, Optional

# 本包的引擎基类与异常
from .base import TranslateError, Translator

__all__ = ["LocalTranslator", "PACKAGE_NAME", "installed_languages"]

# 可选包名（供 available() 判断装没装）
PACKAGE_NAME = "argostranslate"

# Argos 认的语言码：两个字母，简体中文是 zh
LANGUAGE_CODES = {
    "zh": "zh",
    "cn": "zh",
    "zh-cn": "zh",
    "chinese": "zh",
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


def installed_languages() -> List[str]:
    """Return the language codes Argos has packages for, or ``[]``.

    Never raises: a missing package simply means "nothing installed".
    """
    try:
        # 延迟导入：没装也别让整个模块 import 失败。
        # pyright 会报"找不到这个包"——这是**故意的可选依赖**，CI 里不一定装，
        # 所以这一行显式忽略缺失导入（真正没装时下面的 except 会兜住）。
        from argostranslate import translate as argos_translate  # pyright: ignore[reportMissingImports]
    except ImportError:
        return []
    # 有的版本是 get_installed_languages()，取它的 code 属性
    try:
        return [str(language.code) for language in argos_translate.get_installed_languages()]
    except Exception:  # pragma: no cover - a broken/partial install
        return []


class LocalTranslator(Translator):
    """Argos Translate, running entirely on this machine."""

    name = "local"
    # 不需要密钥，但需要可选包
    requires_package = PACKAGE_NAME
    language_codes = LANGUAGE_CODES

    def __init__(
        self,
        credentials: Optional[Mapping[str, Any]] = None,
        timeout: int = 0,
    ) -> None:
        # 没有凭证，但基类仍然收下（保持构造统一）
        super().__init__(credentials)
        # 本地翻译没有网络超时，留个字段是为了与其它引擎签名一致
        self.timeout = int(timeout)
        # 调用次数（测试用）
        self.requests = 0

    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate one chunk locally."""
        # 空文本直接返回
        if not str(text or "").strip():
            return ""
        try:
            # 延迟导入：包很重，不用本地引擎就不该付这个代价
            # （可选依赖，见 installed_languages() 里的说明）
            from argostranslate import translate as argos_translate  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            raise TranslateError(
                "本地翻译需要 Argos Translate：pip install 'wreader[local]'"
            ) from exc
        # 语言码按 Argos 的写法转换；auto 无法本地识别，默认按英文源处理
        source = self.language(from_lang, "en")
        target = self.language(to_lang, "en")
        # auto 在本地没有意义：Argos 必须先知道源语言
        if source == "auto":
            source = "en"
        # 计数 +1
        self.requests += 1
        try:
            translated = argos_translate.translate(text, source, target)
        except Exception as exc:
            # 语言包缺失是最常见的失败：把安装方法写进提示
            raise TranslateError(
                "本地翻译失败（{} -> {}）：{}。缺语言包时可用 "
                "python -c \"import argostranslate.package as p; p.update_package_index(); "
                "p.install_from_index(p.get_available_packages()[0])\" 安装".format(
                    source, target, str(exc) or exc.__class__.__name__
                )
            ) from exc
        # 底层返回 None 时兜成空串
        return str(translated or "")

    def available(self) -> bool:
        """Whether the package is installed *and* has any language pack."""
        # 包都没装就不必再看语言包
        if not super().available():
            return False
        # 装了包但一个语言包都没有：第一次翻译必然失败，提前报"没配好"
        return bool(installed_languages())

    @classmethod
    def missing_credentials(cls, credentials: Optional[Mapping[str, object]] = None) -> List[str]:
        """Argos needs no credentials, so nothing can ever be missing."""
        # 覆盖基类：否则空凭证表会被 configure() 当成"缺东西"
        return []

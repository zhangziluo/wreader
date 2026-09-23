"""The translation engine contract every provider module implements.

An engine knows how to talk to **one** provider and nothing else::

    translate(text, from_lang="auto", to_lang="en") -> str

Everything that is not provider specific -- batching several paragraphs into one
request, the per chapter cache, the bilingual view, ``werd translate`` -- lives in
:mod:`wreader.translator`, which wraps whichever engine the settings pick.  Adding
a provider therefore means writing one module here and registering it in
:data:`wreader.translate.ENGINE_FACTORIES`; no other module has to change.

Credentials arrive as a plain mapping rather than being read from
``settings.toml`` in here, so an engine never imports :mod:`wreader.config` and
cannot create an import cycle with :mod:`wreader.translator`.
"""

# 延迟求值类型注解
from __future__ import annotations

# 抽象基类：强制子类实现 translate()
from abc import ABC, abstractmethod
# 只查规格不真导入，用来判断可选包（如 argostranslate）装没装
from importlib.util import find_spec
# 类型注解
from typing import Any, Dict, List, Mapping, Optional, Tuple

__all__ = [
    "TranslateError",
    "TranslateUnavailable",
    "Translator",
    "language_code",
]


class TranslateError(Exception):
    """Raised when an engine cannot complete a translation it was asked for."""


class TranslateUnavailable(TranslateError):
    """Raised when an engine cannot be reached at all.

    The distinction matters to :mod:`wreader.translator`: a whole-book run gives up
    on a *connectivity* problem (no point trying the next 300 chapters) but carries
    on after a per-chapter failure such as a rejected string.
    """


def language_code(mapping: Mapping[str, str], name: Optional[str], default: str = "auto") -> str:
    """Map a canonical language name (``zh-CN``) onto the provider's spelling.

    The project stores language names in one canonical form (see
    :data:`wreader.translator.LANGUAGE_ALIASES`) but every provider spells them
    differently -- Baidu wants ``zh``, Youdao ``zh-CHS``, Tencent ``zh``.  A name
    the mapping does not know is passed through untouched, so a provider specific
    code typed by the user still works.
    """
    # 空值就退回默认（多数是 "auto"，即让后端自己识别）
    key = str(name or "").strip()
    if not key:
        return default
    # 查表时统一小写；查不到就原样交出去
    return mapping.get(key.lower(), key)


def _module_installed(name: str) -> bool:
    """Whether the optional package *name* can be imported right now."""
    # 只找规格、不真的导入：导入 heavy 包（argostranslate）代价很大
    try:
        return find_spec(name) is not None
    except (ImportError, ValueError):  # pragma: no cover - broken install
        return False


class Translator(ABC):
    """One translation provider.

    Subclasses set :attr:`name`, declare :attr:`required_credentials` (so the
    front end can tell "not configured yet" apart from "the request failed"),
    optionally list :attr:`requires_package`, and implement :meth:`translate`.

    :meth:`pause` exists because providers rate limit differently: the translator
    calls it between batches and the default is a no-op, which is right for every
    provider that does not need to be throttled.
    """

    #: Short id used in ``settings.toml`` and in error messages.
    name = "base"
    #: ``(credential key, what it is called in the docs)`` that must not be blank.
    required_credentials: Tuple[Tuple[str, str], ...] = ()
    #: Every settings key this engine reads (required *and* optional), so the
    #: factory can hand it exactly the slice of ``[translate]`` it cares about.
    credential_keys: Tuple[str, ...] = ()
    #: Name of an optional package this engine needs, or ``""``.
    requires_package = ""
    #: Canonical language name -> this provider's code.
    language_codes: Dict[str, str] = {}

    def __init__(self, credentials: Optional[Mapping[str, Any]] = None) -> None:
        # 凭证统一存成 str->str，取值时就不用关心 None 了
        self.credentials: Dict[str, str] = {
            str(key): str(value if value is not None else "")
            for key, value in dict(credentials or {}).items()
        }

    # -- credential helpers ----------------------------------------------
    def credential(self, key: str, default: str = "") -> str:
        """Return one credential, stripped; missing means *default*."""
        # 去空白：配置文件里手打进去的空格很常见
        value = str(self.credentials.get(key) or "").strip()
        return value or default

    @classmethod
    def missing_credentials(cls, credentials: Optional[Mapping[str, Any]] = None) -> List[str]:
        """Return the labels of the required credentials that are blank."""
        # 和 __init__ 一样先归一化，回调方不用自己处理 None
        values = {str(key): str(value or "").strip() for key, value in dict(credentials or {}).items()}
        # 只报"真正缺的"，顺序跟声明一致，提示语好读
        return [label for key, label in cls.required_credentials if not values.get(key)]

    @classmethod
    def configured(cls, credentials: Optional[Mapping[str, Any]] = None) -> bool:
        """Whether *credentials* are enough to even attempt a request."""
        # 缺凭证就不必发请求了
        return not cls.missing_credentials(credentials)

    def available(self) -> bool:
        """Whether this engine can run right now (credentials + optional package)."""
        # 先看凭证
        if not self.configured(self.credentials):
            return False
        # 再看待选的第三方包装没装
        if self.requires_package and not _module_installed(self.requires_package):
            return False
        return True

    # -- language helper -------------------------------------------------
    def language(self, name: Optional[str], default: str = "auto") -> str:
        """Translate a canonical language name into this provider's code."""
        # 走模块级工具函数，子类只要声明 language_codes 即可
        return language_code(self.language_codes, name, default)

    # -- the one thing every engine must do ------------------------------
    @abstractmethod
    def translate(self, text: str, from_lang: str = "auto", to_lang: str = "en") -> str:
        """Translate *text* and return the result (empty string for blank input)."""

    def pause(self) -> None:
        """Wait between two requests when the provider is rate limited."""
        # 默认不需要限速
        return None

"""可插拔的翻译引擎：按名字造一个 :class:`~wreader.translate.base.Translator`。

``settings.toml`` 的 ``[translate]`` 段用 ``engine`` 指定引擎；本模块负责把"引擎名 +
凭证表"变成一个可用的引擎对象。**这里刻意不读配置文件** —— 由
:mod:`wreader.translator` 解析好配置再传进来，这样本包不依赖 ``config``，
也不会和 ``translator`` 形成循环导入，而且整条分派逻辑都能脱离终端/网络单测。

加一个新厂商 = 写一个 ``xxx.py`` + 在 :data:`ENGINES` 里登记一行，别处都不用改。
"""

# 延迟求值类型注解
from __future__ import annotations

# 类型注解
from typing import Any, Dict, List, Mapping, Optional, Tuple

# 各引擎实现
from .baidu import BaiduTranslator
from .base import TranslateError, TranslateUnavailable, Translator, language_code
from .deepseek import DeepSeekTranslator
from .google import GoogleTranslator
from .local import LocalTranslator
from .tencent import TencentTranslator
from .youdao import YoudaoTranslator

# 公开的名字：基类/异常 + 分派函数 + 引擎登记表
__all__ = [
    "DEFAULT_ENGINE",
    "ENGINE_LABELS",
    "ENGINES",
    "TranslateError",
    "TranslateUnavailable",
    "Translator",
    "available_engines",
    "credential_keys",
    "engine_from_settings",
    "engine_names",
    "language_code",
    "make_engine",
    "missing_credentials",
    "not_configured_hint",
]

# 没配置时按默认用 Google（免费、免密钥，保证开箱可用）
DEFAULT_ENGINE = "google"

# 引擎名 -> 实现类。顺序即"大多数人的选择"顺序，展示时也用这个顺序。
ENGINES: Dict[str, type] = {
    "google": GoogleTranslator,
    "baidu": BaiduTranslator,
    "youdao": YoudaoTranslator,
    "tencent": TencentTranslator,
    "deepseek": DeepSeekTranslator,
    "local": LocalTranslator,
}

# 引擎名的中文说明，给 `werd config translate` 的菜单和文档用
ENGINE_LABELS: Dict[str, str] = {
    "google": "Google（免费，免密钥）",
    "baidu": "百度翻译（需要 APPID + 密钥）",
    "youdao": "有道智云（需要应用 ID + 密钥）",
    "tencent": "腾讯云 TMT（需要 SecretId + SecretKey）",
    "deepseek": "DeepSeek（需要 API key）",
    "local": "本地 Argos Translate（离线，需先装语言包）",
}

# 提示语：未配置或配置不全时统一让用户跑这个命令
CONFIGURE_HINT = "运行 werd config translate 配置翻译引擎"


def engine_names() -> List[str]:
    """Return every known engine name."""
    # 按登记顺序返回，菜单里顺序稳定
    return list(ENGINES)


def engine_class(engine: str) -> type:
    """Return the class for *engine*, or raise a helpful :class:`TranslateError`."""
    # 名字统一小写去空白，容忍配置文件里的手写空格/大小写
    key = str(engine or "").strip().lower()
    if key not in ENGINES:
        raise TranslateError(
            "未知的翻译引擎 {!r}，可选：{}".format(engine, "、".join(engine_names()))
        )
    return ENGINES[key]


def credential_keys(engine: str) -> Tuple[str, ...]:
    """Return every ``[translate]`` key *engine* reads."""
    # 交给引擎类自己声明，本模块不维护第二份清单
    return tuple(getattr(engine_class(engine), "credential_keys", ()))


def missing_credentials(
    engine: str, section: Optional[Mapping[str, Any]] = None
) -> List[str]:
    """Return the labels of the credentials *engine* still needs."""
    # 缺凭证是人最容易犯的错，所以单独暴露出来给前端提示
    return engine_class(engine).missing_credentials(section)


def make_engine(
    engine: str,
    credentials: Optional[Mapping[str, Any]] = None,
    **options: Any,
) -> Translator:
    """Build one engine from a name plus its credentials.

    *options* are passed on to the engine constructor, which is what the tests use
    to inject a fixed sleep / timeout without patching module globals.
    """
    # 认名字 -> 取类 -> 只把该类声明过的键喂给它
    cls = engine_class(engine)
    wanted = {key: (credentials or {}).get(key, "") for key in cls.credential_keys}
    return cls(wanted, **options)


def engine_from_settings(section: Optional[Mapping[str, Any]] = None) -> Optional[Translator]:
    """Build the engine named by a ``[translate]`` table.

    Returns ``None`` when no engine is selected (``engine`` blank), which the
    caller turns into either the legacy fallback or the "not configured yet" hint.
    """
    # 没有 section 或 engine 为空：交给调用方决定回退策略
    name = str((section or {}).get("engine") or "").strip()
    if not name:
        return None
    # 其余交给 make_engine（它会做白名单裁剪与未知引擎校验）
    return make_engine(name, section)


def available_engines() -> List[str]:
    """Return the engines that can actually run right now (deps + credentials)."""
    # 逐个试建：构造本身不发请求，安全
    usable = []
    for name in engine_names():
        try:
            if make_engine(name).available():
                usable.append(name)
        except TranslateError:  # pragma: no cover - 防御：构造不该失败
            continue
    return usable


def not_configured_hint(reason: str = "") -> str:
    """Return the message shown when no working engine is configured."""
    # 统一口径：告诉用户跑哪个命令，必要时附上具体原因
    if reason:
        return "{}（{}）".format(CONFIGURE_HINT, reason)
    return CONFIGURE_HINT

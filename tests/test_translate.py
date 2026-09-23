"""Tests for :mod:`wreader.translate` — the pluggable translation engines.

No test touches the network.  Every engine keeps its request building (signing,
canonical strings, payloads) in plain methods, and the one HTTP call each engine
makes goes through a module level ``_http_get`` / ``_http_post`` that these tests
replace with a canned answer.  Where a provider publishes a worked example
(Baidu's sign, Tencent's hashed payload) it is asserted against those literals.
"""

# 延迟求值类型注解
from __future__ import annotations

# 类型注解
from typing import Any, Dict, List

# pytest.raises / parametrize
import pytest

# 被测包与各引擎模块（要 monkeypatch 它们各自的 HTTP 接缝）
from wreader import translate
from wreader.translate import baidu, base, deepseek, google, local, tencent, youdao


# ------------------------------------------------------------------- registry
def test_the_registry_lists_every_engine_in_a_stable_order() -> None:
    # 顺序就是菜单顺序：google 打头（默认、免密钥）
    assert translate.engine_names() == [
        "google",
        "baidu",
        "youdao",
        "tencent",
        "deepseek",
        "local",
    ]
    # 每个引擎都要有中文说明，配置菜单才有得显示
    for name in translate.engine_names():
        assert name in translate.ENGINE_LABELS
    # 默认引擎是免费的 Google
    assert translate.DEFAULT_ENGINE == "google"


def test_credential_keys_come_from_the_engine_itself() -> None:
    # 引擎自己声明要读哪些键，配置向导据此提问
    assert translate.credential_keys("baidu") == ("baidu_appid", "baidu_secret")
    assert translate.credential_keys("deepseek") == (
        "deepseek_api_key",
        "deepseek_model",
        "deepseek_url",
    )
    # 不需要密钥的引擎声明为空
    assert translate.credential_keys("google") == ()
    assert translate.credential_keys("local") == ()


def test_missing_credentials_reports_labels_not_keys() -> None:
    # 报的是"人话"标签（提示语里直接可用）
    assert translate.missing_credentials("baidu", {}) == ["APPID", "密钥"]
    assert translate.missing_credentials("baidu", {"baidu_appid": "a"}) == ["密钥"]
    assert (
        translate.missing_credentials("baidu", {"baidu_appid": "a", "baidu_secret": "s"})
        == []
    )


def test_make_engine_rejects_an_unknown_name() -> None:
    with pytest.raises(translate.TranslateError) as excinfo:
        translate.make_engine("bing")
    # 报错里列出现有引擎，方便改正
    assert "baidu" in str(excinfo.value)


def test_make_engine_only_hands_over_the_keys_it_declares() -> None:
    engine = translate.make_engine(
        "baidu",
        {"baidu_appid": "a", "baidu_secret": "s", "tencent_region": "ignored"},
    )
    assert isinstance(engine, baidu.BaiduTranslator)
    # 别人的键不会被塞进来
    assert set(engine.credentials) == {"baidu_appid", "baidu_secret"}


def test_engine_from_settings_returns_none_when_unselected() -> None:
    # engine 为空 = 还没选过（调用方据此回退或提示）
    assert translate.engine_from_settings({}) is None
    assert translate.engine_from_settings({"engine": "  "}) is None
    # 选了就造出来
    picked = translate.engine_from_settings(
        {"engine": "youdao", "youdao_appid": "a", "youdao_secret": "s"}
    )
    assert isinstance(picked, youdao.YoudaoTranslator)


def test_available_engines_only_lists_usable_ones() -> None:
    # 本环境装了 deep-translator（google 可用），没装 argostranslate（local 不可用）
    usable = translate.available_engines()
    assert "google" in usable
    assert "local" not in usable
    # 需要密钥的引擎在没配密钥时不算可用
    assert "baidu" not in usable


def test_not_configured_hint_mentions_the_wizard() -> None:
    # 提示语统一指向那条命令，带上原因时也要保留
    assert "werd config translate" in translate.not_configured_hint()
    assert "缺 APPID" in translate.not_configured_hint("缺 APPID")


# ------------------------------------------------------------------ languages
@pytest.mark.parametrize(
    "name, expected",
    [("zh-CN", "zh"), ("zh", "zh"), ("cn", "zh"), ("en", "en"), ("EN", "en"), ("", "auto")],
)
def test_language_code_maps_onto_the_provider_spelling(name: str, expected: str) -> None:
    # 空值走默认；大小写不敏感
    assert base.language_code(baidu.LANGUAGE_CODES, name) == expected


def test_language_code_passes_unknown_codes_through() -> None:
    # 认不出来就原样交给后端（用户可能写了provider 自己的码）
    assert base.language_code(baidu.LANGUAGE_CODES, "ko-KR") == "ko-KR"


def test_each_engine_spells_chinese_its_own_way() -> None:
    # 同一个 zh-CN 在三家眼里是三种写法
    assert translate.make_engine("baidu").language("zh-CN") == "zh"
    assert translate.make_engine("youdao").language("zh-CN") == "zh-CHS"
    assert translate.make_engine("tencent").language("zh-CN") == "zh"
    assert translate.make_engine("local").language("zh-CN") == "zh"


# ---------------------------------------------------------------------- local
def test_local_needs_no_credentials_but_does_need_the_package() -> None:
    engine = translate.make_engine("local")
    # 不需要密钥，所以 missing_credentials 恒为空
    assert engine.missing_credentials({}) == []
    # 但包没装就不算可用
    assert engine.available() is False


def test_local_lists_no_languages_without_the_package() -> None:
    # 没装包时"装了哪些语言包"就是空表（绝不抛异常）
    assert local.installed_languages() == []


def test_local_translate_without_the_package_raises_a_hint() -> None:
    with pytest.raises(translate.TranslateError) as excinfo:
        translate.make_engine("local").translate("hi")
    assert "wreader[local]" in str(excinfo.value)


# ---------------------------------------------------------------------- baidu
def test_baidu_sign_matches_the_official_example() -> None:
    """百度官方文档的签名示例（appid=2015063000000001, q=apple, salt=1435660288）。

    这是外部可对照的向量：签名算法一改就会立刻红。
    """
    engine = baidu.BaiduTranslator(
        {"baidu_appid": "2015063000000001", "baidu_secret": "12345678"}
    )
    assert (
        engine.sign("apple", "1435660288") == "f89f9594663708c1605f3d736d01d2d4"
    )


def test_baidu_params_carry_the_signature() -> None:
    engine = baidu.BaiduTranslator({"baidu_appid": "app", "baidu_secret": "sec"})
    params = engine.params("hi", "auto", "zh-CN", salt="1")
    # q 原样参与签名（不能 strip，否则服务端一定报 Invalid Sign）
    assert params["q"] == "hi"
    assert params["appid"] == "app"
    assert params["from"] == "auto"
    assert params["to"] == "zh"
    assert params["sign"] == engine.sign("hi", "1")


def test_baidu_parse_joins_multiple_lines() -> None:
    engine = baidu.BaiduTranslator({})
    # 多行请求会有多条 trans_result，用换行拼回去
    assert (
        engine.parse({"trans_result": [{"dst": "a"}, {"dst": "b"}]}) == "a\nb"
    )


def test_baidu_parse_reports_error_codes() -> None:
    engine = baidu.BaiduTranslator({})
    with pytest.raises(translate.TranslateError) as excinfo:
        engine.parse({"error_code": "54001", "error_msg": "Invalid Sign"})
    assert "54001" in str(excinfo.value)
    # 没有译文也算失败，不能把空串当结果悄悄用掉
    with pytest.raises(translate.TranslateError):
        engine.parse({"trans_result": []})


def test_baidu_translate_goes_through_the_http_seam(monkeypatch) -> None:
    captured: Dict[str, Any] = {}

    def fake_get(url: str, params: Dict[str, Any], timeout: int) -> Any:
        # 记下引擎实际发了什么
        captured["url"] = url
        captured["params"] = params
        return {"trans_result": [{"src": "hi", "dst": "你好"}]}

    monkeypatch.setattr(baidu, "_http_get", fake_get)
    engine = baidu.BaiduTranslator({"baidu_appid": "a", "baidu_secret": "s"})
    assert engine.translate("hi", "auto", "zh-CN") == "你好"
    assert captured["url"] == baidu.ENDPOINT
    assert captured["params"]["appid"] == "a"
    # 真的发了请求才计数
    assert engine.requests == 1


def test_baidu_short_circuits_blank_text(monkeypatch) -> None:
    called: List[Any] = []
    monkeypatch.setattr(baidu, "_http_get", lambda *a, **k: called.append(a) or {})
    engine = baidu.BaiduTranslator({"baidu_appid": "a", "baidu_secret": "s"})
    assert engine.translate("   ") == ""
    assert called == []


def test_baidu_without_credentials_never_sends_a_request(monkeypatch) -> None:
    called: List[Any] = []
    monkeypatch.setattr(baidu, "_http_get", lambda *a, **k: called.append(a) or {})
    engine = baidu.BaiduTranslator({})
    with pytest.raises(translate.TranslateError) as excinfo:
        engine.translate("hi")
    # 提示要可操作
    assert "werd config translate" in str(excinfo.value)
    assert called == []


def test_a_dead_connection_is_reported_as_unavailable(monkeypatch) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise OSError("network down")

    monkeypatch.setattr(baidu, "_http_get", boom)
    engine = baidu.BaiduTranslator({"baidu_appid": "a", "baidu_secret": "s"})
    # 连不上 = unavailable：整本书的翻译会因此中止，而不是一章章重试
    with pytest.raises(translate.TranslateUnavailable) as excinfo:
        engine.translate("hi")
    assert "network down" in str(excinfo.value)


# --------------------------------------------------------------------- youdao
def test_youdao_truncate_rule() -> None:
    # 不超过 20 个字符：原样
    assert youdao.truncate("short") == "short"
    assert youdao.truncate("x" * 20) == "x" * 20
    # 超过：前 10 + 长度 + 后 10
    assert youdao.truncate("x" * 25) == "x" * 10 + "25" + "x" * 10


def test_youdao_params_use_v3_signing() -> None:
    engine = youdao.YoudaoTranslator({"youdao_appid": "app", "youdao_secret": "sec"})
    params = engine.params("hi", "auto", "zh-CN", salt="1", curtime="2")
    assert params["appKey"] == "app"
    assert params["signType"] == "v3"
    assert params["to"] == "zh-CHS"
    assert params["sign"] == engine.sign("hi", "1", "2")


def test_youdao_parse_reports_error_codes() -> None:
    engine = youdao.YoudaoTranslator({})
    assert engine.parse({"errorCode": "0", "translation": ["你好"]}) == "你好"
    with pytest.raises(translate.TranslateError) as excinfo:
        engine.parse({"errorCode": "108"})
    assert "108" in str(excinfo.value)


def test_youdao_translate_uses_the_http_seam(monkeypatch) -> None:
    monkeypatch.setattr(
        youdao,
        "_http_get",
        lambda url, params, timeout: {"errorCode": "0", "translation": ["你好"]},
    )
    engine = youdao.YoudaoTranslator({"youdao_appid": "a", "youdao_secret": "s"})
    assert engine.translate("hi", "auto", "zh-CN") == "你好"


# -------------------------------------------------------------------- tencent
# 腾讯云官方"签名方法 v3"文档里的示例请求体与它的哈希（外部可对照的向量）
TENCENT_DOC_PAYLOAD = (
    '{"Limit": 1, "Filters": [{"Values": ["\\u672a\\u547d\\u540d"], "Name": "instance-name"}]}'
)
TENCENT_DOC_HASH = "35e9c5b0e3ae67532d3c9f17ead6c90222632e5b1ff7f6e89887f1398934f064"


def test_tencent_hash_matches_the_official_example() -> None:
    # 官方把"请求体 -> sha256"这一步的结果印在文档里，正好用来验哈希实现
    assert tencent._hash_sha256(TENCENT_DOC_PAYLOAD) == TENCENT_DOC_HASH


def test_tencent_canonical_request_shape() -> None:
    engine = tencent.TencentTranslator(
        {"tencent_secret_id": "AKID", "tencent_secret_key": "SK"}
    )
    body = engine.body(engine.payload("你好", "zh-CN", "en"))
    # 六段用换行连接；规范头本身以小写头名+"\n"逐行拼接、最后也留一个换行，
    # 所以规范头与"参与签名的头名"之间会有一个空行 —— 这正是官方文档的格式。
    expected = "\n".join(
        [
            "POST",
            "/",
            "",
            "content-type:application/json; charset=utf-8\n"
            "host:tmt.tencentcloudapi.com\n"
            "x-tc-action:texttranslate\n",
            "content-type;host;x-tc-action",
            tencent._hash_sha256(body),
        ]
    )
    assert engine.canonical_request(body) == expected


def test_tencent_body_is_compact_and_unscaped() -> None:
    engine = tencent.TencentTranslator({})
    body = engine.body(engine.payload("你好", "zh-CN", "en"))
    # 紧凑分隔符 + 中文原样：哈希与发送必须是同一串
    assert body == '{"SourceText":"你好","Source":"zh","Target":"en","ProjectId":0}'


def test_tencent_string_to_sign_uses_the_utc_date_scope() -> None:
    engine = tencent.TencentTranslator(
        {"tencent_secret_id": "AKID", "tencent_secret_key": "SK"}
    )
    body = engine.body(engine.payload("hi", "auto", "en"))
    parts = engine.string_to_sign(body, 1551113065).split("\n")
    assert parts[0] == "TC3-HMAC-SHA256"
    assert parts[1] == "1551113065"
    # 1551113065 对应的 UTC 日期
    assert parts[2] == "2019-02-25/tmt/tc3_request"
    assert parts[3] == tencent._hash_sha256(engine.canonical_request(body))


def test_tencent_authorization_header_shape() -> None:
    engine = tencent.TencentTranslator(
        {
            "tencent_secret_id": "AKID",
            "tencent_secret_key": "SK",
            "tencent_region": "ap-shanghai",
        }
    )
    body = engine.body(engine.payload("hi", "auto", "en"))
    headers = engine.headers(body, 1551113065)
    assert headers["Authorization"].startswith(
        "TC3-HMAC-SHA256 Credential=AKID/2019-02-25/tmt/tc3_request, "
        "SignedHeaders=content-type;host;x-tc-action, Signature="
    )
    assert headers["X-TC-Action"] == "TextTranslate"
    assert headers["X-TC-Version"] == tencent.VERSION
    assert headers["X-TC-Timestamp"] == "1551113065"
    # 地域来自凭证表
    assert headers["X-TC-Region"] == "ap-shanghai"


def test_tencent_signature_changes_with_the_body() -> None:
    engine = tencent.TencentTranslator(
        {"tencent_secret_id": "AKID", "tencent_secret_key": "SK"}
    )
    first = engine.body(engine.payload("hi", "auto", "en"))
    second = engine.body(engine.payload("bye", "auto", "en"))
    assert engine.authorization(first, 1551113065) != engine.authorization(
        second, 1551113065
    )


def test_tencent_parse_reports_errors() -> None:
    engine = tencent.TencentTranslator({})
    assert engine.parse({"Response": {"TargetText": "hello"}}) == "hello"
    with pytest.raises(translate.TranslateError) as excinfo:
        engine.parse({"Response": {"Error": {"Code": "AuthFailure", "Message": "bad"}}})
    assert "AuthFailure" in str(excinfo.value)


def test_tencent_translate_uses_the_http_seam(monkeypatch) -> None:
    seen: Dict[str, Any] = {}

    def fake_post(url: str, body: str, headers: Dict[str, str], timeout: int) -> Any:
        # 记下发出去的请求体
        seen["body"] = body
        return {"Response": {"TargetText": "你好"}}

    monkeypatch.setattr(tencent, "_http_post", fake_post)
    engine = tencent.TencentTranslator(
        {"tencent_secret_id": "AKID", "tencent_secret_key": "SK"}
    )
    assert engine.translate("hi", "auto", "zh-CN") == "你好"
    # 发出去的正是被签名的那一串
    assert seen["body"] == engine.body(engine.payload("hi", "auto", "zh-CN"))


# ------------------------------------------------------------------- deepseek
def test_deepseek_system_prompt_switches_by_target() -> None:
    assert deepseek.system_prompt("en") == deepseek.DEEPSEEK_SYSTEM_PROMPT
    assert "zh-CN" in deepseek.system_prompt("zh-CN")


@pytest.mark.parametrize(
    "line, expected",
    [
        ('data: {"choices":[{"delta":{"content":"hi"}}]}', "hi"),
        ('data: {"choices":[{"text":"old style"}]}', "old style"),
        ("data: [DONE]", None),
        ("", ""),
        ("data: not json", ""),
    ],
)
def test_deepseek_parse_sse(line: str, expected: Any) -> None:
    assert deepseek.parse_sse(line) == expected


def test_deepseek_joins_the_stream(monkeypatch) -> None:
    class FakeResponse:
        def iter_lines(self, decode_unicode: bool = False) -> List[str]:
            # 两帧内容 + 一个结束帧
            return [
                'data: {"choices":[{"delta":{"content":"Hel"}}]}',
                'data: {"choices":[{"delta":{"content":"lo"}}]}',
                "data: [DONE]",
            ]

    monkeypatch.setattr(deepseek, "_http_post", lambda *a, **k: FakeResponse())
    engine = deepseek.DeepSeekTranslator({"deepseek_api_key": "k"})
    assert engine.translate("你好", "auto", "en") == "Hello"
    assert engine.requests == 1


def test_deepseek_is_unavailable_without_a_key() -> None:
    # conftest 清掉了 DEEPSEEK_API_KEY，这里拿不到 key
    engine = deepseek.DeepSeekTranslator({})
    assert engine.available() is False


# --------------------------------------------------------------------- google
def test_google_needs_no_credentials() -> None:
    engine = translate.make_engine("google")
    # 免费引擎：没有任何必填凭证
    assert engine.missing_credentials({}) == []
    assert engine.available() is True


def test_google_pause_can_be_switched_off(monkeypatch) -> None:
    slept: List[float] = []
    # 把 time.sleep 换成记录器，避免真的等待
    monkeypatch.setattr(google.time, "sleep", slept.append)
    # 等待时间设 0 时完全不等
    assert translate.make_engine("google", sleep_seconds=0).pause() is None
    assert slept == []
    # 非 0 时会真的等那么久
    translate.make_engine("google", sleep_seconds=2.5).pause()
    assert slept == [2.5]

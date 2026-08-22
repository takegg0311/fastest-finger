"""xAI Grok プロバイダのテスト。

実際の API は叩かない。AsyncOpenAI を差し替え、どこへ何を送ろうと
したかだけを検証する。

complete() は非同期だが、リポジトリに非同期テストの仕組みが無いため
asyncio.run() で回す。この Issue のためだけに pytest-asyncio を
足すほどの本数ではない。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm import openai_provider
from app.llm.base import ProviderError
from app.llm.openai_provider import OpenAIProvider
from app.llm.router import router
from app.llm.xai_provider import BASE_URL, XaiProvider, _reclassify


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_キーがあれば_xai_が_available_になりモデルが並ぶ(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "dummy")

    xai = _find(client, "xai")

    assert xai["available"] is True
    assert xai["label"] == "xAI Grok"
    assert xai["models"] == list(XaiProvider.models)


def test_キーが無ければ理由付きで_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "")

    xai = _find(client, "xai")

    assert xai["available"] is False
    assert "XAI_API_KEY" in xai["reason"]


def test_キー未設定なら_complete_は_auth_エラー(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "")

    with pytest.raises(ProviderError) as raised:
        asyncio.run(XaiProvider().complete("問題文", "grok-4.6"))

    assert raised.value.kind == "auth"
    assert "XAI_API_KEY" in raised.value.message


def test_xai_は_xai_の_base_url_へ繋ぐ(monkeypatch: pytest.MonkeyPatch) -> None:
    """xAI のキーを OpenAI へ送らないことの確認。宛先が最も壊れて困る箇所。"""
    monkeypatch.setenv("XAI_API_KEY", "xai-dummy")
    captured = _capture_client(monkeypatch)

    asyncio.run(XaiProvider().complete("問題文", "grok-4.6"))

    assert captured["base_url"] == BASE_URL
    assert captured["base_url"] == "https://api.x.ai/v1"
    assert captured["api_key"] == "xai-dummy"


def test_openai_は_base_url_を差し替えない(monkeypatch: pytest.MonkeyPatch) -> None:
    """xAI 対応で OpenAI 側の宛先が動いていないことの確認。"""
    monkeypatch.setenv("OPENAI_API_KEY", "openai-dummy")
    captured = _capture_client(monkeypatch)

    asyncio.run(OpenAIProvider().complete("問題文", "gpt-5"))

    # None は SDK の既定（OpenAI 本家）を意味する
    assert captured["base_url"] is None
    assert captured["api_key"] == "openai-dummy"


def test_モデル名はそのまま渡る(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XAI_API_KEY", "xai-dummy")
    captured = _capture_client(monkeypatch)

    asyncio.run(XaiProvider().complete("問題文", "grok-4.3"))

    assert captured["model"] == "grok-4.3"
    assert captured["messages"] == [{"role": "user", "content": "問題文"}]
    # 応答フォーマット違反を観測するため、JSON 強制は掛けない
    assert "response_format" not in captured["kwargs"]


@pytest.mark.parametrize(
    ("exception_name", "kind"),
    [
        ("AuthenticationError", "auth"),
        ("PermissionDeniedError", "auth"),
        ("RateLimitError", "rate_limit"),
        ("APITimeoutError", "timeout"),
        ("APIConnectionError", "network"),
        ("BadRequestError", "bad_request"),
        ("NotFoundError", "bad_request"),
        ("UnprocessableEntityError", "bad_request"),
    ],
)
def test_例外型は正しい_errorkind_へ写る(exception_name: str, kind: str) -> None:
    # SDK の例外は型名で判定されるため、名前だけ揃えた型で足りる
    error = type(exception_name, (Exception,), {})("失敗")

    assert openai_provider._normalize(error).kind == kind


def test_知らない例外は_unknown_になる() -> None:
    assert openai_provider._normalize(ValueError("何か")).kind == "unknown"


def test_エラー文言に_openai_という社名が混ざらない() -> None:
    """xAI の失敗として画面に出るため、OpenAI 固有の文言は入れられない。"""
    for name in ("AuthenticationError", "RateLimitError", "APITimeoutError", "APIConnectionError"):
        error = type(name, (Exception,), {})("失敗")
        assert "OpenAI" not in openai_provider._normalize(error).message


def test_predict_が_xai_で成功する(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake(self: XaiProvider, prompt: str, model: str) -> str:
        return json.dumps(
            {"continuation": "問題文？", "answer": "エベレスト"}, ensure_ascii=False
        )

    monkeypatch.setattr(XaiProvider, "complete", fake)

    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "xai",
            "model": "grok-4.6",
            "partial_text": "日本で一番高い山は富士山です",
            "complete": False,
        },
    ).json()

    assert body["ok"] is True
    assert body["answer"] == "エベレスト"
    assert body["continuation"] == "問題文？"


def test_xai_に無いモデルは_bad_request(client: TestClient) -> None:
    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "xai",
            "model": "gpt-5",
            "partial_text": "問題文",
            "complete": False,
        },
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "bad_request"


def _find(client: TestClient, vendor: str) -> dict:
    providers = client.get("/api/llm/health").json()["providers"]
    return next(p for p in providers if p["vendor"] == vendor)


def _capture_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """AsyncOpenAI を差し替え、生成時と送信時の引数を控える。

    complete() は import 済みの openai モジュールから AsyncOpenAI を
    引くため、モジュール属性ごと差し替える。
    """
    captured: dict[str, Any] = {}

    class FakeCompletions:
        async def create(self, model: str, messages: list, **kwargs: Any) -> Any:
            captured["model"] = model
            captured["messages"] = messages
            captured["kwargs"] = kwargs
            return _response("{}")

    class FakeChat:
        completions = FakeCompletions()

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.chat = FakeChat()

    import openai

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeAsyncOpenAI)
    return captured


def _response(content: str) -> Any:
    """SDK の応答のうち、complete() が触る部分だけを模す。"""

    class Message:
        def __init__(self) -> None:
            self.content = content

    class Choice:
        def __init__(self) -> None:
            self.message = Message()

    class Response:
        def __init__(self) -> None:
            self.choices = [Choice()]

    return Response()


def test_キー不正の_400_は_auth_に分類される() -> None:
    """xAI はキーが不正でも 401 ではなく 400 を返す。

    OpenAI 用の分類をそのまま通すと bad_request になり、画面から
    「キーが違う」と分からない。実際の応答の文言をそのまま写して検証する。
    """
    original = ProviderError(
        "bad_request",
        "リクエストが受け付けられませんでした: Error code: 400 - "
        "{'code': 'invalid-argument', 'error': 'Incorrect API key provided.'}",
    )

    reclassified = _reclassify(original)

    assert reclassified.kind == "auth"
    # 前置きが二重にならないこと
    assert "リクエストが受け付けられませんでした" not in reclassified.message


def test_キー不正でない_400_は_bad_request_のまま() -> None:
    """400 を一律 auth に寄せない。"""
    original = ProviderError(
        "bad_request", "リクエストが受け付けられませんでした: unknown model"
    )

    assert _reclassify(original).kind == "bad_request"


def test_bad_request_以外は_触らない() -> None:
    """レート制限などの分類を巻き込まないこと。"""
    original = ProviderError("rate_limit", "レート制限に達しました")

    assert _reclassify(original) is original

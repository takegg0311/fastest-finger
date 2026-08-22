"""Anthropic Claude プロバイダのテスト。

実際の API は叩かず、complete を差し替えるか、SDK に依存しない
整形部分だけを直接呼んで検証する。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.anthropic_provider import AnthropicProvider, _extract_text, _normalize
from app.llm.base import ProviderError
from app.llm.router import router


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


class _Block:
    """content block のスタブ。SDK を介さず整形だけを試すために使う。"""

    def __init__(self, type: str, text: str = "") -> None:
        self.type = type
        self.text = text


def test_キーがあれば_available_になりモデルが並ぶ(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")

    anthropic = _find(client, "anthropic")

    assert anthropic["available"] is True
    assert anthropic["models"] == list(AnthropicProvider.models)


def test_health_で_openai_の次に並ぶ(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy")

    providers = client.get("/api/llm/health").json()["providers"]

    # health の並び順はそのまま画面の表示順になる
    assert [p["vendor"] for p in providers] == ["openai", "anthropic", "google", "xai"]


def test_キーが無ければ理由付きで_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    anthropic = _find(client, "anthropic")

    assert anthropic["available"] is False
    assert "ANTHROPIC_API_KEY" in anthropic["reason"]


@pytest.mark.anyio
async def test_キー未設定なら_api_を叩かず_auth_エラーになる(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    with pytest.raises(ProviderError) as raised:
        await AnthropicProvider().complete("問題文", "claude-opus-5")

    assert raised.value.kind == "auth"
    assert "ANTHROPIC_API_KEY" in raised.value.message


@pytest.mark.parametrize(
    ("type_name", "expected"),
    [
        ("AuthenticationError", "auth"),
        ("PermissionDeniedError", "auth"),
        ("RateLimitError", "rate_limit"),
        ("APITimeoutError", "timeout"),
        ("APIConnectionError", "network"),
        ("BadRequestError", "bad_request"),
        ("NotFoundError", "bad_request"),
        ("SomethingUnexpectedError", "unknown"),
    ],
)
def test_sdk_の例外は種別ごとに正規化される(type_name: str, expected: str) -> None:
    # 例外は型名だけで判定されるため、名前を合わせたダミーで足りる
    error = type(type_name, (Exception,), {})("失敗しました")

    assert _normalize(error).kind == expected


def test_text_ブロックだけが連結される() -> None:
    blocks = [
        _Block("thinking", "ここは思考なので本文ではない"),
        _Block("text", '{"answer":'),
        _Block("text", ' "エベレスト"}'),
    ]

    assert _extract_text(blocks) == '{"answer": "エベレスト"}'


def test_content_が空なら_unknown_エラーになる() -> None:
    with pytest.raises(ProviderError) as raised:
        _extract_text([])

    assert raised.value.kind == "unknown"


def test_text_ブロックが無ければ空文字になる() -> None:
    # 思考だけで本文が無い場合。違反として観測させたいので、
    # ここでは例外にせず空文字を返しパーサへ委ねる
    assert _extract_text([_Block("thinking", "思考のみ")]) == ""


def test_予測が成功すると応答時間付きで返る(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub(
        monkeypatch,
        json.dumps({"continuation": "問題文？", "answer": "エベレスト"}, ensure_ascii=False),
    )

    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "anthropic",
            "model": "claude-opus-5",
            "partial_text": "日本で一番高い山は富士山です",
            "complete": False,
        },
    ).json()

    assert body["ok"] is True
    assert body["answer"] == "エベレスト"
    assert body["continuation"] == "問題文？"
    assert isinstance(body["elapsed_ms"], int)
    assert "raw" in body


def test_知らないモデルは_bad_request(client: TestClient) -> None:
    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "anthropic",
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


def _stub(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    """プロバイダの応答を固定する。実際の API は叩かない。"""

    async def fake(self: AnthropicProvider, prompt: str, model: str) -> str:
        return raw

    monkeypatch.setattr(AnthropicProvider, "complete", fake)

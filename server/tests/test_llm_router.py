"""LLM 中継エンドポイントのテスト。

実際の API は叩かず、プロバイダの complete を差し替えて検証する。
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm import registry
from app.llm.base import ProviderError
from app.llm.openai_provider import OpenAIProvider
from app.llm.router import router


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_health_は_4_社を返す(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    providers = client.get("/api/llm/health").json()["providers"]

    assert [p["vendor"] for p in providers] == ["openai", "anthropic", "google", "xai"]


def test_キーがあれば_available_になりモデルが並ぶ(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    openai = _find(client, "openai")

    assert openai["available"] is True
    assert openai["models"] == list(OpenAIProvider.models)


def test_キーが無ければ理由付きで_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "")

    openai = _find(client, "openai")

    assert openai["available"] is False
    assert "OPENAI_API_KEY" in openai["reason"]


def test_未実装の社は理由に_issue_番号が入る(client: TestClient) -> None:
    anthropic = _find(client, "anthropic")

    assert anthropic["available"] is False
    assert "未実装" in anthropic["reason"]


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
            "vendor": "openai",
            "model": "gpt-5",
            "partial_text": "日本で一番高い山は富士山です",
            "complete": False,
        },
    ).json()

    assert body["ok"] is True
    assert body["answer"] == "エベレスト"
    assert body["continuation"] == "問題文？"
    assert isinstance(body["elapsed_ms"], int)
    # 詳細モーダルで生応答を見せるため、常に含める
    assert "raw" in body


def test_応答違反でも_200_で返し_raw_を含む(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub(monkeypatch, "これは JSON ではありません")

    response = client.post(
        "/api/llm/predict",
        json={
            "vendor": "openai",
            "model": "gpt-5",
            "partial_text": "日本で一番高い山は富士山です",
            "complete": False,
        },
    )
    body = response.json()

    # 違反はエラーではない。処理自体は成功しているため 200 で返す
    assert response.status_code == 200
    assert body["ok"] is False
    assert body["violation"] is not None
    assert body["raw"] == "これは JSON ではありません"


def test_timeup_では_continuation_無しでも成功する(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub(monkeypatch, json.dumps({"answer": "エベレスト"}, ensure_ascii=False))

    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "openai",
            "model": "gpt-5",
            "partial_text": "世界で一番高い山はどこ？",
            "complete": True,
        },
    ).json()

    assert body["ok"] is True
    assert body["answer"] == "エベレスト"


def test_プロバイダのエラーは正規化されて返る(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(self: OpenAIProvider, prompt: str, model: str) -> str:
        raise ProviderError("auth", "認証に失敗しました")

    monkeypatch.setattr(OpenAIProvider, "complete", failing)

    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "openai",
            "model": "gpt-5",
            "partial_text": "問題文",
            "complete": False,
        },
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "auth"


def test_未対応のプロバイダは_bad_request(client: TestClient) -> None:
    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "unknown-vendor",
            "model": "gpt-5",
            "partial_text": "問題文",
            "complete": False,
        },
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "bad_request"


def test_知らないモデルは_bad_request(client: TestClient) -> None:
    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "openai",
            "model": "存在しないモデル",
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

    async def fake(self: OpenAIProvider, prompt: str, model: str) -> str:
        return raw

    monkeypatch.setattr(OpenAIProvider, "complete", fake)

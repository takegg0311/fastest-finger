"""Gemini プロバイダのテスト。

実際の API は叩かず、SDK の例外を模したダミーで正規化だけを検証する。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.base import ProviderError
from app.llm.gemini_provider import GeminiProvider, _normalize
from app.llm.router import router


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as test_client:
        yield test_client


def test_キーがあれば_google_が_available_になりモデルが並ぶ(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")

    google = _find(client, "google")

    assert google["available"] is True
    assert google["models"] == list(GeminiProvider.models)


def test_キーが無ければ理由付きで_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")

    google = _find(client, "google")

    assert google["available"] is False
    assert "GEMINI_API_KEY" in google["reason"]


def test_キー未設定なら_complete_は_auth_で失敗する(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")

    # complete は async だが、キー未設定は SDK を触る前に弾かれる。
    # 非同期テストの仕組みを増やさずに済ませるため asyncio.run で回す。
    with pytest.raises(ProviderError) as raised:
        asyncio.run(GeminiProvider().complete("問題文", "gemini-2.5-pro"))

    assert raised.value.kind == "auth"


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, "auth"),
        (403, "auth"),
        (429, "rate_limit"),
        (400, "bad_request"),
        (404, "bad_request"),
        (500, "unknown"),
    ],
)
def test_api_エラーは_http_ステータスで分類される(code: int, expected: str) -> None:
    assert _normalize(_ApiError(code)).kind == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("TimeoutException", "timeout"),
        ("ReadTimeout", "timeout"),
        ("ConnectTimeout", "timeout"),
        ("ConnectError", "network"),
    ],
)
def test_httpx_の例外は型名で分類される(name: str, expected: str) -> None:
    error = type(name, (Exception,), {})("転送に失敗しました")

    assert _normalize(error).kind == expected


def test_分類できない例外は_unknown() -> None:
    assert _normalize(RuntimeError("何かが壊れた")).kind == "unknown"


def test_google_vendor_で予測が成功する(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = json.dumps({"continuation": "問題文？", "answer": "エベレスト"}, ensure_ascii=False)

    async def fake(self: GeminiProvider, prompt: str, model: str) -> str:
        return raw

    monkeypatch.setattr(GeminiProvider, "complete", fake)

    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "google",
            "model": "gemini-2.5-pro",
            "partial_text": "日本で一番高い山は富士山です",
            "complete": False,
        },
    ).json()

    assert body["ok"] is True
    assert body["answer"] == "エベレスト"
    assert body["continuation"] == "問題文？"
    assert body["raw"] == raw


def test_知らないモデルは_bad_request(client: TestClient) -> None:
    body = client.post(
        "/api/llm/predict",
        json={
            "vendor": "google",
            "model": "gemini-1.0-pro",
            "partial_text": "問題文",
            "complete": False,
        },
    ).json()

    assert body["ok"] is False
    assert body["error_kind"] == "bad_request"


class _ApiError(Exception):
    """google.genai.errors.APIError の代役。

    分類に使うのは code だけなので、SDK の APIError を組み立てずに済ませる
    （コンストラクタが response_json を要求し、テストの意図がぼやけるため）。
    """

    def __init__(self, code: int) -> None:
        super().__init__(f"{code} エラー")
        self.code = code


def _find(client: TestClient, vendor: str) -> dict:
    providers = client.get("/api/llm/health").json()["providers"]
    return next(p for p in providers if p["vendor"] == vendor)


def test_キー不正の_400_は_auth_に分類される() -> None:
    """Gemini はキーが不正でも 401 ではなく 400 を返す。

    ステータスだけで見ると bad_request になり、画面から「キーが違う」と
    分からなくなる。実際の応答から details の形をそのまま写して検証する。
    """

    class ClientError(Exception):
        code = 400
        details = {
            "error": {
                "code": 400,
                "message": "API key not valid. Please pass a valid API key.",
                "status": "INVALID_ARGUMENT",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                        "reason": "API_KEY_INVALID",
                        "domain": "googleapis.com",
                    }
                ],
            }
        }

    assert _normalize(ClientError("400 INVALID_ARGUMENT")).kind == "auth"


def test_キー不正でない_400_は_bad_request_のまま() -> None:
    """reason が無い 400 まで auth に寄せない。"""

    class ClientError(Exception):
        code = 400
        details = {"error": {"code": 400, "message": "bad model", "details": []}}

    assert _normalize(ClientError("400 INVALID_ARGUMENT")).kind == "bad_request"


def test_details_が無くても_400_は_bad_request_として扱える() -> None:
    """SDK が details を載せない場合でも落ちないこと。"""

    class ClientError(Exception):
        code = 400

    assert _normalize(ClientError("400")).kind == "bad_request"

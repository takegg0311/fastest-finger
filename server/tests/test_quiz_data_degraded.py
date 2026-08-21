"""questions.csv を読めない場合の縮退動作のテスト。

サーバは起動を続けるが、オンライン版の入口だけを閉じる。
LLM 中継は出題データに依存しないため使える。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.llm.router import router as llm_router
from app.ws import ConnectionManager, router as ws_router


def build_app(*, quiz_error: str | None) -> FastAPI:
    """main.py と同じ組み立てを、CSV の読み込み結果だけ差し替えて再現する。

    main.py 自体は import 時に実データを読むため、テストからは
    条件を作れない。構造（room が None なら閉じる）を写して検証する。
    """
    app = FastAPI()
    app.state.questions = []
    app.state.quiz_error = quiz_error
    app.state.host_token = "test-token"
    app.state.room = None if quiz_error is not None else object()
    app.state.connections = ConnectionManager()

    def require_quiz_data() -> None:
        if app.state.quiz_error is not None:
            raise HTTPException(status_code=503, detail="出題データを読み込めていません")

    @app.get("/player")
    async def player_page() -> dict[str, str]:
        require_quiz_data()
        return {"ok": "yes"}

    app.include_router(llm_router)
    app.include_router(ws_router)
    return app


@pytest.fixture
def degraded() -> Iterator[TestClient]:
    with TestClient(build_app(quiz_error="questions.csv が空です。")) as client:
        yield client


def test_csv_が壊れていても_llm_health_は応答する(degraded: TestClient) -> None:
    response = degraded.get("/api/llm/health")

    assert response.status_code == 200
    assert "providers" in response.json()


def test_csv_が壊れていると_player_は_503(degraded: TestClient) -> None:
    assert degraded.get("/player").status_code == 503


def test_csv_が壊れていると_ws_接続は閉じられる(degraded: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with degraded.websocket_connect("/ws") as websocket:
            websocket.receive_text()


def test_csv_が正常なら_player_は通る() -> None:
    with TestClient(build_app(quiz_error=None)) as client:
        assert client.get("/player").status_code == 200

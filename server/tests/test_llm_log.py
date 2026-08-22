"""予測結果の CSV 記録のテスト。"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.llm.log import CSV_COLUMNS, LogRecord, append_records, log_path
from app.llm.router import router


def make_record(
    *,
    vendor: str = "openai",
    model: str = "gpt-5",
    answer: str = "エベレスト",
    continuation: str | None = None,
    elapsed_ms: int = 1234,
    ok: bool = True,
    error_kind: str | None = None,
    correct: bool = True,
    manual: bool = False,
) -> LogRecord:
    return LogRecord(
        vendor=vendor,
        model=model,
        answer=answer,
        continuation=continuation,
        elapsed_ms=elapsed_ms,
        ok=ok,
        error_kind=error_kind,
        correct=correct,
        manual=manual,
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_ヘッダごと新規作成される(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "predictions.csv"

    written = append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[make_record()],
        path=target,
    )

    assert written == 1
    assert target.exists()

    with target.open(encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream))
    assert tuple(header) == CSV_COLUMNS


def test_1_送信_1_llm_で_1_レコードになる(tmp_path: Path) -> None:
    target = tmp_path / "predictions.csv"

    written = append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[
            make_record(vendor="openai", model="gpt-5"),
            make_record(vendor="anthropic", model="claude-opus-5"),
            make_record(vendor="google", model="gemini-2.5-flash"),
        ],
        path=target,
    )

    assert written == 3
    rows = read_csv(target)
    assert len(rows) == 3
    assert [row["vendor"] for row in rows] == ["openai", "anthropic", "google"]


def test_同じ送信の行は同じ時刻を持つ(tmp_path: Path) -> None:
    """後から 1 回ぶんとしてまとめられるよう、時刻は送信単位で共通にする。"""
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[make_record(vendor="openai"), make_record(vendor="anthropic")],
        path=target,
    )

    rows = read_csv(target)
    assert rows[0]["timestamp"] == rows[1]["timestamp"]


def test_追記でヘッダが重複しない(tmp_path: Path) -> None:
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="1 問目",
        complete=True,
        expected_answer="A",
        records=[make_record()],
        path=target,
    )
    append_records(
        question_text="2 問目",
        complete=False,
        expected_answer="B",
        records=[make_record()],
        path=target,
    )

    rows = read_csv(target)
    assert len(rows) == 2
    assert [row["question_text"] for row in rows] == ["1 問目", "2 問目"]


def test_手動正解が記録される(tmp_path: Path) -> None:
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[
            make_record(vendor="openai", answer="エベレスト", correct=True, manual=False),
            make_record(vendor="anthropic", answer="エベレスト山", correct=True, manual=True),
        ],
        path=target,
    )

    rows = read_csv(target)
    assert rows[0]["manual"] == "false"
    assert rows[0]["correct"] == "true"
    # 表記揺れを手動で拾った場合、correct は true だが manual も true になる
    assert rows[1]["manual"] == "true"
    assert rows[1]["correct"] == "true"


def test_補完文が無ければ空欄になる(tmp_path: Path) -> None:
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[make_record(continuation=None)],
        path=target,
    )

    assert read_csv(target)[0]["continuation"] == ""


def test_補完文が記録される(tmp_path: Path) -> None:
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="日本で一番高い山は富士山ですが、",
        complete=False,
        expected_answer="エベレスト",
        records=[
            make_record(continuation="日本で一番高い山は富士山ですが、世界で一番高い山は何でしょう？")
        ],
        path=target,
    )

    row = read_csv(target)[0]
    assert row["complete"] == "false"
    assert row["continuation"].endswith("何でしょう？")


def test_失敗した予測も記録される(tmp_path: Path) -> None:
    """どのモデルが失敗したかを残すため、違反・エラーも行として書く。"""
    target = tmp_path / "predictions.csv"

    append_records(
        question_text="世界で一番高い山は？",
        complete=True,
        expected_answer="エベレスト",
        records=[
            make_record(answer="", ok=False, error_kind="violation", correct=False),
        ],
        path=target,
    )

    row = read_csv(target)[0]
    assert row["ok"] == "false"
    assert row["error_kind"] == "violation"
    assert row["answer"] == ""


def test_問題文の_カンマ_と改行が壊れない(tmp_path: Path) -> None:
    """CSV のクォート処理に委ねる。問題文には読点も改行も入りうる。"""
    target = tmp_path / "predictions.csv"
    text = 'A社は「X」ですが,B社は\n「Y」でしょう？'

    append_records(
        question_text=text,
        complete=True,
        expected_answer="Y",
        records=[make_record()],
        path=target,
    )

    assert read_csv(target)[0]["question_text"] == text


def test_環境変数で記録先を差し替えられる(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "custom" / "out.csv"
    monkeypatch.setenv("LLM_POC_LOG_PATH", str(target))

    assert log_path() == target


class TestLogEndpoint:
    """POST /api/llm/log。実際の記録先は環境変数で tmp_path へ逃がす。"""

    @pytest.fixture
    def client(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        monkeypatch.setenv("LLM_POC_LOG_PATH", str(tmp_path / "predictions.csv"))
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as test_client:
            yield test_client

    def test_記録できる(self, client: TestClient, tmp_path: Path) -> None:
        response = client.post(
            "/api/llm/log",
            json={
                "question_text": "世界で一番高い山は？",
                "complete": True,
                "expected_answer": "エベレスト",
                "records": [
                    {
                        "vendor": "openai",
                        "model": "gpt-5",
                        "answer": "エベレスト",
                        "continuation": None,
                        "elapsed_ms": 900,
                        "ok": True,
                        "error_kind": None,
                        "correct": True,
                        "manual": False,
                    }
                ],
            },
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True, "written": 1}
        assert read_csv(tmp_path / "predictions.csv")[0]["answer"] == "エベレスト"

    def test_問題文が空なら弾く(self, client: TestClient) -> None:
        response = client.post(
            "/api/llm/log",
            json={
                "question_text": "",
                "complete": True,
                "expected_answer": "エベレスト",
                "records": [{"vendor": "openai", "model": "gpt-5"}],
            },
        )

        assert response.status_code == 422

    def test_レコードが空なら弾く(self, client: TestClient) -> None:
        """記録する中身が無い要求は、書き込みの前に弾く。"""
        response = client.post(
            "/api/llm/log",
            json={
                "question_text": "世界で一番高い山は？",
                "complete": True,
                "expected_answer": "エベレスト",
                "records": [],
            },
        )

        assert response.status_code == 422

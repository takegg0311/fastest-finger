"""LLM 応答の解釈と、応答フォーマット違反の判定のテスト。

判定は buzz（complete=False）と timeUp（complete=True）で分かれる。
timeUp は continuation を要求しないぶん許容が広い。
"""

from __future__ import annotations

import json

import pytest

from app.llm.parser import parse_response


def test_buzz_で_continuation_と_answer_が揃えば正常() -> None:
    raw = json.dumps(
        {"continuation": "日本で一番高い山は富士山ですが、世界では？", "answer": "エベレスト"},
        ensure_ascii=False,
    )
    parsed = parse_response(raw, complete=False)

    assert parsed.violation is None
    assert parsed.answer == "エベレスト"
    assert parsed.continuation == "日本で一番高い山は富士山ですが、世界では？"


def test_buzz_で_continuation_が無ければ違反() -> None:
    parsed = parse_response('{"answer": "エベレスト"}', complete=False)

    assert parsed.violation is not None
    assert parsed.answer is None


def test_buzz_で平文は違反() -> None:
    parsed = parse_response("エベレスト", complete=False)

    assert parsed.violation is not None


def test_timeup_で_answer_だけでも正常() -> None:
    parsed = parse_response('{"answer": "エベレスト"}', complete=True)

    assert parsed.violation is None
    assert parsed.answer == "エベレスト"
    assert parsed.continuation is None


def test_timeup_で短い平文は答えとして扱う() -> None:
    parsed = parse_response("エベレスト", complete=True)

    assert parsed.violation is None
    assert parsed.answer == "エベレスト"


def test_timeup_で長い平文は違反(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PLAIN_ANSWER_MAX_LENGTH", "30")
    long_text = "この問題文から推測すると、世界一高い山を問うているので、答えはエベレストだと考えられます。"

    parsed = parse_response(long_text, complete=True)

    assert parsed.violation is not None


def test_平文を許容する閾値を環境変数で変えられる(monkeypatch: pytest.MonkeyPatch) -> None:
    # 既定の 30 文字では違反になる長さを、閾値を上げて通す
    text = "あ" * 40
    monkeypatch.setenv("LLM_PLAIN_ANSWER_MAX_LENGTH", "50")

    assert parse_response(text, complete=True).violation is None

    monkeypatch.setenv("LLM_PLAIN_ANSWER_MAX_LENGTH", "30")

    assert parse_response(text, complete=True).violation is not None


def test_コードフェンスで囲まれていても読める() -> None:
    raw = '```json\n{"continuation": "問題文？", "answer": "答え"}\n```'
    parsed = parse_response(raw, complete=False)

    assert parsed.violation is None
    assert parsed.answer == "答え"


def test_前置きが付いていても_json_を取り出せる() -> None:
    raw = 'はい、こちらです。\n{"continuation": "問題文？", "answer": "答え"}'
    parsed = parse_response(raw, complete=False)

    assert parsed.violation is None
    assert parsed.answer == "答え"


def test_json_として読めなければ違反() -> None:
    parsed = parse_response("{壊れた", complete=False)

    assert parsed.violation is not None


def test_answer_が空文字なら違反() -> None:
    parsed = parse_response('{"continuation": "問題文？", "answer": "  "}', complete=False)

    assert parsed.violation is not None


def test_timeup_で空応答は違反() -> None:
    parsed = parse_response("   ", complete=True)

    assert parsed.violation is not None

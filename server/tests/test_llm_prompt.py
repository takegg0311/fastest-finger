"""プロンプト生成のテスト。

早押しクイズの文脈が伝わることが要件。これが抜けると、途中までの問題文から
説明文が補完されてしまい、答えを出せない。
"""

from __future__ import annotations

from app.llm.prompt import build_prompt


def test_早押しクイズであることを伝えている() -> None:
    prompt = build_prompt("日本で一番高い山は富士山です", complete=False)

    assert "早押しクイズ" in prompt


def test_buzz_では途中で切れていることを伝えている() -> None:
    prompt = build_prompt("日本で一番高い山は富士山です", complete=False)

    assert "途中" in prompt
    assert "continuation" in prompt


def test_パラレル問題への注意を含む() -> None:
    """「〜ですが、」形式で前半の語が答えだと誤認するのを防ぐ指示。"""
    prompt = build_prompt("日本で一番高い山は富士山です", complete=False)

    assert "ですが" in prompt


def test_timeup_では_continuation_を求めない() -> None:
    prompt = build_prompt("世界で一番高い山はどこ？", complete=True)

    assert "continuation" not in prompt
    assert "answer" in prompt


def test_問題文が本文に含まれる() -> None:
    prompt = build_prompt("日本で一番高い山は富士山です", complete=False)

    assert "日本で一番高い山は富士山です" in prompt

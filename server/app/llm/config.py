"""LLM 中継の設定。API キーと閾値を環境変数から読む。

キーはリポジトリに入れられないため server/.env に置き、python-dotenv で読む。
.env が無くても（CI や、環境変数を直接与える運用でも）起動できるようにする。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# server/ 直下の .env を読む。既に環境変数がある場合はそちらを優先する
# （CI や docker run -e での上書きを .env が奪わないようにするため）。
SERVER_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(SERVER_ROOT / ".env", override=False)

# timeUp の応答で平文を許容する最大文字数。
# 読み切り後は続きの予測が不要なぶん応答の自由度を上げており、
# 短い平文はそのまま答えとみなす。長い応答は説明文とみなして違反とする。
DEFAULT_PLAIN_ANSWER_MAX_LENGTH = 30

# 1 リクエストの上限。人間が待てる範囲を超えたら諦める。
REQUEST_TIMEOUT_SECONDS = 60.0


def plain_answer_max_length() -> int:
    """timeUp の平文応答を許容する最大文字数。

    毎回読むのは、テストで環境変数を差し替えられるようにするため。
    不正な値は既定値へ落とす（PoC の起動を止めるほどの問題ではない）。
    """
    raw = os.getenv("LLM_PLAIN_ANSWER_MAX_LENGTH")
    if raw is None or raw.strip() == "":
        return DEFAULT_PLAIN_ANSWER_MAX_LENGTH
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_PLAIN_ANSWER_MAX_LENGTH
    return value if value > 0 else DEFAULT_PLAIN_ANSWER_MAX_LENGTH


def api_key(name: str) -> str | None:
    """API キーを読む。未設定と空文字は同じ「未設定」として扱う。"""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    return value.strip()

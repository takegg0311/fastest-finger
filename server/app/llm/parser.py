"""LLM の応答を解釈し、応答フォーマット違反を判定する。

判定は buzz 用と timeUp 用で分ける。timeUp は continuation を要求しないぶん
許容が広い。

    | 応答                          | buzz   | timeUp |
    |-------------------------------|--------|--------|
    | continuation と answer を持つ | OK     | OK     |
    | answer のみ                   | 違反   | OK     |
    | 平文（閾値以内）              | 違反   | OK     |
    | 平文（閾値超過）              | 違反   | 違反   |
    | JSON として読めない           | 違反   | 違反   |

違反は「エラー」ではない。処理は成功しており、モデルが指示に従わなかった
という観測結果として画面に出す。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import plain_answer_max_length


@dataclass
class ParsedResponse:
    """解釈済みの応答。violation が None でなければフォーマット違反。"""

    continuation: str | None
    answer: str | None
    violation: str | None


# ```json ... ``` で囲って返すモデルが多いため、フェンスを剥がす。
# 指示には書いていないが、これは体裁の問題であって「答えを JSON で返す」
# という指示自体には従えているため、違反とはしない。
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def _strip_fence(text: str) -> str:
    matched = _FENCE.match(text)
    return matched.group(1) if matched else text.strip()


def _extract_json_object(text: str) -> dict[str, object] | None:
    """応答から JSON オブジェクトを取り出す。取り出せなければ None。

    まず全体をそのまま試し、駄目なら最初の { から最後の } までを試す。
    前置きを付けてしまうモデルを救うためで、JSON 自体が無ければ諦める。
    """
    candidate = _strip_fence(text)

    for source in (candidate, _slice_braces(candidate)):
        if source is None:
            continue
        try:
            parsed = json.loads(source)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed

    return None


def _slice_braces(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _as_text(value: object) -> str | None:
    """JSON の値を文字列として取り出す。空文字は未指定として扱う。"""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None


def parse_response(raw: str, *, complete: bool) -> ParsedResponse:
    """応答を解釈する。complete が True なら timeUp 用の緩い判定を使う。"""
    obj = _extract_json_object(raw)

    if obj is not None:
        answer = _as_text(obj.get("answer"))
        continuation = _as_text(obj.get("continuation"))

        if answer is None:
            return ParsedResponse(None, None, "JSON に answer が含まれていません")

        # buzz では continuation まで揃って初めて指示どおり。
        # timeUp では continuation を要求していないため、有無を問わない。
        if not complete and continuation is None:
            return ParsedResponse(None, None, "JSON に continuation が含まれていません")

        return ParsedResponse(continuation, answer, None)

    # ここから先は JSON として読めなかった場合。
    # timeUp に限り、短い平文はそのまま答えとみなす。
    if complete:
        plain = _strip_fence(raw)
        limit = plain_answer_max_length()
        if plain != "" and len(plain) <= limit:
            return ParsedResponse(None, plain, None)
        if plain == "":
            return ParsedResponse(None, None, "応答が空でした")
        return ParsedResponse(
            None,
            None,
            f"JSON として解釈できず、平文としても長すぎます（{len(plain)} 文字 / 上限 {limit} 文字）",
        )

    return ParsedResponse(None, None, "JSON として解釈できませんでした")

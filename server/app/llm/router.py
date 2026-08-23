"""LLM 中継の HTTP エンドポイント。

PoC はフロントエンド単体でバックエンドを持たないが、API キーをバンドルに
埋め込めず、各社 API にはブラウザからの直接呼び出しに CORS 制限がある。
そのためここで中継する。

/predict は問題文の全文と正解を受け取らない。PoC 側が保持したままにし、
LLM へ渡すのは早押し時点で画面に出ていた文字列だけとする。

/log は llm-poc（LLM 予測比較 PoC）の記録用で、こちらは正解と正誤を受け取る。
predict に相乗りさせないのは、predict の時点ではまだ正解が入力されておらず
（画面の流れが「送信 → 回答を待つ → 正解を入力」のため）、正誤を残せないため。
"""

from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .base import ProviderError
from .config import REQUEST_TIMEOUT_SECONDS
from .log import LogRecord, append_records
from .parser import parse_response
from .prompt import build_prompt
from .registry import find, health_view

router = APIRouter(prefix="/api/llm", tags=["llm"])


class PredictRequest(BaseModel):
    vendor: str
    model: str
    #: 早押し時点で表示されていた問題文。文の途中で切れていてよい
    partial_text: str = Field(min_length=1)
    #: 読み切られたか。True なら timeUp 用のプロンプトを使う
    complete: bool = False


@router.get("/health")
async def health() -> dict[str, object]:
    """利用可能なプロバイダとモデルを返す。

    PoC はこれを起動時に叩き、疎通しなければ予測枠を縮退させる。
    未実装の社も available: false で並べる。
    """
    return {"providers": health_view()}


@router.post("/predict")
async def predict(request: PredictRequest) -> dict[str, object]:
    """問題文から答えを予測させる。

    HTTP のステータスは、プロバイダ側が失敗しても 200 のままとする。
    PoC は 4 枠を並べて表示しており、枠ごとの失敗は画面に出す情報であって
    リクエスト自体の失敗ではないため。区別は ok と error_kind で行う。
    """
    provider = find(request.vendor)
    if provider is None:
        return {
            "ok": False,
            "error_kind": "bad_request",
            "error": f"未対応のプロバイダです: {request.vendor}",
            "elapsed_ms": 0,
        }

    if request.model not in provider.models:
        return {
            "ok": False,
            "error_kind": "bad_request",
            "error": f"{provider.label} に {request.model} はありません",
            "elapsed_ms": 0,
        }

    prompt = build_prompt(request.partial_text, complete=request.complete)

    # 応答時間は送信から全文受信まで。JSON をパースする都合で
    # ストリーミングは使えないため、単純な実測でよい。
    started = time.perf_counter()
    try:
        raw = await provider.complete(prompt, request.model)
    except ProviderError as error:
        return {
            "ok": False,
            "error_kind": error.kind,
            "error": error.message,
            "elapsed_ms": _elapsed_ms(started),
        }
    except Exception as error:  # noqa: BLE001 - 枠ごとの失敗として画面へ返す
        return {
            "ok": False,
            "error_kind": "unknown",
            "error": str(error) or type(error).__name__,
            "elapsed_ms": _elapsed_ms(started),
        }

    elapsed_ms = _elapsed_ms(started)
    parsed = parse_response(raw, complete=request.complete)

    # 違反はエラーではない。処理は成功しており、モデルが指示に従わなかった
    # という観測結果として返す。raw は常に含め、画面の詳細モーダルで見せる。
    if parsed.violation is not None:
        return {
            "ok": False,
            "violation": parsed.violation,
            "elapsed_ms": elapsed_ms,
            "raw": raw,
        }

    return {
        "ok": True,
        "continuation": parsed.continuation,
        "answer": parsed.answer,
        "elapsed_ms": elapsed_ms,
        "raw": raw,
    }


class LogRecordRequest(BaseModel):
    """1 送信 × 1 LLM ぶんの記録。"""

    vendor: str
    model: str
    #: LLM が返した答え。違反・エラー時は空
    answer: str = ""
    #: 補完された問題文全文。読み切り時と失敗時は None
    continuation: str | None = None
    elapsed_ms: int = 0
    ok: bool = False
    #: 失敗の種別。成功時は None
    error_kind: str | None = None
    #: 最終的な正誤（手動正解を反映した後）
    correct: bool = False
    #: 手動正解ボタンで正解にしたか
    manual: bool = False


class LogRequest(BaseModel):
    question_text: str = Field(min_length=1)
    complete: bool = False
    expected_answer: str = ""
    records: list[LogRecordRequest] = Field(min_length=1)


@router.post("/log")
async def log(request: LogRequest) -> dict[str, object]:
    """予測結果を CSV へ追記する。

    predict と違い、失敗は HTTP 500 で返す。predict が 200 のままなのは
    枠ごとの失敗が「画面に出す観測結果」だからだが、記録の失敗は観測結果では
    なく、その送信ぶんが CSV に残らなかったという事実である。
    成功と同じ 200 で返すと、画面が取りこぼしに気づけない。
    """
    records = [
        LogRecord(
            vendor=record.vendor,
            model=record.model,
            answer=record.answer,
            continuation=record.continuation,
            elapsed_ms=record.elapsed_ms,
            ok=record.ok,
            error_kind=record.error_kind,
            correct=record.correct,
            manual=record.manual,
        )
        for record in request.records
    ]

    try:
        written = append_records(
            question_text=request.question_text,
            complete=request.complete,
            expected_answer=request.expected_answer,
            records=records,
        )
    except OSError as error:
        raise HTTPException(
            status_code=500,
            detail=f"記録先へ書き込めませんでした: {error}",
        ) from error

    return {"ok": True, "written": written}


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)

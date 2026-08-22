"""予測結果の CSV 記録。

ブラウザからファイルへ追記できないため、記録はサーバ側で行う。
llm-poc は LLM 予測が主目的で server の起動が前提であり、
記録だけをフロントへ退避させる必要はない。

1 送信 × 1 LLM を 1 レコードとする。枠ごとに列を並べる形（1 送信 = 1 行）は、
枠数やモデルの組み合わせが変わると列構成まで変わってしまうため採らない。

書き込みは追記のみで、既存行の更新は行わない。そのため呼び出し側
（フロントの「この問題を確定」）が、正解の入力と手動正解の操作を
済ませてから 1 回だけ送る前提になっている。
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone

# server/app/llm/log.py -> リポジトリルート
REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_LOG_PATH = REPO_ROOT / "llm-poc" / "logs" / "predictions.csv"

CSV_COLUMNS = (
    "timestamp",
    "question_text",
    "complete",
    "expected_answer",
    "vendor",
    "model",
    "answer",
    "continuation",
    "elapsed_ms",
    "ok",
    "error_kind",
    "correct",
    "manual",
)


@dataclass(frozen=True)
class LogRecord:
    """1 送信 × 1 LLM ぶんの記録。"""

    vendor: str
    model: str
    answer: str
    continuation: str | None
    elapsed_ms: int
    ok: bool
    error_kind: str | None
    correct: bool
    manual: bool


def log_path() -> Path:
    """記録先。テストで差し替えられるよう環境変数を見る。"""
    override = os.getenv("LLM_POC_LOG_PATH")
    if override is not None and override.strip() != "":
        return Path(override.strip())
    return DEFAULT_LOG_PATH


def append_records(
    *,
    question_text: str,
    complete: bool,
    expected_answer: str,
    records: list[LogRecord],
    path: Path | None = None,
) -> int:
    """1 送信ぶんを CSV へ追記し、書いた行数を返す。

    ファイルが無ければヘッダごと作る。ディレクトリも同様に用意する
    （logs/ は .gitignore 対象で、クローン直後には存在しないため）。
    """
    target = path if path is not None else log_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    # 追記の前にヘッダの要否を決める。空ファイルもヘッダ無しとして扱う。
    needs_header = not target.exists() or target.stat().st_size == 0

    # 記録時刻は 1 送信で共通にする。行ごとに取ると、同じ送信のはずが
    # ミリ秒単位でずれ、後から 1 回ぶんとしてまとめにくくなる。
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    with target.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        if needs_header:
            writer.writerow(CSV_COLUMNS)

        for record in records:
            writer.writerow(
                (
                    timestamp,
                    question_text,
                    _to_csv_bool(complete),
                    expected_answer,
                    record.vendor,
                    record.model,
                    record.answer,
                    record.continuation if record.continuation is not None else "",
                    record.elapsed_ms,
                    _to_csv_bool(record.ok),
                    record.error_kind if record.error_kind is not None else "",
                    _to_csv_bool(record.correct),
                    _to_csv_bool(record.manual),
                )
            )

    return len(records)


def _to_csv_bool(value: bool) -> str:
    """CSV 上の真偽値。表計算ソフトで読んでも判別できる形にする。"""
    return "true" if value else "false"

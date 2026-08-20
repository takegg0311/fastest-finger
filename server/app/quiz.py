"""quiz_data/questions.csv の読み込みと検証。

PoC は poc/scripts/build-manifest.ts で CSV を manifest.json へ変換していたが、
それはバックエンドを持たずブラウザから CSV を解決できなかったための方式である。
サーバがある以上 CSV を直接読めばよく、manifest.json は介さない。
ビルド前スクリプトの実行忘れという運用事故も無くなる。

検証仕様は build-manifest.ts と同一。ズレたまま出題されるとクイズを遊ぶまで
気づけないため、問題があればサーバを起動させない。
"""

from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass, field
from pathlib import Path

# 1 問につきこの 3 つが揃っている必要がある
REQUIRED_EXTENSIONS = (".wav", ".txt", ".lab")

# alt_answers 列の区切り文字
ALT_ANSWER_SEPARATOR = "|"

CSV_COLUMNS = ("batch", "seq", "text", "answer", "alt_answers")

# quiz_data はリポジトリルートに置き、PoC と共有している
REPO_ROOT = Path(__file__).resolve().parents[2]
QUIZ_DATA_DIR = REPO_ROOT / "quiz_data"


def seq_width(count: int) -> int:
    """出力数から、連番のゼロ埋め桁数を求める。

    VOICEPEAK は同じ接尾語で出力したファイル数に応じて連番をゼロ埋めする。
    10 個以上なら 2 桁、100 個以上なら 3 桁。境界は連番の値ではなく出力数で
    決まるため、9 個（0〜8）は 1 桁、10 個（00〜09）は 2 桁になる。
    """
    return len(str(max(count, 1)))


def question_file_path(batch: str, seq: int, ext: str, width: int = 1) -> str:
    """1 問分のファイルの、quiz_data からの相対パスを組み立てる。

    VOICEPEAK は連番だけの出力ができず接尾語が必須のため、接尾語にバッチ名
    （日付）を指定する運用とし、`{batch}/{seq}-{batch}.{ext}` を期待する。
    接尾語がフォルダ名と一致することで、別バッチのファイルを取り違えて
    置いた場合にファイルが見つからず検出できる。

    連番は width 桁までゼロ埋めする（`00-20260821.wav` など）。桁数は
    バッチ内の出力数で決まるため、呼び出し側が seq_width で求めて渡す。
    """
    return f"{batch}/{seq:0{width}d}-{batch}{ext}"


class QuizDataError(Exception):
    """questions.csv の内容に問題がある。起動を止めるために送出する。"""


@dataclass(frozen=True)
class Question:
    """出題 1 問分。"""

    # `{batch}/{seq}` 形式の問題 ID
    id: str
    batch: str
    seq: int
    # quiz_data からの相対パス
    wav: str
    txt: str
    lab: str
    text: str
    # 正解と別解。先頭が主たる正解。
    # 新システムでは判定に使わないが、出題者画面に正解を表示するために要る。
    answers: list[str]

    def audio_url(self) -> str:
        return f"/quiz_data/{self.wav}"

    def lab_url(self) -> str:
        return f"/quiz_data/{self.lab}"


@dataclass
class _RowError:
    """1 行分の検証結果。エラーがあれば entry は None になる。"""

    entry: Question | None = None
    messages: list[str] = field(default_factory=list)


def _to_answers(row: dict[str, str]) -> list[str]:
    """正解と別解をまとめる。空要素は落とす。"""
    alternatives = [
        value.strip()
        for value in row["alt_answers"].split(ALT_ANSWER_SEPARATOR)
        if value.strip() != ""
    ]
    return [row["answer"], *alternatives]


def _validate_row(
    row: dict[str, str], line_number: int, quiz_data_dir: Path, width: int
) -> _RowError:
    """1 行を検証して Question にする。問題があれば理由を messages へ積む。

    width はバッチ内の連番のゼロ埋め桁数。バッチ全体を見ないと決まらないため
    呼び出し側から渡す。
    """
    label = f"{line_number} 行目"
    result = _RowError()

    for column in ("batch", "seq", "text", "answer"):
        if row[column] == "":
            result.messages.append(f"{label}: {column} が空です。")

    seq: int | None = None
    if row["seq"] != "":
        try:
            seq = int(row["seq"])
            if seq < 0:
                raise ValueError
        except ValueError:
            result.messages.append(
                f"{label}: seq は 0 以上の整数である必要があります（{row['seq']}）。"
            )
            seq = None

    # 1 問 1 ブロックが前提。改行があると seq が複数消費され対応が崩れる
    if "\n" in row["text"]:
        result.messages.append(f"{label}: text に改行を含められません（1 問 1 ブロック）。")

    if result.messages or seq is None:
        return result

    question_id = f"{row['batch']}/{seq}"
    paths: dict[str, str] = {}

    for ext in REQUIRED_EXTENSIONS:
        relative_path = question_file_path(row["batch"], seq, ext, width)
        if not (quiz_data_dir / relative_path).exists():
            result.messages.append(f"{label} ({question_id}): {relative_path} が見つかりません。")
            continue
        paths[ext] = relative_path

    if result.messages:
        return result

    # CSV の text と VOICEPEAK が出力した txt を突き合わせる。
    # ズレたまま出題されるとクイズを遊ぶまで気づけないため、ここで止める。
    txt_content = (quiz_data_dir / paths[".txt"]).read_text(encoding="utf-8").strip()
    if txt_content != row["text"]:
        result.messages.append(
            f"{label} ({question_id}): text が {paths['.txt']} と一致しません。\n"
            f"    CSV: {row['text']}\n"
            f"    TXT: {txt_content}"
        )
        return result

    result.entry = Question(
        id=question_id,
        batch=row["batch"],
        seq=seq,
        wav=paths[".wav"],
        txt=paths[".txt"],
        lab=paths[".lab"],
        text=row["text"],
        answers=_to_answers(row),
    )
    return result


def load_questions(quiz_data_dir: Path | None = None) -> list[Question]:
    """questions.csv を読んで検証し、出題可能な問題一覧を返す。

    検証に失敗した場合は QuizDataError を送出する。
    """
    directory = quiz_data_dir if quiz_data_dir is not None else QUIZ_DATA_DIR
    csv_path = directory / "questions.csv"

    try:
        source = csv_path.read_text(encoding="utf-8")
    except OSError as error:
        raise QuizDataError(
            f"{csv_path} を読み取れませんでした。"
            "batch,seq,text,answer,alt_answers の 5 列を持つ CSV を配置してください。"
        ) from error

    # 問題文に `,` が含まれるためクォートの解釈が要る。csv モジュールは
    # クォート内の改行も 1 フィールドとして読むので、行番号はレコード単位でズレない。
    reader = csv.reader(io.StringIO(source))
    try:
        header = next(reader)
    except StopIteration:
        raise QuizDataError("questions.csv が空です。") from None

    header_names = [name.strip() for name in header]
    missing = [name for name in CSV_COLUMNS if name not in header_names]
    if missing:
        raise QuizDataError(
            f"questions.csv のヘッダに {', '.join(missing)} がありません。"
            f"期待する列: {', '.join(CSV_COLUMNS)}"
        )

    column_index = {name: header_names.index(name) for name in CSV_COLUMNS}

    errors: list[str] = []
    questions: list[Question] = []
    seen_ids: dict[str, int] = {}

    # ファイル名のゼロ埋め桁数はバッチ内の出力数で決まるため、行ごとの検証に入る前に
    # 全行を読んでバッチごとの連番の最大値を集める。
    rows: list[tuple[int, dict[str, str]]] = []
    max_seq: dict[str, int] = {}

    for index, cells in enumerate(reader):
        # 空行は読み飛ばす
        if not any(cell.strip() for cell in cells):
            continue

        # ヘッダ行があるため、CSV 上の行番号は +2
        line_number = index + 2
        row = {
            name: (cells[position].strip() if position < len(cells) else "")
            for name, position in column_index.items()
        }
        rows.append((line_number, row))

        # 桁数の集計。ここでは検証せず、数として読めるものだけを見る。
        # 不正な値は _validate_row が行番号つきで報告する。
        try:
            seq = int(row["seq"])
        except ValueError:
            continue
        if seq < 0:
            continue
        batch = row["batch"]
        if seq > max_seq.get(batch, -1):
            max_seq[batch] = seq

    # 連番は 0 起点なので、出力数は最大値 + 1。
    # CSV の行数を使わないのは、行を削っても実ファイル名の桁数は変わらないため。
    widths = {batch: seq_width(largest + 1) for batch, largest in max_seq.items()}

    for line_number, row in rows:
        result = _validate_row(row, line_number, directory, widths.get(row["batch"], 1))
        errors.extend(result.messages)
        if result.entry is None:
            continue

        duplicated_at = seen_ids.get(result.entry.id)
        if duplicated_at is not None:
            errors.append(
                f"{line_number} 行目: {result.entry.id} が {duplicated_at} 行目と重複しています。"
            )
            continue

        seen_ids[result.entry.id] = line_number
        questions.append(result.entry)

    if errors:
        joined = "\n  - ".join(errors)
        raise QuizDataError(f"questions.csv に問題があります。\n  - {joined}")
    if not questions:
        raise QuizDataError("questions.csv に出題可能な問題がありません。")

    return questions


def pick_random(questions: list[Question], exclude: str | None = None) -> Question | None:
    """次の問題を 1 問選ぶ。

    直前と同じ問題が続くのを避けるため、候補が 2 問以上あるときは exclude を除外する。
    複数端末が繋がる以上、次の問題の決定はサーバの 1 箇所で行う。
    """
    if not questions:
        return None

    candidates = (
        [question for question in questions if question.id != exclude]
        if len(questions) > 1 and exclude is not None
        else questions
    )
    pool = candidates if candidates else questions

    return random.choice(pool)

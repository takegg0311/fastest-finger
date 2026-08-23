"""quiz_data/questions.csv の読み込みと検証。

PoC は poc/scripts/build-manifest.ts で CSV を manifest.json へ変換していたが、
それはバックエンドを持たずブラウザから CSV を解決できなかったための方式である。
サーバがある以上 CSV を直接読めばよく、manifest.json は介さない。
ビルド前スクリプトの実行忘れという運用事故も無くなる。

ズレたまま出題されるとクイズを遊ぶまで気づけないため、問題があれば
QuizDataError を送出する（main.py がこれを捕まえ、オンライン版の入口を閉じる）。

音声（.wav/.txt/.lab）は必須ではない。3 点セットが揃っていれば音声あり問題、
まったく無ければ音声なし問題として扱う。一部だけある場合はファイルの
置き忘れ・置き間違いとみなしてエラーにする。
"""

from __future__ import annotations

import csv
import io
import os
import random
from dataclasses import dataclass, field
from pathlib import Path

# 音声あり問題は、この 3 つが揃っている必要がある。
# 1 つも無ければ音声なし問題、一部だけあればエラー。
AUDIO_EXTENSIONS = (".wav", ".txt", ".lab")

# ファイル探索で試すゼロ埋め桁数。VOICEPEAK は出力数に応じて 1〜3 桁を使う。
CANDIDATE_WIDTHS = (1, 2, 3)

# 音声なし問題の文字送り間隔（ミリ秒/文字）。
# VOICEPEAK の読み上げ実測から逆算した値。句読点でのウェイトは入れず等速で送る。
DEFAULT_CHAR_INTERVAL_MS = 120

# alt_answers 列の区切り文字
ALT_ANSWER_SEPARATOR = "|"

CSV_COLUMNS = ("batch", "seq", "text", "answer", "alt_answers")

# quiz_data はリポジトリルートに置き、PoC と共有している
REPO_ROOT = Path(__file__).resolve().parents[2]
QUIZ_DATA_DIR = REPO_ROOT / "quiz_data"


def char_interval_ms() -> int:
    """音声なし問題の文字送り間隔を返す。

    毎回読むのは、テストで環境変数を差し替えられるようにするため。
    不正な値は既定値へ落とす（出題を止めるほどの問題ではない）。
    """
    raw = os.getenv("QUIZ_CHAR_INTERVAL_MS")
    if raw is None or raw.strip() == "":
        return DEFAULT_CHAR_INTERVAL_MS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_CHAR_INTERVAL_MS
    return value if value > 0 else DEFAULT_CHAR_INTERVAL_MS


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
    """出題 1 問分。

    音声を持たない問題では wav / txt / lab が None になる。
    その場合フロントは読み上げ音声を鳴らさず、1 文字ずつ等速で問題文を送る。
    """

    # `{batch}/{seq}` 形式の問題 ID
    id: str
    batch: str
    seq: int
    # quiz_data からの相対パス。音声なし問題では None
    wav: str | None
    txt: str | None
    lab: str | None
    text: str
    # 正解と別解。先頭が主たる正解。
    # 新システムでは判定に使わないが、出題者画面に正解を表示するために要る。
    answers: list[str]

    @property
    def has_audio(self) -> bool:
        """読み上げ音声を持つか。wav と lab が揃っていれば出題できる。"""
        return self.wav is not None and self.lab is not None

    def audio_url(self) -> str | None:
        return f"/quiz_data/{self.wav}" if self.wav is not None else None

    def lab_url(self) -> str | None:
        return f"/quiz_data/{self.lab}" if self.lab is not None else None


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


def _find_audio_paths(
    batch: str, seq: int, quiz_data_dir: Path, width: int
) -> tuple[dict[str, str], list[str]]:
    """1 問分の音声ファイルを探す。見つかった分と、見つからなかった拡張子を返す。

    まず想定桁数 width で探し、1 つも見つからなければ他の桁数でも試す。

    他の桁数まで見るのは、音声なし問題がバッチの連番の最大値を押し上げ、
    既存の音声あり問題の探索パスまで変えてしまうため。例えば 0〜41 の 42 問
    （2 桁）に seq=100 を足すと width が 3 になり、`00-...wav` を
    `000-...wav` として探して全問が見失われる。

    「音声なしかどうか」は桁数が決まらないとファイル名を組み立てられないため
    判定できず、桁数の算出側で音声なし問題を除外する順序では解けない（循環する）。
    そこで探索側で複数の桁数を試し、どれでも見つからないときに音声なしと判定する。
    """
    for candidate in (width, *(w for w in CANDIDATE_WIDTHS if w != width)):
        found: dict[str, str] = {}
        missing: list[str] = []

        for ext in AUDIO_EXTENSIONS:
            relative_path = question_file_path(batch, seq, ext, candidate)
            if (quiz_data_dir / relative_path).exists():
                found[ext] = relative_path
            else:
                missing.append(ext)

        # 1 つでも見つかった桁数を採用する。部分的に欠けている場合は
        # 置き忘れとして報告したいので、その桁数での結果をそのまま返す。
        if found:
            return found, missing

    # どの桁数でも 1 つも見つからなかった = 音声なし問題
    return {}, list(AUDIO_EXTENSIONS)


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
    paths, missing = _find_audio_paths(row["batch"], seq, quiz_data_dir, width)

    # 一部だけある場合はファイルの置き忘れ・置き間違いとして止める。
    # ここを黙って音声なしへ倒すと、音声を用意したはずの問題が無音で
    # 出題され、本番で初めて気づくことになる。
    if paths and missing:
        found_names = ", ".join(sorted(paths.values()))
        missing_names = ", ".join(missing)
        result.messages.append(
            f"{label} ({question_id}): 音声ファイルが揃っていません。"
            f"{missing_names} が見つかりません（{found_names} はあります）。\n"
            f"    3 点すべて揃えるか、3 点とも置かない（音声なし問題）にしてください。"
        )
        return result

    if paths:
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

    # paths が空なら音声なし問題。CSV の text だけで出題する。
    result.entry = Question(
        id=question_id,
        batch=row["batch"],
        seq=seq,
        wav=paths.get(".wav"),
        txt=paths.get(".txt"),
        lab=paths.get(".lab"),
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

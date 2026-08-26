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
    そこで探索側で複数の桁数を試し、どれでも 3 点セットが見つからないときに
    音声なしと判定する。
    """
    at_width = _probe_width(batch, seq, quiz_data_dir, width)

    # 想定桁に 1 つでもあれば、その結果をそのまま返す。想定桁は本来ファイルが
    # 置かれるべき場所なので、そこに一部だけあるなら置き忘れとみなす。
    # ここで他の桁へ逃がすと、置き忘れの検出が甘くなる。
    if at_width[0]:
        return at_width

    # 想定桁が空の場合だけ、他の桁を見る。桁数が変わったのは音声なし問題が
    # バッチの連番の最大値を押し上げたためで、実ファイルは以前の桁数のまま
    # 置かれている可能性がある。
    #
    # ここでは 3 点揃いを優先する。1 つでも見つかった桁を採る方式だと、
    # 古い桁数で作ったファイルの残骸（9 問時代の `0-...wav` など）が
    # 揃っている側より先に当たり、実際には揃っているのに一部欠けとして
    # 弾いてしまう。
    partial: tuple[dict[str, str], list[str]] | None = None

    for candidate in CANDIDATE_WIDTHS:
        if candidate == width:
            continue

        found, missing = _probe_width(batch, seq, quiz_data_dir, candidate)
        if found and not missing:
            return found, missing
        # 一部だけある桁は、3 点揃いが他に無かった場合に報告する
        if found and partial is None:
            partial = (found, missing)

    if partial is not None:
        return partial

    # どの桁数でも 1 つも見つからなかった = 音声なし問題
    return {}, list(AUDIO_EXTENSIONS)


def _probe_width(
    batch: str, seq: int, quiz_data_dir: Path, width: int
) -> tuple[dict[str, str], list[str]]:
    """指定した桁数で 1 問分のファイルを探す。"""
    found: dict[str, str] = {}
    missing: list[str] = []

    for ext in AUDIO_EXTENSIONS:
        relative_path = question_file_path(batch, seq, ext, width)
        if (quiz_data_dir / relative_path).exists():
            found[ext] = relative_path
        else:
            missing.append(ext)

    return found, missing


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


class QuestionShuffler:
    """全問を 1 つの山としてシャッフルし、頭から消化していく抽選器。

    単純な乱数選択では、未出題の問題が残っていても既出が繰り返し選ばれる。
    山を作って頭から配れば、一巡するまで同じ問題は出ない。

    山は起動時に組み、使い切ったら組み直す。プロセス内メモリだけで持ち、
    永続化しない。会ごとにサーバを立て直す運用であり、前回の履歴を
    引き継ぐ必要がないため。

    複数端末が繋がる以上、次の問題の決定はサーバの 1 箇所で行う。
    """

    def __init__(self, questions: list[Question]) -> None:
        # 呼び出し側のリストが後から変わっても山が壊れないよう複製する
        self._questions = list(questions)
        # 未出題の問題。末尾から pop して配るため、山は逆順に積む
        self._deck: list[Question] = []
        # 直前に出題した問題。山を組み直すときの重複回避に使う
        self._last_id: str | None = None
        self._refill()

    @property
    def total(self) -> int:
        """全問数。"""
        return len(self._questions)

    @property
    def remaining(self) -> int:
        """この一巡で、まだ出題していない問題数。"""
        return len(self._deck)

    def _refill(self) -> None:
        """山を組み直す。

        末尾から pop するため、シャッフル結果を逆順に積む。こうすると
        _deck[-1] が「次に出す問題」になり、先頭の重複回避が末尾の
        入れ替えとして書ける。
        """
        shuffled = list(self._questions)
        random.shuffle(shuffled)
        self._deck = list(reversed(shuffled))

        # 組み直した山の先頭が直前の問題と同じだと、一巡したのに同じ問題が
        # 2 回続いて見える。その場合だけ先頭と 2 番目を入れ替える。
        # 全体を引き直さないのは、引き直しでは最悪ケースで終わらないため。
        # 2 問目以降は対象にしない（一巡分離れていれば連続とは感じられない）。
        if (
            len(self._deck) > 1
            and self._last_id is not None
            and self._deck[-1].id == self._last_id
        ):
            self._deck[-1], self._deck[-2] = self._deck[-2], self._deck[-1]

    def take(self, question_id: str | None = None) -> Question | None:
        """次の 1 問を取り出し、山から取り除く。

        question_id を指定した場合はその問題を返し、山に残っていれば取り除く。
        取り除かないと、指定して出題した問題が後で山の順番どおりに再び出てくる。

        山が空になったら組み直す。誤答でもスルーでも、一度取り出した問題は
        山へ戻さない。会場で読み上げられた時点で消費されているため。
        """
        if not self._questions:
            return None

        # 山を組み直すのは取り出しの直前だけにする。取り出した後に先回りして
        # 組み直すと、最後の 1 問を出した時点で残数が満数に戻ってしまい、
        # 「残り 0」が表示されないまま一巡が終わったように見える。
        if not self._deck:
            self._refill()

        if question_id is not None:
            question = next((q for q in self._questions if q.id == question_id), None)
            if question is None:
                return None
            self._deck = [q for q in self._deck if q.id != question_id]
        else:
            question = self._deck.pop()

        self._last_id = question.id
        return question

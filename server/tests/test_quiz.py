"""questions.csv の読み込みと検証のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.quiz import QuizDataError, load_questions, pick_random, question_file_path

HEADER = "batch,seq,text,answer,alt_answers\n"


def write_quiz_data(
    directory: Path,
    csv_body: str,
    *,
    files: dict[str, str] | None = None,
) -> Path:
    """検証用の quiz_data ディレクトリを組み立てる。

    files は `{batch}/{seq}-{batch}.txt` -> 中身 の対応。指定がなければ CSV の
    text をそのまま .txt に書き、wav / lab は空ファイルで用意する。
    """
    (directory / "questions.csv").write_text(HEADER + csv_body, encoding="utf-8")

    if files is not None:
        for relative_path, content in files.items():
            path = directory / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    return directory


def make_question_files(directory: Path, batch: str, seq: int, text: str) -> None:
    """1 問分の wav / txt / lab を用意する。

    ファイル名の組み立ては本番と同じ question_file_path に委ね、
    テスト側に命名規則を二重に書かない。
    """
    (directory / batch).mkdir(parents=True, exist_ok=True)
    (directory / question_file_path(batch, seq, ".txt")).write_text(text, encoding="utf-8")
    (directory / question_file_path(batch, seq, ".wav")).write_bytes(b"")
    (directory / question_file_path(batch, seq, ".lab")).write_text(
        "0 1000000 pau\n", encoding="utf-8"
    )


def test_正常な_csv_を読み込める(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "日本の首都はどこ？")
    write_quiz_data(tmp_path, "20260820,0,日本の首都はどこ？,東京,とうきょう\n")

    questions = load_questions(tmp_path)

    assert len(questions) == 1
    question = questions[0]
    assert question.id == "20260820/0"
    assert question.batch == "20260820"
    assert question.seq == 0
    assert question.text == "日本の首都はどこ？"
    assert question.answers == ["東京", "とうきょう"]
    assert question.audio_url() == "/quiz_data/20260820/0-20260820.wav"
    assert question.lab_url() == "/quiz_data/20260820/0-20260820.lab"


def test_問題文に_カンマ_を含められる(tmp_path: Path) -> None:
    text = "日本で一番高い山は富士山ですが、世界で一番高い山はどこ？"
    make_question_files(tmp_path, "20260820", 0, text)
    write_quiz_data(tmp_path, f'20260820,0,"{text}",エベレスト,\n')

    questions = load_questions(tmp_path)

    assert questions[0].text == text


def test_別解が空なら正解だけになる(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "問題")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")

    assert load_questions(tmp_path)[0].answers == ["答え"]


def test_別解の空要素は落とされる(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "問題")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,別解1||別解2\n")

    assert load_questions(tmp_path)[0].answers == ["答え", "別解1", "別解2"]


def test_csv_が無ければエラー(tmp_path: Path) -> None:
    with pytest.raises(QuizDataError, match="読み取れませんでした"):
        load_questions(tmp_path)


def test_ヘッダの列が足りなければエラー(tmp_path: Path) -> None:
    (tmp_path / "questions.csv").write_text("batch,seq,text\n", encoding="utf-8")

    with pytest.raises(QuizDataError, match="answer, alt_answers がありません"):
        load_questions(tmp_path)


def test_必須列が空ならエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, "20260820,0,,答え,\n")

    with pytest.raises(QuizDataError, match="2 行目: text が空です"):
        load_questions(tmp_path)


def test_seq_が整数でなければエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, "20260820,abc,問題,答え,\n")

    with pytest.raises(QuizDataError, match="seq は 0 以上の整数"):
        load_questions(tmp_path)


def test_seq_が負ならエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, "20260820,-1,問題,答え,\n")

    with pytest.raises(QuizDataError, match="seq は 0 以上の整数"):
        load_questions(tmp_path)


def test_問題文に改行があればエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, '20260820,0,"前半\n後半",答え,\n')

    with pytest.raises(QuizDataError, match="text に改行を含められません"):
        load_questions(tmp_path)


def test_音声ファイルが無ければエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")

    with pytest.raises(QuizDataError, match=r"20260820/0-20260820\.wav が見つかりません"):
        load_questions(tmp_path)


def test_txt_と一致しなければエラー(tmp_path: Path) -> None:
    """CSV の text と VOICEPEAK 出力の txt がズレたまま出題されるのを防ぐ。"""
    make_question_files(tmp_path, "20260820", 0, "音声側の問題文")
    write_quiz_data(tmp_path, "20260820,0,CSV側の問題文,答え,\n")

    with pytest.raises(QuizDataError, match="text が 20260820/0-20260820.txt と一致しません"):
        load_questions(tmp_path)


def test_id_が重複すればエラー(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "問題")
    write_quiz_data(tmp_path, "20260820,0,問題,答え1,\n20260820,0,問題,答え2,\n")

    with pytest.raises(QuizDataError, match="20260820/0 が 2 行目と重複しています"):
        load_questions(tmp_path)


def test_出題可能な問題が_0_問ならエラー(tmp_path: Path) -> None:
    write_quiz_data(tmp_path, "")

    with pytest.raises(QuizDataError, match="出題可能な問題がありません"):
        load_questions(tmp_path)


def test_空行は読み飛ばす(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "問題")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n\n")

    assert len(load_questions(tmp_path)) == 1


def test_エラーは行番号つきでまとめて報告される(tmp_path: Path) -> None:
    make_question_files(tmp_path, "20260820", 0, "問題")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n,1,問題2,答え2,\n20260820,xyz,問題3,答え3,\n")

    with pytest.raises(QuizDataError) as error:
        load_questions(tmp_path)

    message = str(error.value)
    assert "3 行目: batch が空です" in message
    assert "4 行目: seq は 0 以上の整数" in message


class TestPickRandom:
    def test_空なら_none(self) -> None:
        assert pick_random([]) is None

    def test_1_問しかなければ_exclude_を無視する(self, tmp_path: Path) -> None:
        """候補が尽きるくらいなら同じ問題を返す。出題を止めないため。"""
        make_question_files(tmp_path, "20260820", 0, "問題")
        write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")
        questions = load_questions(tmp_path)

        assert pick_random(questions, exclude="20260820/0") is questions[0]

    def test_直前の問題を除外する(self, tmp_path: Path) -> None:
        for seq in range(2):
            make_question_files(tmp_path, "20260820", seq, f"問題{seq}")
        write_quiz_data(
            tmp_path,
            "20260820,0,問題0,答え0,\n20260820,1,問題1,答え1,\n",
        )
        questions = load_questions(tmp_path)

        # 乱数に依存するため繰り返して確認する
        for _ in range(30):
            assert pick_random(questions, exclude="20260820/0").id == "20260820/1"

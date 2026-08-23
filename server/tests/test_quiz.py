"""questions.csv の読み込みと検証のテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.quiz import (
    QuizDataError,
    char_interval_ms,
    load_questions,
    pick_random,
    question_file_path,
    seq_width,
)

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


def make_question_files(
    directory: Path, batch: str, seq: int, text: str, width: int = 1
) -> None:
    """1 問分の wav / txt / lab を用意する。

    ファイル名の組み立ては本番と同じ question_file_path に委ね、
    テスト側に命名規則を二重に書かない。width は連番のゼロ埋め桁数。
    """
    (directory / batch).mkdir(parents=True, exist_ok=True)
    (directory / question_file_path(batch, seq, ".txt", width)).write_text(text, encoding="utf-8")
    (directory / question_file_path(batch, seq, ".wav", width)).write_bytes(b"")
    (directory / question_file_path(batch, seq, ".lab", width)).write_text(
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


def test_音声ファイルが無ければ音声なし問題になる(tmp_path: Path) -> None:
    """3 点とも無いのはエラーではない。CSV だけで出題できる。"""
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")

    questions = load_questions(tmp_path)

    assert len(questions) == 1
    assert questions[0].has_audio is False
    assert questions[0].wav is None
    assert questions[0].lab is None
    assert questions[0].audio_url() is None
    assert questions[0].lab_url() is None
    # 問題文と正解は CSV から取れている
    assert questions[0].text == "問題"
    assert questions[0].answers == ["答え"]


def test_音声が一部だけあればエラー(tmp_path: Path) -> None:
    """置き忘れ・置き間違いを検出する。黙って音声なしへ倒さない。

    ここを緩めると、音声を用意したはずの問題が無音で出題され、
    本番で初めて気づくことになる。
    """
    (tmp_path / "20260820").mkdir(parents=True)
    (tmp_path / question_file_path("20260820", 0, ".wav")).write_bytes(b"")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")

    with pytest.raises(QuizDataError, match=r"音声ファイルが揃っていません"):
        load_questions(tmp_path)


def test_一部だけある場合は欠けている拡張子を挙げる(tmp_path: Path) -> None:
    (tmp_path / "20260820").mkdir(parents=True)
    (tmp_path / question_file_path("20260820", 0, ".wav")).write_bytes(b"")
    write_quiz_data(tmp_path, "20260820,0,問題,答え,\n")

    with pytest.raises(QuizDataError) as error:
        load_questions(tmp_path)

    message = str(error.value)
    assert "2 行目" in message
    assert ".txt" in message
    assert ".lab" in message


def test_音声ありとなしが混在できる(tmp_path: Path) -> None:
    """同じ CSV に両方を並べられる。"""
    make_question_files(tmp_path, "20260820", 0, "音声あり問題", width=2)
    make_question_files(tmp_path, "20260820", 1, "これも音声あり", width=2)
    write_quiz_data(
        tmp_path,
        "20260820,0,音声あり問題,答え1,\n"
        "20260820,1,これも音声あり,答え2,\n"
        "csvonly,0,音声なし問題,答え3,\n",
    )

    questions = load_questions(tmp_path)

    assert len(questions) == 3
    assert [q.has_audio for q in questions] == [True, True, False]


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


class TestSeqWidth:
    """VOICEPEAK は出力数に応じて連番をゼロ埋めする。境界は出力数で決まる。"""

    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (1, 1),
            (9, 1),  # 0〜8 なので 1 桁
            (10, 2),  # 00〜09 なので 2 桁
            (11, 2),
            (99, 2),
            (100, 3),  # 000〜099 なので 3 桁
            (101, 3),
        ],
    )
    def test_出力数から桁数を求める(self, count: int, expected: int) -> None:
        assert seq_width(count) == expected

    def test_ゼロ埋めしてパスを組み立てる(self) -> None:
        assert question_file_path("20260821", 0, ".wav", 2) == "20260821/00-20260821.wav"
        assert question_file_path("20260821", 10, ".wav", 2) == "20260821/10-20260821.wav"
        assert question_file_path("20260821", 5, ".wav", 3) == "20260821/005-20260821.wav"


class TestZeroPadding:
    """バッチ内の連番の最大値から桁数を決める。"""

    def test_10_問なら_2_桁で探索する(self, tmp_path: Path) -> None:
        body = ""
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)
            body += f"20260821,{seq},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 10
        assert questions[0].wav == "20260821/00-20260821.wav"
        assert questions[9].wav == "20260821/09-20260821.wav"
        # ID は整数のまま。ゼロ埋めはファイル名だけの話である
        assert questions[0].id == "20260821/0"

    def test_9_問なら_ゼロ埋めしない(self, tmp_path: Path) -> None:
        body = ""
        for seq in range(9):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}")
            body += f"20260821,{seq},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 9
        assert questions[0].wav == "20260821/0-20260821.wav"
        assert questions[8].wav == "20260821/8-20260821.wav"

    def test_100_問なら_3_桁で探索する(self, tmp_path: Path) -> None:
        body = ""
        for seq in range(100):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=3)
            body += f"20260821,{seq},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 100
        assert questions[0].wav == "20260821/000-20260821.wav"
        assert questions[99].wav == "20260821/099-20260821.wav"

    def test_バッチごとに桁数を決める(self, tmp_path: Path) -> None:
        """1 問だけのバッチと 10 問のバッチが混在しても、それぞれの桁数で解決する。"""
        make_question_files(tmp_path, "20260820", 0, "単独の問題")
        body = "20260820,0,単独の問題,答え,\n"
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)
            body += f"20260821,{seq},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = {question.id: question for question in load_questions(tmp_path)}

        assert questions["20260820/0"].wav == "20260820/0-20260820.wav"
        assert questions["20260821/0"].wav == "20260821/00-20260821.wav"

    def test_csv_の_seq_がゼロ埋めされていても同じ結果になる(self, tmp_path: Path) -> None:
        """表計算ソフトで桁落ちしても壊れないよう、seq は整数として解釈する。"""
        body = ""
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)
            # CSV 側は 00, 01, ... とゼロ埋めして書く
            body += f"20260821,{seq:02d},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 10
        assert questions[0].id == "20260821/0"
        assert questions[0].wav == "20260821/00-20260821.wav"

    def test_行を削っても既存ファイルを見失わない(self, tmp_path: Path) -> None:
        """桁数は seq の最大値から決める。行数基準だと 10 行を切った時点で破綻する。"""
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)

        # 11 問出力したあと CSV を 9 行に減らした状況を模す。
        # 実ファイルは 2 桁のままなので、9 行でも 2 桁で探さなければならない。
        body = ""
        for seq in [0, 1, 2, 3, 4, 6, 7, 8, 9]:
            body += f"20260821,{seq},問題{seq},答え{seq},\n"
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 9
        assert questions[0].wav == "20260821/00-20260821.wav"


    def test_音声なし問題が既存の桁数を狂わせない(self, tmp_path: Path) -> None:
        """音声なし問題を既存バッチに足しても、音声ありが見失われない。

        seq_width はバッチ内の連番の最大値から桁数を決めるため、大きな seq の
        音声なし問題を足すと想定桁数が増える。探索側で複数桁を試すことで、
        既存の音声あり問題（2 桁で置かれている）が引き続き見つかる。
        """
        # 0〜9 の 10 問を 2 桁で置く
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)

        rows = "".join(f"20260821,{seq},問題{seq},答え{seq},\n" for seq in range(10))
        # seq=100 の音声なし問題を足す。これで seq_width は 3 桁を返す
        rows += "20260821,100,音声なし問題,答え100,\n"
        write_quiz_data(tmp_path, rows)

        questions = load_questions(tmp_path)

        assert len(questions) == 11
        # 既存の 10 問は音声つきのまま見つかる
        assert all(q.has_audio for q in questions[:10])
        # 足した 1 問だけが音声なし
        assert questions[10].has_audio is False
        assert questions[10].seq == 100

    def test_古い桁数の残骸があっても揃っている側を選ぶ(self, tmp_path: Path) -> None:
        """9 問時代の 1 桁ファイルが残っていても、2 桁の 3 点セットを採用する。

        バッチを 9 問から増やすと、実ファイルの桁数は 1 桁から 2 桁へ変わる。
        古い出力を消し忘れると 1 桁のファイルが残る。ここで「1 つでも
        見つかった桁を採用する」方式だと、残骸が揃っている側より先に当たり、
        実際には揃っているのに一部欠けとして弾いてしまう。
        """
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)

        # 9 問時代の名残。.wav だけが 1 桁で残っている
        (tmp_path / question_file_path("20260821", 0, ".wav", 1)).write_bytes(b"")

        rows = "".join(f"20260821,{seq},問題{seq},答え{seq},\n" for seq in range(10))
        # seq=100 を足して想定桁を 3 にする（探索順が 3 → 1 → 2 になる）
        rows += "20260821,100,音声なし問題,答え100,\n"
        write_quiz_data(tmp_path, rows)

        questions = load_questions(tmp_path)

        assert len(questions) == 11
        # 残骸に引きずられず、2 桁の 3 点セットが選ばれる
        assert questions[0].has_audio is True
        assert questions[0].wav == question_file_path("20260821", 0, ".wav", 2)
        assert questions[10].has_audio is False

    def test_他の桁数に一部だけあればエラー(self, tmp_path: Path) -> None:
        """3 点揃いがどの桁にも無く、一部だけある場合は置き忘れとして報告する。"""
        (tmp_path / "20260821").mkdir(parents=True)
        # 想定桁は 1 だが、2 桁側に .wav だけ置く
        (tmp_path / question_file_path("20260821", 0, ".wav", 2)).write_bytes(b"")
        write_quiz_data(tmp_path, "20260821,0,問題,答え,\n")

        with pytest.raises(QuizDataError, match=r"音声ファイルが揃っていません"):
            load_questions(tmp_path)

    def test_想定桁に一部あれば他の桁へ逃がさない(self, tmp_path: Path) -> None:
        """想定桁は本来の置き場所。そこに一部だけあるなら置き忘れとみなす。

        ここで他の桁を探しに行くと、置き忘れの検出が甘くなる。
        """
        (tmp_path / "20260821").mkdir(parents=True)
        # 想定桁（1 桁）に .wav だけ、2 桁側には 3 点すべて置く
        (tmp_path / question_file_path("20260821", 0, ".wav", 1)).write_bytes(b"")
        make_question_files(tmp_path, "20260821", 0, "問題", width=2)
        write_quiz_data(tmp_path, "20260821,0,問題,答え,\n")

        # 2 桁側が揃っていても、想定桁の欠けを優先して報告する
        with pytest.raises(QuizDataError, match=r"音声ファイルが揃っていません"):
            load_questions(tmp_path)

    def test_音声なし問題を別バッチに置いても混ざらない(self, tmp_path: Path) -> None:
        """推奨する運用（別バッチに置く）でも正しく判定される。"""
        for seq in range(10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)

        rows = "".join(f"20260821,{seq},問題{seq},答え{seq},\n" for seq in range(10))
        rows += "csvonly,0,音声なし問題,答え,\n"
        write_quiz_data(tmp_path, rows)

        questions = load_questions(tmp_path)

        assert len(questions) == 11
        assert all(q.has_audio for q in questions[:10])
        assert questions[10].has_audio is False


class TestCharInterval:
    """音声なし問題の文字送り間隔。"""

    def test_既定は_120ms(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("QUIZ_CHAR_INTERVAL_MS", raising=False)
        assert char_interval_ms() == 120

    def test_環境変数で変更できる(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("QUIZ_CHAR_INTERVAL_MS", "300")
        assert char_interval_ms() == 300

    @pytest.mark.parametrize("value", ["", "abc", "0", "-1"])
    def test_不正な値は既定へ落ちる(self, value: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """出題を止めるほどの問題ではないため、エラーにせず既定値を使う。"""
        monkeypatch.setenv("QUIZ_CHAR_INTERVAL_MS", value)
        assert char_interval_ms() == 120


class TestExtraFiles:
    """VOICEPEAK の副産物がバッチフォルダに同居しても壊れない。"""

    def test_連結ファイルと_vpp_が同居しても読み込める(self, tmp_path: Path) -> None:
        make_question_files(tmp_path, "20260821", 0, "問題0", width=2)
        make_question_files(tmp_path, "20260821", 1, "問題1", width=2)
        for seq in range(2, 10):
            make_question_files(tmp_path, "20260821", seq, f"問題{seq}", width=2)

        # VOICEPEAK は連番ファイルとは別に、全体を連結した txt / lab も出力する。
        # vpp は出力元のプロジェクトファイル。いずれも本システムでは使用しない。
        batch_dir = tmp_path / "20260821"
        (batch_dir / "20260821.txt").write_text("問題0\n問題1\n", encoding="utf-8")
        (batch_dir / "20260821.lab").write_text("0 1000000 pau\n", encoding="utf-8")
        (batch_dir / "20260821.vpp").write_bytes(b"dummy")

        body = "".join(f"20260821,{seq},問題{seq},答え{seq},\n" for seq in range(10))
        write_quiz_data(tmp_path, body)

        questions = load_questions(tmp_path)

        assert len(questions) == 10
        assert questions[0].wav == "20260821/00-20260821.wav"

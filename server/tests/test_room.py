"""ルーム状態機械のテスト。

とくに早押し判定は、複数端末での同時押しを手動で再現できないため
ここが唯一現実的な検証手段になる。
"""

from __future__ import annotations

import pytest

from app.quiz import Question
from app.room import Room


def make_question(seq: int) -> Question:
    return Question(
        id=f"20260820/{seq}",
        batch="20260820",
        seq=seq,
        wav=f"20260820/{seq}.wav",
        txt=f"20260820/{seq}.txt",
        lab=f"20260820/{seq}.lab",
        text=f"問題{seq}",
        answers=[f"答え{seq}"],
    )


@pytest.fixture
def room() -> Room:
    return Room(questions=[make_question(0), make_question(1)])


@pytest.fixture
def started_room(room: Room) -> Room:
    """2 人が参加し、出題が始まった状態。"""
    room.join("たけ", None)
    room.join("はな", None)
    room.start_question()
    return room


class TestJoin:
    def test_参加すると一覧に載る(self, room: Room) -> None:
        player = room.join("たけ", None)

        assert player.name == "たけ"
        assert player.connected is True
        assert room.players[player.id] is player

    def test_token_で同じ参加者として復帰する(self, room: Room) -> None:
        """リロードで別人になってしまうのを防ぐ。"""
        first = room.join("たけ", None)
        again = room.join("たけ", first.token)

        assert again.id == first.id
        assert len(room.players) == 1

    def test_未知の_token_なら新規参加になる(self, room: Room) -> None:
        first = room.join("たけ", None)
        other = room.join("はな", "でたらめなトークン")

        assert other.id != first.id
        assert len(room.players) == 2

    def test_再接続で名前を更新できる(self, room: Room) -> None:
        first = room.join("たけ", None)
        again = room.join("たけし", first.token)

        assert again.id == first.id
        assert again.name == "たけし"

    def test_長い名前は切り詰める(self, room: Room) -> None:
        """投影画面のレイアウトが崩れないようにする。"""
        player = room.join("あ" * 30, None)

        assert len(player.name) == 12

    def test_空の名前は名無しになる(self, room: Room) -> None:
        assert room.join("   ", None).name == "名無し"

    def test_切断しても一覧から消えない(self, room: Room) -> None:
        """投影画面から名前が消えると出題者が混乱するため。"""
        player = room.join("たけ", None)
        room.disconnect(player.id)

        assert player.id in room.players
        assert room.players[player.id].connected is False

    def test_同名が複数居ると連番が付く(self, room: Room) -> None:
        first = room.join("たけ", None)
        second = room.join("たけ", None)
        names = room.display_names()

        assert names[first.id] == "たけ (1)"
        assert names[second.id] == "たけ (2)"

    def test_同名が居なければ連番は付かない(self, room: Room) -> None:
        player = room.join("たけ", None)

        assert room.display_names()[player.id] == "たけ"


class TestStartQuestion:
    def test_出題すると_reading_になる(self, room: Room) -> None:
        room.start_question()

        assert room.phase == "reading"
        assert room.question is not None

    def test_出題のたびに_round_id_が増える(self, room: Room) -> None:
        room.start_question()
        first = room.round_id
        room.next_question()
        room.start_question()

        assert room.round_id == first + 1

    def test_問題を指定して出題できる(self, room: Room) -> None:
        question = room.start_question("20260820/1")

        assert question is not None
        assert question.id == "20260820/1"

    def test_存在しない問題を指定すると_none(self, room: Room) -> None:
        assert room.start_question("存在しない") is None

    def test_直前と同じ問題は連続しない(self, room: Room) -> None:
        first = room.start_question()
        assert first is not None

        for _ in range(20):
            room.next_question()
            following = room.start_question()
            assert following is not None
            assert following.id != first.id
            first = following


class TestBuzz:
    def test_最初の一人だけが通る(self, started_room: Room) -> None:
        """完了条件: 先着 1 件だけが accepted、後続は too_late。"""
        first_id, second_id = list(started_room.players)

        first = started_room.buzz(first_id, started_room.round_id)
        second = started_room.buzz(second_id, started_room.round_id)

        assert first.accepted is True
        assert first.player is not None
        assert first.player.id == first_id

        assert second.accepted is False
        assert second.reason == "too_late"

    def test_同一人物の連打も二度目は弾く(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))

        assert started_room.buzz(player_id, started_room.round_id).accepted is True
        assert started_room.buzz(player_id, started_room.round_id).reason == "too_late"

    def test_古いラウンドの_buzz_は弾く(self, started_room: Room) -> None:
        """完了条件: round_id 不一致は stale_round。

        前問の押し込みが遅延して次問に届くのを防ぐ。
        """
        player_id = next(iter(started_room.players))
        stale = started_room.round_id - 1

        result = started_room.buzz(player_id, stale)

        assert result.accepted is False
        assert result.reason == "stale_round"
        assert started_room.phase == "reading"

    def test_新しすぎるラウンドの_buzz_も弾く(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))

        result = started_room.buzz(player_id, started_room.round_id + 1)

        assert result.reason == "stale_round"

    @pytest.mark.parametrize("phase", ["idle", "timeUp", "result"])
    def test_reading_以外では受け付けない(self, started_room: Room, phase: str) -> None:
        """完了条件: reading 以外での buzz は wrong_phase。

        buzzed は「先客が居る」状態なので too_late が正しく、別途検証する。
        """
        player_id = next(iter(started_room.players))
        started_room.phase = phase  # type: ignore[assignment]

        result = started_room.buzz(player_id, started_room.round_id)

        assert result.accepted is False
        assert result.reason == "wrong_phase"

    def test_idle_では受け付けない(self, room: Room) -> None:
        player = room.join("たけ", None)

        result = room.buzz(player.id, room.round_id)

        assert result.reason == "wrong_phase"

    def test_お手つき中の回答者は弾く(self, started_room: Room) -> None:
        """完了条件: locked_out の回答者は locked_out。"""
        first_id, second_id = list(started_room.players)

        started_room.buzz(first_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)
        started_room.release(started_room.round_id)

        rejected = started_room.buzz(first_id, started_room.round_id)
        accepted = started_room.buzz(second_id, started_room.round_id)

        assert rejected.accepted is False
        assert rejected.reason == "locked_out"
        assert accepted.accepted is True

    def test_未参加の_id_は弾く(self, started_room: Room) -> None:
        result = started_room.buzz("p_999", started_room.round_id)

        assert result.accepted is False

    def test_buzz_すると_phase_が変わる(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        assert started_room.phase == "buzzed"
        assert started_room.buzzed is not None
        assert started_room.buzzed.id == player_id


class TestReadingEnded:
    def test_読み切ると_timeup_になる(self, started_room: Room) -> None:
        assert started_room.reading_ended(started_room.round_id) is True
        assert started_room.phase == "timeUp"

    def test_古いラウンドなら無視する(self, started_room: Room) -> None:
        assert started_room.reading_ended(started_room.round_id - 1) is False
        assert started_room.phase == "reading"

    def test_押された後なら無視する(self, started_room: Room) -> None:
        """buzz と読み切りが競合しても、先に成立した buzz を優先する。"""
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        assert started_room.reading_ended(started_room.round_id) is False
        assert started_room.phase == "buzzed"


class TestJudge:
    def test_正解で_result_になる(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        assert started_room.judge(started_room.round_id, correct=True) is True
        assert started_room.phase == "result"
        assert started_room.judgement is not None
        assert started_room.judgement.correct is True
        assert started_room.judgement.player_id == player_id

    def test_誤答するとお手つきになる(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)

        assert started_room.players[player_id].locked_out is True

    def test_正解ならお手つきにしない(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=True)

        assert started_room.players[player_id].locked_out is False

    def test_読み切りからでも判定できる(self, started_room: Room) -> None:
        started_room.reading_ended(started_room.round_id)

        assert started_room.judge(started_room.round_id, correct=False) is True
        assert started_room.phase == "result"

    def test_reading_中は判定できない(self, started_room: Room) -> None:
        assert started_room.judge(started_room.round_id, correct=True) is False

    def test_古いラウンドなら無視する(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        assert started_room.judge(started_room.round_id - 1, correct=True) is False


class TestRelease:
    def test_解除すると同じ問題へ戻る(self, started_room: Room) -> None:
        question = started_room.question
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)

        assert started_room.release(started_room.round_id) is True
        assert started_room.phase == "reading"
        assert started_room.question is question
        assert started_room.buzzed is None
        assert started_room.judgement is None

    def test_解除してもお手つきは残る(self, started_room: Room) -> None:
        """誤答した人を弾いたまま、他の人に回答権を与えるため。"""
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)
        started_room.release(started_room.round_id)

        assert started_room.players[player_id].locked_out is True

    def test_古いラウンドなら無視する(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        assert started_room.release(started_room.round_id - 1) is False


class TestNextQuestion:
    def test_idle_へ戻る(self, started_room: Room) -> None:
        started_room.next_question()

        assert started_room.phase == "idle"
        assert started_room.question is None
        assert started_room.buzzed is None

    def test_お手つきが解除される(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)
        started_room.next_question()

        assert started_room.players[player_id].locked_out is False

    def test_出題し直してもお手つきは解除される(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)
        started_room.judge(started_room.round_id, correct=False)
        started_room.start_question()

        assert started_room.players[player_id].locked_out is False


class TestStateMessage:
    def test_出題者には問題文と正解を送る(self, started_room: Room) -> None:
        message = started_room.to_state_message(for_host=True)

        assert message.question is not None
        assert message.question.text.startswith("問題")
        assert message.question.answers

    def test_回答者には問題を送らない(self, started_room: Room) -> None:
        """音声より先に問題文が読めると早押しの意味が無くなる。"""
        message = started_room.to_state_message(for_host=False)

        assert message.question is None

    def test_参加者一覧が含まれる(self, started_room: Room) -> None:
        message = started_room.to_state_message(for_host=False)

        assert {player.name for player in message.players} == {"たけ", "はな"}

    def test_buzz_した人が含まれる(self, started_room: Room) -> None:
        player_id = next(iter(started_room.players))
        started_room.buzz(player_id, started_room.round_id)

        message = started_room.to_state_message(for_host=False)

        assert message.buzzed is not None
        assert message.buzzed.player_id == player_id

    def test_同名の連番が反映される(self, room: Room) -> None:
        room.join("たけ", None)
        room.join("たけ", None)

        message = room.to_state_message(for_host=False)

        assert {player.name for player in message.players} == {"たけ (1)", "たけ (2)"}

"""ルームの状態機械。早押し判定の本体。

    idle ──start_question──▶ reading ──buzz──▶ buzzed ──judge──▶ result ──next──▶ idle
                                │  ▲              │
                          reading_ended           └─release（お手つき解除）
                                ▼  └──────────────┘
                             timeUp ──judge──▶ result

サーバの phase は「早押しを受け付けてよいか」を決めるためだけに存在する。
PoC の loading / jingle に当たるものは持たない。前者はクライアント都合、
後者は出題者フロントのローカル演出であり、混ぜると排他ロジックが読めなくなる。

このモジュールは同期メソッドだけで構成し、送信（await）は呼び出し側で行う。
理由は buzz() のコメントを参照。
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from .protocol import (
    BuzzedView,
    BuzzRejectReason,
    JudgementView,
    Phase,
    PlayerView,
    QuestionView,
    RoomStateMessage,
)
from .quiz import Question, pick_random

# 投影画面のレイアウトが崩れない範囲に切る
MAX_NAME_LENGTH = 12


@dataclass
class Player:
    id: str
    name: str
    # 再接続時に同じ player_id へ再バインドするための秘密
    token: str
    connected: bool = True
    # お手つき。同一ラウンドの間だけ早押しを禁じる
    locked_out: bool = False

    def to_view(self) -> PlayerView:
        return PlayerView(
            id=self.id,
            name=self.name,
            connected=self.connected,
            locked_out=self.locked_out,
        )


@dataclass
class BuzzResult:
    """buzz() の結果。accepted が False なら reason が入る。"""

    accepted: bool
    player: Player | None = None
    reason: BuzzRejectReason | None = None


@dataclass
class Room:
    questions: list[Question]

    phase: Phase = "idle"
    # start_question のたびに +1 する。古い buzz を弾くために使う
    round_id: int = 0
    question: Question | None = None
    buzzed: Player | None = None
    judgement: JudgementView | None = None

    players: dict[str, Player] = field(default_factory=dict)
    # token -> player_id。再接続の名寄せに使う
    _tokens: dict[str, str] = field(default_factory=dict)
    _next_player_number: int = 1
    # 直前に出題した問題。同じ問題が連続しないようにするため
    _last_question_id: str | None = None

    # ------------------------------------------------------------ 参加者

    def join(self, name: str, token: str | None) -> Player:
        """参加または再接続する。

        token が既知なら同じ player_id へ再バインドし、名前だけ更新する。
        リロードで別人になってしまうのを防ぐ。
        """
        trimmed = name.strip()[:MAX_NAME_LENGTH] or "名無し"

        if token is not None:
            player_id = self._tokens.get(token)
            if player_id is not None and player_id in self.players:
                player = self.players[player_id]
                player.name = trimmed
                player.connected = True
                return player

        player = Player(
            id=f"p_{self._next_player_number}",
            name=trimmed,
            token=secrets.token_urlsafe(24),
        )
        self._next_player_number += 1
        self.players[player.id] = player
        self._tokens[player.token] = player.id
        return player

    def disconnect(self, player_id: str) -> None:
        """切断を記録する。一覧からは消さない。

        投影画面から名前が消えると出題者が混乱するため。
        buzzed 中に切断しても phase は変えない。会場にその人は居るので
        出題者が手動で判定できる。
        """
        player = self.players.get(player_id)
        if player is not None:
            player.connected = False

    def display_names(self) -> dict[str, str]:
        """投影用の表示名。同名が複数居るときだけ連番を付ける。"""
        counts: dict[str, int] = {}
        for player in self.players.values():
            counts[player.name] = counts.get(player.name, 0) + 1

        seen: dict[str, int] = {}
        names: dict[str, str] = {}
        for player in self.players.values():
            if counts[player.name] == 1:
                names[player.id] = player.name
                continue
            seen[player.name] = seen.get(player.name, 0) + 1
            names[player.id] = f"{player.name} ({seen[player.name]})"
        return names

    # ------------------------------------------------------------ 出題

    def start_question(self, question_id: str | None = None) -> Question | None:
        """出題を始める。ジングルの完了は待たない。

        ジングル中の buzz はサーバが受け付け、出題者フロントがジングルを止めて
        その人を表示すればよい。フライングは会場の判断で処理できる。
        「ジングル完了を待って reading にする」設計は往復が挟まる分だけ
        受付開始の境界が曖昧になる。
        """
        if question_id is not None:
            question = next((q for q in self.questions if q.id == question_id), None)
        else:
            question = pick_random(self.questions, exclude=self._last_question_id)

        if question is None:
            return None

        self.round_id += 1
        self.phase = "reading"
        self.question = question
        self.buzzed = None
        self.judgement = None
        self._last_question_id = question.id

        # ラウンドが変わればお手つきは解除する
        for player in self.players.values():
            player.locked_out = False

        return question

    def buzz(self, player_id: str, round_id: int) -> BuzzResult:
        """早押しを受け付ける。最初の 1 人だけが通る。

        排他について:
        FastAPI/uvicorn の WebSocket ハンドラは単一の asyncio イベントループ上の
        コルーチンで、await の切れ目でしか他へ切り替わらない。したがって
        検証から self.buzzed への代入までを await を挟まずに実行すれば、
        2 人が同時に押しても割り込まれず、asyncio.Lock は要らない。

        !!! このメソッドの中に await を入れてはならない !!!
        入れた瞬間、2 人目が「まだ buzzed が None」の状態で通過しうる。
        送信は呼び出し側で行うこと。

        判定は「サーバがメッセージを受け取った順」であり、クライアントが申告した
        時刻は使わない。端末時計のズレを補正するには NTP 相当の同期が要り、
        「ネットワークによる判定ラグは許容」という前提と釣り合わないため。
        """
        # --- ここから await 禁止 ---
        if round_id != self.round_id:
            return BuzzResult(accepted=False, reason="stale_round")

        # 押し負けたことは wrong_phase ではなく too_late として返す。
        # 1 人目の buzz で phase は buzzed に変わっているため、phase を先に
        # 見ると 2 人目まで wrong_phase になり、回答者の画面に出す文言も
        # 「今は押せない」と「もう押された」で取り違えてしまう。
        if self.buzzed is not None:
            return BuzzResult(accepted=False, reason="too_late")

        if self.phase != "reading":
            return BuzzResult(accepted=False, reason="wrong_phase")

        player = self.players.get(player_id)
        if player is None:
            return BuzzResult(accepted=False, reason="wrong_phase")

        if player.locked_out:
            return BuzzResult(accepted=False, reason="locked_out")

        self.buzzed = player
        self.phase = "buzzed"
        # --- ここまで await 禁止 ---

        return BuzzResult(accepted=True, player=player)

    def reading_ended(self, round_id: int) -> bool:
        """押されないまま読み切った。"""
        if round_id != self.round_id or self.phase != "reading":
            return False
        self.phase = "timeUp"
        return True

    def judge(self, round_id: int, correct: bool) -> bool:
        """出題者が正誤を判定する。

        誤答なら当該回答者をお手つきにする。release で同じ問題を再開できる。
        """
        if round_id != self.round_id or self.phase not in ("buzzed", "timeUp"):
            return False

        if self.buzzed is not None:
            self.judgement = JudgementView(
                player_id=self.buzzed.id,
                name=self.buzzed.name,
                correct=correct,
            )
            if not correct:
                self.buzzed.locked_out = True
        else:
            # 押されずに読み切った場合。判定対象の回答者が居ない
            self.judgement = None

        self.phase = "result"
        return True

    def release(self, round_id: int) -> bool:
        """お手つき解除。誤答者を弾いたまま同じ問題の続きを再開する。"""
        if round_id != self.round_id or self.phase not in ("buzzed", "result"):
            return False
        if self.question is None:
            return False

        self.buzzed = None
        self.judgement = None
        self.phase = "reading"
        return True

    def next_question(self) -> None:
        """出題待ちへ戻す。"""
        self.phase = "idle"
        self.question = None
        self.buzzed = None
        self.judgement = None
        for player in self.players.values():
            player.locked_out = False

    # ------------------------------------------------------------ 配信

    def to_state_message(self, *, for_host: bool) -> RoomStateMessage:
        """現在の状態を組み立てる。

        問題文と正解は出題者にだけ送る。回答者の画面に問題文が出てしまうと
        音声より先に読めてしまい、早押しの意味が無くなる。
        """
        names = self.display_names()

        question_view: QuestionView | None = None
        if for_host and self.question is not None:
            question_view = QuestionView(
                id=self.question.id,
                text=self.question.text,
                audio_url=self.question.audio_url(),
                lab_url=self.question.lab_url(),
                answers=self.question.answers,
            )

        buzzed_view: BuzzedView | None = None
        if self.buzzed is not None:
            buzzed_view = BuzzedView(
                player_id=self.buzzed.id,
                name=names.get(self.buzzed.id, self.buzzed.name),
            )

        return RoomStateMessage(
            round_id=self.round_id,
            phase=self.phase,
            players=[
                PlayerView(
                    id=player.id,
                    name=names.get(player.id, player.name),
                    connected=player.connected,
                    locked_out=player.locked_out,
                )
                for player in self.players.values()
            ],
            buzzed=buzzed_view,
            question=question_view,
            judgement=self.judgement,
        )

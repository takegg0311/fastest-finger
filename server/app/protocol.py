"""WebSocket のメッセージ定義。

全メッセージは {"type": "..."} を持ち、type で判別する（discriminated union）。
この定義が web/src/protocol.ts と対になる。

方針: 状態は差分イベントではなく room_state を丸ごと送る。
再接続が「繋いで最新の room_state を受け取るだけ」で復元でき、
復元用のコードを別途書かずに済む。参加者は十数人・状態は小さいので
帯域は問題にならない。

例外は buzz_accepted で、これだけは音声停止のレイテンシに直結するため
room_state の組み立てを待たず最小ペイロードで先に送る。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------- 共通

Phase = Literal["idle", "reading", "buzzed", "timeUp", "result"]

# 早押しを受け付けなかった理由
BuzzRejectReason = Literal["too_late", "stale_round", "locked_out", "wrong_phase"]


class PlayerView(BaseModel):
    """参加者 1 人の公開情報。"""

    id: str
    name: str
    # 切断しても一覧からは消さない。投影画面から名前が消えると出題者が混乱する。
    connected: bool
    # お手つきで同一ラウンドの早押しを禁じられている
    locked_out: bool


class BuzzedView(BaseModel):
    """回答権を得た参加者。"""

    player_id: str
    name: str


class QuestionView(BaseModel):
    """出題内容。回答者には送らない（問題文を先に見せないため）。"""

    id: str
    text: str
    audio_url: str
    lab_url: str
    # 正解と別解。出題者が手元で確認するために使う
    answers: list[str]


class JudgementView(BaseModel):
    """正誤判定の結果。"""

    player_id: str
    name: str
    correct: bool


# ---------------------------------------------------- クライアント → サーバ


class JoinMessage(BaseModel):
    type: Literal["join"] = "join"
    name: str
    # 再接続時に前回の player_id へ再バインドするための token
    token: str | None = None


class HostHelloMessage(BaseModel):
    type: Literal["host_hello"] = "host_hello"
    host_token: str


class BuzzMessage(BaseModel):
    type: Literal["buzz"] = "buzz"
    round_id: int
    # 端末時計はズレるため判定には使わない。ログ・後日分析用。
    client_sent_at: int | None = None


class StartQuestionMessage(BaseModel):
    type: Literal["start_question"] = "start_question"
    # 省略時はサーバが抽選する
    question_id: str | None = None


class ReadingEndedMessage(BaseModel):
    """押されないまま問題音声を読み切った。出題者フロントが送る。"""

    type: Literal["reading_ended"] = "reading_ended"
    round_id: int


class JudgeMessage(BaseModel):
    type: Literal["judge"] = "judge"
    round_id: int
    correct: bool


class ReleaseMessage(BaseModel):
    """お手つき解除。誤答者を弾いたまま同じ問題を再開する。"""

    type: Literal["release"] = "release"
    round_id: int


class NextMessage(BaseModel):
    type: Literal["next"] = "next"


ClientMessage = Annotated[
    JoinMessage
    | HostHelloMessage
    | BuzzMessage
    | StartQuestionMessage
    | ReadingEndedMessage
    | JudgeMessage
    | ReleaseMessage
    | NextMessage,
    Field(discriminator="type"),
]


# ---------------------------------------------------- サーバ → クライアント


class WelcomeMessage(BaseModel):
    type: Literal["welcome"] = "welcome"
    player_id: str
    # localStorage に保存し、次回の join に載せてもらう
    token: str
    role: Literal["player", "host"]


class RoomStateMessage(BaseModel):
    type: Literal["room_state"] = "room_state"
    round_id: int
    phase: Phase
    players: list[PlayerView]
    buzzed: BuzzedView | None = None
    # 回答者へは None にして送る
    question: QuestionView | None = None
    judgement: JudgementView | None = None


class BuzzAcceptedMessage(BaseModel):
    """最初の 1 人が確定した。音声停止のレイテンシに直結するので最小構成。"""

    type: Literal["buzz_accepted"] = "buzz_accepted"
    round_id: int
    player_id: str
    name: str


class BuzzRejectedMessage(BaseModel):
    type: Literal["buzz_rejected"] = "buzz_rejected"
    round_id: int
    reason: BuzzRejectReason


class ErrorMessage(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


ServerMessage = (
    WelcomeMessage
    | RoomStateMessage
    | BuzzAcceptedMessage
    | BuzzRejectedMessage
    | ErrorMessage
)

"""WebSocket エンドポイント。接続の管理とメッセージの振り分け。

状態遷移そのものは room.py が持ち、ここは「誰が送ってよいメッセージか」の
検証と送信を担当する。

回答者が起こせる遷移は buzz ひとつだけで、他はすべて host_token で弾く。
同一 LAN のクローズドな利用が前提なので、認証は起動時に生成した
host_token 1 本で足りる。オープンネットワークへ出す段になったら見直す。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError
from starlette.websockets import WebSocketState

from .protocol import (
    BuzzAcceptedMessage,
    BuzzRejectedMessage,
    ClientMessage,
    ErrorMessage,
    WelcomeMessage,
)
from .room import Room

logger = logging.getLogger(__name__)

router = APIRouter()

_client_message_adapter: TypeAdapter[ClientMessage] = TypeAdapter(ClientMessage)


class ConnectionManager:
    """接続中のクライアントを保持し、ブロードキャストする。

    出題者と回答者で送る内容が違う（問題文と正解は出題者だけ）ため、
    別々に持つ。
    """

    def __init__(self) -> None:
        # player_id -> WebSocket
        self.players: dict[str, WebSocket] = {}
        self.hosts: set[WebSocket] = set()

    async def send(self, websocket: WebSocket, message: object) -> None:
        """1 件送る。切断済みなら黙って捨てる。"""
        if websocket.client_state is not WebSocketState.CONNECTED:
            return
        try:
            await websocket.send_text(message.model_dump_json())  # type: ignore[attr-defined]
        except (WebSocketDisconnect, RuntimeError):
            # 送信中に切れることは普通に起きる。ここで落とさない
            logger.debug("送信先が切断済みでした", exc_info=True)

    async def broadcast_state(self, room: Room) -> None:
        """全員へ現在の状態を送る。

        差分ではなく丸ごと送るので、受け取った側は上書きするだけでよい。
        """
        host_message = room.to_state_message(for_host=True)
        player_message = room.to_state_message(for_host=False)

        for websocket in list(self.hosts):
            await self.send(websocket, host_message)
        for websocket in list(self.players.values()):
            await self.send(websocket, player_message)

    async def broadcast_raw(self, message: object) -> None:
        """同じ内容を全員へ送る。buzz_accepted のように区別が要らないもの用。"""
        for websocket in list(self.hosts):
            await self.send(websocket, message)
        for websocket in list(self.players.values()):
            await self.send(websocket, message)


def _get_room(websocket: WebSocket) -> Room:
    return websocket.app.state.room


def _get_manager(websocket: WebSocket) -> ConnectionManager:
    return websocket.app.state.connections


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()

    room = _get_room(websocket)
    manager = _get_manager(websocket)
    host_token: str = websocket.app.state.host_token

    # この接続の素性。最初の join / host_hello で決まる
    player_id: str | None = None
    is_host = False

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                message = _client_message_adapter.validate_json(raw)
            except ValidationError:
                await manager.send(
                    websocket,
                    ErrorMessage(code="invalid_message", message="メッセージの形式が不正です。"),
                )
                continue

            match message.type:
                case "join":
                    player = room.join(message.name, message.token)
                    player_id = player.id
                    is_host = False
                    manager.players[player.id] = websocket
                    await manager.send(
                        websocket,
                        WelcomeMessage(player_id=player.id, token=player.token, role="player"),
                    )
                    await manager.broadcast_state(room)

                case "host_hello":
                    if message.host_token != host_token:
                        await manager.send(
                            websocket,
                            ErrorMessage(code="forbidden", message="出題者用トークンが違います。"),
                        )
                        continue
                    is_host = True
                    manager.hosts.add(websocket)
                    await manager.send(
                        websocket,
                        WelcomeMessage(player_id="host", token=host_token, role="host"),
                    )
                    await manager.broadcast_state(room)

                case "buzz":
                    if player_id is None:
                        await manager.send(
                            websocket,
                            ErrorMessage(code="not_joined", message="先に参加してください。"),
                        )
                        continue

                    # 判定は同期的に完了する。詳細は Room.buzz のコメントを参照
                    result = room.buzz(player_id, message.round_id)

                    if not result.accepted or result.player is None:
                        await manager.send(
                            websocket,
                            BuzzRejectedMessage(
                                round_id=message.round_id,
                                reason=result.reason or "wrong_phase",
                            ),
                        )
                        continue

                    # 音声停止のレイテンシに直結するので、状態の組み立てを待たず先に送る
                    display_name = room.display_names().get(
                        result.player.id, result.player.name
                    )
                    await manager.broadcast_raw(
                        BuzzAcceptedMessage(
                            round_id=room.round_id,
                            player_id=result.player.id,
                            name=display_name,
                        )
                    )
                    await manager.broadcast_state(room)

                case "start_question":
                    if not _require_host(is_host):
                        await _deny(manager, websocket)
                        continue
                    if room.start_question(message.question_id) is None:
                        await manager.send(
                            websocket,
                            ErrorMessage(code="no_question", message="出題できる問題がありません。"),
                        )
                        continue
                    await manager.broadcast_state(room)

                case "reading_ended":
                    if not _require_host(is_host):
                        await _deny(manager, websocket)
                        continue
                    if room.reading_ended(message.round_id):
                        await manager.broadcast_state(room)

                case "judge":
                    if not _require_host(is_host):
                        await _deny(manager, websocket)
                        continue
                    if room.judge(message.round_id, message.correct):
                        await manager.broadcast_state(room)

                case "release":
                    if not _require_host(is_host):
                        await _deny(manager, websocket)
                        continue
                    if room.release(message.round_id):
                        await manager.broadcast_state(room)

                case "next":
                    if not _require_host(is_host):
                        await _deny(manager, websocket)
                        continue
                    room.next_question()
                    await manager.broadcast_state(room)

    except WebSocketDisconnect:
        pass
    finally:
        if is_host:
            manager.hosts.discard(websocket)
        if player_id is not None:
            # 同じ player_id で新しい接続に差し替わっている場合は消さない
            if manager.players.get(player_id) is websocket:
                del manager.players[player_id]
            room.disconnect(player_id)
            await manager.broadcast_state(room)


def _require_host(is_host: bool) -> bool:
    return is_host


async def _deny(manager: ConnectionManager, websocket: WebSocket) -> None:
    await manager.send(
        websocket,
        ErrorMessage(code="forbidden", message="この操作は出題者のみ行えます。"),
    )

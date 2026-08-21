"""プロバイダの共通契約とエラーの正規化。

各社の SDK は例外の型も文言もばらばらだが、画面に出したいのは
「認証で弾かれた」「レート制限」「繋がらない」「時間切れ」程度の粒度である。
ここで分類を 1 本にまとめ、プロバイダ実装は自社の例外をこれへ写すだけにする。

プロバイダを追加する場合は Provider を継承し、REGISTRY へ登録する。
プロンプトと応答パーサは共通のものを使い、社ごとの調整はしない
（社ごとに変えると予測精度の比較が公平でなくなるため）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

ErrorKind = Literal["auth", "rate_limit", "timeout", "network", "bad_request", "unknown"]


@dataclass
class ProviderError(Exception):
    """プロバイダ呼び出しの失敗。画面に出す粒度まで正規化したもの。"""

    kind: ErrorKind
    message: str

    def __str__(self) -> str:
        return self.message


class Provider(ABC):
    """1 社ぶんの接続。

    vendor は API とフロントで使う識別子、label は画面に出す表示名。
    models はコード内の定数として持つ。各社の models API を叩く動的取得は
    PoC には過剰なため採らない。
    """

    vendor: str
    label: str
    models: tuple[str, ...]
    #: API キーを読む環境変数名
    env_key: str

    @abstractmethod
    async def complete(self, prompt: str, model: str) -> str:
        """プロンプトを投げ、応答の本文をそのまま返す。

        JSON への解釈は呼び出し側（parser）が行う。ここで整形すると
        応答フォーマット違反を観測できなくなるため、生の文字列を返すこと。

        失敗した場合は ProviderError を送出する。
        """
        raise NotImplementedError

"""xAI Grok プロバイダ。

xAI の API は OpenAI 互換のため、SDK も呼び出し手順も OpenAI と同一で、
差分は接続先（base_url）と読むキーの環境変数だけである。
そこで OpenAIProvider を継承し、差分をクラス属性で差し替える形にした。

共通処理を関数へ切り出して両者から呼ぶ案も検討したが、社ごとに違うのは
呼び出しの「手順」ではなく「宛先」というデータだけであり、切り出しても
関数と 2 つの薄いクラスに分かれるだけで読む場所が増える。将来 xAI 側だけ
仕様がずれたら、その時点で complete() を上書きすれば済む。

response_format による JSON 強制を使わないのは OpenAI 側と同じ理由
（応答フォーマット違反の観測がこの PoC の目的の一つであるため）。
"""

from __future__ import annotations

from .base import ProviderError
from .openai_provider import OpenAIProvider

#: xAI の OpenAI 互換エンドポイント。ここだけが OpenAI との接続上の差分。
BASE_URL = "https://api.x.ai/v1"

# grok-4 系はいずれも 2026-08-15 に提供終了となったため、現行の
# grok-4.6（最上位）と grok-4.3（安価な汎用）の 2 つを採る。
# OpenAI の gpt-5 / gpt-5-mini と同じく「最上位と軽量」の組で揃える。
MODELS = ("grok-4.6", "grok-4.3")

#: キー不正の 400 を見分ける手がかり。xAI は機械可読な識別子を返さない。
_MISCLASSIFIED_AUTH = "Incorrect API key"


class XaiProvider(OpenAIProvider):
    vendor = "xai"
    label = "xAI Grok"
    models = MODELS
    env_key = "XAI_API_KEY"
    base_url = BASE_URL

    async def complete(self, prompt: str, model: str) -> str:
        try:
            return await super().complete(prompt, model)
        except ProviderError as error:
            raise _reclassify(error) from error


def _reclassify(error: ProviderError) -> ProviderError:
    """xAI 固有のエラー分類の差を吸収する。

    xAI はキーが不正でも 401 ではなく 400 を返すため、OpenAI 用の分類を
    そのまま通すと bad_request になり、画面から「キーが違う」と分からない。

    xAI の 400 応答には Gemini の `reason` にあたる機械可読な識別子が無く、
    本文の文言で見るしかない。文言が変わればここは効かなくなるが、その場合も
    bad_request として出るだけで、握り潰しにはならない。
    """
    if error.kind != "bad_request" or _MISCLASSIFIED_AUTH not in error.message:
        return error

    # 元の message は OpenAI 用の「リクエストが受け付けられませんでした」で
    # 始まっている。前置きを重ねると二重になるので、原文だけを載せ替える。
    _, _, detail = error.message.partition(": ")
    return ProviderError("auth", f"認証に失敗しました: {detail or error.message}")

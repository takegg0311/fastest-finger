"""Google Gemini プロバイダ。

response_schema / response_mime_type による JSON 強制は使わない。応答
フォーマット違反の観測がこの PoC の目的の一つであり、強制すると違反が
起きなくなるため（OpenAI で response_format を使わないのと同じ理由）。
"""

from __future__ import annotations

from .base import Provider, ProviderError
from .config import REQUEST_TIMEOUT_SECONDS, api_key

MODELS = ("gemini-2.5-pro", "gemini-2.5-flash")

# google-genai の HttpOptions.timeout はミリ秒指定（int）で、SDK 内部で
# 1000 で割って httpx へ渡している。config の秒（float）と単位が違うため
# ここで変換する。
_TIMEOUT_MILLISECONDS = int(REQUEST_TIMEOUT_SECONDS * 1000)


class GeminiProvider(Provider):
    vendor = "google"
    label = "Gemini"
    models = MODELS
    env_key = "GEMINI_API_KEY"

    async def complete(self, prompt: str, model: str) -> str:
        key = api_key(self.env_key)
        if key is None:
            raise ProviderError("auth", f"{self.env_key} が設定されていません")

        # SDK の import はここで行う。未インストールでもサーバ全体は
        # 起動できるようにし、health で理由を返せるようにするため。
        try:
            from google import genai
        except ImportError as error:  # pragma: no cover - 依存が入っていれば通らない
            raise ProviderError(
                "unknown", f"google-genai SDK を読み込めません: {error}"
            ) from error

        client = genai.Client(
            api_key=key,
            http_options={"timeout": _TIMEOUT_MILLISECONDS},
        )

        try:
            response = await client.aio.models.generate_content(
                model=model,
                contents=prompt,
            )
        except Exception as error:  # noqa: BLE001 - SDK の例外を正規化して返す
            raise _normalize(error) from error

        # text は「全テキストパートの連結」で、テキストパートが無ければ None。
        # safety でブロックされた場合などがこれにあたる。
        text = response.text
        return text if text is not None else ""


def _normalize(error: Exception) -> ProviderError:
    """google-genai の例外を、画面に出す粒度へ写す。

    google-genai は OpenAI SDK と違い API 由来の失敗を APIError（と
    ClientError / ServerError の 2 分割）にまとめており、認証もレート制限も
    型では区別できない。そのため API 由来のものは HTTP ステータスで分類する。

    一方タイムアウトと接続断は SDK が包まず httpx の例外のまま抜けてくるので、
    こちらは型名で判定する。SDK の例外クラスを import せず名前で見るのは、
    SDK のバージョン差で import に失敗しても分類を続けられるようにするため
    （openai_provider._normalize と同じ方針）。
    """
    name = type(error).__name__
    message = str(error) or name

    # httpx.ConnectTimeout / ReadTimeout などは TimeoutException を継承する。
    # 継承関係が使えないので、接尾辞で拾う。
    if name.endswith("TimeoutException") or name.endswith("Timeout"):
        return ProviderError("timeout", f"応答がタイムアウトしました（{REQUEST_TIMEOUT_SECONDS:.0f} 秒）")
    if name.endswith("ConnectError"):
        return ProviderError("network", f"接続できませんでした: {message}")

    # APIError は code に HTTP ステータスを持つ。型を import せずに済ませたいので
    # 属性の有無で判定する。
    code = getattr(error, "code", None)
    if isinstance(code, int):
        # Gemini はキーが不正でも 401 ではなく 400 INVALID_ARGUMENT を返す。
        # ステータスだけで見ると bad_request になり、画面から「キーが違う」と
        # 分からなくなるため、details の reason で先に拾う。
        # 文言ではなく機械可読な識別子を見るので、メッセージの変更には影響されない。
        if _is_invalid_api_key(error):
            return ProviderError("auth", f"認証に失敗しました: {message}")
        if code in (401, 403):
            return ProviderError("auth", f"認証に失敗しました: {message}")
        if code == 429:
            return ProviderError("rate_limit", f"レート制限に達しました: {message}")
        if code in (400, 404):
            return ProviderError("bad_request", f"リクエストが受け付けられませんでした: {message}")

    return ProviderError("unknown", message)


def _is_invalid_api_key(error: Exception) -> bool:
    """キー不正による 400 かどうか。

    Gemini は details に `reason: "API_KEY_INVALID"` を載せてくるので、
    それを探す。details の形は APIError.details（dict）に入るが、
    SDK のバージョンで欠けることもあるため、無ければ False に倒して
    通常の bad_request として扱う。
    """
    details = getattr(error, "details", None)
    if not isinstance(details, dict):
        return False

    entries = details.get("error", {}).get("details", [])
    if not isinstance(entries, list):
        return False

    return any(
        isinstance(entry, dict) and entry.get("reason") == "API_KEY_INVALID"
        for entry in entries
    )

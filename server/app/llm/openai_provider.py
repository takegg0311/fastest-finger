"""OpenAI プロバイダ。

OpenAI 互換 API を提供する社（xAI など）はこれを継承し、base_url と
env_key だけを差し替える。complete() が接続先を self.base_url から取るのは
そのためで、OpenAI 自身は None のまま SDK の既定へ繋ぐ。

response_format による JSON 強制は使わない。応答フォーマット違反の観測が
この PoC の目的の一つであり、強制すると違反が起きなくなるため。
"""

from __future__ import annotations

from .base import Provider, ProviderError
from .config import REQUEST_TIMEOUT_SECONDS, api_key

MODELS = ("gpt-5", "gpt-5-mini")


class OpenAIProvider(Provider):
    vendor = "openai"
    label = "OpenAI"
    models = MODELS
    env_key = "OPENAI_API_KEY"
    #: 接続先。OpenAI 互換 API の社（xAI など）が継承して差し替えるための口で、
    #: None なら SDK の既定（OpenAI 本家）へ繋ぐ。誤って別社のキーを
    #: OpenAI へ送らないよう、宛先は必ずここから決めること。
    base_url: str | None = None

    async def complete(self, prompt: str, model: str) -> str:
        key = api_key(self.env_key)
        if key is None:
            raise ProviderError("auth", f"{self.env_key} が設定されていません")

        # SDK の import はここで行う。未インストールでもサーバ全体は
        # 起動できるようにし、health で理由を返せるようにするため。
        try:
            from openai import AsyncOpenAI
        except ImportError as error:  # pragma: no cover - 依存が入っていれば通らない
            raise ProviderError("unknown", f"openai SDK を読み込めません: {error}") from error

        client = AsyncOpenAI(
            api_key=key, timeout=REQUEST_TIMEOUT_SECONDS, base_url=self.base_url
        )

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as error:  # noqa: BLE001 - SDK の例外を正規化して返す
            raise _normalize(error) from error

        choices = response.choices
        if not choices:
            raise ProviderError("unknown", "応答に choices が含まれていません")

        content = choices[0].message.content
        return content if content is not None else ""


def _normalize(error: Exception) -> ProviderError:
    """OpenAI SDK の例外を、画面に出す粒度へ写す。

    OpenAI 互換 API の社も同じ SDK の例外型で失敗するため、継承先から
    そのまま使える。文言に社名を入れていないのはこのためである。

    SDK の例外クラスを直接 import せず名前で判定するのは、
    SDK のバージョン差で import に失敗しても分類を続けられるようにするため。
    """
    name = type(error).__name__
    message = str(error) or name

    if name == "AuthenticationError" or name == "PermissionDeniedError":
        return ProviderError("auth", f"認証に失敗しました: {message}")
    if name == "RateLimitError":
        return ProviderError("rate_limit", f"レート制限に達しました: {message}")
    if name == "APITimeoutError":
        return ProviderError("timeout", f"応答がタイムアウトしました（{REQUEST_TIMEOUT_SECONDS:.0f} 秒）")
    if name == "APIConnectionError":
        return ProviderError("network", f"接続できませんでした: {message}")
    if name in ("BadRequestError", "NotFoundError", "UnprocessableEntityError"):
        return ProviderError("bad_request", f"リクエストが受け付けられませんでした: {message}")

    return ProviderError("unknown", message)

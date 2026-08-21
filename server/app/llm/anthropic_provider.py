"""Anthropic Claude プロバイダ。

tool use による構造化は使わない。応答フォーマット違反の観測が
この PoC の目的の一つであり、強制すると違反が起きなくなるため。
"""

from __future__ import annotations

from typing import Any

from .base import Provider, ProviderError
from .config import REQUEST_TIMEOUT_SECONDS, api_key

MODELS = ("claude-opus-5", "claude-sonnet-5")

# Anthropic は OpenAI と違い max_tokens が必須。
# この用途の応答は continuation と answer だけの短い JSON なので、
# 打ち切られない範囲で小さく取る。大きくしても課金は実出力分だが、
# 上限を絞ることで暴走した長文応答を早めに止められる。
MAX_TOKENS = 1024


class AnthropicProvider(Provider):
    vendor = "anthropic"
    label = "Claude"
    models = MODELS
    env_key = "ANTHROPIC_API_KEY"

    async def complete(self, prompt: str, model: str) -> str:
        key = api_key(self.env_key)
        if key is None:
            raise ProviderError("auth", f"{self.env_key} が設定されていません")

        # SDK の import はここで行う。未インストールでもサーバ全体は
        # 起動できるようにし、health で理由を返せるようにするため。
        try:
            from anthropic import AsyncAnthropic
        except ImportError as error:  # pragma: no cover - 依存が入っていれば通らない
            raise ProviderError("unknown", f"anthropic SDK を読み込めません: {error}") from error

        client = AsyncAnthropic(api_key=key, timeout=REQUEST_TIMEOUT_SECONDS)

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                # Claude は extended thinking が既定で有効だが、この PoC では
                # 応答時間そのものが観測対象であり、思考が入ると他社と比較に
                # ならないほど遅くなる。そのため思考量を最小に抑える。
                # thinking={"type": "disabled"} でも同じことはできるが、
                # effort が high の場合に拒否される組み合わせがあり脆いため、
                # 単独で成立する effort 指定のほうを採る。
                output_config={"effort": "low"},
                # temperature / top_p / top_k は Opus 5 / Sonnet 5 では
                # 廃止されており、送ると 400 になるため渡さない。
            )
        except Exception as error:  # noqa: BLE001 - SDK の例外を正規化して返す
            raise _normalize(error) from error

        return _extract_text(response.content)


def _extract_text(blocks: Any) -> str:
    """content block の並びから本文だけを連結する。

    content[0] を決め打ちしないのは、thinking など text 以外のブロックが
    先頭に混ざりうるため。type を見て text のものだけを拾う。
    """
    if not blocks:
        raise ProviderError("unknown", "応答に content が含まれていません")

    texts = [getattr(block, "text", "") for block in blocks if getattr(block, "type", None) == "text"]
    return "".join(texts)


def _normalize(error: Exception) -> ProviderError:
    """Anthropic SDK の例外を、画面に出す粒度へ写す。

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

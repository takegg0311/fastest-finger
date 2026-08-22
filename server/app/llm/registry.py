"""プロバイダの一覧。

未実装の社もプレースホルダとして並べる。health が 4 社を常に返すことで、
PoC 側は「実装済みかどうか」を知らずに済み、後続の Issue で社が増えても
フロントを直さずにセレクトボックスへ現れる。
"""

from __future__ import annotations

from dataclasses import dataclass

from .anthropic_provider import AnthropicProvider
from .base import Provider
from .config import api_key
from .openai_provider import OpenAIProvider


@dataclass(frozen=True)
class Planned:
    """まだ実装していない社。health に理由付きで並べるためだけに使う。"""

    vendor: str
    label: str
    issue: str


# 実装済みのプロバイダ
PROVIDERS: tuple[Provider, ...] = (OpenAIProvider(), AnthropicProvider())

# 未実装の社。担当 Issue が終わり次第 PROVIDERS へ移す。
PLANNED: tuple[Planned, ...] = (
    Planned("google", "Gemini", "#16"),
    Planned("xai", "xAI Grok", "#17"),
)


def find(vendor: str) -> Provider | None:
    for provider in PROVIDERS:
        if provider.vendor == vendor:
            return provider
    return None


def health_view() -> list[dict[str, object]]:
    """health のレスポンス本体。実装済みと未実装をこの順で並べる。"""
    views: list[dict[str, object]] = []

    for provider in PROVIDERS:
        available = api_key(provider.env_key) is not None
        view: dict[str, object] = {
            "vendor": provider.vendor,
            "label": provider.label,
            "available": available,
            "models": list(provider.models) if available else [],
        }
        if not available:
            view["reason"] = f"{provider.env_key} が設定されていません"
        views.append(view)

    for planned in PLANNED:
        views.append(
            {
                "vendor": planned.vendor,
                "label": planned.label,
                "available": False,
                "models": [],
                "reason": f"未実装（{planned.issue}）",
            }
        )

    return views

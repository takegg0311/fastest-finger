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
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider


@dataclass(frozen=True)
class Planned:
    """まだ実装していない社。health に理由付きで並べるためだけに使う。"""

    vendor: str
    label: str
    issue: str


# 実装済みのプロバイダ
PROVIDERS: tuple[Provider, ...] = (
    OpenAIProvider(),
    AnthropicProvider(),
    GeminiProvider(),
)

# 未実装の社。担当 Issue が終わり次第 PROVIDERS へ移す。
PLANNED: tuple[Planned, ...] = (
    Planned("xai", "xAI Grok", "#17"),
)

# health に並べる順。実装済みを先に出すと、社が実装されるたびに PoC の
# セレクトボックスの並びが入れ替わってしまう。並びは実装状況ではなく
# この定数で固定し、実装の有無は available だけで表す。
DISPLAY_ORDER: tuple[str, ...] = ("openai", "anthropic", "google", "xai")


def find(vendor: str) -> Provider | None:
    for provider in PROVIDERS:
        if provider.vendor == vendor:
            return provider
    return None


def health_view() -> list[dict[str, object]]:
    """health のレスポンス本体。DISPLAY_ORDER の順に全社を並べる。"""
    views: list[dict[str, object]] = []

    for vendor in DISPLAY_ORDER:
        provider = find(vendor)
        if provider is not None:
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
            continue

        planned = _find_planned(vendor)
        if planned is None:  # pragma: no cover - DISPLAY_ORDER の書き漏らし
            continue
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


def _find_planned(vendor: str) -> Planned | None:
    for planned in PLANNED:
        if planned.vendor == vendor:
            return planned
    return None

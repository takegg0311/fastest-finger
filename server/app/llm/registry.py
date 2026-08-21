"""プロバイダの一覧。

未実装の社もプレースホルダとして並べる。health が 4 社を常に返すことで、
PoC 側は「実装済みかどうか」を知らずに済み、後続の Issue で社が増えても
フロントを直さずにセレクトボックスへ現れる。
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Provider
from .config import api_key
from .openai_provider import OpenAIProvider
from .xai_provider import XaiProvider


@dataclass(frozen=True)
class Planned:
    """まだ実装していない社。health に理由付きで並べるためだけに使う。"""

    vendor: str
    label: str
    issue: str


# 実装済みのプロバイダ
PROVIDERS: tuple[Provider, ...] = (OpenAIProvider(), XaiProvider())

# 未実装の社。担当 Issue が終わり次第 PROVIDERS へ移す。
PLANNED: tuple[Planned, ...] = (
    Planned("anthropic", "Claude", "#15"),
    Planned("google", "Gemini", "#16"),
)

# health に並べる順。実装の有無で順番が動くと PoC の 4 枠も動いてしまうため、
# 実装済み / 未実装とは切り離してここで固定する。社が実装されるたびに
# 画面の並びが入れ替わると、続けて遊ぶ利用者が枠を取り違えるため。
DISPLAY_ORDER: tuple[str, ...] = ("openai", "anthropic", "google", "xai")


def find(vendor: str) -> Provider | None:
    for provider in PROVIDERS:
        if provider.vendor == vendor:
            return provider
    return None


def health_view() -> list[dict[str, object]]:
    """health のレスポンス本体。DISPLAY_ORDER の順に 4 社を並べる。"""
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

    # DISPLAY_ORDER に無い社は末尾へ回す。並び順の更新漏れで
    # 社が health から消えてしまうより、順番が崩れるほうが軽いため。
    def rank(view: dict[str, object]) -> int:
        vendor = view["vendor"]
        if vendor in DISPLAY_ORDER:
            return DISPLAY_ORDER.index(vendor)  # type: ignore[arg-type]
        return len(DISPLAY_ORDER)

    views.sort(key=rank)
    return views

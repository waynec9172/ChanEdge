"""config_hash. Canonical JSON lives in domain.canon so ids share one formatter."""

from __future__ import annotations

import hashlib

from chanedge.config.model import Settings
from chanedge.domain.canon import canonical_json

__all__ = ["canonical_json", "config_hash"]


def config_hash(settings: Settings) -> str:
    """sha256 hex of the settings fields that are allowed to change a decision id."""
    payload = _hash_payload(settings)
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _hash_payload(settings: Settings) -> dict[str, object]:
    universe = settings.universe.model_dump(mode="python")
    universe.pop("pin", None)
    risk = settings.risk.model_dump(mode="python")
    risk.pop("initial_equity_quote", None)
    market = settings.marketdata
    execution = settings.execution
    return _with_systemone({
        "runtime": {
            "venue": settings.runtime.venue,
            "product": settings.runtime.product,
        },
        "universe": universe,
        "marketdata": {
            "windows": market.windows,
            "max_gap_bars": market.max_gap_bars,
            "stale_grace_seconds": market.stale_grace_seconds,
            "closed_bars_only": market.closed_bars_only,
        },
        "chanlun": settings.chanlun.model_dump(mode="python"),
        "features": settings.features.model_dump(mode="python"),
        "volatility": settings.volatility.model_dump(mode="python"),
        "session": settings.session.model_dump(mode="python"),
        "jev": settings.jev.model_dump(mode="python"),
        "risk": risk,
        "execution": {
            "fee_bps": execution.fee_bps,
            "slippage_bps": execution.slippage_bps,
            "fill_model": execution.fill_model,
            "order_type": execution.order_type,
            "position_mode": execution.position_mode,
            "margin_mode": execution.margin_mode,
        },
    }, settings)


def _with_systemone(payload: dict[str, object], settings: Settings) -> dict[str, object]:
    systemone = settings.systemone
    if not systemone.enabled:
        return payload
    payload["systemone"] = {
        "enabled": True,
        "model_pin": systemone.model_pin,
        "question_set": systemone.question_set,
    }
    return payload

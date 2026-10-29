"""feature_version. This is not engine_version or marketdata_version.

Decimal inference stays on marketdata_version. config_hash does not include
this string. The caller passes it into decision_id.
"""

from __future__ import annotations

FEATURE_VERSION = (
    "feature-v1"
    "|prior-high-low-are-bi-endpoints-only"
    "|missing-prior-high-or-low-skips-0.20-penalty"
    "|second-buy-sell-loc-uses-dist-defending-atr"
    "|zhongshu-absent-clarity-term-0.5"
    "|vol-tent-peak-is-symbol-atr-pct-p50"
)

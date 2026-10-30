"""engine_version. This is not marketdata_version.

PR-6 extends this string when signals start to emit. Decimal inference stays
on marketdata_version. config_hash does not include this string.
"""

from __future__ import annotations

ENGINE_VERSION = (
    "engine-v1"
    "|zhongshu-zg-zd-frozen-when-third-bi-endpoint-replaced"
    "|outside-bi-stays-out-closed-zhongshu-stays-closed"
    "|zg-le-zd-drop-earliest-keep-later-two-consumed-no-revive"
    "|second-buy-sell-no-first-class-point"
    "|third-buy-sell-no-reemit-on-endpoint-replace-keep-fields-except-related-bi-id"
    "|second-buy-sell-reemit-on-new-confirm-bar-when-price-holds-no-cap"
    "|fenxing-confirms-on-first-raw-bar-of-right-merged-bar"
)

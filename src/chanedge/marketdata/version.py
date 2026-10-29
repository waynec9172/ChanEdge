"""marketdata_version. This is not engine_version.

Change the string when vision paths, the symbol filter, the quote_volume <= 0
skip, or CSV-text decimal inference change. decision_id picks the string up
through the caller. config_hash does not.
"""

from __future__ import annotations

MARKETDATA_VERSION = (
    "marketdata-v1"
    "|vision-um-klines-monthly-else-daily"
    "|fundingRate-monthly-csv"
    "|symbol-endswith-USDT-no-underscore-exclude-bases"
    "|skip-quote-volume-le-0"
    "|csv-text-decimal-inference"
)

"""Read-only chart monitor (Phase 2, PR-13).

`python -m chanedge.monitor` serves chart_frames from the paper ledger on
127.0.0.1. It imports domain and journal only: no chanlun, jev, risk, or
execution, and no order route.

static/lightweight-charts.standalone.production.js is TradingView Lightweight
Charts v4.2.3, Apache-2.0 (static/LICENSE.lightweight-charts). The npm tarball
matched the registry integrity sha512-5kS/2hY3wNYNzhnS8Gb+GAS07DX8GPF2YVDnd2NMC85gJVQ6RLU6YrXNgNJ6eg0AnWPwCnvaGtYmGky3HiLQEw==.
"""

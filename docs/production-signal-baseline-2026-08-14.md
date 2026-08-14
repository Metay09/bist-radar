# Production Signal Baseline — 2026-08-14 21:35 Europe/Istanbul

Captured read-only from the BIST Radar production PostgreSQL database before migration `0009`.
No production rows were inserted, updated, deleted, or synthesized for this snapshot.

| Metric | Count |
|---|---:|
| Total / unique Radar signals | 1041 / 1041 |
| Unique symbols | 409 |
| Signals today / previous session | 732 / 290 |
| Pending / partial / completed | 25 / 752 / 264 |
| 15m / 30m / 60m / 120m mature | 1016 / 1001 / 958 / 898 |
| EOD / next-day mature | 971 / 309 |
| MFE / MAE available | 1016 / 1016 |
| Trade-plan snapshot / legacy missing | 732 / 309 |
| Legacy conservative stop-first | 131 |
| Legacy reference-price +1% / +2% / +3% touch | 505 / 324 / 221 |
| Market bars / outcome rows | 159583 / 6246 |
| Shadow observations / fully labeled | 1041 / 264 |
| Datasets / models / evaluations / predictions | 0 / 0 / 0 / 0 |

The pre-milestone target counters were generic reference-price percentage touches, not immutable
trade-plan H1/H2/H3 events. They are retained as legacy evidence but must not be presented as plan
target truth. Migration `0009` begins persisted plan-level first-hit tracking without inventing it for
the 309 signals that lack a plan snapshot.

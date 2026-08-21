# Radar execution and coherent-read acceptance — 2026-08-21

## Scope

This acceptance closes the previously uncommitted BIST executable-price, intraday RVOL,
candidate-ranking and coherent dashboard read work. Live order routing remains absent and all
execution remains paper/research-only.

## Exchange-price rules

The equity tick table in `app.market.bist` matches the Borsa İstanbul Pay Market table published
in the official 2026 Pay Market Procedure: 0.01 below TRY 20; 0.02 at 20–49.99; 0.05 at
50–99.99; 0.10 at 100–249.99; 0.25 at 250–499.99; 0.50 at 500–999.99; 1.00 at
1,000–2,499.99; and 2.50 from 2,500. Directional normalization is conservative: entries and
breakout triggers round up, stops and targets round down, and risk/reward is recomputed from
normalized levels.

Official source: https://www.borsaistanbul.com/files/pay-piyasasi-proseduru.pdf

## Score-distribution evidence

A read-only comparison used 80 candidates in the last persisted production scan before the new
worker was deployed. The stored score distribution was 47 at 70–79, 25 at 80–89 and 8 at
90–100 (mean 79.58). Re-evaluation with the completed de-saturation/RVOL-quality policy produced
57 below 70 and 23 at 70–79 (mean 65.30; maximum absolute change 34 points).

This is an intentional recalibration, not a backward-compatible presentation change. Correlated
positive indicators no longer saturate setup quality and RVOL earns no volume points without at
least five prior observations for the same Europe/Istanbul session slot. The production candidate
threshold remains 70; no threshold was relaxed to restore the old candidate count.

## Coherent dashboard read

`GET /dashboard/opportunities` returns one immutable read model containing `snapshot_id`,
`data_timestamp`, candidate fields and the backend-owned trade plan. Candidate rows can still be
painted from the faster candidate endpoint, but the frontend exposes plan levels only when the
candidate and plan timestamps identify the same completed observation. A mismatch is rendered as
`Plan güncelleniyor`; it cannot create a financial verdict.

All recent lows are selected with one bounded window query (ten per symbol). The opportunity and
legacy trade-plan endpoints therefore do not issue one query per candidate. Dashboard endpoint
latency is logged, returned in `Server-Timing`, and summarized over the latest 500 in-process
observations by `GET /dashboard/latency`.

## Safety invariants

- Shadow output cannot change Radar, plans, paper fills or outcomes.
- Adaptive remains a paper/research challenger.
- No frontend financial calculation was introduced.
- No live broker/order capability was introduced.
- Existing persisted plans and outcomes are not rewritten.

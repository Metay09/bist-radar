# Frontend feature inventory

| Feature | Previous page / API | New page / component | Status |
|---|---|---|---|
| Market status, freshness, completed bar, coverage | Radar; summary + universe | Radar header and coverage strip | IMPROVED |
| Candidate search and strength filters | Radar; candidates | Radar opportunity center | PRESERVED |
| Radar, RVOL, momentum and classification | Radar; candidates | Decision-first table/mobile card | IMPROVED |
| Trade plan action, entry, stop, targets, R/R | Radar/detail; trade-plans | Candidate quick levels + symbol summary | IMPROVED |
| Candidate sort | Radar score | Importance, Radar, RVOL, momentum, R/R, recency, distance | IMPROVED |
| Adaptive decision and persisted events | Symbol; adaptive-decision | Symbol decision hero + lifecycle tab | RELOCATED |
| Candlestick and backend plan levels | Symbol; detail | Symbol chart tab | PRESERVED |
| Symbol technical overview | Symbol; detail | Summary tab | RELOCATED |
| Persisted signal results and MFE/MAE | Symbol/signals; history/results | Symbol history + global History | PRESERVED |
| Shadow status and calibrated display guard | Symbol/Analysis; shadow | Research tab / Quant evidence | RELOCATED |
| Daily signal scorecard and filters | Signals; daily/history | History | RELOCATED |
| Paper portfolio and trades | Portfolio; performance/trades | Tracking lower section; `/portfolio` alias | RELOCATED |
| Setup tracking groups | Signals + persisted lifecycle | Tracking | IMPROVED |
| Score-bucket results | Analysis; analytics/scores | Analysis | PRESERVED |
| Evidence, model maturity and edge verdicts | Analysis; research/evidence | Analysis / Quant evidence | PRESERVED |
| API, DB, provider, scan and universe health | System; system/summary/universe | System operations board | PRESERVED |
| Product tour and paper-only notice | Global shell | Global shell | PRESERVED |
| Back-navigation search/filter/scroll state | Radar session state | Radar session state | PRESERVED |

The frontend implements no financial formula, Radar score behavior, Adaptive state transition,
outcome label, Shadow inference, or governance threshold; those remain backend-owned.

## Recorded technical debt

- `frontend/src/App.tsx` remains an approximately 61 KB monolith. Page and
  business-component extraction belongs in a future architecture milestone, not
  this quality closeout.
- `frontend/src/styles/legacy.css` remains the compatibility layer for existing
  selectors. Consolidating it into the tokenized component styles belongs in a
  future CSS architecture milestone.
# Radar execution and ranking invariants

- Backend trade-plan prices are executable BIST equity prices. Entry-zone low and stops
  round down; entry-zone high and breakout triggers round up; targets round down so tick
  conversion cannot improve advertised risk/reward. R/R is recomputed from these normalized
  levels. The frontend only localizes the returned decimal value; it does not derive prices.
- Radar Score measures setup quality, not immediate executability. `action_state` is evaluated
  independently on every completed market update. Default ranking is action-first
  (`BREAKOUT_ONAYI`, `GIRIS_BOLGESINDE`, waiting, chased, invalid), then proximity/freshness and
  score. A READY 81 therefore ranks ahead of a WAITING 94.
- Intraday RVOL is the completed 15-minute bar volume divided by the mean of up to 20 prior,
  positive-volume observations for the same `Europe/Istanbul` session slot. At least five
  observations are required. Insufficient history produces RVOL 0 with
  `rvol_quality=INSUFFICIENT_DATA` and earns no volume score; it is never replaced by an
  across-slot rolling average. `rvol_baseline`, `rvol_sample_size`, and `rvol_is_outlier` make
  exceptional values auditable.
- Candidate symbols are canonicalized (`SELEC.IS`, `BIST:SELEC` → `SELEC`) and merged before API
  serialization. The deterministic winner is actionable first, then newest, score and data
  confidence; all contributing strategy identifiers are retained in `matched_strategies`.

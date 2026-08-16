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

No financial formula, Radar score behavior, Adaptive state transition, outcome label,
Shadow inference, or governance threshold is implemented or changed by this UI work.

## Recorded technical debt

- `frontend/src/App.tsx` remains an approximately 61 KB monolith. Page and
  business-component extraction belongs in a future architecture milestone, not
  this quality closeout.
- `frontend/src/styles/legacy.css` remains the compatibility layer for existing
  selectors. Consolidating it into the tokenized component styles belongs in a
  future CSS architecture milestone.

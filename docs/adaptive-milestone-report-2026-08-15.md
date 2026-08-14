# Adaptive Trade Decision Engine — Milestone Report

Date: 2026-08-15  
Mode: paper research; live trading disabled

## Current policy

- Champion: `static-entry-v2` (preserved; no historical overwrite)
- Challenger: `adaptive-v1-h1-partial-trailing`
- Promotion: not authorized and not performed
- OOS conclusion: insufficient comparable terminal windows; no improvement claim

## Production replay snapshot

The replay used persisted production symbols and their available completed bars. It did not insert synthetic production outcomes.

- Planned adaptive setups: 731
- Entry activated: 64 (8.76%)
- Open/non-terminal: 84
- No-entry decay: 232
- No-entry structure: 222
- No-entry expired: 15
- Chased: 130
- Stop before H1: 20
- Time exit loss/flat/profit: 10/2/16
- H1 touch events: 2
- H2/H3 touch events: 0/0
- Median time to entry: 30 minutes
- Median time to H1: 105 minutes
- Mean realized R after configured cost: -0.1725 R
- Median realized R after configured cost: -0.5020 R

These figures describe this replay only. They do not establish out-of-sample superiority.

## Model heads

All heads remain shadow-only and cannot change Radar actions.

| Head | Conditional sample | Test ROC-AUC | Test Brier | Display status | Edge |
| --- | ---: | ---: | ---: | --- | --- |
| Entry before expiry | 520 | 0.514 | 0.293 | Uncalibrated shadow score | No |
| Stop before H1, given entry | 242 | 0.533 | 0.410 | Uncalibrated shadow score | No |
| H1 before time exit, given entry | 242 | 0.675 | 0.148 | Uncalibrated shadow score | No—sample/calibration gate failed |
| H2 given H1 | 33 | 0.000 | 0.564 | Uncalibrated shadow score | No |
| H3 given H2 | 15 | not identifiable | 0.003 | Insufficient class variation | No |

Percent probabilities are suppressed for every head. The UI exposes only shadow scores until calibration gates pass.

## Verified production examples

- Waiting pullback: TKNSA
- Entry ready: ISDMR
- Entry active: PINSU
- Progressing/H1: MPARK
- Stalled: FORTE
- Decay cancellation: METRO
- Structure cancellation: KTLEV
- Expired: TERA
- Chased: CIMSA
- Hard stop: GSDDE
- Time exit flat/loss/profit: TGSAS / TUPRS / DARDL
- H2/H3: unavailable in the observed production window; none fabricated

## Known limitations

- Existing historical records without a complete immutable plan are skipped and surfaced as degraded coverage; missing plan values are never fabricated.
- Adaptive plan-version persistence is implemented, but this first replay did not establish an evidence-backed rule for automatic pre-entry price-plan revision.
- Only the versioned H1-partial-plus-trailing challenger is executable. The four profit policies require comparable walk-forward terminal samples before selection.
- Shadow heads currently learn from entry-aware static-v2 labels. Adaptive terminal labels need more matured observations before they can form a separate training dataset.
- Market breadth, XU100-relative and sector-relative features remain unknown where a real aligned provider series is absent.
- No setup-type classifier or MFE/MAE quantile model was promoted; available labels are insufficient.
- Manual research close is represented in the taxonomy but no user write workflow was added.

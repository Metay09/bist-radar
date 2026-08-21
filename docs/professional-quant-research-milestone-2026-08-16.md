# BIST Radar — Professional Quant Research & Decision Lab

## Safety and champion freeze

- `TRADING_MODE=paper`, `LIVE_TRADING=false`, `ml_mode=shadow` and
  `allow_ml_to_change_radar=false` are hard validation boundaries.
- Champion is `champion-adaptive-v1-2026-08-16`, policy
  `adaptive-v1-h1-partial-trailing`. Baselines and experiments are append-only.
- `score_radar`, the existing action card and execution decision path are unchanged.
- Auto-promotion is impossible in this milestone. A future Level-1 veto/tie-breaker
  evaluation requires a separate PR.

## DATASET

Current local operational database is not treated as proof of a predictive edge.
Research datasets are content-hashed and each experiment stores its feature schema,
policy version, hyperparameters, date blocks, prior trial count and OOS metrics.

## 15M HISTORY

Implemented bounded, batched, provider-available backfill for discovery. Data remains
`RESEARCH_ONLY`, `UNVERIFIED_SOURCE` and `PROVIDER_RANGE_LIMITED`. Provider failure is
recorded; missing history is never synthesized.

## 5M HISTORY

Implemented a bounded priority union: active adaptive setups, Radar shortlist, then
observed traded-value liquidity leaders (default maximum 30). Whole-BIST continuous
5m ingestion is intentionally absent. 5m is entry/exit timing research only.

## 5M LATENCY

Persists bar close, first provider availability and persistence timestamps. Reports
p50/p95 provider and end-to-end latency. A minimum of 20 symbols and 20 observations
per symbol is required for a mature status. Current evidence: **INSUFFICIENT** until a
real full-session measurement is collected; production dependency is denied.

## FEATURES

Point-in-time schema covers 5m micro momentum, retest quality, volume acceleration,
short ATR, VWAP distance and EMA structure; 15m frozen Radar/breakout/RVOL/momentum/
ATR/setup age; 60m trend; daily volatility regime; and timestamp-cohort ranks.
XU100-relative data is populated only from validated observations. Sector-relative
data remains `UNKNOWN` without authoritative mapping.

Each feature definition and observation retains source timeframe, source timestamp,
availability timestamp, formula and missing policy. Future-derived values, MFE, MAE,
future return, target hit, terminal result and realized R are rejected as features.

## OOS SAMPLE

Walk-forward splits use whole trading-session blocks, expanding train windows,
validation and untouched test windows, plus configurable purge and embargo sessions.
Same-timestamp cross-sectional cohorts cannot be split between partitions.

Current project data does not yet provide sufficient multiple mature OOS folds for a
scientific superiority claim.

## RADAR BASELINE / LOGISTIC / HIST GRADIENT BOOSTING

The model lab supplies base-rate, logistic regression and
`HistGradientBoostingClassifier` per conditional task. Realized-R uses linear and
`HistGradientBoostingRegressor` baselines/challengers; q10/q50/q90 use quantile HGB.
Uncalibrated output is `SHADOW_SCORE`; only a separate validation-block calibrated
head may display probability.

## ENTRY / STOP / H1 / H2 / H3

Tasks are conditional: entry for all mature eligible setups; stop and H1 after entry;
H2 after H1; H3 after H2. Targets use the current adaptive policy-version truth.
Current edge verdict by task: **NO — insufficient multi-fold OOS evidence**.

## EXPECTED-R MODEL / QUANTILE COVERAGE / CALIBRATION

Expected R and q10/q50/q90 are shadow-only and traceable to one model/experiment.
Pinball loss and empirical q10–q90 coverage are implemented. Wide or missing intervals
produce `LOW_CONFIDENCE` and a research-only `NO_TRADE` suggestion.

## RADAR VS ML / DISAGREEMENT GROUPS

Radar is evaluated only with ROC-AUC, PR-AUC, buckets and top-decile lift. It is never
treated as a probability for Brier/log loss. ML adds Brier, log loss, reliability bins
and calibration gap. Four Radar-high/low × ML-high/low cohorts are supported for entry,
stop/H1/H2/H3, realized R and MFE/MAE summaries.

## STATIC VS ADAPTIVE / ML-VETO / EXPECTED-R RANKING

A/B/C/D comparisons must use identical OOS blocks. C and D are simulations only and
cannot change production actions. Current comparison: **INSUFFICIENT COMPARABLE OOS**.

## EXPECTED R / DRAWDOWN / TRADE COUNT

Economic evaluation is after commission and slippage and reports mean/median/expected
R, profit factor, max drawdown, trade count/frequency and time in trade. No result is
reported here because a full mature OOS run has not yet occurred.

## OVERFITTING RISK

Trial count is persisted. Selection-risk/deflated-Sharpe proxy is reported only from
at least eight comparable trials; full PBO requires enough independent strategy paths.
Current status: **INSUFFICIENT**.

## FINAL VERDICT

- PREDICTIVE EDGE PROVEN: **NO**, for every task.
- ECONOMIC EDGE PROVEN: **NO**.
- WHAT ACTUALLY IMPROVED: research controls, traceability, point-in-time features,
  temporal validation, challenger breadth, uncertainty/no-trade simulation, and UI
  disclosure.
- WHAT DID NOT IMPROVE: no production Radar decision, score, entry or exit behavior.
- NEXT RECOMMENDATION: collect a full-session 20–30-symbol 5m latency panel, complete
  multiple purged walk-forward folds, then publish the OOS report without selecting a
  winner from repeated trials. Do not promote in this milestone.

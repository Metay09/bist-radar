# Adaptive Decision Engine — Research Contract

## Scope and safety

`adaptive-v1` is a paper/research challenger. `static-entry-v2` remains the production champion.
Neither policy can place an order, mutate Radar scores, or enable live trading. Historical static
audits are append-only truth and are never converted into adaptive results.

## Deterministic policy problem

The engine must answer three separate questions without look-ahead: whether a setup remains valid,
whether a completed-bar decision may execute at the next eligible bar open, and how an activated
paper trade is managed. Pre-entry validity uses only changes observable since the signal: age,
close/VWAP/EMA structure, three-bar momentum, rolling relative volume, ATR regime and frozen-plan
reward/risk. Missing context stays `UNKNOWN` and never contributes a favorable assumption.

Default challenger configuration is declared, not optimized: entry TTL 8 bars (offline sensitivity
4/8/12), maximum holding 16 bars, minimum reward/risk 2.0, and policy `H1_PARTIAL_TRAILING`.
Sensitivity results cannot rewrite this configuration automatically.

## ML tasks and sample requirements

Five conditional heads are evaluated independently: entry before expiry; stop before H1 conditional
on entry; H1 before time exit conditional on entry; H2 conditional on H1; H3 conditional on H2.
Base-rate and regularized logistic regression are the only initial candidates. A decision stump is a
diagnostic challenger already available in the dependency set; it may be marked better only after
out-of-sample improvement and calibration stability. Deep learning and reinforcement learning are
excluded: production history is too short and the conditional H2/H3 samples are sparse.

Minimum display sample is 50 per head; minimum promotion-research sample is 200 with both classes
present. These are governance gates, not claims of statistical sufficiency.

## Leakage and validation

Features are snapshotted at decision time. Execution happens on the next eligible bar open. Random
splits are forbidden. Evaluation is expanding walk-forward with a gap equal to the maximum tracking
horizon. This follows the time-ordered/gap semantics described by scikit-learn `TimeSeriesSplit`.
Static-vs-adaptive comparison uses the same signals and chronological OOS windows; no parameter is
selected from the reported production test window.

## Calibration and promotion

Brier score and reliability bins are mandatory. A head is `CALIBRATED` only with at least 50 OOS
observations, at least two populated reliability bins, Brier below its OOS base-rate predictor and
maximum populated-bin calibration gap <= 0.15. Otherwise the UI says `Shadow score`; it must not
render a percentage probability.

Champion/challenger promotion is never automatic. “Better” requires improvement over base rate in
multiple temporal windows, acceptable calibration, sufficient conditional sample and no material
expected-R degradation. More data alone is not improvement. Recent degradation sets
`MODEL_DEGRADED`.

## Evidence

- scikit-learn TimeSeriesSplit: time-ordered evaluation and explicit gap.
- scikit-learn probability calibration guide: reliability diagrams and calibration behavior.
- Bailey et al., *The Probability of Backtest Overfitting*: selection over many backtests can create
  false discoveries; therefore sensitivity research is reported rather than auto-promoted.

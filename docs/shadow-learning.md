# Shadow Learning Safety

Shadow learning stores immutable feature snapshots separately from mutable outcome labels. Its
mandatory configuration is `ML_MODE=shadow` and `ALLOW_ML_TO_CHANGE_RADAR=false`; startup rejects
any other setting.

Predictions are diagnostic only. The `apply_shadow` security boundary returns the original Radar
decision unchanged. A model cannot change score, class, entry, exit, stop, target, quantity, or
portfolio risk and cannot open a trade. Tests enforce the entire decision object invariant.

Labels cover 15m, 30m, 60m, 120m, end-of-day and next-day forward return, MFE, MAE, percentage-hit
thresholds and conservative stop-first ordering. Missing future bars remain `LABEL_PENDING` while
the stream is live and become `LABEL_UNAVAILABLE` only for a known-complete dataset. This avoids
inventing labels and keeps signals that did not become paper trades, reducing selection bias.

Training datasets use chronological 60/20/20 train/validation/test splits; random splitting is
forbidden. Model maturity describes sample size only. Metrics include Brier score, log loss,
precision, recall, F1 and probability calibration buckets. ROC-AUC and PR-AUC are required in an
actual trained-model evaluation; no model is promoted merely because it is more complex.

## Entry-aware plan truth (v2)

A Radar observation is not a trade. The immutable plan becomes active only when a completed
15-minute bar overlaps its snapshotted entry band during the next 8 completed bars. If no overlap
occurs, the terminal label is `NO_ENTRY`; stop and targets are never counted before activation.

After activation, 16 completed bars are replayed in timestamp order. Stop is evaluated before
targets on a bar because OHLC cannot reveal intrabar ordering. Terminal outcomes are `STOPPED`,
`H3_REACHED`, or `EXPIRED_H0/H1/H2`; non-terminal states are `WAITING_ENTRY`, `ENTRY_ACTIVE`,
`H1_ACTIVE`, and `H2_ACTIVE`. Legacy plan-less signals remain `PLAN_UNAVAILABLE` and are excluded
from v2 training.

The shadow learner fits separate regularized logistic probability heads for entry, stop, H1, H2,
and H3 using only terminal v2 audits. Samples remain chronological (60/20/20) and a management-
horizon embargo is removed from split boundaries. Each trained model scores every persisted signal,
including new signals that arrive between retraining events. Predictions remain advisory and cannot
mutate Radar score, trade plans, sizing, or execution.

The free provider's currently available intraday history may be too short or unstable for a useful
model. Until mature labeled samples exist, `/ml/status` reports insufficient data and Radar output
contains no fabricated probabilities.

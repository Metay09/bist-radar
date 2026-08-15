# Autonomous Evidence Accumulation & Model Governance

## Safety boundary

The autonomous cycle observes and evaluates the deterministic champion. It cannot
change Radar score/class, entry, stop, targets, paper action or create a broker order.
Runtime configuration remains `TRADING_MODE=paper`, `LIVE_TRADING=false`,
`ML_MODE=shadow`, `ALLOW_ML_TO_CHANGE_RADAR=false`, `AUTO_PROMOTION=false`.

## Completed-bar cycle

After operational 15m ingestion, the worker runs Radar scan, outcome maturation and
adaptive lifecycle exactly as before. The post-Radar research cycle then performs:

1. bounded priority 5m research ingestion and latency observation;
2. signal-time feature manifest/observation persistence;
3. terminal outcome and cost-adjusted-R label maturation;
4. content-hashed dataset versioning;
5. shadow inference and retraining eligibility evaluation;
6. daily scorecard, weekly report, latency and health checkpoints.

The cycle key is the completed 15m bar timestamp. Replaying the same bar returns the
stored result and creates no duplicate label, dataset, feature or cycle row.

## Retraining policy

Versioned conservative defaults:

- minimum total mature labels: 250;
- minimum new labels since the previous model: 50;
- minimum elapsed time since the previous model: 168 hours.

Inference for an existing model may run without retraining. Model artifacts retain
model/experiment/dataset IDs, feature and policy versions, temporal date blocks,
dataset hash, code commit SHA, config/hyperparameters and random seed.

## 5m latency maturity (`latency-v1`)

Each persisted observation keeps symbol, bar close, first provider observation,
persist time and provider/end-to-end latency. Daily evidence contains sample,
coverage, missing, p50/p90/p95/p99.

- `INSUFFICIENT`: no real observations;
- `OBSERVING`: observations exist but fewer than 3 sessions or completeness below 90%;
- `RESEARCH_READY`: at least 3 sessions, at least 90% completeness and p95 ≤ 180s;
- `DEGRADED`: p95 > 300s or the ready conditions are unstable.

5m remains `RESEARCH_ONLY / UNVERIFIED` and is never a production Radar dependency.

## Evidence and governance

Evidence maturity uses independent OOS sessions/folds, not one favorable fold. Initial
promotion-candidate research requires at least 500 OOS observations, 3 folds, 67% fold
wins, positive cost-adjusted expected R and economic improvement, acceptable drawdown,
calibration, no leakage and no severe regime instability. Passing all conditions may
only produce a research label; auto-promotion remains impossible.

The health monitor exposes stale scan/training/adaptive/research jobs, stalled label
growth and recent OOS economic/drawdown degradation. Daily and weekly reports are
persistent and available at `/research/daily` and `/research/weekly`; aggregate
evidence is available at `/research/evidence`.

## PostgreSQL migration acceptance

GitHub Actions starts an empty PostgreSQL 16 service, upgrades from base to head,
verifies revision and required research tables, downgrades `0013` to `0012`, upgrades
again and repeats verification. SQLite is used by unit tests only and is not presented
as the production migration target.

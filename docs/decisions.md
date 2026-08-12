# Architecture Decision Records

## ADR-001 — Live trading disabled

`LIVE_TRADING=False`; configuration rejects every mode except `paper`. No broker/order module exists.

## ADR-002 — Provider abstraction mandatory

Market, KAP and takas data enter through interfaces. Fixture/Mock providers keep development deterministic; brittle production HTML scraping is excluded.

## ADR-003 — Fail-closed validation

Invalid, stale, conflicting, missing or provider-down data vetoes signals. Quality below 90 and invalid risk plans also veto.

## ADR-004 — PostgreSQL selected

PostgreSQL is the deployment store and Alembic controls migrations. SQLite supports isolated local tests.

## ADR-005 — Explainable deterministic scoring

No ML in V1. Each score component has a fixed weight and human-readable reasons. AI may later summarize KAP/news but cannot calculate indicators, risk or P&L.

## ADR-006 — Time and execution semantics

Store UTC, present Europe/Istanbul. Backtests execute at t+1 open to avoid same-bar ambiguity and look-ahead leakage.

## ADR-007 — Isolated deployment

Compose owns only namespaced BIST Radar services, network and volume. API binds `127.0.0.1` by default; no existing server resources are modified.

# Architecture

```text
MarketDataProvider / benchmark provider
             ↓
Validation + cross-provider reconciliation + Data Quality Score
             ↓
Deterministic Feature Engine (indicators, trend, momentum, RVOL, breakout)
             ↓
Market Regime + Relative Strength
             ↓
Transparent Radar Score components (0–100)
             ↓
Risk Engine (ATR/structure stop, targets, sizing, R/R gate)
             ↓
Signal (fail closed)
             ↓
Paper Trading ledger / t+1 Backtest execution
             ↓
Notification interface
```

IO and financial calculations are separated. Providers can be swapped without changing scoring. Data becomes eligible only after schema, ordering, OHLCV, symbol, timestamp, staleness and anomaly checks. A second provider can veto data through configurable reconciliation tolerance.

PostgreSQL is the container database; SQLite is the zero-dependency local default. Alembic owns schema changes. Timestamps are stored UTC and converted to Europe/Istanbul at presentation boundaries. `MarketCalendar` allows an official exchange calendar later; weekday fallback is explicitly incomplete.

Radar V1 weights are trend 15, momentum 15, RVOL 20, breakout 15, relative strength 10, volatility 5, regime 10, risk/reward 10. Every component and reason is returned. Risk-off penalizes rather than silently overrides, while any safety/data gate vetoes the signal.

Backtests use only completed bars. A signal at close t executes at open t+1. Parameter train/validation/out-of-sample boundaries can be layered over the strategy interface; optimization is intentionally absent in V1. Historical constituent membership is required to control survivorship bias.

Historical replay injects a `ReplayClock`, historical provider and signal strategy. The execution state machine rejects invalid transitions. Persistent run checkpoints contain `run_id`, last timestamp, status, immutable config snapshot/hash; trade idempotency is keyed by strategy/symbol/signal time. Intrabar ordering is unknowable from OHLC, therefore the documented default is conservative `STOP_FIRST`.

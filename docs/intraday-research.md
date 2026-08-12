# Intraday Research Radar

The intraday subsystem is research-only and uses strategy ID `radar-intraday-v1`. It does not
modify the frozen daily Radar V1. Yahoo Finance is unofficial, unverified, delayed by an unknown
amount, and may restrict intraday history. Supported adapter intervals are 5m, 15m, 30m and 60m;
the actually returned range must always be reported with `INTRADAY_RANGE_LIMITED` when incomplete.

Only completed bars are eligible. A bar timestamp is its opening time and becomes eligible after
one full timeframe plus the configured provider delay buffer. Provider and received timestamps are
stored separately; latest/p50/p95/p99 observed latency is reported rather than assuming 15 minutes.

The pipeline remains provider adapter → canonical Decimal bars → validation → deduplication →
persistence → completed-bar filter → features → Radar. Incremental updates preserve prior bars;
same-value bars count as duplicates and changed values are revisions rather than silent overwrites.

The 15m scan calculates RSI, MACD, EMA 9/20/50, session VWAP, ATR, same-slot RVOL, ROC, rolling
volatility, breakout proximity, prior-day high distance, and volume/price acceleration. Same-slot
RVOL falls back to a rolling estimator and explicitly reports the method. The Early Momentum Score
is diagnostic and cannot alter execution or the daily strategy.

Candidate snapshots and all outcomes are retained in PostgreSQL. Cooldown suppresses repeated
signals, while a configured score increase is audited as `SIGNAL_UPGRADED`. No retention deletion
is performed by default. Research paper execution continues to use next completed-bar semantics,
configured assumed commission/slippage, and never submits a real order.

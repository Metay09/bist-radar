# Free research market data

`YFinanceResearchProvider` is an isolated, optional historical-data adapter. It maps exact
canonical BIST symbols (`THYAO`) to Yahoo symbols (`THYAO.IS`), requests daily data with an
explicit adjusted/unadjusted policy, and sends every row through the canonical Decimal,
timestamp and quality-validation boundary.

This provider is not an official Borsa Istanbul data source. It is labelled `RESEARCH_ONLY`,
`UNVERIFIED_SOURCE`, and `CALENDAR_UNVERIFIED`; it cannot be approved in
`DATA_ENVIRONMENT=production`. It must not be used for live trading or production validation.
Network failure only degrades research availability; core health remains independent.

## Reproducible workflow

1. Keep `TRADING_MODE=paper`, use `DATA_ENVIRONMENT=research`, and select
   `RESEARCH_PRICE_MODE=adjusted` or `unadjusted` explicitly.
2. Run `python -m app.cli research-download --years 3 --dry-run` before writing.
3. Review missing symbols, date range, invalid/duplicate counts and quality.
4. Import with `python -m app.cli research-download --years 3`; retain its dataset ID/hash.
5. Run `python -m app.cli research-replay --dataset-id <id>` and
   `python -m app.cli research-scan --dataset-id <id>`.

The cache under `data/research-cache/` has a finite TTL and is excluded from Git. Downloads are
deterministic (`threads=False`) with bounded exponential backoff. No cookie, anti-bot, or
rate-limit bypass is implemented.

## Biases and assumptions

The checked-in BIST100 file is a manually maintained current-membership snapshot derived from
Borsa Istanbul's quarterly publication. Applying it to earlier years creates survivorship bias,
so every result carries `SURVIVORSHIP_BIAS_POSSIBLE`. It is not historical index membership.
Sector data is left empty rather than invented. Yahoo corporate-action data is unverified.
Replay keeps Radar V1 parameters frozen and uses assumed costs of 10 bps commission and 5 bps
slippage; these are not represented as any broker's actual tariff.

## Performance accounting

Research performance has separate `realized_only` and `mark_to_market` views. Total return is
always `final_equity / initial_equity - 1`; overlapping trade returns are never compounded as a
portfolio return. Open positions are valued each completed trading day at the last available
close using the configured slippage and estimated round-trip commission as a conservative net
liquidation value. They are not silently force-closed.

The report identifies dataset, post-warmup eligible, and first-trade periods separately. The
headline CAGR uses the full dataset start/end dates. Max drawdown, Sharpe and Sortino use the
daily mark-to-market equity series with 252-day annualization, zero risk-free rate, sample
standard deviation for Sharpe, and downside deviation
`sqrt(mean(min(daily_return, 0)^2))` for Sortino.

Exposure is reported as average/peak gross market value divided by daily MTM equity, percentage
of dataset days with at least one position, and average open-position count. These replace the
ambiguous sum-of-trade-durations metric.

Daily Yahoo bars are date labels, not proof that a session has completed. A same-day bar is
eligible only after configured BIST close time plus `RESEARCH_CLOSE_DELAY_MINUTES`, evaluated in
`Europe/Istanbul`. Earlier same-day bars are excluded from replay and latest-completed scans.

Yahoo availability, retention and revisions are outside this project's control. Dataset hashes
identify frozen DB snapshots so a later upstream revision does not silently replace a replay's
input identity.

# Telegram Alerts

Telegram is disabled by default. Set `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`, and
`TELEGRAM_CHAT_ID` only in `.env`; credentials are never returned by an API or logged. The Bot API
uses HTTPS with a bounded timeout. Missing credentials leave the application healthy.

Strong/very-strong candidate alerts are fail-closed when the market is closed or observed data age
exceeds `MAX_ALERT_DATA_AGE_MINUTES`. Every send/suppression is persisted. The unique notification
key prevents worker retries from resending a symbol/bar/score, and `TELEGRAM_UPGRADE_POINTS`
suppresses insignificant upgrades. Supported configuration names also reserve paper-open/close,
provider stale/recovered and daily-summary alert types.

Messages always state `RESEARCH / PAPER ONLY` and the investment-advice disclaimer. Test formatting
with the unit suite; do not place a real token in source control.

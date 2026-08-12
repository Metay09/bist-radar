import re
from datetime import UTC, datetime, timedelta

import pandas as pd

from app.models.domain import DataStatus, ValidationResult

REQUIRED = {"symbol", "timestamp", "open", "high", "low", "close", "volume"}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,12}$")


class DataValidator:
    def __init__(
        self, stale_after: timedelta = timedelta(days=2), max_jump_percent: float = 40
    ) -> None:
        self.stale_after = stale_after
        self.max_jump_percent = max_jump_percent

    def validate(self, frame: pd.DataFrame, now: datetime | None = None) -> ValidationResult:
        if frame.empty or not REQUIRED.issubset(frame.columns):
            return ValidationResult(DataStatus.MISSING, 0, ["missing rows or columns"])
        errors: list[str] = []
        timestamps = pd.to_datetime(frame.timestamp, utc=True, errors="coerce")
        numeric = frame[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce"
        )
        if timestamps.isna().any():
            errors.append("invalid timestamp")
        if timestamps.duplicated().any():
            errors.append("duplicate bar")
        if not timestamps.is_monotonic_increasing:
            errors.append("bars out of order")
        if numeric.isna().any().any():
            errors.append("non-numeric value")
        if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
            errors.append("non-positive price")
        if (numeric.volume < 0).any():
            errors.append("negative volume")
        if (
            (numeric.low > numeric.open)
            | (numeric.open > numeric.high)
            | (numeric.low > numeric.close)
            | (numeric.close > numeric.high)
        ).any():
            errors.append("invalid OHLC")
        if (
            not frame.symbol.astype(str)
            .map(lambda value: bool(SYMBOL_PATTERN.fullmatch(value)))
            .all()
        ):
            errors.append("invalid symbol")
        if frame.symbol.nunique() != 1:
            errors.append("unexpected symbol")
        jumps = numeric.close.pct_change().abs() * 100
        if (jumps > self.max_jump_percent).any():
            errors.append("abnormal jump; corporate action adjustment required")
        if errors:
            return ValidationResult(DataStatus.INVALID, max(0, 100 - len(errors) * 20), errors)
        current = now or datetime.now(UTC)
        latest = timestamps.iloc[-1].to_pydatetime()
        if current - latest > self.stale_after:
            return ValidationResult(DataStatus.STALE, 70, ["stale data"])
        return ValidationResult(DataStatus.OK, 100, [])

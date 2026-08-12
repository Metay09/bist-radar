from datetime import UTC, datetime, time, timedelta

import pytest

from app.data.research import is_completed_daily_bar


def test_partial_current_day_daily_bar_rejected() -> None:
    bar = datetime(2026, 8, 11, 21, tzinfo=UTC)  # 12 Aug midnight Istanbul label
    before_close_buffer = datetime(2026, 8, 12, 15, 20, tzinfo=UTC)  # 18:20 Istanbul
    assert not is_completed_daily_bar(bar, before_close_buffer, time(18, 10), timedelta(minutes=30))


def test_completed_historical_and_current_daily_bar_accepted() -> None:
    historical = datetime(2026, 8, 10, 21, tzinfo=UTC)
    now = datetime(2026, 8, 12, 16, tzinfo=UTC)
    current = datetime(2026, 8, 11, 21, tzinfo=UTC)
    assert is_completed_daily_bar(historical, now)
    assert is_completed_daily_bar(current, now, time(18, 10), timedelta(minutes=30))


def test_daily_completion_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        is_completed_daily_bar(datetime(2026, 1, 1), datetime.now(UTC))

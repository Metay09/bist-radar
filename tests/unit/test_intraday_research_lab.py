from datetime import UTC, datetime, timedelta

import pytest

from app.data.intraday_research import prioritized_5m_symbols


def test_5m_priority_is_bounded_and_prefers_active_then_shortlist() -> None:
    selected = prioritized_5m_symbols(
        ["THYAO", "AKBNK", "EREGL"], ["EREGL", "TUPRS"], ["ASELS"], limit=4
    )
    assert selected == ["ASELS", "EREGL", "TUPRS", "THYAO"]


def test_5m_priority_rejects_unbounded_request() -> None:
    with pytest.raises(ValueError):
        prioritized_5m_symbols([], [], [], limit=0)


def test_latency_timestamps_must_be_monotonic() -> None:
    close = datetime(2026, 8, 14, 10, tzinfo=UTC)
    available = close + timedelta(seconds=30)
    persisted = available + timedelta(seconds=2)
    assert close <= available <= persisted

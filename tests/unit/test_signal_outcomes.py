from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from app.intraday.outcomes import LabelStatus, accuracy_buckets, label_signal, lifecycle


def bars(start: datetime, count: int = 12) -> pd.DataFrame:
    index = pd.date_range(start + timedelta(minutes=15), periods=count, freq="15min")
    return pd.DataFrame(
        {
            "open": [100] * count,
            "high": [101.5 + i * 0.2 for i in range(count)],
            "low": [99.5] * count,
            "close": [100 + i * 0.1 for i in range(count)],
            "volume": [1000] * count,
        },
        index=index,
    )


def test_pending_partial_and_all_intraday_horizons() -> None:
    signal = datetime(2026, 1, 5, 7, tzinfo=UTC)
    pending = label_signal(signal, 100, bars(signal), signal + timedelta(minutes=10))
    assert pending["15m"].status == LabelStatus.LABEL_PENDING
    assert lifecycle(pending) == "OUTCOME_PENDING"
    partial = label_signal(signal, 100, bars(signal), signal + timedelta(minutes=70))
    assert partial["15m"].forward_return is not None
    assert partial["30m"].status == LabelStatus.LABEL_AVAILABLE
    assert partial["60m"].hit_plus_1_percent
    assert partial["120m"].status == LabelStatus.LABEL_PENDING
    assert lifecycle(partial) == "PARTIALLY_LABELED"
    complete = label_signal(
        signal, 100, bars(signal), signal + timedelta(days=2), dataset_complete=True
    )
    assert complete["120m"].maximum_favorable_excursion is not None
    assert complete["EOD"].status == LabelStatus.LABEL_AVAILABLE
    assert complete["NEXT_DAY"].status == LabelStatus.LABEL_UNAVAILABLE
    assert lifecycle(complete) == "FULLY_LABELED"


def test_horizons_count_completed_bars_across_session_gap_and_eod_waits_for_close() -> None:
    signal = datetime(2026, 1, 5, 14, 45, tzinfo=UTC)  # 17:45 Istanbul
    index = pd.DatetimeIndex(
        [
            datetime(2026, 1, 6, 7, 0, tzinfo=UTC),
            datetime(2026, 1, 6, 7, 15, tzinfo=UTC),
        ]
    )
    data = pd.DataFrame(
        {
            "open": [100, 101],
            "high": [102, 103],
            "low": [99, 100],
            "close": [101, 102],
            "volume": [1, 1],
        },
        index=index,
    )
    result = label_signal(signal, 100, data, datetime(2026, 1, 6, 7, 31, tzinfo=UTC))
    assert result["15m"].forward_return == pytest.approx(0.01)
    assert result["30m"].forward_return == pytest.approx(0.02)
    assert result["60m"].status == LabelStatus.LABEL_PENDING
    assert result["NEXT_DAY"].status == LabelStatus.LABEL_PENDING


def test_eod_is_not_labeled_from_an_intraday_close() -> None:
    signal = datetime(2026, 1, 5, 7, 0, tzinfo=UTC)
    result = label_signal(signal, 100, bars(signal, 2), signal + timedelta(minutes=45))
    assert result["EOD"].status == LabelStatus.LABEL_PENDING


def test_stop_first_is_conservative() -> None:
    signal = datetime(2026, 1, 5, 7, tzinfo=UTC)
    data = bars(signal)
    data.iloc[0, data.columns.get_loc("low")] = 97
    data.iloc[0, data.columns.get_loc("high")] = 103
    outcome = label_signal(signal, 100, data, signal + timedelta(hours=3), stop=98)
    assert outcome["15m"].hit_stop_first is True


def test_accuracy_score_and_rvol_buckets() -> None:
    rows = [
        {
            "radar_score": 75,
            "rvol": 1.6,
            "hit_plus_1_percent": True,
            "maximum_favorable_excursion": 0.02,
            "maximum_adverse_excursion": -0.01,
        },
        {
            "radar_score": 85,
            "rvol": 2.2,
            "hit_plus_1_percent": False,
            "maximum_favorable_excursion": 0.005,
            "maximum_adverse_excursion": -0.02,
        },
    ]
    score = accuracy_buckets(rows)
    assert [item["bucket"] for item in score] == ["70-79", "80-89"]
    assert accuracy_buckets(rows, "rvol")[1]["bucket"] == "2+"
    assert (
        accuracy_buckets([rows[0] | {"market_regime": "RISK_ON"}], "market_regime")[0]["bucket"]
        == "RISK_ON"
    )
    pending = rows[0] | {
        "hit_plus_1_percent": None,
        "maximum_favorable_excursion": None,
        "maximum_adverse_excursion": None,
    }
    assert accuracy_buckets([pending])[0]["plus_1_hit_rate"] is None


def test_outcome_input_validation_and_missing_live_data() -> None:
    signal = datetime(2026, 1, 5, 7, tzinfo=UTC)
    empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    result = label_signal(signal, 100, empty, signal + timedelta(hours=3))
    assert result["120m"].status == LabelStatus.LABEL_PENDING
    try:
        label_signal(signal.replace(tzinfo=None), 100, empty, signal)
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    try:
        accuracy_buckets([{"radar_score": "bad"}])
    except ValueError as exc:
        assert "numeric" in str(exc)

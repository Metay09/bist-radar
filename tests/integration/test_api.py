import pytest
from fastapi import HTTPException

from app.api.main import (
    health,
    intraday_scan,
    intraday_scan_symbol,
    intraday_status,
    ml_evaluation,
    ml_models,
    ml_predictions,
    ml_status,
    radar,
    radar_symbol,
    ready,
    signals,
    system_status,
)


def test_health_and_demo_expected_behaviour() -> None:
    assert health()["trading_mode"] == "paper"
    assert isinstance(ready()["ready"], bool)
    by_symbol = {x["symbol"]: x for x in radar()}
    assert by_symbol["RALLY"]["score"] >= 80
    assert by_symbol["FLAT"]["score"] < 70
    assert (
        by_symbol["BAD_DATA"]["score"] == 0
        and by_symbol["BAD_DATA"]["data_status"] == "DATA_INVALID"
    )
    with pytest.raises(HTTPException):
        radar_symbol("UNKNOWN")
    assert isinstance(signals(), list)
    # Persistent endpoints are exercised against an isolated database in repository tests.
    assert system_status()["trading_mode"] == "paper"


def test_intraday_and_shadow_read_only_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.main.research_repository.latest_report",
        lambda report_type: None,
    )
    monkeypatch.setattr(
        "app.api.main.intraday_repository.status",
        lambda: {"mode": "SHADOW", "allow_ml_to_change_radar": False},
    )
    monkeypatch.setattr("app.api.main.intraday_repository.models", lambda: [])
    monkeypatch.setattr("app.api.main.intraday_repository.predictions", lambda: [])
    monkeypatch.setattr("app.api.main.intraday_repository.evaluations", lambda: [])
    assert intraday_status()["strategy_id"] == "radar-intraday-v1"
    assert "candidates" in intraday_scan()
    with pytest.raises(HTTPException):
        intraday_scan_symbol("MISSING")
    assert ml_status()["mode"] == "SHADOW"
    assert ml_status()["allow_ml_to_change_radar"] is False
    assert isinstance(ml_models(), list)
    assert isinstance(ml_predictions(), list)
    assert isinstance(ml_evaluation(), list)

import pytest
from fastapi import HTTPException

from app.api.main import health, radar, radar_symbol


def test_health_and_demo_expected_behaviour() -> None:
    assert health()["trading_mode"] == "paper"
    by_symbol = {x["symbol"]: x for x in radar()}
    assert by_symbol["RALLY"]["score"] >= 80
    assert by_symbol["FLAT"]["score"] < 70
    assert (
        by_symbol["BAD_DATA"]["score"] == 0
        and by_symbol["BAD_DATA"]["data_status"] == "DATA_INVALID"
    )
    with pytest.raises(HTTPException):
        radar_symbol("UNKNOWN")

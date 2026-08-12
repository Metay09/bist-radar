import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_live_trading_is_rejected() -> None:
    with pytest.raises(ValidationError, match="LIVE TRADING IS DISABLED"):
        Settings(trading_mode="live")

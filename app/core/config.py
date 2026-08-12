from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "BIST Radar"
    trading_mode: Literal["paper", "live"] = "paper"
    database_url: str = "sqlite:///./bist_radar.db"
    timezone: str = "Europe/Istanbul"
    min_data_quality_score: float = 90
    data_stale_minutes: int = 1440
    provider_price_tolerance_percent: float = 0.25
    ema_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rvol_lookback: int = 20
    breakout_lookback: int = 20
    max_risk_per_trade_percent: float = 0.75
    min_risk_reward: float = 2.0
    max_position_percent: float = 20
    commission_bps: float = 10
    slippage_bps: float = 5
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_chat_id: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def reject_live(self) -> "Settings":
        if self.trading_mode != "paper":
            raise ValueError("LIVE TRADING IS DISABLED: TRADING_MODE must be paper")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

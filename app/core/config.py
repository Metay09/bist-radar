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
    execution_model: Literal["NEXT_BAR_OPEN"] = "NEXT_BAR_OPEN"
    max_entry_gap_percent: float = 3
    intrabar_ambiguity_policy: Literal["STOP_FIRST"] = "STOP_FIRST"
    max_open_positions: int = 5
    max_total_open_risk_percent: float = 3
    reject_possible_corporate_action: bool = True
    data_environment: Literal["fixture", "research", "production"] = "fixture"
    require_verified_calendar: bool = True
    raw_payload_archive_enabled: bool = False
    raw_payload_retention_days: int = 7
    research_price_mode: Literal["adjusted", "unadjusted"] = "adjusted"
    research_cache_dir: str = "data/research-cache"
    research_cache_ttl_hours: int = 24
    research_download_attempts: int = 3
    research_batch_size: int = 25
    min_warmup_bars: int = 200
    min_avg_daily_value_traded: float = 0
    min_avg_daily_volume: float = 0
    min_history_bars: int = 200
    min_price: float = 0
    bist_daily_close_time: str = "18:10"
    research_close_delay_minutes: int = 30
    intraday_scan_minutes: int = 15
    intraday_signal_cooldown_minutes: int = 60
    intraday_signal_upgrade_points: int = 5
    intraday_stale_minutes: int = 45
    ml_mode: Literal["shadow"] = "shadow"
    allow_ml_to_change_radar: bool = False
    api_host: str = "127.0.0.1"
    api_port: int = 8765
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_chat_id: str | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def reject_live(self) -> "Settings":
        if self.trading_mode != "paper":
            raise ValueError("LIVE TRADING IS DISABLED: TRADING_MODE must be paper")
        if self.data_environment == "production" and not self.require_verified_calendar:
            raise ValueError("production requires verified calendar")
        if self.ml_mode != "shadow" or self.allow_ml_to_change_radar:
            raise ValueError("ML is diagnostic-only: shadow mode is mandatory")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

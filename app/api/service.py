from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.core.config import get_settings
from app.data.providers import CsvProvider, ProviderError
from app.data.validation import DataValidator
from app.market.analysis import classify_regime, classify_trend, features, relative_strength
from app.models.domain import DataStatus
from app.risk.engine import build_trade_plan
from app.scoring.radar import RadarResult, score_radar

FIXTURES = Path(__file__).parents[2] / "tests" / "fixtures"


class RadarService:
    def __init__(self) -> None:
        self.provider = CsvProvider(FIXTURES)
        self.symbols = ["RALLY", "FLAT", "SELLOFF", "BAD_DATA"]
        self.last_scan: datetime | None = None
        self.last_successful_scan: datetime | None = None
        self.last_error: str | None = None

    def scan(self) -> list[RadarResult]:
        settings = get_settings()
        results: list[RadarResult] = []
        self.last_scan = datetime.now(UTC)
        try:
            benchmark = self.provider.get_daily_bars("XU100")
        except ProviderError as exc:
            self.last_error = str(exc)
            return []
        regime = classify_regime(benchmark)
        for symbol in self.symbols:
            frame = self.provider.get_daily_bars(symbol)
            validation = DataValidator(timedelta(days=5000)).validate(frame)
            if validation.status != DataStatus.OK:
                results.append(
                    score_radar(
                        symbol,
                        {},
                        classify_trend({}) if False else classify_trend(features(benchmark)),
                        regime,
                        0,
                        0,
                        validation.status,
                        validation.quality_score,
                        settings.min_data_quality_score,
                    )
                )
                continue
            f = features(frame)
            trend = classify_trend(f)
            rs = relative_strength(frame, benchmark)
            try:
                plan = build_trade_plan(
                    Decimal(str(frame.close.iloc[-1])),
                    Decimal(str(f["atr"])),
                    Decimal(str(f["recent_low"])),
                )
                rr = float(plan.risk_reward)
            except ValueError:
                rr = 0
            results.append(
                score_radar(
                    symbol,
                    f,
                    trend,
                    regime,
                    rs,
                    rr,
                    validation.status,
                    validation.quality_score,
                    settings.min_data_quality_score,
                )
            )
        self.last_successful_scan = datetime.now(UTC)
        self.last_error = None
        return results


service = RadarService()

from abc import ABC, abstractmethod
from datetime import datetime

from app.backtest.replay_models import Timeframe
from app.data.canonical import (
    CanonicalBar,
    DataMode,
    ProviderCapabilities,
    ProviderMetadata,
    QualityFlag,
    SymbolMapper,
    decimal_from_vendor,
    normalize_timestamp,
)


class CapabilityUnavailable(RuntimeError):
    pass


class CanonicalMarketDataProvider(ABC):
    metadata: ProviderMetadata
    capabilities: ProviderCapabilities

    @abstractmethod
    def normalize(self, payload: dict[str, object], received_at: datetime) -> CanonicalBar: ...
    def require(self, capability: str) -> None:
        if not getattr(self.capabilities, capability, False):
            raise CapabilityUnavailable("PROVIDER_CAPABILITY_UNAVAILABLE")


class MockVendorA(CanonicalMarketDataProvider):
    metadata = ProviderMetadata(
        "mock-a",
        "Mock Vendor A",
        DataMode.DELAYED,
        "Europe/Istanbul",
        license_type="test",
        dataset_version="v1",
    )
    capabilities = ProviderCapabilities(historical_bars=True, intraday_bars=True, delayed=True)

    def __init__(self) -> None:
        self.mapper = SymbolMapper({"BIST:THYAO": "THYAO"})

    def normalize(self, p: dict[str, object], received_at: datetime) -> CanonicalBar:
        return CanonicalBar(
            self.mapper.map(str(p["ticker"])),
            normalize_timestamp(p["time"]),
            Timeframe(str(p["interval"])),
            decimal_from_vendor(p["o"]),
            decimal_from_vendor(p["h"]),
            decimal_from_vendor(p["l"]),
            decimal_from_vendor(p["c"]),
            decimal_from_vendor(p["v"]),
            self.metadata.provider_id,
            received_at,
            quality_flags=(
                QualityFlag.RESEARCH_ONLY,
                QualityFlag.UNVERIFIED_SOURCE,
                QualityFlag.CALENDAR_UNVERIFIED,
            ),
        )


class MockVendorB(CanonicalMarketDataProvider):
    metadata = ProviderMetadata(
        "mock-b", "Mock Vendor B", DataMode.FIXTURE, "UTC", dataset_version="v1"
    )
    capabilities = ProviderCapabilities(historical_bars=True)

    def __init__(self) -> None:
        self.mapper = SymbolMapper({"THYAO.IS": "THYAO"})

    def normalize(self, p: dict[str, object], received_at: datetime) -> CanonicalBar:
        return CanonicalBar(
            self.mapper.map(str(p["instrument"])),
            normalize_timestamp(p["ts"], epoch=True),
            Timeframe(str(p["tf"])),
            decimal_from_vendor(p["openPrice"]),
            decimal_from_vendor(p["highPrice"]),
            decimal_from_vendor(p["lowPrice"]),
            decimal_from_vendor(p["lastPrice"]),
            decimal_from_vendor(p["totalVolume"]),
            self.metadata.provider_id,
            received_at,
            quality_flags=(
                QualityFlag.RESEARCH_ONLY,
                QualityFlag.UNVERIFIED_SOURCE,
                QualityFlag.CALENDAR_UNVERIFIED,
            ),
        )

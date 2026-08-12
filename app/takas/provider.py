from abc import ABC, abstractmethod
from dataclasses import dataclass

TAKAS_DATA_UNAVAILABLE = "TAKAS_DATA_UNAVAILABLE"


@dataclass(frozen=True)
class TakasSnapshot:
    symbol: str
    change_5d: float
    change_10d: float
    change_20d: float
    top_broker_concentration: float
    accumulating_brokers: int
    distributing_brokers: int
    broker_persistence: float


class TakasProvider(ABC):
    @abstractmethod
    def get_takas(self, symbol: str) -> TakasSnapshot | None: ...
    @abstractmethod
    def get_broker_distribution(self, symbol: str) -> dict[str, float]: ...


class MockTakasProvider(TakasProvider):
    def __init__(self, snapshots: dict[str, TakasSnapshot] | None = None) -> None:
        self.snapshots = snapshots or {}

    def get_takas(self, symbol: str) -> TakasSnapshot | None:
        return self.snapshots.get(symbol)

    def get_broker_distribution(self, symbol: str) -> dict[str, float]:
        return {}

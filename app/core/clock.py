from abc import ABC, abstractmethod
from datetime import UTC, datetime


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime: ...


class RealClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class ReplayClock(Clock):
    def __init__(self, current: datetime) -> None:
        self.current = current

    def now(self) -> datetime:
        return self.current

    def advance(self, current: datetime) -> None:
        if current < self.current:
            raise ValueError("replay clock cannot move backwards")
        self.current = current

from abc import ABC, abstractmethod
from datetime import date


class MarketCalendar(ABC):
    @abstractmethod
    def is_session(self, day: date) -> bool: ...


class WeekdayCalendar(MarketCalendar):
    """Fallback only; replace with an official BIST holiday calendar provider."""

    def is_session(self, day: date) -> bool:
        return day.weekday() < 5

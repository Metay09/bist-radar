from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Announcement:
    announcement_id: str
    symbol: str
    published_at: datetime
    title: str
    category: str
    raw_text: str
    source_url: str


class KapProvider(ABC):
    @abstractmethod
    def get_announcements(self, symbol: str) -> list[Announcement]: ...


class MockKapProvider(KapProvider):
    def __init__(self, announcements: list[Announcement] | None = None) -> None:
        self.announcements = announcements or []

    def get_announcements(self, symbol: str) -> list[Announcement]:
        return [a for a in self.announcements if a.symbol == symbol]


CATEGORIES = {
    "temettü": "dividend",
    "geri alım": "buyback",
    "ihale": "tender",
    "kapasite": "capacity_increase",
    "sermaye artır": "capital_increase",
    "finansal sonuç": "financial_results",
    "dava": "lawsuit",
    "borçlan": "borrowing",
    "faaliyet durdur": "operations_halted",
    "ortak satış": "shareholder_sale",
    "yatırım": "investment",
    "iş ilişkisi": "new_business",
}


def classify(text: str) -> str:
    lowered = text.casefold()
    return next((category for phrase, category in CATEGORIES.items() if phrase in lowered), "other")

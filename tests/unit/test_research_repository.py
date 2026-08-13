from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.backtest.replay_models import Timeframe
from app.data.canonical import CanonicalBar, QualityFlag
from app.data.research_repository import ResearchRepository
from app.database.base import Base


def test_research_dataset_persistence_duplicate_and_reports() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    repository = ResearchRepository(sessions)
    with pytest.raises(ValueError, match="empty dataset"):
        repository.import_dataset([], {}, {})
    bar = CanonicalBar(
        symbol="THYAO",
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        timeframe=Timeframe.D1,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        provider="yfinance-research",
        received_at=datetime(2025, 1, 2, tzinfo=UTC),
        is_adjusted=True,
        quality_flags=(QualityFlag.RESEARCH_ONLY,),
    )
    dataset_id, inserted, duplicates = repository.import_dataset(
        [bar], {"universe": "bist100"}, {"quality_score": 100}
    )
    assert inserted == 1 and duplicates == 0
    frozen_id, inserted_again, duplicates_again = repository.import_dataset(
        [bar], {}, {"quality_score": 100}
    )
    assert frozen_id == dataset_id and inserted_again == 0 and duplicates_again == 1
    loaded = repository.bars(dataset_id)
    assert len(loaded) == 1 and loaded[0].close == Decimal("10.5")
    assert repository.bars(dataset_id, "MISSING") == []
    assert repository.latest_report("scan") is None
    repository.save_report("scan", dataset_id, {"candidates": [{"symbol": "THYAO"}]})
    assert repository.latest_report("scan") == {"candidates": [{"symbol": "THYAO"}]}
    repository.save_report("scan", dataset_id, {"candidates": []})
    assert repository.latest_report("scan") == {"candidates": []}
    assert repository.latest_report("scan", require_candidates=True) == {
        "candidates": [{"symbol": "THYAO"}]
    }

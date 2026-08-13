import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app import cli
from app.backtest.replay_models import ReplayResult, Timeframe
from app.data.canonical import CanonicalBar
from app.data.research import SymbolQuality
from app.data.yfinance_provider import ResearchDownload


def sample_bar(symbol: str = "THYAO") -> CanonicalBar:
    return CanonicalBar(
        symbol=symbol,
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
        timeframe=Timeframe.D1,
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10.5"),
        volume=Decimal("1000"),
        provider="yfinance-research",
        received_at=datetime(2025, 1, 2, tzinfo=UTC),
    )


def test_download_research_builds_aggregate_report(monkeypatch: object) -> None:
    from pytest import MonkeyPatch

    patch = monkeypatch
    assert isinstance(patch, MonkeyPatch)
    universe = SimpleNamespace(
        universe_id="bist100-current",
        snapshot_hash="abc",
        members=(SimpleNamespace(symbol="THYAO", active=True),),
    )
    patch.setattr(cli, "load_universe", lambda _: universe)

    def many(self: object, symbols: list[str], start: date, end: date) -> object:
        quality = SymbolQuality("THYAO", bars_received=1, bars_valid=1)
        return {"THYAO": ResearchDownload((sample_bar(),), quality, start, end)}, {
            "XU100": "INDEX_DATA_UNAVAILABLE"
        }

    patch.setattr(cli.YFinanceResearchProvider, "download_many", many)
    bars, report = cli.download_research(date(2025, 1, 1), date(2025, 2, 1))
    assert len(bars) == 1 and report["found_symbols"] == 1
    assert report["missing_symbols"] == {"XU100": "INDEX_DATA_UNAVAILABLE"}
    assert report["adjusted"] is True and len(str(report["dataset_hash"])) == 64


def test_cli_download_scan_and_replay_commands(monkeypatch: object, capsys: object) -> None:
    from pytest import CaptureFixture, MonkeyPatch

    patch = monkeypatch
    capture = capsys
    assert isinstance(patch, MonkeyPatch) and isinstance(capture, CaptureFixture)
    saved: list[str] = []

    class Repo:
        def import_dataset(self, bars: object, report: object, quality: object) -> object:
            return "dataset-1", 1, 0

        def bars(self, dataset_id: str) -> list[CanonicalBar]:
            return [sample_bar(), sample_bar("XU100")]

        def save_report(self, report_type: str, dataset_id: str, payload: object) -> str:
            saved.append(report_type)
            return "report-1"

    patch.setattr(cli, "ResearchRepository", Repo)
    patch.setattr(
        cli,
        "download_research",
        lambda start, end: ([sample_bar()], {"quality_score": 100}),
    )
    patch.setattr(
        cli,
        "research_scan",
        lambda bars, warmup: {"candidates": [], "warning": "RESEARCH DATA"},
    )
    result = ReplayResult("run", Decimal("100000"), Decimal("100000"))
    patch.setattr(cli, "run_research_replay", lambda bars, equity, warmup: (result, {"trades": 0}))
    patch.setattr(cli.ReplayRepository, "save", lambda self, result, config: None)

    patch.setattr(sys, "argv", ["app.cli", "research-download"])
    cli.main()
    assert json.loads(capture.readouterr().out)["dataset_id"] == "dataset-1"
    patch.setattr(sys, "argv", ["app.cli", "research-scan", "--dataset-id", "dataset-1"])
    cli.main()
    assert json.loads(capture.readouterr().out)["warning"] == "RESEARCH DATA"
    patch.setattr(sys, "argv", ["app.cli", "research-replay", "--dataset-id", "dataset-1"])
    cli.main()
    assert json.loads(capture.readouterr().out)["trades"] == 0
    assert saved == ["scan", "replay"]


def test_universe_discovery_cli_is_dry_run(monkeypatch: object, capsys: object) -> None:
    from pytest import CaptureFixture, MonkeyPatch

    patch = monkeypatch
    capture = capsys
    assert isinstance(patch, MonkeyPatch) and isinstance(capture, CaptureFixture)
    items = (
        SimpleNamespace(symbol="ASELS", accepted=True, instrument_type="EQUITY"),
        SimpleNamespace(symbol="FUNDX", accepted=False, instrument_type="FUND"),
    )
    discovery = SimpleNamespace(
        instruments=items,
        equities=(items[0],),
        source_timestamp=datetime(2026, 8, 13, tzinfo=UTC),
        snapshot_id="a" * 64,
    )
    patch.setattr(cli.KapMarketUniverseSource, "fetch", lambda self: discovery)
    patch.setattr(sys, "argv", ["app.cli", "universe-discover", "--dry-run"])
    cli.main()
    report = json.loads(capture.readouterr().out)
    assert report["dry_run"] is True
    assert report["equity_accepted"] == 1
    assert report["excluded_by_type"] == {"FUND": 1}
    assert report["duplicate_mappings"] == 0

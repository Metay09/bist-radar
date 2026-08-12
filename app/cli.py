import argparse
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from app.backtest.repository import ReplayRepository
from app.backtest.research_replay import research_scan, run_research_replay
from app.core.config import get_settings
from app.data.canonical import CanonicalBar, dataset_hash
from app.data.readiness import assert_environment_compatible
from app.data.research import ResearchCache, load_universe
from app.data.research_repository import ResearchRepository
from app.data.yfinance_provider import YFinanceResearchProvider


def download_research(start: date, end: date) -> tuple[list[CanonicalBar], dict[str, object]]:
    settings = get_settings()
    assert_environment_compatible(
        settings.data_environment,
        YFinanceResearchProvider.metadata.data_mode,
        False,
        False,
    )
    universe = load_universe(Path("config/universes/bist100.csv"))
    symbols = [member.symbol for member in universe.members if member.active] + ["XU100"]
    provider = YFinanceResearchProvider(
        cache=ResearchCache(
            Path(settings.research_cache_dir), timedelta(hours=settings.research_cache_ttl_hours)
        ),
        price_mode=settings.research_price_mode,
        attempts=settings.research_download_attempts,
    )
    results, failures = provider.download_many(symbols, start, end)
    bars = [bar for result in results.values() for bar in result.bars]
    invalid = sum(result.quality.invalid for result in results.values())
    duplicates = sum(result.quality.duplicates for result in results.values())
    report: dict[str, object] = {
        "provider": "yfinance-research",
        "provider_flags": [
            "RESEARCH_ONLY",
            "UNVERIFIED_SOURCE",
            "CALENDAR_UNVERIFIED",
            "SURVIVORSHIP_BIAS_POSSIBLE",
        ],
        "universe": universe.universe_id,
        "universe_hash": universe.snapshot_hash,
        "requested_symbols": len(symbols),
        "found_symbols": len(results),
        "missing_symbols": failures,
        "requested_start": start.isoformat(),
        "requested_end": end.isoformat(),
        "actual_start": min((bar.timestamp for bar in bars), default=None),
        "actual_end": max((bar.timestamp for bar in bars), default=None),
        "total_bars": len(bars),
        "valid_bars": len(bars),
        "invalid_bars": invalid,
        "duplicates": duplicates,
        "quality_score": max(0, len(bars) / max(1, len(bars) + invalid) * 100),
        "adjusted": settings.research_price_mode == "adjusted",
        "dataset_hash": dataset_hash(bars),
        "downloaded_at": datetime.now(UTC),
    }
    return bars, report


def main() -> None:
    parser = argparse.ArgumentParser(prog="bist-radar research")
    parser.add_argument(
        "command", choices=("research-download", "research-scan", "research-replay")
    )
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dataset-id")
    args = parser.parse_args()
    repository = ResearchRepository()
    if args.command == "research-download":
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=365 * args.years)
        bars, report = download_research(start, end)
        if not args.dry_run:
            dataset_id, inserted, duplicates = repository.import_dataset(
                bars, report, {"quality_score": report["quality_score"]}
            )
            report |= {"dataset_id": dataset_id, "inserted": inserted, "db_duplicates": duplicates}
        print(json.dumps(report, default=str, sort_keys=True))
        return
    if not args.dataset_id:
        parser.error("--dataset-id is required")
    bars = repository.bars(args.dataset_id)
    if args.command == "research-scan":
        report = research_scan(bars, get_settings().min_warmup_bars)
        repository.save_report("scan", args.dataset_id, report)
        print(json.dumps(report, default=str, sort_keys=True))
        return
    result, report = run_research_replay(bars, Decimal("100000"), get_settings().min_warmup_bars)
    ReplayRepository().save(result, {"strategy_id": "radar-v1-frozen"})
    repository.save_report("replay", args.dataset_id, report)
    print(json.dumps(report, default=str, sort_keys=True))


if __name__ == "__main__":
    main()

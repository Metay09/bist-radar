import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from app.backtest.replay_models import Timeframe
from app.backtest.repository import ReplayRepository
from app.backtest.research_replay import research_scan, run_research_replay
from app.core.config import get_settings
from app.data.canonical import CanonicalBar, dataset_hash
from app.data.readiness import assert_environment_compatible
from app.data.research import ResearchCache, completed_daily_bars, load_universe
from app.data.research_repository import ResearchRepository
from app.data.yfinance_provider import YFinanceResearchProvider
from app.intraday.service import IntradayResearchService
from app.universe.service import KapMarketUniverseSource


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
    invalid_by_reason: dict[str, int] = {}
    quality_by_symbol: dict[str, object] = {}
    for symbol, result in sorted(results.items()):
        quality_by_symbol[symbol] = {
            "bars_received": result.quality.bars_received,
            "bars_valid": result.quality.bars_valid,
            "invalid": result.quality.invalid,
            "duplicates": result.quality.duplicates,
            "zero_volume": result.quality.zero_volume,
            "large_gaps": result.quality.large_gaps,
            "invalid_reasons": result.quality.invalid_reasons,
            "quality_score": result.quality.quality_score,
        }
        for reason, count in result.quality.invalid_reasons.items():
            invalid_by_reason[reason] = invalid_by_reason.get(reason, 0) + count
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
        "invalid_by_reason": invalid_by_reason,
        "quality_by_symbol": quality_by_symbol,
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
        "command",
        choices=(
            "research-download",
            "research-scan",
            "research-replay",
            "intraday-download",
            "intraday-scan",
            "universe-discover",
        ),
    )
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--dataset-id")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--timeframe", choices=("5m", "15m", "30m", "60m"), default="15m")
    args = parser.parse_args()
    repository = ResearchRepository()
    if args.command == "universe-discover":
        discovery = KapMarketUniverseSource().fetch()
        excluded: dict[str, int] = {}
        for item in discovery.instruments:
            if not item.accepted:
                excluded[item.instrument_type] = excluded.get(item.instrument_type, 0) + 1
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "source": "Borsa İstanbul linked KAP market registry",
                    "source_timestamp": discovery.source_timestamp,
                    "discovered_instruments": len(discovery.instruments),
                    "equity_accepted": len(discovery.equities),
                    "excluded_by_type": excluded,
                    "duplicate_mappings": len(discovery.equities)
                    - len({x.symbol for x in discovery.equities}),
                    "snapshot_hash": discovery.snapshot_id,
                },
                default=str,
                sort_keys=True,
            )
        )
        return
    if args.command == "intraday-download":
        settings = get_settings()
        universe = load_universe(Path("config/universes/bist100.csv"))
        symbols = [member.symbol for member in universe.members if member.active]
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=args.days)
        timeframe = Timeframe(args.timeframe)
        provider = YFinanceResearchProvider(
            price_mode=settings.research_price_mode, attempts=settings.research_download_attempts
        )
        results, failures = provider.download_many_intraday(
            symbols, start, end, timeframe, settings.research_batch_size
        )
        bars = [bar for result in results.values() for bar in result.bars]
        report: dict[str, object] = {
            "provider": provider.metadata.provider_id,
            "flags": ["RESEARCH_ONLY", "UNVERIFIED_SOURCE", "INTRADAY_RANGE_LIMITED"],
            "timeframe": timeframe.value,
            "requested_symbols": len(symbols),
            "found_symbols": len(results),
            "missing_symbols": failures,
            "bars": len(bars),
            "actual_start": min((bar.timestamp for bar in bars), default=None),
            "actual_end": max((bar.timestamp for bar in bars), default=None),
            "quality": sum(result.quality.bars_valid for result in results.values())
            / max(1, sum(result.quality.bars_received for result in results.values()))
            * 100,
        }
        if not args.dry_run and bars:
            dataset_id, inserted, duplicates = repository.import_dataset(bars, report, report)
            report |= {"dataset_id": dataset_id, "inserted": inserted, "duplicates": duplicates}
        print(json.dumps(report, default=str, sort_keys=True))
        return
    if args.command == "intraday-scan":
        print(json.dumps(IntradayResearchService().run(), default=str, sort_keys=True))
        return
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
    close_hour, close_minute = map(int, get_settings().bist_daily_close_time.split(":"))
    bars = completed_daily_bars(
        bars,
        datetime.now(UTC),
        time(close_hour, close_minute),
        timedelta(minutes=get_settings().research_close_delay_minutes),
    )
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

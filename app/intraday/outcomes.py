from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

import pandas as pd


class LabelStatus(StrEnum):
    LABEL_PENDING = "LABEL_PENDING"
    LABEL_AVAILABLE = "LABEL_AVAILABLE"
    LABEL_UNAVAILABLE = "LABEL_UNAVAILABLE"


HORIZONS = {"15m": 1, "30m": 2, "60m": 4, "120m": 8}
ISTANBUL = ZoneInfo("Europe/Istanbul")
SESSION_CLOSE = time(18, 0)
ENTRY_WINDOW_BARS = 8
MANAGEMENT_WINDOW_BARS = 16


def _number(value: object) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError("numeric outcome field required")
    return float(value)


@dataclass(frozen=True)
class HorizonOutcome:
    horizon: str
    status: LabelStatus
    forward_return: float | None = None
    maximum_favorable_excursion: float | None = None
    maximum_adverse_excursion: float | None = None
    hit_plus_1_percent: bool | None = None
    hit_plus_2_percent: bool | None = None
    hit_plus_3_percent: bool | None = None
    hit_plus_5_percent: bool | None = None
    hit_stop_first: bool | None = None


def _outcome(name: str, price: float, future: pd.DataFrame, stop: float | None) -> HorizonOutcome:
    high_move = float(future.high.max() / price - 1)
    low_move = float(future.low.min() / price - 1)
    stop_first: bool | None = None
    if stop is not None:
        target = price * 1.01
        stop_first = False
        for row in future.itertuples():
            if row.low <= stop:  # conservative same-bar ambiguity
                stop_first = True
                break
            if row.high >= target:
                break
    return HorizonOutcome(
        name,
        LabelStatus.LABEL_AVAILABLE,
        float(future.close.iloc[-1] / price - 1),
        high_move,
        low_move,
        high_move >= 0.01,
        high_move >= 0.02,
        high_move >= 0.03,
        high_move >= 0.05,
        stop_first,
    )


def label_signal(
    signal_time: datetime,
    price: float,
    bars: pd.DataFrame,
    now: datetime,
    *,
    stop: float | None = None,
    dataset_complete: bool = False,
) -> dict[str, HorizonOutcome]:
    if signal_time.tzinfo is None or now.tzinfo is None:
        raise ValueError("timezone-aware timestamps required")
    result: dict[str, HorizonOutcome] = {}
    # A live tracker must never label from bars that exist in a preloaded frame but
    # are still in the simulation future.
    completed_before = now - timedelta(minutes=15)
    future_all = bars.loc[(bars.index > signal_time) & (bars.index <= completed_before)]
    for name, bar_count in HORIZONS.items():
        future = future_all.iloc[:bar_count]
        if len(future) < bar_count:
            status = (
                LabelStatus.LABEL_UNAVAILABLE if dataset_complete else LabelStatus.LABEL_PENDING
            )
            result[name] = HorizonOutcome(name, status)
        else:
            result[name] = _outcome(name, price, future, stop)
    signal_day = signal_time.astimezone(ISTANBUL).date()
    if future_all.empty:
        eod = later_days = future_all
    else:
        if not isinstance(future_all.index, pd.DatetimeIndex):
            raise ValueError("datetime bar index required")
        local_dates = future_all.index.tz_convert(ISTANBUL).date
        eod = future_all.loc[local_dates == signal_day]
        later_days = future_all.loc[local_dates > signal_day]
    next_day = (
        later_days.loc[
            later_days.index.tz_convert(ISTANBUL).date
            == later_days.index.tz_convert(ISTANBUL).date.min()
        ]
        if not later_days.empty
        else later_days
    )
    now_local = now.astimezone(ISTANBUL)
    next_day_date = next_day.index[0].tz_convert(ISTANBUL).date() if not next_day.empty else None
    mature = {
        "EOD": now_local.date() > signal_day
        or (now_local.date() == signal_day and now_local.time() >= SESSION_CLOSE),
        "NEXT_DAY": next_day_date is not None
        and (
            now_local.date() > next_day_date
            or (now_local.date() == next_day_date and now_local.time() >= SESSION_CLOSE)
        ),
    }
    for name, future in (("EOD", eod), ("NEXT_DAY", next_day)):
        if future.empty or not mature[name]:
            status = (
                LabelStatus.LABEL_UNAVAILABLE if dataset_complete else LabelStatus.LABEL_PENDING
            )
            result[name] = HorizonOutcome(name, status)
        else:
            result[name] = _outcome(name, price, future, stop)
    return result


def lifecycle(outcomes: dict[str, HorizonOutcome]) -> str:
    available = sum(item.status == LabelStatus.LABEL_AVAILABLE for item in outcomes.values())
    terminal = sum(item.status != LabelStatus.LABEL_PENDING for item in outcomes.values())
    if terminal == len(outcomes):
        return "FULLY_LABELED"
    if available:
        return "PARTIALLY_LABELED"
    return "OUTCOME_PENDING"


def level_audit(
    signal_time: datetime, bars: pd.DataFrame, plan: dict[str, object]
) -> dict[str, object]:
    """Evaluate an immutable plan only after its entry band trades.

    Entry is valid for eight completed bars. Once active, the plan is managed for
    sixteen bars. Stop wins any same-bar OHLC ambiguity. This is deliberately a
    conservative, reproducible research convention rather than an execution claim.
    """
    future = bars.loc[bars.index > signal_time]
    entry_low = plan.get("entry_zone_low")
    entry_high = plan.get("entry_zone_high")
    stop = plan.get("stop_price")
    raw_targets = plan.get("targets")
    targets = raw_targets if isinstance(raw_targets, list) else []
    if not isinstance(entry_low, (int, float)) or not isinstance(entry_high, (int, float)):
        return {
            "audit_version": 2,
            "entry_hit_at": None,
            "entry_price": None,
            "stop_hit_at": None,
            "target1_hit_at": None,
            "target2_hit_at": None,
            "target3_hit_at": None,
            "ordering": "NONE",
            "result_classification": "PLAN_UNAVAILABLE",
            "highest_target": 0,
            "bars_to_entry": None,
            "bars_after_entry": 0,
            "terminal_at": None,
        }
    low, high = sorted((float(entry_low), float(entry_high)))
    levels: list[float | None] = [
        float(stop) if isinstance(stop, (int, float)) else None,
        *[
            float(item["price"])
            if isinstance(item, dict) and isinstance(item.get("price"), (int, float))
            else None
            for item in targets[:3]
        ],
    ]
    levels += [None] * (4 - len(levels))
    entry_at: datetime | None = None
    entry_price: float | None = None
    entry_index: int | None = None
    entry_window = future.iloc[:ENTRY_WINDOW_BARS]
    for index, (stamp, row) in enumerate(entry_window.iterrows(), start=1):
        if float(row.low) <= high and float(row.high) >= low:
            entry_at = pd.Timestamp(stamp).to_pydatetime()
            opening = float(row.open)
            entry_price = min(max(opening, low), high)
            entry_index = index
            break
    base = {
        "audit_version": 2,
        "entry_hit_at": entry_at,
        "entry_price": entry_price,
        "highest_target": 0,
        "bars_to_entry": entry_index,
        "bars_after_entry": 0,
        "terminal_at": None,
    }
    if entry_index is None:
        terminal = len(future) >= ENTRY_WINDOW_BARS
        return base | {
            "stop_hit_at": None,
            "target1_hit_at": None,
            "target2_hit_at": None,
            "target3_hit_at": None,
            "ordering": "NONE",
            "result_classification": "NO_ENTRY" if terminal else "WAITING_ENTRY",
            "terminal_at": (
                pd.Timestamp(entry_window.index[-1]).to_pydatetime() if terminal else None
            ),
        }

    managed = future.iloc[entry_index - 1 : entry_index - 1 + MANAGEMENT_WINDOW_BARS]
    hits: list[datetime | None] = [None, None, None, None]
    stopped = False
    for stamp, row in managed.iterrows():
        timestamp = pd.Timestamp(stamp).to_pydatetime()
        # Stop is checked first: OHLC cannot reveal intrabar ordering.
        if levels[0] is not None and float(row.low) <= levels[0]:
            hits[0] = timestamp
            stopped = True
            break
        for index in range(1, 4):
            target_level = levels[index]
            if hits[index] is None and target_level is not None and float(row.high) >= target_level:
                hits[index] = timestamp
        if hits[3] is not None:
            break
    highest = 3 if hits[3] else 2 if hits[2] else 1 if hits[1] else 0
    terminal = stopped or highest == 3 or len(managed) >= MANAGEMENT_WINDOW_BARS
    if stopped:
        result = "STOPPED"
        ordering = "STOP_FIRST" if highest == 0 else f"H{highest}_THEN_STOP"
    elif highest == 3:
        result, ordering = "H3_REACHED", "TARGET1_FIRST"
    elif terminal:
        result, ordering = f"EXPIRED_H{highest}", "TARGET1_FIRST" if highest else "NONE"
    else:
        result, ordering = (
            (f"H{highest}_ACTIVE" if highest else "ENTRY_ACTIVE"),
            ("TARGET1_FIRST" if highest else "NONE"),
        )
    return base | {
        "stop_hit_at": hits[0],
        "target1_hit_at": hits[1],
        "target2_hit_at": hits[2],
        "target3_hit_at": hits[3],
        "ordering": ordering,
        "result_classification": result,
        "highest_target": highest,
        "bars_after_entry": len(managed),
        "terminal_at": (
            hits[0]
            or hits[3]
            or (pd.Timestamp(managed.index[-1]).to_pydatetime() if terminal else None)
        ),
    }


def accuracy_buckets(
    rows: list[dict[str, object]], group: str = "score"
) -> list[dict[str, object]]:
    buckets: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        if group == "score":
            score = int(_number(row["radar_score"]))
            key = "90+" if score >= 90 else "80-89" if score >= 80 else "70-79"
        elif group == "rvol":
            value = _number(row["rvol"])
            key = "2+" if value >= 2 else "1.5-2" if value >= 1.5 else "<1.5"
        else:
            key = str(row.get(group, "UNKNOWN"))
        buckets.setdefault(key, []).append(row)
    output = []
    for key, members in sorted(buckets.items()):
        mature = [item for item in members if item.get("hit_plus_1_percent") is not None]
        count = len(mature)
        output.append(
            {
                "bucket": key,
                "signals": len(members),
                "labeled": count,
                "plus_1_hit_rate": (
                    sum(bool(item["hit_plus_1_percent"]) for item in mature) / count
                    if count
                    else None
                ),
                "average_mfe": (
                    sum((_number(item["maximum_favorable_excursion"]) for item in mature), 0.0)
                    / count
                    if count
                    else None
                ),
                "average_mae": (
                    sum((_number(item["maximum_adverse_excursion"]) for item in mature), 0.0)
                    / count
                    if count
                    else None
                ),
            }
        )
    return output

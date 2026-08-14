from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

POLICY_VERSION = "adaptive-v1-h1-partial-trailing"
TERMINAL_PRE = {
    "CANCELLED_DECAY",
    "CANCELLED_STRUCTURE",
    "EXPIRED",
    "CHASED",
    "NO_ENTRY",
}
TERMINAL_POST = {
    "HARD_STOP",
    "TRAILING_STOP",
    "TIME_EXIT",
    "THESIS_INVALIDATED",
    "SESSION_EXIT",
    "H3_REACHED",
}


@dataclass(frozen=True)
class AdaptiveConfig:
    entry_ttl_bars: int = 8
    max_holding_bars: int = 16
    min_risk_reward: float = 2.0
    transaction_cost_rate: float = 0.001
    profit_policy: str = "H1_PARTIAL_TRAILING"
    policy_version: str = POLICY_VERSION


@dataclass
class AdaptiveResult:
    state: str
    health: str
    action: dict[str, object]
    events: list[dict[str, object]] = field(default_factory=list)
    plans: list[dict[str, object]] = field(default_factory=list)
    entry_time: datetime | None = None
    entry_price: float | None = None
    initial_stop: float | None = None
    active_stop: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    outcome: str | None = None
    highest_target: int = 0
    metrics: dict[str, object] = field(default_factory=dict)


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _plan_values(plan: dict[str, object]) -> tuple[float, float, float, list[float]]:
    low, high, stop = (
        _num(plan.get(key)) for key in ("entry_zone_low", "entry_zone_high", "stop_price")
    )
    raw_targets = plan.get("targets")
    targets = (
        [
            float(item["price"])
            for item in raw_targets
            if isinstance(item, dict) and isinstance(item.get("price"), (int, float))
        ]
        if isinstance(raw_targets, list)
        else []
    )
    if low is None or high is None or stop is None or len(targets) < 3:
        raise ValueError("complete immutable trade plan required")
    return min(low, high), max(low, high), stop, targets[:3]


def _context(frame: pd.DataFrame) -> dict[str, float | None]:
    close = frame.close.astype(float)
    volume = frame.volume.astype(float)
    typical = (frame.high.astype(float) + frame.low.astype(float) + close) / 3
    cumulative = volume.cumsum()
    vwap = (
        float((typical * volume).cumsum().iloc[-1] / cumulative.iloc[-1])
        if cumulative.iloc[-1]
        else None
    )
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    momentum = float(close.iloc[-1] / close.iloc[-4] - 1) if len(close) >= 4 else None
    base_volume = float(volume.iloc[-9:-1].mean()) if len(volume) >= 9 else None
    rvol = float(volume.iloc[-1] / base_volume) if base_volume and base_volume > 0 else None
    previous = close.shift(1)
    true_range = pd.concat(
        [
            frame.high.astype(float) - frame.low.astype(float),
            (frame.high.astype(float) - previous).abs(),
            (frame.low.astype(float) - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(14).mean()) if len(true_range) else None
    return {
        "close": float(close.iloc[-1]),
        "vwap": vwap,
        "ema20": ema20,
        "momentum": momentum,
        "rvol": rvol,
        "atr": atr,
    }


def _health(
    context: dict[str, float | None], initial: dict[str, object], age: int
) -> tuple[str, list[str], str | None]:
    reasons: list[str] = []
    close, vwap, ema20 = context["close"], context["vwap"], context["ema20"]
    momentum, rvol = context["momentum"], context["rvol"]
    initial_rvol = _num(initial.get("rvol"))
    if close is not None and vwap is not None and ema20 is not None and momentum is not None:
        if close < vwap and close < ema20 and momentum < -0.01:
            return (
                "GEÇERSİZ",
                ["Fiyat VWAP ve EMA20 altına indi", "Üç bar momentumu negatif"],
                "CANCELLED_STRUCTURE",
            )
    if age >= 3 and rvol is not None and initial_rvol is not None and momentum is not None:
        if rvol < max(0.5, initial_rvol * 0.35) and momentum < 0:
            return (
                "BOZULDU",
                ["Göreli hacim sinyal anına göre belirgin düştü", "Momentum negatif"],
                "CANCELLED_DECAY",
            )
        if rvol < initial_rvol * 0.6 or momentum < 0:
            reasons.append("Hacim veya momentum sinyal anına göre zayıflıyor")
    if reasons:
        return "ZAYIFLIYOR", reasons, None
    return "GÜÇLÜ", ["Yapı ve momentum iptal eşiğini ihlal etmedi"], None


def evaluate_adaptive_setup(
    signal_time: datetime,
    bars: pd.DataFrame,
    features: dict[str, object],
    plan: dict[str, object],
    now: datetime,
    *,
    config: AdaptiveConfig | None = None,
    data_usable: bool = True,
) -> AdaptiveResult:
    """Replay one setup using completed bars only and next-bar-open decisions."""
    config = config or AdaptiveConfig()
    low, high, stop, targets = _plan_values(plan)
    completed = bars.loc[(bars.index > signal_time) & (bars.index <= now - timedelta(minutes=15))]
    result = AdaptiveResult("DETECTED", "GÜÇLÜ", {})
    result.plans.append(
        {
            "version": 1,
            "created_at": signal_time,
            "effective_at": signal_time,
            "reason": "SIGNAL_PLAN",
            "plan": plan,
        }
    )

    def event(
        stamp: datetime, kind: str, new_state: str, payload: dict[str, object] | None = None
    ) -> None:
        old = result.state
        result.events.append(
            {
                "sequence": len(result.events) + 1,
                "event_time": stamp,
                "event_type": kind,
                "state_from": old,
                "state_to": new_state,
                "payload": payload or {},
            }
        )
        result.state = new_state

    event(signal_time, "SIGNAL_DETECTED", "DETECTED", {"policy_version": config.policy_version})
    pending_decision: tuple[str, dict[str, object]] | None = (
        "ARMED",
        {"reason": ["İlk completed bar bekleniyor"]},
    )
    entry_bar_index: int | None = None
    active_stop = stop
    mfe = mae = 0.0
    realized_r: float | None = None

    for index, (stamp, row) in enumerate(completed.iterrows(), start=1):
        timestamp = pd.Timestamp(stamp).to_pydatetime()
        # Decisions made at the prior close become effective at this bar open.
        if pending_decision:
            state, payload = pending_decision
            pending_decision = None
            if state == "ENTRY_ACTIVATED":
                opening = float(row.open)
                risk = opening - stop
                if opening > high + max(risk, 0) * 0.5:
                    event(
                        timestamp,
                        "ENTRY_REJECTED_CHASE",
                        "CHASED",
                        {"open": opening, "entry_high": high},
                    )
                    result.outcome = "CHASED"
                    break
                if risk <= 0 or (targets[0] - opening) / risk < config.min_risk_reward:
                    event(
                        timestamp,
                        "ENTRY_REJECTED_RR",
                        "NO_ENTRY",
                        {"reason": "RISK_REWARD_DETERIORATED"},
                    )
                    result.outcome = "NO_ENTRY_STRUCTURE"
                    break
                result.entry_time, result.entry_price = timestamp, opening
                result.initial_stop = result.active_stop = stop
                active_stop = stop
                entry_bar_index = index
                event(
                    timestamp,
                    "ENTRY_FILLED_NEXT_OPEN",
                    "ENTRY_ACTIVATED",
                    {"entry_price": opening, "plan_version": len(result.plans)},
                )
            else:
                event(timestamp, "STATE_REVIEW", state, payload)

        if result.state in TERMINAL_PRE | TERMINAL_POST:
            break

        history = bars.loc[bars.index <= stamp]
        context = _context(history)
        if result.entry_time is None:
            health, reasons, invalid = _health(context, features, index)
            result.health = health
            if not data_usable:
                result.action = {
                    "action": "ALMA_VERI_ESKI",
                    "reason": ["Provider veya veri tazeliği uygun değil"],
                    "valid_until": timestamp,
                    "next_review": timestamp + timedelta(minutes=15),
                    "data_timestamp": timestamp,
                }
                continue
            if invalid:
                touched = float(row.low) <= high and float(row.high) >= low
                event(
                    timestamp,
                    "SETUP_INVALIDATED",
                    invalid,
                    {"reason": reasons, "zone_touched": touched},
                )
                result.outcome = (
                    "NO_ENTRY_DECAY" if invalid == "CANCELLED_DECAY" else "NO_ENTRY_STRUCTURE"
                )
                break
            if index >= config.entry_ttl_bars:
                event(
                    timestamp, "ENTRY_TTL_EXPIRED", "EXPIRED", {"ttl_bars": config.entry_ttl_bars}
                )
                result.outcome = "NO_ENTRY_EXPIRED"
                break
            risk = high - stop
            if float(row.close) > high + risk * 0.5:
                event(
                    timestamp,
                    "SETUP_CHASED",
                    "CHASED",
                    {"close": float(row.close), "entry_high": high},
                )
                result.outcome = "CHASED"
                break
            touched = float(row.low) <= high and float(row.high) >= low
            if touched:
                pending_decision = ("ENTRY_ACTIVATED", {"reason": reasons})
                event(
                    timestamp,
                    "ENTRY_CONDITIONS_READY",
                    "ENTRY_READY",
                    {"reason": reasons, "execute": "NEXT_BAR_OPEN"},
                )
            else:
                next_state = "WAITING_PULLBACK" if float(row.close) > high else "ARMED"
                if result.state != next_state:
                    event(timestamp, "SETUP_REVIEWED", next_state, {"reason": reasons})
            continue

        assert result.entry_price is not None and entry_bar_index is not None
        risk = result.entry_price - stop
        mfe = max(mfe, (float(row.high) - result.entry_price) / risk)
        mae = min(mae, (float(row.low) - result.entry_price) / risk)
        # Intrabar ordering is unknowable: stop is conservative first.
        if float(row.low) <= active_stop:
            outcome = "STOP_BEFORE_H1" if result.highest_target == 0 else "TRAILING_EXIT"
            state = "HARD_STOP" if result.highest_target == 0 else "TRAILING_STOP"
            result.exit_time, result.exit_price, result.outcome = timestamp, active_stop, outcome
            realized_r = (active_stop - result.entry_price) / risk
            event(
                timestamp, state, state, {"exit_price": active_stop, "conservative_ordering": True}
            )
            break
        for target_index, target in enumerate(targets, start=1):
            if target_index > result.highest_target and float(row.high) >= target:
                result.highest_target = target_index
                event(
                    timestamp,
                    f"H{target_index}_TOUCHED",
                    f"H{target_index}_REACHED",
                    {"price": target},
                )
                if target_index == 1:
                    tightened = max(active_stop, result.entry_price)
                    if tightened > active_stop:
                        active_stop = tightened
                        result.active_stop = active_stop
                        event(
                            timestamp,
                            "STOP_TIGHTENED",
                            "PROGRESSING",
                            {"new_stop": active_stop, "rule": "BREAKEVEN_AFTER_H1"},
                        )
                if target_index == 3:
                    result.exit_time, result.exit_price, result.outcome = (
                        timestamp,
                        target,
                        "H3_EXIT",
                    )
                    realized_r = (target - result.entry_price) / risk
                    result.state = "H3_REACHED"
                    break
        if result.outcome:
            break
        holding = index - entry_bar_index + 1
        if result.highest_target >= 1 and context["atr"] is not None:
            trail = float(context["close"] or result.entry_price) - 2 * float(context["atr"])
            tightened = max(active_stop, min(trail, float(row.close)))
            if tightened > active_stop:
                active_stop = tightened
                result.active_stop = active_stop
                event(
                    timestamp,
                    "STOP_TIGHTENED",
                    "PROGRESSING",
                    {"new_stop": active_stop, "rule": "2_ATR_TRAIL"},
                )
        momentum = context["momentum"]
        if (
            holding >= 4
            and result.highest_target == 0
            and momentum is not None
            and momentum < -0.01
            and context["close"] is not None
            and context["vwap"] is not None
            and context["close"] < context["vwap"]
        ):
            pending_decision = (
                "THESIS_INVALIDATED",
                {"reason": ["Momentum ve VWAP yapısı bozuldu"]},
            )
        elif holding >= config.max_holding_bars:
            if result.highest_target == 0 and mfe <= 0.5 and result.state != "STALLED":
                event(timestamp, "TRADE_STALLED", "STALLED", {"mfe_r": mfe})
            pending_decision = ("TIME_EXIT", {"reason": ["Maksimum holding süresi doldu"]})
        elif holding >= max(4, config.max_holding_bars // 2) and mfe < 0.5:
            if result.state != "STALLED":
                event(timestamp, "TRADE_STALLED", "STALLED", {"mfe_r": mfe})
        elif result.state not in {"PROGRESSING", "H1_REACHED", "H2_REACHED"}:
            event(timestamp, "POSITION_ACTIVE", "ACTIVE", {})

        if pending_decision and pending_decision[0] in {"TIME_EXIT", "THESIS_INVALIDATED"}:
            # Exit decision is applied only when another completed bar exists.
            if index < len(completed):
                next_row = completed.iloc[index]
                next_stamp = pd.Timestamp(completed.index[index]).to_pydatetime()
                exit_price = float(next_row.open)
                exit_state, payload = pending_decision
                result.exit_time, result.exit_price = next_stamp, exit_price
                realized_r = (exit_price - result.entry_price) / risk
                if exit_state == "TIME_EXIT":
                    result.outcome = (
                        "TIME_EXIT_PROFIT"
                        if realized_r > 0.1
                        else "TIME_EXIT_LOSS"
                        if realized_r < -0.1
                        else "TIME_EXIT_FLAT"
                    )
                else:
                    result.outcome = "THESIS_INVALIDATED"
                event(
                    next_stamp,
                    "EXIT_FILLED_NEXT_OPEN",
                    exit_state,
                    payload | {"exit_price": exit_price},
                )
                break

    last_stamp = (
        pd.Timestamp(completed.index[-1]).to_pydatetime() if not completed.empty else signal_time
    )
    action_map = {
        "DETECTED": "BEKLE",
        "ARMED": "BEKLE",
        "WAITING_PULLBACK": "BEKLE",
        "ENTRY_READY": "ALIM_ICIN_HAZIR",
        "ENTRY_ACTIVATED": "KORU",
        "ACTIVE": "KORU",
        "PROGRESSING": "RISK_AZALT",
        "STALLED": "ZAMAN_CIKISI",
        "CANCELLED_DECAY": "ALMA_SETUP_BOZULDU",
        "CANCELLED_STRUCTURE": "ALMA_SETUP_BOZULDU",
        "EXPIRED": "ALMA_SETUP_BOZULDU",
        "CHASED": "ALMA_GEC_KALINDI",
        "HARD_STOP": "STOP",
        "TRAILING_STOP": "STOP",
        "TIME_EXIT": "ZAMAN_CIKISI",
        "THESIS_INVALIDATED": "TEZ_BOZULDU",
        "H3_REACHED": "HEDEF",
    }
    last_payload = result.events[-1]["payload"]
    reasons = (
        last_payload.get("reason", [str(result.events[-1]["event_type"])])
        if isinstance(last_payload, dict)
        else [str(result.events[-1]["event_type"])]
    )
    result.action = {
        "action": action_map.get(result.state, "BEKLE"),
        "reason": reasons,
        "valid_until": last_stamp + timedelta(minutes=15),
        "next_review": last_stamp + timedelta(minutes=15),
        "data_timestamp": last_stamp,
    }
    result.metrics = {
        "mfe_r": mfe,
        "mae_r": mae,
        "realized_r": realized_r,
        "realized_r_after_cost": realized_r - config.transaction_cost_rate * 2
        if realized_r is not None
        else None,
        "bars_to_entry": next(
            (i for i, e in enumerate(result.events) if e["event_type"] == "ENTRY_FILLED_NEXT_OPEN"),
            None,
        ),
        "bars_in_trade": (len(completed) - entry_bar_index + 1) if entry_bar_index else 0,
        "profit_policy": config.profit_policy,
    }
    result.active_stop = active_stop if result.entry_time else None
    return result

from datetime import UTC, datetime
from decimal import Decimal

from app.risk.engine import calculate_stop, position_size

D = Decimal


def _decimal(value: object) -> Decimal:
    return D(str(value))


def build_research_trade_plan(
    candidate: dict[str, object],
    recent_lows: list[object],
    *,
    account_equity: Decimal,
    risk_percent: Decimal,
    max_position_percent: Decimal,
    now: datetime | None = None,
    stale_minutes: int = 45,
) -> dict[str, object]:
    """Build an advisory plan without changing the underlying Radar decision."""
    symbol = str(candidate.get("symbol", ""))
    timestamp_value = candidate.get("timestamp")
    timestamp = (
        datetime.fromisoformat(timestamp_value)
        if isinstance(timestamp_value, str)
        else timestamp_value
        if isinstance(timestamp_value, datetime)
        else None
    )
    base: dict[str, object] = {
        "symbol": symbol,
        "timestamp": timestamp,
        "research_only": True,
        "status": "GECERSIZ",
        "explanation": [],
    }
    try:
        reference = _decimal(candidate["price"])
        atr = _decimal(candidate["atr"])
        swing = min(_decimal(value) for value in recent_lows[-10:])
        if reference <= 0 or atr <= 0:
            raise ValueError("positive price and ATR required")
        breakout_distance = _decimal(candidate.get("breakout_distance", 0))
        breakout = reference * (D("1") + breakout_distance / D("100"))
        zone_low = breakout - atr * D("0.25")
        zone_high = breakout + atr * D("0.10")
        entry = (zone_low + zone_high) / 2
        stop, stop_reason = calculate_stop(entry, atr, swing)
        risk = entry - stop
        targets = [entry + risk * multiple for multiple in (D("1.5"), D("2.5"), D("3"))]
        rr = (targets[1] - entry) / risk
        quantity = position_size(
            account_equity,
            entry,
            stop,
            risk_percent=risk_percent,
            max_position_percent=max_position_percent,
        )
    except (KeyError, ValueError, ArithmeticError):
        base["explanation"] = ["Henüz güvenli işlem planı oluşturmak için yeterli bağlam yok."]
        return base

    if reference <= stop:
        status = "GECERSIZ"
    elif reference > zone_high + atr * D("0.50"):
        status = "KACMIS_KOVALAMA"
    elif reference >= breakout:
        status = "BREAKOUT_ONAYI"
    elif zone_low <= reference <= zone_high:
        status = "GIRIS_BOLGESINDE"
    else:
        status = "GIRIS_BEKLENIYOR"

    checked_at = (now or datetime.now(UTC)).astimezone(UTC)
    age_minutes = (
        max(D("0"), D(str((checked_at - timestamp.astimezone(UTC)).total_seconds() / 60)))
        if timestamp
        else None
    )
    explanations = [
        f"Stop: {stop_reason}",
        f"RVOL {float(_decimal(candidate.get('rvol', 0))):.2f}x",
        f"Breakout mesafesi %{float(_decimal(candidate.get('breakout_distance', 0))):.2f}",
    ]
    if _decimal(candidate.get("vwap_distance", 0)) > 0:
        explanations.append("Fiyat VWAP üzerinde.")
    if (
        _decimal(candidate.get("ema9_distance", 0)) > 0
        and _decimal(candidate.get("ema20_distance", 0)) > 0
    ):
        explanations.append("Kısa dönem EMA bağlamı pozitif.")
    if age_minutes is None or age_minutes > stale_minutes:
        explanations.append("Veri eski; plan yalnız son tamamlanmış araştırma barına dayanır.")

    def money(value: Decimal) -> float:
        return float(value.quantize(D("0.01")))

    return base | {
        "reference_price": money(reference),
        "entry_zone_low": money(zone_low),
        "entry_zone_high": money(zone_high),
        "breakout_trigger": money(breakout),
        "stop_price": money(stop),
        "stop_distance_percent": float(((entry - stop) / entry * 100).quantize(D("0.01"))),
        "targets": [
            {
                "price": money(target),
                "return_percent": float(((target / entry - 1) * 100).quantize(D("0.01"))),
            }
            for target in targets
        ],
        "risk_reward": float(rr.quantize(D("0.01"))),
        "status": status,
        "explanation": explanations,
        "data_age_minutes": float(age_minutes) if age_minutes is not None else None,
        "stale": age_minutes is None or age_minutes > stale_minutes,
        "position_sizing": {
            "account_equity": float(account_equity),
            "max_risk_percent": float(risk_percent),
            "allowed_risk_amount": float(account_equity * risk_percent / 100),
            "suggested_position_value": money(quantity * entry),
            "estimated_quantity": int(quantity),
            "advisory_only": True,
        },
    }

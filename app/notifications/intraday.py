from app.intraday.core import IntradaySnapshot


def research_payload(snapshot: IntradaySnapshot, shadow: dict[str, float] | None = None) -> str:
    lines = [
        "🔥 BIST RADAR — RESEARCH",
        "",
        snapshot.symbol,
        f"Radar: {snapshot.radar_score}",
        f"15m RVOL: {snapshot.rvol:.2f}x",
        f"Early momentum: {snapshot.early_momentum_score}",
        f"Data timestamp: {snapshot.timestamp.isoformat()}",
        f"Data latency: {snapshot.provider_latency_seconds / 60:.1f}m",
    ]
    if shadow:
        lines.extend(["", "Shadow ML:"] + [f"{key}: {value:.1%}" for key, value in shadow.items()])
        lines.append("Mode: SHADOW")
    lines.extend(["", "RESEARCH / PAPER ONLY", "Bu sistem yatırım tavsiyesi değildir."])
    return "\n".join(lines)

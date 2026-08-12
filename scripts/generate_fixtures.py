from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[1] / "tests" / "fixtures"
ROOT.mkdir(parents=True, exist_ok=True)


def frame(symbol: str, close: np.ndarray, volume: np.ndarray) -> pd.DataFrame:
    noise = np.sin(np.arange(len(close))) * 0.12
    open_ = close - noise
    high = np.maximum(open_, close) + 0.35
    low = np.minimum(open_, close) - 0.35
    dates = pd.date_range("2025-01-01", periods=len(close), freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "symbol": symbol,
            "timestamp": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


n = 260
x = np.arange(n)
rally = 20 + x * 0.08 + np.sin(x / 7) * 0.3
rally[-1] = rally[-21:-1].max() + 1.2
rally_volume = np.full(n, 1_000_000.0)
rally_volume[-1] = 3_500_000
flat = 30 + np.sin(x / 6) * 0.4
selloff = 60 - x * 0.1 + np.sin(x / 8) * 0.3
xu100 = 100 + x * 0.05 + np.sin(x / 9) * 0.5
for name, data, volume in [
    ("rally", rally, rally_volume),
    ("flat", flat, np.full(n, 900_000.0)),
    ("selloff", selloff, np.full(n, 1_100_000.0)),
    ("xu100", xu100, np.full(n, 5_000_000.0)),
]:
    frame(name.upper(), data, volume).to_csv(ROOT / f"{name}.csv", index=False)
bad = frame("BAD_DATA", flat, np.full(n, 100.0))
bad.loc[n - 1, "low"] = bad.loc[n - 1, "high"] + 2
bad.to_csv(ROOT / "bad_data.csv", index=False)

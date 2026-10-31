import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_candles(n: int = 3000, seed: int = 7, start: str = "2026-03-02", drift: float = 0.0,
                 vol: float = 0.0004, price: float = 1.10) -> pd.DataFrame:
    """کندل‌های ۵ دقیقه‌ای مصنوعی با رژیم‌های متغیر (روند/رنج) — فقط روزهای کاری."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=n * 2, freq="5min", tz="UTC")
    idx = idx[idx.weekday < 5][:n]
    regime = np.sin(np.arange(n) / 400.0)
    rets = rng.normal(drift + 0.00004 * regime, vol, n)
    close = price * np.exp(np.cumsum(rets))
    open_ = np.r_[price, close[:-1]]
    spread_h = np.abs(rng.normal(0, vol * price * 0.7, n))
    spread_l = np.abs(rng.normal(0, vol * price * 0.7, n))
    high = np.maximum(open_, close) + spread_h
    low = np.minimum(open_, close) - spread_l
    hours = idx.hour
    tv = rng.integers(50, 150, n) * (1 + ((hours >= 7) & (hours <= 16)))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "tick_volume": tv.astype(float), "spread": 10.0}, index=idx)


@pytest.fixture
def candles():
    return make_candles()

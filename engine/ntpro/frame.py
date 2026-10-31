"""محاسبه‌ی یک‌جای اندیکاتورها روی کل سری (برداری) تا هم موتور زنده و هم بک‌تست سریع باشند.

همه‌ی ستون‌ها فقط از داده‌ی گذشته استفاده می‌کنند (بدون نگاه به آینده)، پس خواندن ردیف i در بک‌تست مجاز است.
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind


def compute(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    f = pd.DataFrame(index=df.index)
    for n in (9, 21, 50, 200):
        f[f"ema{n}"] = ind.ema(c, n)
    f["atr"] = ind.atr(df, 14)
    f["rsi"] = ind.rsi(c, 14)
    f["stoch_k"], f["stoch_d"] = ind.stochastic(df)
    f["macd"], f["macd_sig"], f["macd_hist"] = ind.macd(c)
    f["bb_lo"], f["bb_mid"], f["bb_hi"] = ind.bollinger(c)
    f["kc_lo"], f["kc_mid"], f["kc_hi"] = ind.keltner(df)
    f["adx"], f["pdi"], f["mdi"] = ind.adx(df)
    f["st_line"], f["st_dir"] = ind.supertrend(df)
    f["vwap"] = ind.session_vwap(df)
    f["rvol"] = ind.relative_volume(df)
    f["body"] = (df["close"] - df["open"]).abs()
    f["range"] = df["high"] - df["low"]
    f["squeeze"] = (f["bb_lo"] > f["kc_lo"]) & (f["bb_hi"] < f["kc_hi"])
    f["atr_pct"] = f["atr"].rolling(200, min_periods=30).rank(pct=True).fillna(0.5)
    slope = f["ema200"] - f["ema200"].shift(10)
    f["trend_dir"] = 0
    f.loc[(c > f["ema200"]) & (slope > 0), "trend_dir"] = 1
    f.loc[(c < f["ema200"]) & (slope < 0), "trend_dir"] = -1
    f["htf_dir"] = htf_alignment(df)
    return f


def _trend_series(h: pd.DataFrame) -> pd.Series:
    c = h["close"]
    ef, es = ind.ema(c, 50), ind.ema(c, 200)
    d = pd.Series(0, index=h.index)
    d[(c > ef) & (ef > es)] = 1
    d[(c < ef) & (ef < es)] = -1
    return d


def htf_alignment(df: pd.DataFrame, rules: tuple[str, ...] = ("15min", "1h")) -> pd.Series:
    """جهت روند M15 و H1 (فقط کندل‌های بسته‌شده). اگر هم‌جهت بودند همان جهت، وگرنه ۰."""
    m5_close = df.index + pd.Timedelta(minutes=5)
    out = None
    for rule in rules:
        h = ind.resample(df, rule)
        if len(h) < 60:
            return pd.Series(0, index=df.index)
        d = _trend_series(h)
        d.index = d.index + pd.Timedelta(rule)          # زمان بسته شدن کندل HTF
        aligned = d.reindex(d.index.union(m5_close)).ffill().reindex(m5_close).fillna(0).to_numpy()
        out = aligned if out is None else (out * (out == aligned))
    return pd.Series(out, index=df.index).astype(int)

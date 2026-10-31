"""اندیکاتورها با numpy/pandas (بدون وابستگی به TA-Lib). ورودی: DataFrame با open/high/low/close/tick_volume."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """میانگین وایلدر."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift(1)
    return pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return rma(true_range(df), n)


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = rma(d.clip(lower=0), n)
    dn = rma((-d).clip(lower=0), n)
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> tuple[pd.Series, pd.Series]:
    ll = df["low"].rolling(k).min()
    hh = df["high"].rolling(k).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    kk = raw.rolling(smooth).mean()
    return kk.fillna(50), kk.rolling(d).mean().fillna(50)


def macd(s: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(s, fast) - ema(s, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0):
    mid = sma(s, n)
    sd = s.rolling(n).std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def keltner(df: pd.DataFrame, n: int = 20, mult: float = 1.5):
    mid = ema(df["close"], n)
    a = atr(df, n)
    return mid - mult * a, mid, mid + mult * a


def adx(df: pd.DataFrame, n: int = 14) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = rma(true_range(df), n)
    pdi = 100 * rma(plus_dm, n) / tr.replace(0, np.nan)
    mdi = 100 * rma(minus_dm, n) / tr.replace(0, np.nan)
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return rma(dx.fillna(0), n), pdi.fillna(0), mdi.fillna(0)


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> tuple[pd.Series, pd.Series]:
    """خروجی: (خط سوپرترند، جهت +1/-1)."""
    a = atr(df, n).to_numpy()
    hl2 = ((df["high"] + df["low"]) / 2).to_numpy()
    close = df["close"].to_numpy()
    upper = hl2 + mult * a
    lower = hl2 - mult * a
    fu, fl = upper.copy(), lower.copy()
    direction = np.ones(len(df))
    line = np.full(len(df), np.nan)
    for i in range(1, len(df)):
        fu[i] = upper[i] if (upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if direction[i - 1] == -1 and close[i] > fu[i - 1]:
            direction[i] = 1
        elif direction[i - 1] == 1 and close[i] < fl[i - 1]:
            direction[i] = -1
        else:
            direction[i] = direction[i - 1]
        line[i] = fl[i] if direction[i] == 1 else fu[i]
    return pd.Series(line, index=df.index), pd.Series(direction, index=df.index)


def session_vwap(df: pd.DataFrame) -> pd.Series:
    """VWAP روزانه (شروع از ۰۰:۰۰ UTC) با Tick Volume."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["tick_volume"].replace(0, 1.0)
    day = df.index.floor("D")
    pv = (tp * vol).groupby(day).cumsum()
    vv = vol.groupby(day).cumsum()
    return pv / vv


def relative_volume(df: pd.DataFrame, lookback_days: int = 20) -> pd.Series:
    """حجم نسبت به میانگین همان ساعت/دقیقه در روزهای قبل."""
    key = df.index.hour * 60 + df.index.minute
    vol = df["tick_volume"].astype(float)
    avg = vol.groupby(key).transform(lambda x: x.shift(1).rolling(lookback_days, min_periods=3).mean())
    return (vol / avg.replace(0, np.nan)).fillna(1.0)


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[pd.Series, pd.Series]:
    """سقف/کف‌های سوئینگ (فرکتال). مقدار True در کندلی که سوئینگ است — فقط با تأخیر right قابل دانستن است."""
    h, l = df["high"], df["low"]
    w = left + right + 1
    sh = h == h.rolling(w, center=True).max()
    sl = l == l.rolling(w, center=True).min()
    # کندل‌های آخر (بدون right کندل بعدی) هنوز تأیید نشده‌اند
    if right > 0:
        sh.iloc[-right:] = False
        sl.iloc[-right:] = False
    return sh.fillna(False), sl.fillna(False)


def divergence(price: pd.Series, osc: pd.Series, lookback: int = 30) -> int:
    """واگرایی ساده در lookback کندل آخر: +1 صعودی (کف پایین‌تر قیمت، کف بالاتر اسیلاتور)، -1 نزولی، 0 هیچ."""
    if len(price) < lookback + 2:
        return 0
    p, o = price.iloc[-lookback:], osc.iloc[-lookback:]
    half = lookback // 2
    p1, p2 = p.iloc[:half], p.iloc[half:]
    o1, o2 = o.iloc[:half], o.iloc[half:]
    if p2.max() > p1.max() and o2.max() < o1.max() - 1e-9:
        return -1
    if p2.min() < p1.min() and o2.min() > o1.min() + 1e-9:
        return 1
    return 0


def resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """ساخت تایم‌فریم بالاتر (مثلاً '15min' یا '1h') از کندل‌های پایین‌تر."""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum"}
    if "spread" in df:
        agg["spread"] = "mean"
    return df.resample(rule, label="left", closed="left").agg(agg).dropna(subset=["open"])

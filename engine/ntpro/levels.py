"""سطوح کلیدی: حمایت/مقاومت، نواحی نقدینگی (Equal Highs/Lows، سقف/کف روز و سشن قبل) و Volume Profile."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Level:
    price: float
    kind: str          # sr | eqh | eql | pdh | pdl | asia_high | asia_low | poc | vah | val
    strength: float    # تعداد برخورد/اهمیت


def support_resistance(df: pd.DataFrame, lookback: int = 300, tol_atr: float = 0.35) -> list[Level]:
    """سطوح از خوشه‌بندی سوئینگ‌ها؛ قدرت = تعداد برخورد."""
    d = df.iloc[-lookback:]
    if len(d) < 30:
        return []
    sh, sl = ind.swing_points(d, 3, 3)
    pts = list(d["high"][sh]) + list(d["low"][sl])
    if not pts:
        return []
    tol = float(ind.atr(d, 14).iloc[-1]) * tol_atr
    pts.sort()
    clusters: list[list[float]] = [[pts[0]]]
    for p in pts[1:]:
        if p - clusters[-1][-1] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    return [Level(float(np.mean(c)), "sr", float(len(c))) for c in clusters if len(c) >= 2]


def equal_highs_lows(df: pd.DataFrame, lookback: int = 150, tol_atr: float = 0.1) -> list[Level]:
    d = df.iloc[-lookback:]
    if len(d) < 20:
        return []
    sh, sl = ind.swing_points(d, 2, 2)
    tol = float(ind.atr(d, 14).iloc[-1]) * tol_atr
    out = []
    for kind, series in (("eqh", d["high"][sh]), ("eql", d["low"][sl])):
        vals = series.to_numpy()
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                if abs(vals[i] - vals[j]) <= tol:
                    out.append(Level(float((vals[i] + vals[j]) / 2), kind, 2.0))
    return out


def prior_day_levels(df: pd.DataFrame) -> list[Level]:
    days = df.groupby(df.index.floor("D"))
    keys = list(days.groups.keys())
    if len(keys) < 2:
        return []
    prev = days.get_group(keys[-2])
    return [Level(float(prev["high"].max()), "pdh", 3.0), Level(float(prev["low"].min()), "pdl", 3.0)]


def asia_range(df: pd.DataFrame, day=None) -> tuple[float, float] | None:
    """رنج سشن آسیا (۰۰:۰۰ تا ۰۷:۰۰ UTC) روز جاری."""
    if len(df) == 0:
        return None
    day = day or df.index[-1].floor("D")
    m = (df.index >= day) & (df.index < day + pd.Timedelta(hours=7))
    a = df[m]
    if len(a) < 12:
        return None
    return float(a["high"].max()), float(a["low"].min())


def volume_profile(df: pd.DataFrame, bins: int = 40, value_area: float = 0.7) -> dict:
    """POC/VAH/VAL از Tick Volume (توزیع حجم هر کندل روی بازه‌ی high-low)."""
    if len(df) < 10:
        return {}
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return {}
    edges = np.linspace(lo, hi, bins + 1)
    hist = np.zeros(bins)
    for h, l, v in zip(df["high"].to_numpy(), df["low"].to_numpy(), df["tick_volume"].to_numpy()):
        i0 = max(0, np.searchsorted(edges, l, "right") - 1)
        i1 = min(bins - 1, np.searchsorted(edges, h, "right") - 1)
        hist[i0:i1 + 1] += v / (i1 - i0 + 1)
    poc = int(hist.argmax())
    total, acc = hist.sum(), hist[poc]
    lo_i = hi_i = poc
    while acc < value_area * total and (lo_i > 0 or hi_i < bins - 1):
        down = hist[lo_i - 1] if lo_i > 0 else -1
        up = hist[hi_i + 1] if hi_i < bins - 1 else -1
        if up >= down:
            hi_i += 1
            acc += hist[hi_i]
        else:
            lo_i -= 1
            acc += hist[lo_i]
    mid = (edges[:-1] + edges[1:]) / 2
    return {"poc": float(mid[poc]), "vah": float(edges[hi_i + 1]), "val": float(edges[lo_i])}


def liquidity_levels(df: pd.DataFrame) -> list[Level]:
    lv = equal_highs_lows(df) + prior_day_levels(df)
    ar = asia_range(df)
    if ar:
        lv += [Level(ar[0], "asia_high", 2.0), Level(ar[1], "asia_low", 2.0)]
    vp = volume_profile(df.iloc[-288:])  # یک روز ۵ دقیقه‌ای
    for k in ("poc", "vah", "val"):
        if k in vp:
            lv.append(Level(vp[k], k, 1.5))
    return lv


def all_levels(df: pd.DataFrame) -> list[Level]:
    return support_resistance(df) + liquidity_levels(df)


def next_target(levels: list[Level], price: float, direction: int, min_dist: float) -> float | None:
    """نزدیک‌ترین سطح در جهت معامله که حداقل min_dist فاصله دارد (برای حد سود)."""
    cands = [l.price for l in levels if (l.price - price) * direction >= min_dist]
    if not cands:
        return None
    return min(cands, key=lambda p: abs(p - price))


def nearest(levels: list[Level], price: float, max_dist: float) -> Level | None:
    near = [l for l in levels if abs(l.price - price) <= max_dist]
    return max(near, key=lambda l: l.strength) if near else None

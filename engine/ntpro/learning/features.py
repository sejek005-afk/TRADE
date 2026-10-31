"""ویژگی‌ها برای مدل‌های ML (ماژول ۷): جدولی برای LightGBM و توالی کندل برای شبکه‌ی عصبی."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import levels as lv
from ..regime import ALLOWED
from ..strategies import ALL

REGIMES = list(ALLOWED)
SESSIONS = ["asia", "london", "newyork", "overlap", "off"]
STRATS = list(ALL)
SEQ_LEN = 64
SEQ_FEATURES = 6


def tabular(df: pd.DataFrame, f: pd.DataFrame, *, direction: int, strategies: list[str], score: float,
            regime: str, session: str, minutes_to_news: float, intermarket_bias: float, spread_points: float,
            point: float, levels: list | None = None) -> dict[str, float]:
    a = float(f["atr"].iloc[-1]) or 1e-9
    c = df["close"]
    x: dict[str, float] = {"direction": direction, "score": score, "im_bias": intermarket_bias * direction}
    for n in (1, 3, 6, 12, 24):
        x[f"ret_{n}"] = float((c.iloc[-1] - c.iloc[-1 - n]) / a) * direction if len(c) > n else 0.0
    row = f.iloc[-1]
    x.update(
        atr_pct=float(row["atr_pct"]), spread_atr=spread_points * point / a, rvol=float(row["rvol"]),
        rsi=(float(row["rsi"]) - 50) * direction, adx=float(row["adx"]),
        macd_h=float(row["macd_hist"]) / a * direction,
        bb_pos=float((row["bb_hi"] - c.iloc[-1]) / max(row["bb_hi"] - row["bb_lo"], 1e-9)) if direction < 0
        else float((c.iloc[-1] - row["bb_lo"]) / max(row["bb_hi"] - row["bb_lo"], 1e-9)),
        d_ema50=float(c.iloc[-1] - row["ema50"]) / a * direction,
        d_ema200=float(c.iloc[-1] - row["ema200"]) / a * direction,
        st_align=float(row["st_dir"]) * direction, htf_align=float(row["htf_dir"]) * direction,
        trend_align=float(row["trend_dir"]) * direction,
        news_min=min(minutes_to_news, 600.0) / 600.0,
        squeeze=float(bool(row["squeeze"])), body_atr=float(row["body"]) / a, range_atr=float(row["range"]) / a,
    )
    hour = df.index[-1].hour + df.index[-1].minute / 60
    x["hour_sin"], x["hour_cos"] = math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)
    # Delta تقریبی: حجم وزن‌دار با جهت بدنه
    seg = df.iloc[-12:]
    rng = (seg["high"] - seg["low"]).replace(0, np.nan)
    delta = ((seg["close"] - seg["open"]) / rng).fillna(0) * seg["tick_volume"]
    x["delta"] = float(delta.sum() / max(seg["tick_volume"].sum(), 1)) * direction
    # Volume Profile و نقدینگی
    vp = lv.volume_profile(df.iloc[-288:])
    price = float(c.iloc[-1])
    for k in ("poc", "vah", "val"):
        x[f"d_{k}"] = (price - vp[k]) / a * direction if k in vp else 0.0
    if levels is not None:
        ahead = [l.price for l in levels if (l.price - price) * direction > 0]
        behind = [l.price for l in levels if (l.price - price) * direction < 0]
        x["liq_ahead"] = min((abs(p - price) for p in ahead), default=10 * a) / a
        x["liq_behind"] = min((abs(p - price) for p in behind), default=10 * a) / a
    else:
        x["liq_ahead"] = x["liq_behind"] = 10.0
    for r in REGIMES:
        x[f"reg_{r}"] = float(regime == r)
    for s in SESSIONS:
        x[f"ses_{s}"] = float(session == s)
    for s in STRATS:
        x[f"st_{s}"] = float(s in strategies)
    return x


FEATURE_ORDER: list[str] | None = None


def to_matrix(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    cols = sorted(rows[0]) if rows else []
    return np.array([[r.get(c, 0.0) for c in cols] for r in rows], dtype=np.float32), cols


def sequence(df: pd.DataFrame, f: pd.DataFrame, direction: int, n: int = SEQ_LEN) -> np.ndarray:
    """توالی n کندل آخر: تغییر قیمت/ATR، بدنه، سایه‌ها، Tick Volume نرمال، اسپرد/ATR (همه در جهت معامله)."""
    d, ff = df.iloc[-n:], f.iloc[-n:]
    a = ff["atr"].to_numpy() + 1e-9
    ch = np.diff(np.r_[d["open"].iloc[0], d["close"].to_numpy()]) / a * direction
    body = (d["close"] - d["open"]).to_numpy() / a * direction
    up = (d["high"] - d[["open", "close"]].max(axis=1)).to_numpy() / a
    lo = (d[["open", "close"]].min(axis=1) - d["low"]).to_numpy() / a
    v = d["tick_volume"].to_numpy(dtype=float)
    v = (v - v.mean()) / (v.std() + 1e-9)
    sp = d["spread"].to_numpy(dtype=float) if "spread" in d else np.zeros(len(d))
    sp = sp / (sp.mean() + 1e-9)
    seq = np.stack([ch, body, up if direction > 0 else lo, lo if direction > 0 else up, v, sp], axis=1)
    if len(seq) < n:
        seq = np.vstack([np.zeros((n - len(seq), SEQ_FEATURES)), seq])
    return np.clip(seq, -10, 10).astype(np.float32)


def triple_barrier(df: pd.DataFrame, i: int, direction: int, sl_dist: float, tp_dist: float, horizon: int) -> int | None:
    """برچسب: ۱ اگر قیمت قبل از حد ضرر به حد سود برسد (در horizon کندل)، ۰ اگر ضرر یا زمان تمام شد.
    اگر هر دو در یک کندل باشند، محافظه‌کارانه ضرر فرض می‌شود. None اگر داده‌ی آینده کافی نیست."""
    if i + horizon >= len(df):
        return None
    entry = float(df["close"].iloc[i])
    hi = df["high"].to_numpy()[i + 1: i + 1 + horizon]
    lo = df["low"].to_numpy()[i + 1: i + 1 + horizon]
    for h, l in zip(hi, lo):
        if direction > 0:
            hit_sl, hit_tp = l <= entry - sl_dist, h >= entry + tp_dist
        else:
            hit_sl, hit_tp = h >= entry + sl_dist, l <= entry - tp_dist
        if hit_sl:
            return 0
        if hit_tp:
            return 1
    return 0

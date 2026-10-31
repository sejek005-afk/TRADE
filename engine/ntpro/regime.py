"""تشخیص وضعیت بازار (Regime): روندی / رنج / پرنوسان / کم‌نوسان با ADX و ATR.

خروجی یک برچسب اصلی است و لایه‌ی ۱ از روی آن تعیین می‌کند کدام استراتژی‌ها فعال باشند.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import indicators as ind

TRENDING, RANGING, VOLATILE, QUIET = "trending", "ranging", "volatile", "quiet"
REGIME_FA = {TRENDING: "روندی", RANGING: "رنج", VOLATILE: "پرنوسان", QUIET: "کم‌نوسان"}

# کدام استراتژی‌ها در هر Regime مجازند (قانون ثابت لایه‌ی ۱)
ALLOWED = {
    TRENDING: {"ema_cross", "supertrend_ema", "pullback", "macd_momentum", "break_retest", "smc", "vwap",
               "orb", "asia_london", "candle_patterns"},
    RANGING: {"bb_rsi_reversal", "vwap", "smc", "candle_patterns", "break_retest", "squeeze"},
    VOLATILE: {"orb", "asia_london", "break_retest", "smc", "supertrend_ema", "macd_momentum"},
    QUIET: {"squeeze", "bb_rsi_reversal", "asia_london", "orb", "vwap"},
}


@dataclass
class Regime:
    label: str
    adx: float
    atr: float
    atr_pct: float      # صدک ATR نسبت به ۲۰۰ کندل اخیر (۰ تا ۱)
    trend_dir: int      # +1/-1/0 از EMA200 و شیب
    htf_dir: int = 0    # جهت روند تایم‌فریم بالاتر (M15/H1)

    @property
    def fa(self) -> str:
        return REGIME_FA[self.label]


def detect(df: pd.DataFrame, htf: list[pd.DataFrame] | None = None) -> Regime:
    a = ind.atr(df, 14)
    adx_v, pdi, mdi = ind.adx(df, 14)
    cur_atr = float(a.iloc[-1])
    window = a.iloc[-200:].dropna()
    atr_pct = float((window < cur_atr).mean()) if len(window) > 20 else 0.5
    adx_now = float(adx_v.iloc[-1])
    e200 = ind.ema(df["close"], 200)
    slope = float(e200.iloc[-1] - e200.iloc[-10]) if len(df) > 210 else 0.0
    price = float(df["close"].iloc[-1])
    trend_dir = 0
    if price > e200.iloc[-1] and slope > 0:
        trend_dir = 1
    elif price < e200.iloc[-1] and slope < 0:
        trend_dir = -1

    if atr_pct >= 0.90:
        label = VOLATILE
    elif atr_pct <= 0.15 and adx_now < 20:
        label = QUIET
    elif adx_now >= 23:
        label = TRENDING
    else:
        label = RANGING

    htf_dir = 0
    if htf:
        dirs = [trend_direction(h) for h in htf if h is not None and len(h) > 60]
        if dirs and all(d == dirs[0] for d in dirs):
            htf_dir = dirs[0]
    return Regime(label, adx_now, cur_atr, atr_pct, trend_dir, htf_dir)


def from_frame(f: pd.DataFrame) -> Regime:
    """همان detect ولی از ستون‌های از پیش محاسبه‌شده‌ی frame (سریع، برای موتور و بک‌تست)."""
    row = f.iloc[-1]
    adx_now, atr_pct = float(row["adx"]), float(row["atr_pct"])
    if atr_pct >= 0.90:
        label = VOLATILE
    elif atr_pct <= 0.15 and adx_now < 20:
        label = QUIET
    elif adx_now >= 23:
        label = TRENDING
    else:
        label = RANGING
    return Regime(label, adx_now, float(row["atr"]), atr_pct, int(row["trend_dir"]), int(row["htf_dir"]))


def trend_direction(df: pd.DataFrame) -> int:
    """جهت روند یک تایم‌فریم با EMA50/EMA200 (یا EMA20/50 اگر داده کم است)."""
    c = df["close"]
    fast, slow = (50, 200) if len(c) > 220 else (20, 50)
    ef, es = ind.ema(c, fast).iloc[-1], ind.ema(c, slow).iloc[-1]
    if c.iloc[-1] > ef > es:
        return 1
    if c.iloc[-1] < ef < es:
        return -1
    return 0


def allowed_strategies(regime: Regime, enabled: dict[str, bool]) -> set[str]:
    return {s for s in ALLOWED[regime.label] if enabled.get(s, True)}

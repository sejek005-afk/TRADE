"""داده‌های بین‌بازاری: شاخص دلار، بازده ۱۰ ساله‌ی آمریکا، VIX/نزدک → Bias برای هر نماد (−۱ تا +۱)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

# وزن‌های رسمی ICE برای DXY
DXY_WEIGHTS = {"EURUSD": -0.576, "USDJPY": 0.136, "GBPUSD": -0.119, "USDCAD": 0.091, "USDSEK": 0.042, "USDCHF": 0.036}


def synthetic_dxy(closes: dict[str, pd.Series]) -> pd.Series | None:
    """DXY مصنوعی از جفت‌ارزهای موجود (لگاریتم وزن‌دار). حداقل EURUSD لازم است."""
    if "EURUSD" not in closes:
        return None
    parts = [w * np.log(closes[s]) for s, w in DXY_WEIGHTS.items() if s in closes]
    total = sum(abs(w) for s, w in DXY_WEIGHTS.items() if s in closes)
    s = sum(parts) / total
    return np.exp(s - s.dropna().iloc[0]) * 100


def momentum(series: pd.Series | None, n: int = 12, norm: int = 100) -> float:
    """تغییر n کندل اخیر نسبت به انحراف معیار تغییرات (z-score محدودشده به −۱..۱)."""
    if series is None or len(series) < norm + n:
        return 0.0
    ch = series.diff(n)
    sd = ch.iloc[-norm:].std()
    if not sd or math.isnan(sd):
        return 0.0
    return float(np.clip(ch.iloc[-1] / (2 * sd), -1, 1))


def _usd_side(symbol: str) -> int:
    """+1 اگر دلار ارز پایه است (USDJPY)، −1 اگر ارز دوم است (EURUSD/XAUUSD)."""
    s = symbol.upper()
    if s.startswith("USD"):
        return 1
    if s.endswith("USD") or "USD" in s[3:]:
        return -1
    return 0


def bias(symbol: str, dxy: float = 0.0, us10y: float = 0.0, risk: float = 0.0) -> tuple[float, str]:
    """
    dxy/us10y: مومنتوم (−۱..۱). risk: +۱ = Risk-on (نزدک بالا / VIX پایین)، −۱ = Risk-off.
    خروجی: (bias در جهت خرید نماد، توضیح فارسی)
    """
    s = symbol.upper()
    notes = []
    b = 0.0
    if s.startswith("XAU") or s.startswith("GOLD"):
        b += -0.5 * dxy - 0.3 * us10y - 0.2 * risk
        if abs(dxy) > 0.3:
            notes.append(f"دلار {'قوی' if dxy > 0 else 'ضعیف'}")
        if abs(us10y) > 0.3:
            notes.append(f"بازده اوراق {'صعودی' if us10y > 0 else 'نزولی'}")
    elif s.startswith("BTC") or s.startswith("NAS") or s.startswith("US100"):
        b += 0.7 * risk - 0.3 * dxy
    else:
        side = _usd_side(s)
        b += 0.7 * side * dxy
        if "JPY" in s or "CHF" in s:      # ین و فرانک امن‌اند: Risk-off → قوی
            safe_side = 1 if s.endswith(("JPY", "CHF")) else -1
            b += 0.3 * safe_side * risk
        else:
            b += 0.15 * risk * (-side if side else 0)
        if abs(dxy) > 0.3 and side:
            notes.append(f"شاخص دلار {'صعودی' if dxy > 0 else 'نزولی'}")
    if abs(risk) > 0.4:
        notes.append("Risk-on" if risk > 0 else "Risk-off")
    return float(np.clip(b, -1, 1)), "، ".join(notes)


class Intermarket:
    """نگه‌داری آخرین سری‌ها و محاسبه‌ی Bias. سری‌ها از broker به‌روز می‌شوند."""

    def __init__(self):
        self.series: dict[str, pd.Series] = {}

    def update(self, key: str, closes: pd.Series | None) -> None:
        if closes is not None and len(closes):
            self.series[key] = closes

    def state(self) -> dict:
        nas = momentum(self.series.get("nasdaq"))
        vix = momentum(self.series.get("vix"))
        risk = float(np.clip(nas - vix, -1, 1)) if ("nasdaq" in self.series or "vix" in self.series) else 0.0
        return {"dxy": momentum(self.series.get("dxy")), "us10y": momentum(self.series.get("us10y")), "risk": risk}

    def bias_for(self, symbol: str) -> tuple[float, str]:
        st = self.state()
        return bias(symbol, st["dxy"], st["us10y"], st["risk"])

"""پایه‌ی استراتژی‌ها: هر استراتژی یک سیگنال‌دهنده‌ی مستقل با امتیاز ۰ تا ۱۰۰ است."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING

import pandas as pd

from .. import levels as lv

if TYPE_CHECKING:
    from ..regime import Regime
    from ..sessions import SessionState


@dataclass
class Signal:
    strategy: str
    direction: int                 # +1 خرید، -1 فروش
    score: float                   # ۰ تا ۱۰۰
    sl: float                      # حد ضرر پیشنهادی (قیمت)
    reason: str                    # توضیح فارسی
    tp: float | None = None        # حد سود پیشنهادی (اختیاری)
    tags: list[str] = field(default_factory=list)

    def clamp(self) -> "Signal":
        self.score = max(0.0, min(100.0, float(self.score)))
        return self


class Context:
    """داده‌های یک لحظه برای همه‌ی استراتژی‌ها.

    df: کندل‌های ۵ دقیقه تا همین لحظه (کندل آخر = کندل بسته‌شده)
    f:  اندیکاتورهای از پیش محاسبه‌شده (frame.compute) هم‌طول df
    """

    def __init__(self, symbol: str, df: pd.DataFrame, f: pd.DataFrame, regime: "Regime",
                 session: "SessionState", now: datetime, point: float = 0.00001,
                 htf: dict[str, pd.DataFrame] | None = None, levels_cache: list | None = None):
        self.symbol, self.df, self.f = symbol, df, f
        self.regime, self.session, self.now, self.point = regime, session, now, point
        self.htf = htf or {}
        self._levels = levels_cache

    # دسترسی سریع
    def v(self, col: str, back: int = 0) -> float:
        return float(self.f[col].iloc[-1 - back])

    def c(self, col: str, back: int = 0) -> float:
        return float(self.df[col].iloc[-1 - back])

    @property
    def price(self) -> float:
        return self.c("close")

    @property
    def atr(self) -> float:
        return self.v("atr")

    @cached_property
    def levels(self) -> list[lv.Level]:
        if self._levels is not None:
            return self._levels
        return lv.all_levels(self.df.iloc[-400:])

    def swing_low(self, n: int = 10) -> float:
        return float(self.df["low"].iloc[-n:].min())

    def swing_high(self, n: int = 10) -> float:
        return float(self.df["high"].iloc[-n:].max())

    def structural_sl(self, direction: int, n: int = 10, pad_atr: float = 0.2) -> float:
        pad = pad_atr * self.atr
        return self.swing_low(n) - pad if direction > 0 else self.swing_high(n) + pad

    def htf_bonus(self, direction: int, pts: float = 10) -> float:
        d = self.regime.htf_dir
        return pts if d == direction else (-pts if d == -direction else 0.0)


class Strategy:
    name = "base"
    fa = ""
    min_bars = 220

    def evaluate(self, ctx: Context) -> Signal | None:   # pragma: no cover - interface
        raise NotImplementedError

    def sig(self, ctx: Context, direction: int, score: float, reason: str, sl: float | None = None,
            tp: float | None = None) -> Signal:
        if sl is None:
            sl = ctx.structural_sl(direction)
        # حد ضرر هیچ‌وقت نباید کمتر از ۰.۵ ATR فاصله داشته باشد
        min_d = 0.5 * ctx.atr
        if direction > 0:
            sl = min(sl, ctx.price - min_d)
        else:
            sl = max(sl, ctx.price + min_d)
        return Signal(self.name, direction, score, float(sl), f"{self.fa}: {reason}", tp).clamp()

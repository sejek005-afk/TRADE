"""برگشتی‌ها: بولینگر+RSI (فقط رنج) و الگوهای کندلی روی سطوح کلیدی."""
from __future__ import annotations

from .. import levels as lv
from ..regime import RANGING
from .base import Context, Signal, Strategy


class BollingerRsiReversal(Strategy):
    name, fa = "bb_rsi_reversal", "برگشت از بولینگر + RSI"

    def evaluate(self, ctx: Context) -> Signal | None:
        if ctx.regime.label != RANGING:
            return None
        c1, c0 = ctx.c("close", 1), ctx.c("close")
        if c1 < ctx.v("bb_lo", 1) and ctx.v("rsi", 1) < 30 and c0 > ctx.v("bb_lo") and c0 > ctx.c("open"):
            direction = 1
        elif c1 > ctx.v("bb_hi", 1) and ctx.v("rsi", 1) > 70 and c0 < ctx.v("bb_hi") and c0 < ctx.c("open"):
            direction = -1
        else:
            return None
        score = 58 + (6 if ctx.v("adx") < 18 else 0)
        sl = ctx.structural_sl(direction, 5, 0.3)
        return self.sig(ctx, direction, score, "بازگشت به داخل باند در بازار رنج", sl=sl, tp=ctx.v("bb_mid"))


def is_pinbar(o: float, h: float, l: float, c: float) -> int:
    rng = h - l
    if rng <= 0:
        return 0
    body = abs(c - o)
    upper, lower = h - max(o, c), min(o, c) - l
    if body <= 0.33 * rng and lower >= 0.6 * rng:
        return 1
    if body <= 0.33 * rng and upper >= 0.6 * rng:
        return -1
    return 0


def is_engulfing(o1: float, c1: float, o0: float, c0: float) -> int:
    if c1 < o1 and c0 > o0 and c0 >= o1 and o0 <= c1:
        return 1
    if c1 > o1 and c0 < o0 and c0 <= o1 and o0 >= c1:
        return -1
    return 0


class CandlePatterns(Strategy):
    name, fa = "candle_patterns", "الگوی کندلی روی سطح"

    def evaluate(self, ctx: Context) -> Signal | None:
        o, h, l, c = ctx.c("open"), ctx.c("high"), ctx.c("low"), ctx.c("close")
        pin = is_pinbar(o, h, l, c)
        eng = is_engulfing(ctx.c("open", 1), ctx.c("close", 1), o, c)
        direction = pin or eng
        if not direction:
            return None
        if ctx.f["range"].iloc[-1] < 0.6 * ctx.atr:
            return None
        touch = l if direction > 0 else h
        level = lv.nearest(ctx.levels, touch, 0.3 * ctx.atr)
        if level is None:
            return None
        name = "پین‌بار" if pin else "انگالفینگ"
        score = 54 + min(12, 3 * level.strength) + ctx.htf_bonus(direction, 6)
        sl = (l if direction > 0 else h) - direction * 0.2 * ctx.atr
        return self.sig(ctx, direction, score, f"{name} روی سطح {level.kind} ({level.price:.5g})", sl=sl)

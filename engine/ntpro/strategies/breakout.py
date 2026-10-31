"""استراتژی‌های شکست: Opening Range، رنج آسیا در لندن، Break & Retest، Squeeze."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pandas as pd

from .. import levels as lv
from ..sessions import LONDON, NEW_YORK
from .base import Context, Signal, Strategy


def _range_between(df: pd.DataFrame, start: datetime, end: datetime) -> tuple[float, float] | None:
    m = (df.index >= start) & (df.index < end)
    seg = df[m]
    if len(seg) < 3:
        return None
    return float(seg["high"].max()), float(seg["low"].min())


class OpeningRangeBreakout(Strategy):
    """رنج ۳۰ دقیقه‌ی اول بازگشایی لندن و نیویورک؛ شکست با بسته شدن کندل در ۲ ساعت بعد."""
    name, fa = "orb", "شکست رنج بازگشایی"

    def evaluate(self, ctx: Context) -> Signal | None:
        for tz, label in ((LONDON, "لندن"), (NEW_YORK, "نیویورک")):
            local = ctx.now.astimezone(tz)
            open_t = datetime.combine(local.date(), time(8), tz)
            if not (open_t + timedelta(minutes=30) <= local < open_t + timedelta(hours=2, minutes=30)):
                continue
            r = _range_between(ctx.df, open_t, open_t + timedelta(minutes=30))
            if not r:
                continue
            hi, lo = r
            width = hi - lo
            if width < 0.3 * ctx.atr or width > 4 * ctx.atr:
                continue
            c0, c1 = ctx.price, ctx.c("close", 1)
            if c0 > hi >= c1:
                direction, sl = 1, (hi + lo) / 2
            elif c0 < lo <= c1:
                direction, sl = -1, (hi + lo) / 2
            else:
                continue
            score = 55 + ctx.htf_bonus(direction) + (8 if ctx.v("rvol") > 1.3 else 0)
            return self.sig(ctx, direction, score, f"شکست رنج ۳۰ دقیقه‌ی اول {label}", sl=sl,
                            tp=c0 + direction * width * 1.5)
        return None


class AsiaLondonBreakout(Strategy):
    name, fa = "asia_london", "شکست رنج آسیا در لندن"

    def evaluate(self, ctx: Context) -> Signal | None:
        local = ctx.now.astimezone(LONDON)
        if not time(7, 0) <= local.time() < time(10, 0):
            return None
        ar = lv.asia_range(ctx.df)
        if not ar:
            return None
        hi, lo = ar
        width = hi - lo
        if width > 14 * ctx.atr or width < 2 * ctx.atr:
            return None
        c0, c1 = ctx.price, ctx.c("close", 1)
        if c0 > hi >= c1:
            direction = 1
        elif c0 < lo <= c1:
            direction = -1
        else:
            return None
        score = 57 + ctx.htf_bonus(direction) + (6 if ctx.v("rvol") > 1.2 else -6)
        sl = hi - min(0.5 * width, 2.5 * ctx.atr) if direction > 0 else lo + min(0.5 * width, 2.5 * ctx.atr)
        return self.sig(ctx, direction, score, "شکست رنج سشن آسیا در شروع لندن", sl=sl,
                        tp=c0 + direction * max(width, 3 * abs(c0 - sl)))


class BreakRetest(Strategy):
    name, fa = "break_retest", "شکست و پولبک سطح"

    def evaluate(self, ctx: Context) -> Signal | None:
        levels = [l for l in ctx.levels if l.kind == "sr" and l.strength >= 2]
        if not levels:
            return None
        a = ctx.atr
        closes = ctx.df["close"].iloc[-30:]
        for l in sorted(levels, key=lambda x: abs(x.price - ctx.price))[:4]:
            p = l.price
            before = closes.iloc[:-8]
            if len(before) < 5:
                continue
            # صعودی: قبلاً زیر سطح، شکست به بالا، حالا پولبک به سطح و بسته شدن بالای آن
            if (before < p).mean() > 0.6 and ctx.c("low") <= p + 0.2 * a and ctx.price > p and \
                    ctx.c("close") > ctx.c("open") and (closes.iloc[-8:-1] > p).any():
                return self.sig(ctx, 1, 60 + min(10, 2 * l.strength) + ctx.htf_bonus(1),
                                f"شکست مقاومت {p:.5g} و پولبک تأییدشده", sl=p - 0.6 * a)
            if (before > p).mean() > 0.6 and ctx.c("high") >= p - 0.2 * a and ctx.price < p and \
                    ctx.c("close") < ctx.c("open") and (closes.iloc[-8:-1] < p).any():
                return self.sig(ctx, -1, 60 + min(10, 2 * l.strength) + ctx.htf_bonus(-1),
                                f"شکست حمایت {p:.5g} و پولبک تأییدشده", sl=p + 0.6 * a)
        return None


class Squeeze(Strategy):
    name, fa = "squeeze", "اسکوییز بولینگر/کلتنر"

    def evaluate(self, ctx: Context) -> Signal | None:
        sq = ctx.f["squeeze"].iloc[-8:-1]
        if not (sq.sum() >= 6 and not bool(ctx.f["squeeze"].iloc[-1])):
            return None
        mom = ctx.price - ctx.v("bb_mid")
        h = ctx.v("macd_hist")
        if mom > 0 and h > 0:
            direction = 1
        elif mom < 0 and h < 0:
            direction = -1
        else:
            return None
        score = 56 + ctx.htf_bonus(direction) + (6 if ctx.v("rvol") > 1.2 else 0)
        return self.sig(ctx, direction, score, "آزاد شدن فشردگی نوسان", sl=ctx.v("bb_mid") - direction * 0.5 * ctx.atr)

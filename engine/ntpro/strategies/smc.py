"""SMC/ICT: Liquidity Sweep → CHoCH/BOS → ورود در FVG یا Order Block."""
from __future__ import annotations

import pandas as pd

from .. import indicators as ind
from .base import Context, Signal, Strategy


def find_fvg(df: pd.DataFrame, direction: int, lookback: int = 12) -> tuple[float, float] | None:
    """شکاف ارزش منصفانه (۳ کندلی) در جهت داده‌شده؛ آخرین مورد را برمی‌گرداند (low, high)."""
    h, l = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    for i in range(n - 1, max(2, n - lookback), -1):
        if direction > 0 and l[i] > h[i - 2]:
            return float(h[i - 2]), float(l[i])
        if direction < 0 and h[i] < l[i - 2]:
            return float(h[i]), float(l[i - 2])
    return None


def order_block(df: pd.DataFrame, direction: int, lookback: int = 15) -> tuple[float, float] | None:
    """آخرین کندل مخالف قبل از حرکت قوی (low, high)."""
    o, c, h, l = (df[k].to_numpy() for k in ("open", "close", "high", "low"))
    n = len(df)
    for i in range(n - 3, max(0, n - lookback), -1):
        opposite = c[i] < o[i] if direction > 0 else c[i] > o[i]
        strong = (c[i + 1] - o[i + 1]) * direction > 0 and (c[i + 2] - c[i]) * direction > 0
        if opposite and strong:
            return float(l[i]), float(h[i])
    return None


class SmartMoney(Strategy):
    name, fa = "smc", "SMC/ICT"

    def evaluate(self, ctx: Context) -> Signal | None:
        df = ctx.df.iloc[-80:]
        a = ctx.atr
        sh, sl = ind.swing_points(df.iloc[:-6], 3, 3)
        highs, lows = df["high"].iloc[:-6][sh], df["low"].iloc[:-6][sl]
        if len(highs) < 2 or len(lows) < 2:
            return None
        recent = df.iloc[-6:]
        last_h, last_l = float(highs.iloc[-1]), float(lows.iloc[-1])
        liq_levels = [l.price for l in ctx.levels if l.kind in ("eqh", "pdh", "asia_high")] + [last_h]
        liq_lows = [l.price for l in ctx.levels if l.kind in ("eql", "pdl", "asia_low")] + [last_l]

        # Sweep بالا: سایه از سطح نقدینگی عبور کرد ولی بسته شدن زیر آن → فروش
        swept_high = next((p for p in liq_levels if recent["high"].max() > p and recent["close"].iloc[-1] < p), None)
        swept_low = next((p for p in liq_lows if recent["low"].min() < p and recent["close"].iloc[-1] > p), None)
        if swept_high is not None and swept_low is None:
            direction = -1
            minor = float(df["low"].iloc[-6:-1].min())
            choch = ctx.price < minor
            extreme = float(recent["high"].max())
        elif swept_low is not None and swept_high is None:
            direction = 1
            minor = float(df["high"].iloc[-6:-1].max())
            choch = ctx.price > minor
            extreme = float(recent["low"].min())
        else:
            return None
        if not choch:
            return None
        score = 62
        parts = ["جمع‌آوری نقدینگی", "تغییر ساختار (CHoCH)"]
        fvg = find_fvg(df, direction)
        if fvg:
            score += 8
            parts.append("FVG")
        ob = order_block(df, direction)
        if ob:
            score += 5
            parts.append("Order Block")
        bos = (ctx.price > last_h) if direction > 0 else (ctx.price < last_l)
        if bos:
            score += 5
            parts.append("BOS")
        score += ctx.htf_bonus(direction, 8)
        sl = extreme - direction * 0.15 * a
        return self.sig(ctx, direction, score, " + ".join(parts), sl=sl)

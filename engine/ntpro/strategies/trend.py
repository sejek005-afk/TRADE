"""استراتژی‌های روندی: کراس EMA، سوپرترند، پولبک، مومنتوم MACD، VWAP."""
from __future__ import annotations

from .base import Context, Signal, Strategy


class EmaCross(Strategy):
    name, fa = "ema_cross", "کراس EMA 9/21"

    def evaluate(self, ctx: Context) -> Signal | None:
        for back in (0, 1):
            d_now = ctx.v("ema9", back) - ctx.v("ema21", back)
            d_prev = ctx.v("ema9", back + 1) - ctx.v("ema21", back + 1)
            if d_now * d_prev < 0:
                direction = 1 if d_now > 0 else -1
                break
        else:
            return None
        e200 = ctx.v("ema200")
        if (ctx.price - e200) * direction <= 0:
            return None  # فیلتر EMA200: فقط در جهت روند بزرگ
        score = 50 + min(20, ctx.v("adx") - 15) + ctx.htf_bonus(direction)
        if back == 0:
            score += 5
        return self.sig(ctx, direction, score, f"کراس {'صعودی' if direction > 0 else 'نزولی'} بالای/زیر EMA200")


class SupertrendEma(Strategy):
    name, fa = "supertrend_ema", "سوپرترند + EMA"

    def evaluate(self, ctx: Context) -> Signal | None:
        d = int(ctx.v("st_dir"))
        flipped = any(int(ctx.v("st_dir", b)) != int(ctx.v("st_dir", b + 1)) for b in range(3))
        if not flipped:
            return None
        if (ctx.price - ctx.v("ema50")) * d <= 0:
            return None
        score = 55 + min(15, ctx.v("adx") - 18) + ctx.htf_bonus(d)
        sl = ctx.v("st_line") - d * 0.2 * ctx.atr
        return self.sig(ctx, d, score, "تغییر جهت سوپرترند هم‌سو با EMA50", sl=sl)


class Pullback(Strategy):
    name, fa = "pullback", "پولبک در روند"

    def evaluate(self, ctx: Context) -> Signal | None:
        e50, e200 = ctx.v("ema50"), ctx.v("ema200")
        if ctx.price > e200 and e50 > e200:
            direction = 1
        elif ctx.price < e200 and e50 < e200:
            direction = -1
        else:
            return None
        rsi_vals = [ctx.v("rsi", b) for b in range(6)]
        k, d, k1, d1 = ctx.v("stoch_k"), ctx.v("stoch_d"), ctx.v("stoch_k", 1), ctx.v("stoch_d", 1)
        if direction > 0:
            dipped = min(rsi_vals[1:]) < 42
            turn = rsi_vals[0] > rsi_vals[1] and k > d and k1 <= d1 and k1 < 35
        else:
            dipped = max(rsi_vals[1:]) > 58
            turn = rsi_vals[0] < rsi_vals[1] and k < d and k1 >= d1 and k1 > 65
        if not (dipped and turn):
            return None
        score = 58 + ctx.htf_bonus(direction, 12) + min(10, ctx.v("adx") - 20)
        return self.sig(ctx, direction, score, "اصلاح با RSI/استوکاستیک و برگشت در جهت روند", sl=ctx.structural_sl(direction, 8))


class MacdMomentum(Strategy):
    name, fa = "macd_momentum", "مومنتوم MACD"

    def evaluate(self, ctx: Context) -> Signal | None:
        h0, h1, h2 = ctx.v("macd_hist"), ctx.v("macd_hist", 1), ctx.v("macd_hist", 2)
        if h0 > 0 >= h1:
            direction = 1
        elif h0 < 0 <= h1:
            direction = -1
        else:
            return None
        if (ctx.v("macd")) * direction < 0 and abs(ctx.v("macd")) > 0.3 * ctx.atr:
            return None  # کراس خیلی دور از خط صفر در خلاف جهت = ضعیف
        if (ctx.price - ctx.v("ema200")) * direction <= 0:
            return None
        score = 52 + ctx.htf_bonus(direction) + (5 if abs(h0) > abs(h2) else 0) + min(10, ctx.v("adx") - 18)
        return self.sig(ctx, direction, score, "عبور هیستوگرام MACD از صفر در جهت روند")


class Vwap(Strategy):
    name, fa = "vwap", "VWAP"

    def evaluate(self, ctx: Context) -> Signal | None:
        vw = ctx.v("vwap")
        a = ctx.atr
        lo, hi, close, op = ctx.c("low"), ctx.c("high"), ctx.c("close"), ctx.c("open")
        above = all(ctx.c("close", b) > ctx.v("vwap", b) for b in range(1, 6))
        below = all(ctx.c("close", b) < ctx.v("vwap", b) for b in range(1, 6))
        if above and lo <= vw + 0.15 * a and close > vw and close > op:
            direction = 1
        elif below and hi >= vw - 0.15 * a and close < vw and close < op:
            direction = -1
        else:
            return None
        score = 55 + ctx.htf_bonus(direction) + (5 if ctx.v("rvol") > 1.1 else 0)
        sl = vw - direction * 0.6 * a
        return self.sig(ctx, direction, score, "برگشت از VWAP در جهت روند روز", sl=sl)

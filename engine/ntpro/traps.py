"""ماژول ۲: تشخیص تله‌ها قبل از هر ورود.

خروجی: رد کامل، یا (در صورت فعال بودن reverse_on_trap) پیشنهاد معامله‌ی برعکس برای تله‌های قیمتی.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import indicators as ind
from .strategies.base import Context

BREAKOUT_STRATEGIES = {"orb", "asia_london", "break_retest", "squeeze", "ema_cross", "supertrend_ema", "macd_momentum"}


@dataclass
class TrapResult:
    blocked: bool = False
    reverse: bool = False          # تله‌ی قیمتی که می‌شود برعکسش وارد شد
    reasons: list[str] = field(default_factory=list)
    penalty: float = 0.0           # کسر امتیاز برای موارد نرم


def check(ctx: Context, direction: int, strategies: list[str], spread_points: float, cfg: dict,
          symbol: str) -> TrapResult:
    r = TrapResult()
    a = ctx.atr
    df = ctx.df

    # ۱) اسپرد
    lim = cfg["max_spread_points"].get(symbol, cfg["max_spread_points"].get("default", 25))
    if spread_points > lim:
        r.blocked = True
        r.reasons.append(f"اسپرد بالا ({spread_points:.0f} > {lim} پوینت)")

    # ۲) اسپایک / کندل غیرعادی
    rng = float(df["high"].iloc[-1] - df["low"].iloc[-1])
    if rng > cfg["spike_atr_mult"] * a:
        r.blocked = True
        r.reasons.append(f"کندل غیرعادی ({rng / a:.1f}×ATR) — احتمال اسپایک خبری")

    # ۳) شکست کاذب / Bull-Bear Trap: بسته شدن بیرون از سقف/کف ۲۰ کندل، بعد برگشت به داخل
    window = df.iloc[-28:-5]
    if len(window) >= 10:
        hh, ll = float(window["high"].max()), float(window["low"].min())
        recent = df["close"].iloc[-5:-1]
        if direction > 0 and (recent > hh).any() and ctx.price < hh:
            r.blocked, r.reverse = True, True
            r.reasons.append("تله‌ی گاوی: شکست سقف و برگشت به زیر آن")
        if direction < 0 and (recent < ll).any() and ctx.price > ll:
            r.blocked, r.reverse = True, True
            r.reasons.append("تله‌ی خرسی: شکست کف و برگشت به بالای آن")

    # ۴) Stop Hunt: سایه از سقف/کف مشخص رد شده، بدنه داخل → ورود در جهت سایه ممنوع
    last = df.iloc[-1]
    prev = df.iloc[-40:-1]
    if len(prev) > 10:
        ph, pl = float(prev["high"].max()), float(prev["low"].min())
        if direction > 0 and last["high"] > ph and last["close"] < ph:
            r.blocked, r.reverse = True, True
            r.reasons.append("شکار استاپ بالای سقف (سایه بیرون، بسته شدن داخل)")
        if direction < 0 and last["low"] < pl and last["close"] > pl:
            r.blocked, r.reverse = True, True
            r.reasons.append("شکار استاپ زیر کف (سایه بیرون، بسته شدن داخل)")

    # ۵) حرکت بدون حجم (برای شکست‌ها)
    rvol = ctx.v("rvol")
    if set(strategies) & BREAKOUT_STRATEGIES and rvol < cfg["min_relative_volume"]:
        r.blocked = True
        r.reasons.append(f"حرکت بدون حجم (حجم نسبی {rvol:.2f})")

    # ۶) واگرایی RSI/MACD مخالف جهت
    if cfg.get("check_divergence", True):
        d_rsi = ind.divergence(df["close"], ctx.f["rsi"], 30)
        d_macd = ind.divergence(df["close"], ctx.f["macd"], 30)
        if d_rsi == -direction and d_macd == -direction:
            r.blocked = True
            r.reasons.append("واگرایی هم‌زمان RSI و MACD خلاف جهت")
        elif d_rsi == -direction or d_macd == -direction:
            r.penalty += 6
            r.reasons.append("واگرایی خفیف خلاف جهت (کسر امتیاز)")

    # ۷) ساعات کم‌نقدینگی
    if ctx.session.primary == "off" and not symbol.upper().startswith(("USDJPY", "AUD", "NZD")):
        r.penalty += 8
        r.reasons.append("ساعات کم‌نقدینگی (کسر امتیاز)")

    if r.blocked and not cfg.get("reverse_on_trap", False):
        r.reverse = False
    return r

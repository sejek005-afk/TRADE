"""خروج هوشمند: Partial TP، سربه‌سر، Trailing با ATR، حد سود بر اساس نقدینگی، Time Stop."""
from __future__ import annotations

from dataclasses import dataclass

from . import levels as lv
from .risk import RiskManager


@dataclass
class ExitAction:
    kind: str            # partial | modify_sl | close
    volume: float = 0.0
    sl: float = 0.0
    reason: str = ""


def plan_tp(entry: float, sl: float, direction: int, levels: list[lv.Level], cfg_exits: dict,
            min_rr: float, cost: float, strategy_tp: float | None = None) -> tuple[float, float]:
    """(tp1, tp_final). tp_final از ناحیه‌ی نقدینگی/سطح بعدی، با حداقل R:R خالص."""
    risk = abs(entry - sl)
    min_dist = min_rr * (risk + cost) + cost
    tp1 = entry + direction * float(cfg_exits["partial_tp_r"]) * risk
    target = None
    if cfg_exits.get("use_liquidity_tp", True):
        target = lv.next_target(levels, entry, direction, min_dist)
    candidates = [t for t in (target, strategy_tp) if t is not None and (t - entry) * direction >= min_dist]
    if candidates:
        tp = min(candidates, key=lambda t: abs(t - entry))
        # سقف منطقی: حداکثر ۴R
        if abs(tp - entry) > 4 * risk:
            tp = entry + direction * 4 * risk
    else:
        tp = entry + direction * max(min_dist, 2.0 * risk)
    return float(tp1), float(tp)


def manage(trade: dict, price: float, atr: float, bars_held: int, cfg_exits: dict, volume_step: float,
           volume_min: float) -> list[ExitAction]:
    """تصمیم‌های مدیریت یک پوزیشن باز روی کندل بسته‌شده. trade: ردیف trades."""
    acts: list[ExitAction] = []
    d = int(trade["direction"])
    entry, sl = float(trade["entry_price"]), float(trade["sl"])
    init_sl = float(trade.get("initial_sl") or sl)
    risk = abs(entry - init_sl) or 1e-12
    r_now = (price - entry) * d / risk
    vol = float(trade["volume"])

    # ۱) هدف اول: بستن بخشی + سربه‌سر
    if not trade.get("tp1_hit") and trade.get("tp1") and (price - float(trade["tp1"])) * d >= 0:
        part = round(int(vol * float(cfg_exits["partial_close_pct"]) / 100 / volume_step) * volume_step, 8)
        if part >= volume_min and vol - part >= volume_min:
            acts.append(ExitAction("partial", volume=part, reason=f"هدف اول ({cfg_exits['partial_tp_r']}R) — بستن {cfg_exits['partial_close_pct']}٪"))
        if cfg_exits.get("move_be_after_tp1", True) and (entry - sl) * d > 0:
            acts.append(ExitAction("modify_sl", sl=entry, reason="انتقال حد ضرر به نقطه‌ی سربه‌سر"))
        sl = max(sl, entry) if d > 0 else min(sl, entry)

    # ۲) Trailing بعد از هدف اول
    if trade.get("tp1_hit") or (trade.get("tp1") and (price - float(trade["tp1"])) * d >= 0):
        trail = price - d * float(cfg_exits["trail_atr_mult"]) * atr
        if (trail - sl) * d > 0.1 * atr:
            acts.append(ExitAction("modify_sl", sl=trail, reason="حد ضرر متحرک (ATR)"))

    # ۳) Time Stop
    if bars_held >= int(cfg_exits["time_stop_bars"]) and r_now < float(cfg_exits["time_stop_min_r"]) and not trade.get("tp1_hit"):
        acts.append(ExitAction("close", reason=f"Time Stop: بعد از {bars_held} کندل حرکت معناداری نکرد"))

    # فیلتر نهایی: هیچ تغییر SL ای نباید دورتر کند
    safe = []
    cur = float(trade["sl"])
    for a in acts:
        if a.kind == "modify_sl":
            try:
                RiskManager.validate_sl_change(d, cur, a.sl)
            except Exception:
                continue
            cur = a.sl
        safe.append(a)
    # فقط آخرین modify_sl لازم است
    mods = [a for a in safe if a.kind == "modify_sl"]
    if len(mods) > 1:
        safe = [a for a in safe if a.kind != "modify_sl"] + [mods[-1]]
    return safe

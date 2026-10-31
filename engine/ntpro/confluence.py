"""ترکیب سیگنال‌ها (Confluence): وزن هر استراتژی (از یادگیری لایه ۲)، بین‌بازاری، خبر، مدل‌ها."""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median

from .strategies.base import Signal


@dataclass
class Decision:
    direction: int
    score: float
    strategies: list[str]
    signals: list[Signal]
    sl: float
    tp: float | None
    accepted: bool
    reject_reason: str = ""
    parts: dict = field(default_factory=dict)
    reasons_fa: list[str] = field(default_factory=list)


def combine(signals: list[Signal], weights: dict[str, float], cfg: dict, *, intermarket_bias: float = 0.0,
            intermarket_note: str = "", news_bias: float = 0.0, kill_zone_bonus: float = 0.0,
            ml_prob: float | None = None, trap_penalty: float = 0.0) -> Decision | None:
    """signals: سیگنال‌های استراتژی‌های فعال در این لحظه. خروجی None یعنی هیچ سیگنالی نبود."""
    if not signals:
        return None
    side = {1: [s for s in signals if s.direction > 0], -1: [s for s in signals if s.direction < 0]}

    def strength(ss: list[Signal]) -> float:
        return sum(weights.get(s.strategy, 1.0) * s.score for s in ss)

    direction = 1 if strength(side[1]) >= strength(side[-1]) else -1
    agree, oppose = side[direction], side[-direction]
    w_agree = sum(weights.get(s.strategy, 1.0) for s in agree)
    w_opp = sum(weights.get(s.strategy, 1.0) for s in oppose)
    base = strength(agree) / max(w_agree, 1e-9)
    n = len(agree)
    min_n = int(cfg["min_strategies"])
    parts = {"base": round(base, 1)}
    score = base
    agree_bonus = min(12.0, 4.0 * max(0, n - 1))
    score += agree_bonus
    parts["agreement"] = agree_bonus
    if w_opp:
        opp_pen = 20.0 * w_opp / (w_agree + w_opp)
        score -= opp_pen
        parts["opposition"] = -round(opp_pen, 1)
    im = 100.0 * float(cfg.get("intermarket_weight", 0.1)) * intermarket_bias * direction
    score += im
    parts["intermarket"] = round(im, 1)
    nb = news_bias * direction
    score += nb
    parts["news"] = round(nb, 1)
    score += kill_zone_bonus
    parts["kill_zone"] = kill_zone_bonus
    score -= trap_penalty
    parts["traps"] = -trap_penalty

    accepted, reject = True, ""
    if ml_prob is not None:
        mw = float(cfg.get("ml_weight", 0.2))
        before = score
        score = (1 - mw) * score + mw * 100 * ml_prob
        if ml_prob >= float(cfg.get("ml_boost_above", 0.58)):
            score += 4
        parts["ml"] = round(score - before, 1)
        if ml_prob < float(cfg.get("ml_reject_below", 0.42)):
            accepted, reject = False, f"احتمال موفقیت مدل پایین است ({ml_prob:.0%})"

    score = max(0.0, min(100.0, score))
    if accepted and n < min_n:
        accepted, reject = False, f"تعداد استراتژی هم‌جهت کافی نیست ({n} از {min_n})"
    if accepted and score < float(cfg["min_score"]):
        accepted, reject = False, f"امتیاز ترکیبی کمتر از آستانه ({score:.0f} < {cfg['min_score']})"

    sls = [s.sl for s in agree]
    sl = median(sls)
    tps = [s.tp for s in agree if s.tp is not None]
    tp = median(tps) if tps else None
    reasons = [s.reason for s in agree]
    if intermarket_note:
        reasons.append(f"بین‌بازاری: {intermarket_note}")
    return Decision(direction, round(score, 1), [s.strategy for s in agree], agree, float(sl), tp, accepted, reject,
                    parts, reasons)

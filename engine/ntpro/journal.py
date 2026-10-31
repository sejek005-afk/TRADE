"""ژورنال: توضیح ساده‌ی فارسی برای هر معامله (چرا باز شد، چرا بسته شد) و گزارش هفتگی."""
from __future__ import annotations

import json
import time

from .regime import REGIME_FA
from .sessions import SESSION_FA, to_tehran
from .strategies import NAMES_FA


def explain_open(*, symbol: str, direction: int, score: float, strategies: list[str], regime: str, session: str,
                 reasons: list[str], ml_prob: float | None, rr: float, risk_pct: float) -> str:
    side = "خرید" if direction > 0 else "فروش"
    names = "، ".join(NAMES_FA.get(s, s) for s in strategies)
    lines = [f"{side} {symbol} با امتیاز {score:.0f} از ۱۰۰.",
             f"بازار {REGIME_FA.get(regime, regime)} و سشن {SESSION_FA.get(session, session)} بود.",
             f"استراتژی‌های هم‌جهت: {names}."]
    lines += [f"• {r}" for r in reasons[:6]]
    if ml_prob is not None:
        lines.append(f"احتمال رسیدن به حد سود قبل از حد ضرر (مدل): {ml_prob:.0%}.")
    lines.append(f"ریسک {risk_pct:.2g}٪ موجودی، نسبت ریوارد به ریسک بعد از هزینه‌ها 1:{rr:.2f}.")
    return "\n".join(lines)


def explain_close(reason: str, r_multiple: float, pnl: float) -> str:
    result = "سود" if pnl > 0 else ("ضرر" if pnl < 0 else "سربه‌سر")
    return f"{reason}. نتیجه: {result} {pnl:+.2f}$ ({r_multiple:+.2f}R)."


def weekly_report(db) -> dict:
    since = int(time.time()) - 7 * 86400
    trades = db.query("SELECT * FROM trades WHERE status='closed' AND exit_time>=? AND mode!='backtest'", (since,))

    def agg(key_fn):
        out: dict[str, dict] = {}
        for t in trades:
            for k in key_fn(t):
                d = out.setdefault(k, {"trades": 0, "pnl": 0.0, "r": 0.0, "wins": 0})
                d["trades"] += 1
                d["pnl"] += t["pnl"] or 0
                d["r"] += t["r_multiple"] or 0
                d["wins"] += int((t["pnl"] or 0) > 0)
        for d in out.values():
            d["pnl"] = round(d["pnl"], 2)
            d["expectancy"] = round(d["r"] / d["trades"], 2)
            d["win_rate"] = round(100 * d["wins"] / d["trades"], 1)
        return out

    by_s = agg(lambda t: json.loads(t["strategies"] or "[]"))
    by_ses = agg(lambda t: [t["session"]])
    by_sym = agg(lambda t: [t["symbol"]])
    best = lambda d: max(d.items(), key=lambda kv: kv[1]["expectancy"])[0] if d else "-"   # noqa: E731
    worst = lambda d: min(d.items(), key=lambda kv: kv[1]["expectancy"])[0] if d else "-"  # noqa: E731
    wlog = db.query("SELECT * FROM weight_log WHERE time>=? ORDER BY id DESC LIMIT 50", (since,))
    total = sum(t["pnl"] or 0 for t in trades)
    text = [f"گزارش هفتگی ({to_tehran(since)} تا {to_tehran(time.time())})",
            f"تعداد معاملات: {len(trades)} | سود/ضرر: {total:+.2f}$",
            f"بهترین استراتژی: {NAMES_FA.get(best(by_s), best(by_s))} | بدترین: {NAMES_FA.get(worst(by_s), worst(by_s))}",
            f"بهترین سشن: {SESSION_FA.get(best(by_ses), best(by_ses))} | بدترین: {SESSION_FA.get(worst(by_ses), worst(by_ses))}",
            f"بهترین نماد: {best(by_sym)} | بدترین: {worst(by_sym)}",
            f"تغییرات وزن یادگیری: {len(wlog)} مورد"]
    return {"since": since, "trades": len(trades), "pnl": round(total, 2), "by_strategy": by_s, "by_session": by_ses,
            "by_symbol": by_sym, "weight_changes": wlog, "text": "\n".join(text)}

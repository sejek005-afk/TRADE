"""تشخیص فرسودگی استراتژی: مقایسه‌ی آماری عملکرد چند هفته‌ی اخیر با سابقه‌ی همان استراتژی."""
from __future__ import annotations

import json
import time

import numpy as np


def mann_whitney_less(recent: np.ndarray, history: np.ndarray) -> float:
    """p-value یک‌طرفه برای «recent بدتر از history است» (Mann-Whitney U با تقریب نرمال)."""
    try:
        from scipy.stats import mannwhitneyu
        return float(mannwhitneyu(recent, history, alternative="less").pvalue)
    except Exception:
        n1, n2 = len(recent), len(history)
        allv = np.r_[recent, history]
        ranks = allv.argsort().argsort() + 1.0
        u = ranks[:n1].sum() - n1 * (n1 + 1) / 2
        mu, sd = n1 * n2 / 2, np.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
        z = (u - mu) / sd if sd else 0.0
        from math import erf, sqrt
        return float(0.5 * (1 + erf(z / sqrt(2))))


def check(db, cfg) -> list[dict]:
    """برمی‌گرداند استراتژی‌هایی که فرسوده شده‌اند و آن‌ها را موقتاً معلق می‌کند (تا تأیید دستی)."""
    L = cfg.get("learning")
    cutoff = time.time() - int(L["fatigue_weeks"]) * 7 * 86400
    rows = db.query("SELECT exit_time, r_multiple, strategies FROM trades WHERE status='closed' AND mode!='backtest'")
    per: dict[str, list[tuple[int, float]]] = {}
    for r in rows:
        for s in json.loads(r["strategies"] or "[]"):
            per.setdefault(s, []).append((r["exit_time"], float(r["r_multiple"] or 0)))
    suspended = db.kv_get("suspended_strategies", {}) or {}
    found = []
    for s, vals in per.items():
        recent = np.array([v for t, v in vals if t >= cutoff])
        hist = np.array([v for t, v in vals if t < cutoff])
        if len(recent) < 10 or len(hist) < 30:
            continue
        p = mann_whitney_less(recent, hist)
        if p < float(L["fatigue_pvalue"]) and recent.mean() < hist.mean() and s not in suspended:
            suspended[s] = {"time": int(time.time()), "p": round(p, 4), "recent": round(float(recent.mean()), 3),
                            "history": round(float(hist.mean()), 3)}
            db.alert("warning", "fatigue",
                     f"فرسودگی استراتژی {s}: میانگین R اخیر {recent.mean():+.2f} در برابر سابقه {hist.mean():+.2f} "
                     f"(p={p:.3f}). موقتاً غیرفعال شد تا بررسی شما.")
            found.append({"strategy": s, **suspended[s]})
    db.kv_set("suspended_strategies", suspended)
    return found


def suspended(db) -> set[str]:
    return set((db.kv_get("suspended_strategies", {}) or {}).keys())


def reinstate(db, strategy: str) -> None:
    s = db.kv_get("suspended_strategies", {}) or {}
    s.pop(strategy, None)
    db.kv_set("suspended_strategies", s)

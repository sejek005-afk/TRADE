"""قوانین اثر خبر روی معاملات و پوزیشن‌ها."""
from __future__ import annotations

import re
import time

from ..risk import exposures
from .calendar import Event

INVERSE_KEYS = ("unemployment", "jobless", "claims")


def _num(s: str) -> float | None:
    if not s:
        return None
    m = re.search(r"-?\d+(\.\d+)?", s.replace(",", ""))
    return float(m.group()) if m else None


def symbol_currencies(symbol: str) -> set[str]:
    return set(exposures(symbol, 1))


class NewsGuard:
    def __init__(self, cfg, calendar, feed):
        self.cfg, self.calendar, self.feed = cfg, calendar, feed

    @property
    def n(self) -> dict:
        return self.cfg.get("news")

    def relevant(self, symbol: str) -> list[Event]:
        cs = symbol_currencies(symbol)
        if symbol.upper().startswith("XAU"):
            cs |= {"USD"}
        return [e for e in self.calendar.events if e.currency in cs and e.is_high]

    def blocked(self, symbol: str, now: float | None = None) -> str:
        now = now or time.time()
        before, after = self.n["block_before_min"] * 60, self.n["block_after_min"] * 60
        for e in self.relevant(symbol):
            if -after <= e.time - now <= before:
                mins = int((e.time - now) / 60)
                when = f"{mins} دقیقه دیگر" if mins >= 0 else f"{-mins} دقیقه پیش"
                return f"خبر مهم {e.currency} «{e.title}» ({when})"
        return ""

    def minutes_to_next(self, symbol: str, now: float | None = None) -> float:
        now = now or time.time()
        fut = [e.time - now for e in self.relevant(symbol) if e.time >= now]
        return min(fut) / 60 if fut else 9999.0

    def upcoming_soon(self, symbol: str, now: float | None = None) -> Event | None:
        now = now or time.time()
        w = self.n["pre_news_minutes"] * 60
        return next((e for e in self.relevant(symbol) if 0 <= e.time - now <= w), None)

    def surprise_bias(self, symbol: str, now: float | None = None) -> tuple[float, str]:
        """مقایسه‌ی عدد واقعی با پیش‌بینی خبرهای ۹۰ دقیقه‌ی اخیر → امتیاز (در جهت خرید نماد)."""
        now = now or time.time()
        pts = float(self.n["surprise_bias_points"])
        total, notes = 0.0, []
        for e in self.relevant(symbol):
            if not (0 <= now - e.time <= 5400):
                continue
            a, f = _num(e.actual), _num(e.forecast)
            if a is None or f is None or a == f:
                continue
            sign = 1 if a > f else -1
            if any(k in e.title.lower() for k in INVERSE_KEYS):
                sign = -sign
            exp = exposures(symbol, 1).get(e.currency, 0)
            if symbol.upper().startswith("XAU") and e.currency == "USD":
                exp = -1
            total += pts * sign * exp
            notes.append(f"{e.title}: واقعی {e.actual} در برابر پیش‌بینی {e.forecast}")
        return max(-2 * pts, min(2 * pts, total)), "؛ ".join(notes)

    def adverse_headline(self, symbol: str, direction: int, since: float) -> dict | None:
        """تیتر فوری شدیداً مخالف پوزیشن باز در ۱۰ دقیقه‌ی اخیر."""
        for h in reversed(self.feed.recent if self.feed else []):
            if h["time"] < since or h["time"] < time.time() - 600:
                continue
            eff = h.get("effects", {}).get(symbol, 0)
            if eff * direction <= -0.6:
                return h
        return None

    def headline_bias(self, symbol: str, minutes: int = 30) -> float:
        now = time.time()
        vals = [h.get("effects", {}).get(symbol, 0) for h in (self.feed.recent if self.feed else [])
                if now - h["time"] <= minutes * 60]
        if not vals:
            return 0.0
        return max(-6.0, min(6.0, 6.0 * sum(vals) / max(3, len(vals))))

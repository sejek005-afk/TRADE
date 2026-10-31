"""تحلیل احساسات تیتر خبر و اثر آن روی هر ارز/نماد.

پیش‌فرض: واژه‌نامه‌ی مالی سبک (سریع، بدون GPU). اگر FinBERT نصب و فعال باشد، از آن برای قطبیت استفاده می‌شود
و واژه‌نامه فقط برای تعیین ارز درگیر و جهت (هاوکیش/داویش) به کار می‌رود.
"""
from __future__ import annotations

import logging
import re

from ..risk import exposures

log = logging.getLogger("ntpro.sentiment")

CCY_ALIASES = {
    "USD": ["fed", "fomc", "powell", "u.s.", "us ", "united states", "dollar", "treasury", "nfp", "payroll", "white house"],
    "EUR": ["ecb", "lagarde", "euro", "eurozone", "germany", "german", "bund"],
    "GBP": ["boe", "bailey", "sterling", "pound", "uk ", "britain", "gilt"],
    "JPY": ["boj", "ueda", "yen", "japan"],
    "CHF": ["snb", "franc", "swiss"],
    "CAD": ["boc", "loonie", "canada", "canadian"],
    "AUD": ["rba", "aussie", "australia"],
    "NZD": ["rbnz", "kiwi", "new zealand"],
    "XAU": ["gold", "bullion", "xau"],
}

HAWKISH = ["hike", "hawkish", "tighten", "higher for longer", "inflation rises", "hot cpi", "beats", "strong",
           "surge", "jumps", "accelerat", "above expectations", "better than expected", "upbeat", "robust"]
DOVISH = ["cut", "dovish", "ease", "easing", "slows", "weak", "miss", "below expectations", "worse than expected",
          "contraction", "recession", "plunge", "falls", "drops", "slump", "layoffs", "stimulus"]
RISK_OFF = ["war", "attack", "missile", "escalat", "crisis", "default", "sanction", "panic", "crash", "turmoil",
            "conflict", "invasion", "safe haven", "bank run"]
INVERSE_DATA = ["unemployment", "jobless", "claims"]  # عدد بالاتر = بد برای ارز


def currencies_in(text: str) -> list[str]:
    t = f" {text.lower()} "
    return [c for c, words in CCY_ALIASES.items() if any(w in t for w in words)]


def lexicon_polarity(text: str) -> float:
    t = text.lower()
    pos = sum(t.count(w) for w in HAWKISH)
    neg = sum(t.count(w) for w in DOVISH)
    if any(w in t for w in INVERSE_DATA) and re.search(r"\b(rise|rises|jump|higher|up)\b", t):
        pos, neg = neg, pos + 1
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


class FinBert:
    _pipe = None

    @classmethod
    def polarity(cls, text: str) -> float | None:
        try:
            if cls._pipe is None:
                from transformers import pipeline   # اختیاری
                cls._pipe = pipeline("sentiment-analysis", model="ProsusAI/finbert")
            r = cls._pipe(text[:512])[0]
            sign = {"positive": 1, "negative": -1}.get(r["label"].lower(), 0)
            return sign * float(r["score"])
        except Exception as e:  # pragma: no cover - به نصب transformers بستگی دارد
            log.debug("finbert unavailable: %s", e)
            return None


def analyze(headline: str, use_finbert: bool = False) -> dict:
    """خروجی: {'currencies': {...: score}, 'risk_off': bool, 'polarity': float}"""
    pol = lexicon_polarity(headline)
    if use_finbert:
        fb = FinBert.polarity(headline)
        if fb is not None:
            pol = 0.5 * pol + 0.5 * fb if pol else fb
    t = headline.lower()
    risk_off = any(w in t for w in RISK_OFF)
    ccys = currencies_in(headline)
    scores = {c: pol for c in ccys if c != "XAU"}
    if "XAU" in ccys:
        scores["XAU"] = pol
    if risk_off:
        scores["XAU"] = scores.get("XAU", 0) + 0.6
        scores["JPY"] = scores.get("JPY", 0) + 0.3
        scores["CHF"] = scores.get("CHF", 0) + 0.3
    return {"currencies": {k: max(-1.0, min(1.0, v)) for k, v in scores.items()}, "risk_off": risk_off, "polarity": pol}


def symbol_effect(symbol: str, analysis: dict) -> float:
    """اثر خبر روی خرید نماد (−۱..۱)."""
    cs = analysis["currencies"]
    eff = 0.0
    for cur, d in exposures(symbol, 1).items():
        eff += d * cs.get(cur, 0.0)
    if symbol.upper().startswith("XAU") and "USD" in cs and "XAU" not in cs:
        eff = -cs["USD"] * 0.7
    return max(-1.0, min(1.0, eff))


def label(effect: float) -> str:
    if effect > 0.2:
        return "مثبت"
    if effect < -0.2:
        return "منفی"
    return "خنثی"

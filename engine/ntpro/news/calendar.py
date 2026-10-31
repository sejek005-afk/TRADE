"""تقویم اقتصادی از چند منبع با پشتیبان: Finnhub → FMP → Trading Economics → ForexFactory."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from . import http

log = logging.getLogger("ntpro.calendar")

COUNTRY_CCY = {"US": "USD", "EU": "EUR", "EMU": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "UK": "GBP", "GB": "GBP",
               "JP": "JPY", "CH": "CHF", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "CN": "CNY",
               "UNITED STATES": "USD", "EURO AREA": "EUR", "EUROZONE": "EUR", "GERMANY": "EUR",
               "UNITED KINGDOM": "GBP", "JAPAN": "JPY", "SWITZERLAND": "CHF", "CANADA": "CAD",
               "AUSTRALIA": "AUD", "NEW ZEALAND": "NZD", "CHINA": "CNY"}

HIGH_KEYWORDS = ("non-farm", "nonfarm", "nfp", "cpi", "consumer price", "fomc", "interest rate", "rate decision",
                 "fed chair", "powell", "ecb", "boe", "boj", "core pce", "gdp", "unemployment rate", "payrolls")


@dataclass
class Event:
    time: int
    currency: str
    title: str
    impact: str          # high | medium | low
    forecast: str = ""
    previous: str = ""
    actual: str = ""
    source: str = ""

    @property
    def is_high(self) -> bool:
        return self.impact == "high" or any(k in self.title.lower() for k in HIGH_KEYWORDS)


def _ccy(country: str) -> str:
    c = (country or "").strip().upper()
    return COUNTRY_CCY.get(c, c if len(c) == 3 else c[:3])


def _impact(v) -> str:
    s = str(v).lower()
    if s in ("3", "high", "h"):
        return "high"
    if s in ("2", "medium", "m"):
        return "medium"
    return "low"


def _ts(s: str, fmt_utc: bool = True) -> int:
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _s(v) -> str:
    return "" if v is None else str(v)


def from_finnhub(key: str, start: datetime, end: datetime) -> list[Event]:
    url = (f"https://finnhub.io/api/v1/calendar/economic?from={start:%Y-%m-%d}&to={end:%Y-%m-%d}&token={key}")
    data = http.get_json(url).get("economicCalendar", [])
    return [Event(_ts(e["time"]), _ccy(e.get("country", "")), e.get("event", ""), _impact(e.get("impact")),
                  _s(e.get("estimate")), _s(e.get("prev")), _s(e.get("actual")), "finnhub") for e in data]


def from_fmp(key: str, start: datetime, end: datetime) -> list[Event]:
    url = (f"https://financialmodelingprep.com/api/v3/economic_calendar?from={start:%Y-%m-%d}&to={end:%Y-%m-%d}"
           f"&apikey={key}")
    return [Event(_ts(e["date"]), e.get("currency") or _ccy(e.get("country", "")), e.get("event", ""),
                  _impact(e.get("impact")), _s(e.get("estimate")), _s(e.get("previous")), _s(e.get("actual")), "fmp")
            for e in http.get_json(url)]


def from_tradingeconomics(key: str, start: datetime, end: datetime) -> list[Event]:
    url = f"https://api.tradingeconomics.com/calendar/country/all/{start:%Y-%m-%d}/{end:%Y-%m-%d}?c={key}&f=json"
    return [Event(_ts(e["Date"]), e.get("Currency") or _ccy(e.get("Country", "")), e.get("Event", ""),
                  _impact(e.get("Importance")), _s(e.get("Forecast")), _s(e.get("Previous")), _s(e.get("Actual")), "te")
            for e in http.get_json(url)]


def from_forexfactory() -> list[Event]:
    """فید هفتگی رایگان (بدون کلید، بدون عدد واقعی)."""
    data = http.get_json("https://nfs.faireconomy.media/ff_calendar_thisweek.json")
    return [Event(_ts(e["date"]), e.get("country", ""), e.get("title", ""), _impact(e.get("impact")),
                  _s(e.get("forecast")), _s(e.get("previous")), "", "forexfactory") for e in data]


class Calendar:
    def __init__(self, cfg, db=None):
        self.cfg, self.db = cfg, db
        self.events: list[Event] = []
        self.last_ok = 0.0
        self.source = ""

    def refresh(self) -> list[Event]:
        n = self.cfg.get("news")
        now = datetime.now(timezone.utc)
        start, end = now - timedelta(days=1), now + timedelta(days=7)
        chain = []
        if n.get("finnhub_key"):
            chain.append(("finnhub", lambda: from_finnhub(n["finnhub_key"], start, end)))
        if n.get("fmp_key"):
            chain.append(("fmp", lambda: from_fmp(n["fmp_key"], start, end)))
        if n.get("te_key"):
            chain.append(("te", lambda: from_tradingeconomics(n["te_key"], start, end)))
        chain.append(("forexfactory", from_forexfactory))
        for name, fn in chain:
            try:
                evs = [e for e in fn() if e.currency]
                if evs:
                    self.events, self.last_ok, self.source = evs, time.time(), name
                    self._persist(evs)
                    return evs
            except Exception as e:  # منبع بعدی
                log.warning("calendar source %s failed: %s", name, e)
        if self.db is not None and not self.events:
            self.events = self.load_cached()
        return self.events

    def _persist(self, evs: list[Event]) -> None:
        if self.db is None:
            return
        self.db.executemany(
            "INSERT INTO events(time,currency,title,impact,forecast,previous,actual,source) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(time,currency,title) DO UPDATE SET actual=excluded.actual, forecast=excluded.forecast, "
            "impact=excluded.impact",
            [(e.time, e.currency, e.title, e.impact, e.forecast, e.previous, e.actual, e.source) for e in evs])

    def load_cached(self) -> list[Event]:
        since = int(time.time()) - 86400
        rows = self.db.query("SELECT time,currency,title,impact,forecast,previous,actual,source FROM events WHERE time>=?",
                             (since,))
        return [Event(**r) for r in rows]

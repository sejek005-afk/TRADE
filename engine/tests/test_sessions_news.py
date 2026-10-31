import time
from datetime import datetime, timezone

from ntpro.config import DEFAULTS, Config
from ntpro.news import sentiment
from ntpro.news.calendar import Event
from ntpro.news.rules import NewsGuard
from ntpro.news.headlines import parse_rss
from ntpro.sessions import SessionClock, bank_holidays, easter, to_tehran


def test_dst_sessions():
    c = SessionClock(DEFAULTS["sessions"])
    # تابستان: لندن 07:00 UTC باز می‌شود؛ زمستان: 08:00 UTC
    summer = datetime(2026, 7, 7, 7, 30, tzinfo=timezone.utc)
    winter = datetime(2026, 1, 13, 7, 30, tzinfo=timezone.utc)
    assert "london" in c.active_sessions(summer)
    assert "london" not in c.active_sessions(winter)
    ny_overlap = datetime(2026, 7, 7, 13, 0, tzinfo=timezone.utc)
    assert c.state("EURUSD", ny_overlap).primary == "overlap"


def test_blocks_friday_weekend_holiday_rollover():
    c = SessionClock(DEFAULTS["sessions"])
    assert not c.state("EURUSD", datetime(2026, 7, 10, 20, 0, tzinfo=timezone.utc)).can_open   # جمعه
    assert not c.state("EURUSD", datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)).can_open   # شنبه
    assert not c.state("EURUSD", datetime(2026, 12, 25, 12, 0, tzinfo=timezone.utc)).can_open  # کریسمس
    roll = datetime(2026, 7, 7, 21, 5, tzinfo=timezone.utc)   # 17:05 نیویورک (تابستان)
    s = c.state("XAUUSD", roll)
    assert not s.can_open
    assert easter(2026).isoformat() == "2026-04-05"
    assert len(bank_holidays(2026)) >= 8
    assert to_tehran(0).startswith("1970-01-01 03:30")


def test_sentiment_effects():
    a = sentiment.analyze("Fed signals rate hike as inflation rises, dollar strong")
    assert a["currencies"]["USD"] > 0
    assert sentiment.symbol_effect("EURUSD", a) < 0
    assert sentiment.symbol_effect("XAUUSD", a) < 0
    r = sentiment.analyze("Missile attack sparks escalation, investors seek safe haven")
    assert r["risk_off"] and sentiment.symbol_effect("XAUUSD", r) > 0


class _Cal:
    def __init__(self, events):
        self.events = events


def test_news_block_and_surprise(tmp_path):
    cfg = Config(tmp_path / "c.json")
    now = time.time()
    cal = _Cal([Event(int(now + 600), "USD", "Non-Farm Payrolls", "high", "180K", "150K", ""),
                Event(int(now - 1200), "EUR", "CPI y/y", "high", "2.1%", "2.0%", "2.6%")])
    g = NewsGuard(cfg, cal, None)
    assert "Non-Farm" in g.blocked("EURUSD", now)
    assert g.blocked("EURUSD", now - 7200) == ""
    bias, note = g.surprise_bias("EURUSD", now)
    assert bias > 0 and "CPI" in note


def test_rss_parse():
    xml = b"""<rss><channel><item><title>ECB holds rates</title><link>http://x</link>
    <pubDate>Mon, 02 Mar 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    items = parse_rss(xml, "test")
    assert items[0]["headline"] == "ECB holds rates"

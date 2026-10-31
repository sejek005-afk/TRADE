"""فید تیتر لحظه‌ای: Finnhub News + RSS (FinancialJuice، ForexLive و ...)؛ هر منبع که قطع شود بقیه کار می‌کنند."""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from . import http, sentiment

log = logging.getLogger("ntpro.headlines")

RSS_SOURCES = {
    "financialjuice": "https://www.financialjuice.com/feed.ashx?xy=rss",
    "forexlive": "https://www.forexlive.com/feed/news",
    "fxstreet": "https://www.fxstreet.com/rss/news",
}


def parse_rss(xml_bytes: bytes, source: str) -> list[dict]:
    out = []
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        try:
            ts = int(parsedate_to_datetime(pub).timestamp()) if pub else int(time.time())
        except Exception:
            ts = int(time.time())
        out.append({"time": ts, "source": source, "headline": title, "url": item.findtext("link") or ""})
    return out


class HeadlineFeed:
    def __init__(self, cfg, db=None):
        self.cfg, self.db = cfg, db
        self.last_ok = 0.0
        self.recent: list[dict] = []

    def fetch(self) -> list[dict]:
        items: list[dict] = []
        key = self.cfg.get("news", "finnhub_key")
        if key:
            try:
                for cat in ("forex", "general"):
                    for n in http.get_json(f"https://finnhub.io/api/v1/news?category={cat}&token={key}")[:40]:
                        items.append({"time": int(n.get("datetime", time.time())), "source": "finnhub",
                                      "headline": n.get("headline", ""), "url": n.get("url", "")})
            except Exception as e:
                log.warning("finnhub news failed: %s", e)
        for name, url in RSS_SOURCES.items():
            try:
                items += parse_rss(http.get(url), name)[:40]
            except Exception as e:
                log.debug("rss %s failed: %s", name, e)
        if items:
            self.last_ok = time.time()
        return self.ingest(items)

    def ingest(self, items: list[dict]) -> list[dict]:
        use_fb = bool(self.cfg.get("news", "use_finbert"))
        symbols = self.cfg.get("symbols")
        new = []
        seen = {r["headline"] for r in self.recent}
        for it in sorted(items, key=lambda x: x["time"]):
            if not it["headline"] or it["headline"] in seen:
                continue
            a = sentiment.analyze(it["headline"], use_fb)
            effects = {s: round(sentiment.symbol_effect(s, a), 2) for s in symbols}
            it.update(sentiment=a["polarity"], currencies=list(a["currencies"]), effects=effects,
                      impact="high" if a["risk_off"] or max((abs(v) for v in effects.values()), default=0) > 0.6 else "normal")
            new.append(it)
            seen.add(it["headline"])
            if self.db is not None:
                import json
                self.db.execute("INSERT OR IGNORE INTO news(time,source,headline,url,currencies,sentiment,impact,effects) "
                                "VALUES(?,?,?,?,?,?,?,?)",
                                (it["time"], it["source"], it["headline"], it["url"], json.dumps(it["currencies"]),
                                 it["sentiment"], it["impact"], json.dumps(effects, ensure_ascii=False)))
        self.recent = (self.recent + new)[-300:]
        return new

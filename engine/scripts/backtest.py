"""بک‌تست از خط فرمان (روی VPS، با داده‌ی MT5 یا فایل CSV).

مثال‌ها:
  python scripts/backtest.py --symbol XAUUSD --days 90
  python scripts/backtest.py --csv data/EURUSD_M5.csv --symbol EURUSD --per-strategy
  python scripts/backtest.py --symbol EURUSD --days 30 --ticks
CSV: ستون‌های time,open,high,low,close,tick_volume,spread (time به UTC)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ntpro.backtest import report  # noqa: E402
from ntpro.backtest.engine import Backtester  # noqa: E402
from ntpro.config import DATA_DIR, Config  # noqa: E402
from ntpro.risk import default_spec  # noqa: E402
from ntpro.strategies import ALL  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--csv")
    ap.add_argument("--ticks", action="store_true", help="استفاده از داده‌ی تیک MT5")
    ap.add_argument("--per-strategy", action="store_true")
    ap.add_argument("--balance", type=float, default=10000)
    a = ap.parse_args()
    cfg = Config(DATA_DIR / "config.json")
    ticks = None
    if a.csv:
        df = pd.read_csv(a.csv)
        df.index = pd.to_datetime(df.pop("time"), utc=True)
        spec = default_spec(a.symbol)
    else:
        from ntpro.broker.mt5 import MT5Broker
        from ntpro.security.vault import Vault
        v = Vault(DATA_DIR / "master.key")
        b = MT5Broker(cfg, lambda: v.load_secret("mt5"))
        if not b.connect():
            sys.exit(f"MT5: {b.last_error}")
        end = datetime.now(timezone.utc)
        df = b.candles_range(a.symbol, "M5", end - timedelta(days=a.days), end)
        spec = b.spec(a.symbol)
        if a.ticks:
            ticks = b.ticks_range(a.symbol, df.index[0].to_pydatetime(), end)
    bt = Backtester(cfg, a.symbol, df, spec, ticks=ticks, balance=a.balance)
    rep = report.full_report(bt.run(label="ترکیبی"))
    print(report.to_text_fa(rep))
    out = {"combined": rep}
    if a.per_strategy:
        out["per_strategy"] = {}
        for name in ALL:
            r = report.full_report(bt.run(only={name}, label=name), mc_runs=300)
            out["per_strategy"][name] = r
            print("-" * 40)
            print(report.to_text_fa(r))
    path = DATA_DIR / f"backtest_{a.symbol}_{datetime.now():%Y%m%d_%H%M}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\nگزارش کامل: {path}")


if __name__ == "__main__":
    main()

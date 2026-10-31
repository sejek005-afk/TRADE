"""دیتابیس SQLite (حالت WAL) برای کندل، تیک، سیگنال، معامله، خبر، وزن‌ها، مدل‌ها و هشدارها."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT, tf TEXT, time INTEGER, open REAL, high REAL, low REAL, close REAL,
    tick_volume REAL, spread REAL, PRIMARY KEY (symbol, tf, time));
CREATE TABLE IF NOT EXISTS ticks (symbol TEXT, time_msc INTEGER, bid REAL, ask REAL, PRIMARY KEY (symbol, time_msc));
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, symbol TEXT, direction INTEGER,
    combined_score REAL, accepted INTEGER, reject_reason TEXT, regime TEXT, session TEXT,
    ml_prob REAL, nn_prob REAL, shadow_prob REAL, strategies TEXT, payload TEXT);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT, client_id TEXT UNIQUE, ticket INTEGER, mode TEXT,
    symbol TEXT, direction INTEGER, volume REAL, initial_volume REAL,
    entry_time INTEGER, entry_price REAL, requested_price REAL, sl REAL, initial_sl REAL, tp REAL, tp1 REAL,
    exit_time INTEGER, exit_price REAL, pnl REAL, r_multiple REAL, commission REAL,
    slippage_points REAL, spread_points REAL, atr REAL, regime TEXT, session TEXT,
    strategies TEXT, score REAL, ml_prob REAL, nn_prob REAL, news_flag INTEGER DEFAULT 0,
    reason_open TEXT, reason_close TEXT, status TEXT, tp1_hit INTEGER DEFAULT 0,
    bars_held INTEGER DEFAULT 0, mfe_r REAL DEFAULT 0, features TEXT, learned INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS trades_status ON trades(status);
CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, source TEXT, headline TEXT UNIQUE, url TEXT,
    currencies TEXT, sentiment REAL, impact TEXT, effects TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, currency TEXT, title TEXT, impact TEXT,
    forecast TEXT, previous TEXT, actual TEXT, source TEXT, UNIQUE(time, currency, title));
CREATE TABLE IF NOT EXISTS weights (
    bucket TEXT, strategy TEXT, alpha REAL, beta REAL, weight REAL, n REAL, n_raw INTEGER, updated INTEGER,
    PRIMARY KEY (bucket, strategy));
CREATE TABLE IF NOT EXISTS weight_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, bucket TEXT, strategy TEXT,
    old REAL, new REAL, reason TEXT);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, label TEXT, weights TEXT, models TEXT, healthy INTEGER);
CREATE TABLE IF NOT EXISTS models (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, version INTEGER, path TEXT, created INTEGER,
    metrics TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, level TEXT, kind TEXT, message TEXT, sent INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, pw_hash TEXT, totp_secret TEXT, totp_confirmed INTEGER DEFAULT 0, created INTEGER);
CREATE TABLE IF NOT EXISTS refresh_tokens (jti TEXT PRIMARY KEY, username TEXT, expires INTEGER, revoked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS config_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, user TEXT, reason TEXT, changes TEXT, snapshot TEXT);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, time INTEGER, user TEXT, ip TEXT, action TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS equity (time INTEGER PRIMARY KEY, balance REAL, equity REAL);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS health (time INTEGER PRIMARY KEY, ping_ms REAL, mt5 INTEGER, feed_age REAL, news_age REAL);
"""


class DB:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---------- پایه ----------
    def execute(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def executemany(self, sql: str, rows: list) -> None:
        with self._lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    def query(self, sql: str, params: Iterable = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def backup_to(self, dest: str | Path) -> None:
        with self._lock:
            target = sqlite3.connect(str(dest))
            self.conn.backup(target)
            target.close()

    # ---------- kv ----------
    def kv_get(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return default if r is None else json.loads(r["value"])

    def kv_set(self, key: str, value: Any) -> None:
        self.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    # ---------- کندل ----------
    def save_candles(self, symbol: str, tf: str, df) -> None:
        if df is None or len(df) == 0:
            return
        rows = [(symbol, tf, int(t.timestamp()), float(r.open), float(r.high), float(r.low), float(r.close),
                 float(r.tick_volume), float(getattr(r, "spread", 0) or 0)) for t, r in df.iterrows()]
        self.executemany("INSERT OR REPLACE INTO candles VALUES (?,?,?,?,?,?,?,?,?)", rows)

    def load_candles(self, symbol: str, tf: str, since: int = 0, limit: int | None = None):
        import pandas as pd
        sql = "SELECT time,open,high,low,close,tick_volume,spread FROM candles WHERE symbol=? AND tf=? AND time>=? ORDER BY time"
        rows = self.query(sql, (symbol, tf, since))
        if limit:
            rows = rows[-limit:]
        df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "tick_volume", "spread"])
        if len(df):
            df.index = pd.to_datetime(df.pop("time"), unit="s", utc=True)
        return df

    # ---------- هشدار ----------
    def alert(self, level: str, kind: str, message: str) -> int:
        return self.execute("INSERT INTO alerts(time,level,kind,message) VALUES(?,?,?,?)",
                            (int(time.time()), level, kind, message)).lastrowid

    def audit(self, user: str, ip: str, action: str, result: str) -> None:
        self.execute("INSERT INTO audit(time,user,ip,action,result) VALUES(?,?,?,?,?)",
                     (int(time.time()), user, ip, action, result))

    def add_config_version(self, user: str, reason: str, changes: list, snapshot: dict) -> None:
        self.execute("INSERT INTO config_versions(time,user,reason,changes,snapshot) VALUES(?,?,?,?,?)",
                     (int(time.time()), user, reason, json.dumps(changes, ensure_ascii=False),
                      json.dumps(snapshot, ensure_ascii=False)))

    # ---------- معامله ----------
    def insert_trade(self, t: dict) -> int:
        cols = list(t.keys())
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in t.values()]
        sql = f"INSERT INTO trades({','.join(cols)}) VALUES({','.join('?' * len(cols))})"
        return self.execute(sql, vals).lastrowid

    def update_trade(self, trade_id: int, **fields) -> None:
        if not fields:
            return
        vals = [json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for v in fields.values()]
        sets = ",".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE trades SET {sets} WHERE id=?", [*vals, trade_id])

    def open_trades(self, mode: str | None = None) -> list[dict]:
        if mode:
            return self.query("SELECT * FROM trades WHERE status='open' AND mode=?", (mode,))
        return self.query("SELECT * FROM trades WHERE status='open'")

    def closed_trades(self, limit: int = 1000, since: int = 0) -> list[dict]:
        return self.query("SELECT * FROM trades WHERE status='closed' AND exit_time>=? ORDER BY exit_time DESC LIMIT ?",
                          (since, limit))

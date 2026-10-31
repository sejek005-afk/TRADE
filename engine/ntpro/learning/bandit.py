"""لایه‌ی ۲ یادگیری: تنظیم محتاطانه‌ی وزن استراتژی‌ها با Thompson Sampling بعد از هر معامله‌ی بسته‌شده.

قواعد (همه قابل تنظیم، با سقف‌های سخت در config._validate):
  - وزن جدا برای هر ترکیب «Regime + سشن»
  - تا ثبت حداقل ۳۰ معامله در هر ترکیب، وزن ثابت (۱.۰) می‌ماند
  - هر معامله حداکثر ۵٪ وزن را تغییر می‌دهد
  - حداقل وزن ۱۰٪ (هیچ استراتژی‌ای صفر نمی‌شود)
  - Decay با نیمه‌عمر ۱۰۰ معامله
  - معاملات زمان اخبار شدید وزن کمتری در یادگیری دارند
"""
from __future__ import annotations

import json
import time

import numpy as np

MAX_WEIGHT = 2.0
NEUTRAL = 1.0


def bucket_key(regime: str, session: str) -> str:
    return f"{regime}|{session}"


def reward_from_r(r_multiple: float) -> float:
    """پاداش ۰ تا ۱ از R (به‌جای برد/باخت ساده، تا Expectancy مهم باشد نه فقط وین‌ریت)."""
    return float(np.clip(0.5 + r_multiple / 4.0, 0.0, 1.0))


class StrategyBandit:
    def __init__(self, db, cfg, seed: int | None = None):
        self.db, self.cfg = db, cfg
        self.rng = np.random.default_rng(seed)

    @property
    def L(self) -> dict:
        return self.cfg.get("learning")

    def _row(self, bucket: str, strategy: str) -> dict:
        r = self.db.one("SELECT * FROM weights WHERE bucket=? AND strategy=?", (bucket, strategy))
        return r or {"bucket": bucket, "strategy": strategy, "alpha": 1.0, "beta": 1.0, "weight": NEUTRAL,
                     "n": 0.0, "n_raw": 0}

    def weights(self, bucket: str, strategies: list[str]) -> dict[str, float]:
        rows = {r["strategy"]: r["weight"] for r in
                self.db.query("SELECT strategy, weight FROM weights WHERE bucket=?", (bucket,))}
        return {s: float(rows.get(s, NEUTRAL)) for s in strategies}

    def all_weights(self) -> list[dict]:
        return self.db.query("SELECT bucket, strategy, weight, n_raw, alpha, beta, updated FROM weights ORDER BY bucket, strategy")

    def update(self, trade: dict) -> list[dict]:
        """به‌روزرسانی بعد از بسته شدن معامله. خروجی: لیست تغییرات وزن."""
        if not self.L["enabled"] or self.db.kv_get("learning_paused", {}).get("paused"):
            return []
        bucket = bucket_key(trade["regime"], trade["session"])
        strategies = trade["strategies"]
        if isinstance(strategies, str):
            strategies = json.loads(strategies)
        w_trade = float(self.L["news_trade_weight"]) if trade.get("news_flag") else 1.0
        rew = reward_from_r(float(trade.get("r_multiple") or 0.0))
        gamma = 0.5 ** (1.0 / float(self.L["half_life_trades"]))
        changes = []
        for s in strategies:
            row = self._row(bucket, s)
            a = 1.0 + (row["alpha"] - 1.0) * gamma + w_trade * rew
            b = 1.0 + (row["beta"] - 1.0) * gamma + w_trade * (1.0 - rew)
            n_raw = int(row["n_raw"]) + 1
            old = float(row["weight"])
            new = old
            if n_raw >= int(self.L["min_trades_per_bucket"]):
                target = self._target(a, b, bucket, s)
                step = float(self.L["max_step"])
                new = old + float(np.clip(target - old, -step, step))
                new = float(np.clip(new, float(self.L["min_weight"]), MAX_WEIGHT))
            self.db.execute("INSERT OR REPLACE INTO weights(bucket,strategy,alpha,beta,weight,n,n_raw,updated) "
                            "VALUES(?,?,?,?,?,?,?,?)", (bucket, s, a, b, new, a + b - 2, n_raw, int(time.time())))
            if abs(new - old) > 1e-9:
                reason = (f"معامله #{trade.get('id')} R={float(trade.get('r_multiple') or 0):+.2f}"
                          f"{' (خبری، وزن کم)' if trade.get('news_flag') else ''}")
                self.db.execute("INSERT INTO weight_log(time,bucket,strategy,old,new,reason) VALUES(?,?,?,?,?,?)",
                                (int(time.time()), bucket, s, old, new, reason))
                changes.append({"bucket": bucket, "strategy": s, "old": old, "new": new})
        return changes

    def _target(self, a: float, b: float, bucket: str, strategy: str, draws: int = 400) -> float:
        """Thompson Sampling: احتمال اینکه این استراتژی در این bucket از میانگین بقیه بهتر باشد → وزن هدف."""
        others = [r for r in self.db.query("SELECT alpha, beta FROM weights WHERE bucket=? AND strategy!=?",
                                           (bucket, strategy))]
        mine = self.rng.beta(a, b, draws)
        if others:
            ref = np.mean([self.rng.beta(o["alpha"], o["beta"], draws) for o in others], axis=0)
        else:
            ref = np.full(draws, 0.5)
        p_better = float((mine > ref).mean())
        return float(np.clip(0.25 + 1.5 * p_better, float(self.L["min_weight"]), MAX_WEIGHT))

    # ---------- نسخه‌ها و Rollback ----------
    def snapshot(self, label: str, models: dict | None = None, healthy: bool = True) -> int:
        data = self.db.query("SELECT * FROM weights")
        return self.db.execute("INSERT INTO snapshots(time,label,weights,models,healthy) VALUES(?,?,?,?,?)",
                               (int(time.time()), label, json.dumps(data), json.dumps(models or {}),
                                int(healthy))).lastrowid

    def rollback(self, snapshot_id: int | None = None) -> dict | None:
        if snapshot_id is None:
            snap = self.db.one("SELECT * FROM snapshots WHERE healthy=1 ORDER BY id DESC LIMIT 1")
        else:
            snap = self.db.one("SELECT * FROM snapshots WHERE id=?", (snapshot_id,))
        if not snap:
            return None
        rows = json.loads(snap["weights"])
        self.db.execute("DELETE FROM weights")
        if rows:
            self.db.executemany("INSERT INTO weights(bucket,strategy,alpha,beta,weight,n,n_raw,updated) VALUES(?,?,?,?,?,?,?,?)",
                                [(r["bucket"], r["strategy"], r["alpha"], r["beta"], r["weight"], r["n"], r["n_raw"],
                                  r["updated"]) for r in rows])
        self.db.execute("INSERT INTO weight_log(time,bucket,strategy,old,new,reason) VALUES(?,?,?,?,?,?)",
                        (int(time.time()), "*", "*", 0, 0, f"Rollback به نسخه‌ی #{snap['id']} ({snap['label']})"))
        return snap

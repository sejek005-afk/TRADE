import json

import numpy as np

from ntpro.config import Config
from ntpro.db import DB
from ntpro.learning import fatigue, guard
from ntpro.learning.bandit import StrategyBandit, bucket_key
from ntpro.learning.registry import ModelRegistry


def make(tmp_path):
    db = DB(tmp_path / "t.db")
    cfg = Config(tmp_path / "c.json", db=db)
    return db, cfg


def trade(i, r, strategies=("ema_cross", "smc"), news=0):
    return {"id": i, "regime": "trending", "session": "london", "strategies": json.dumps(list(strategies)),
            "r_multiple": r, "news_flag": news}


def test_weights_frozen_until_min_trades(tmp_path):
    db, cfg = make(tmp_path)
    b = StrategyBandit(db, cfg, seed=1)
    for i in range(29):
        b.update(trade(i, 2.0))
    w = b.weights(bucket_key("trending", "london"), ["ema_cross", "smc"])
    assert w == {"ema_cross": 1.0, "smc": 1.0}


def test_step_and_floor_limits(tmp_path):
    db, cfg = make(tmp_path)
    b = StrategyBandit(db, cfg, seed=1)
    prev = 1.0
    for i in range(200):
        b.update(trade(i, -1.0, ("ema_cross",)))
        b.update(trade(i, 2.0, ("smc",)))
        w = b.weights(bucket_key("trending", "london"), ["ema_cross"])["ema_cross"]
        assert abs(w - prev) <= 0.05 + 1e-9
        assert w >= 0.10 - 1e-9
        prev = w
    ws = b.weights(bucket_key("trending", "london"), ["ema_cross", "smc"])
    assert ws["smc"] > ws["ema_cross"]
    assert db.query("SELECT COUNT(*) n FROM weight_log")[0]["n"] > 0


def test_rollback_and_brake(tmp_path):
    db, cfg = make(tmp_path)
    b = StrategyBandit(db, cfg, seed=1)
    reg = ModelRegistry(db, tmp_path / "m")
    sid = b.snapshot("healthy")
    for i in range(60):
        b.update(trade(i, -1.0, ("ema_cross",)))
    assert guard.check_brake(db, cfg, b, reg, 6.0)
    assert db.kv_get("learning_paused")["paused"]
    assert b.weights(bucket_key("trending", "london"), ["ema_cross"])["ema_cross"] == 1.0
    assert b.update(trade(99, 2.0)) == []          # یادگیری متوقف
    guard.resume(db, "me")
    assert not db.kv_get("learning_paused")["paused"]
    assert sid


def test_fatigue_detection(tmp_path):
    db, cfg = make(tmp_path)
    import time
    now = int(time.time())
    rng = np.random.default_rng(0)
    rows = []
    for k in range(80):
        rows.append((now - 60 * 86400 + k * 3600, float(rng.normal(0.6, 0.5))))
    for k in range(25):
        rows.append((now - 2 * 86400 + k * 600, float(rng.normal(-0.6, 0.5))))
    for t, r in rows:
        db.insert_trade({"client_id": f"c{t}", "mode": "demo", "symbol": "EURUSD", "status": "closed",
                         "exit_time": t, "r_multiple": r, "strategies": ["pullback"]})
    found = fatigue.check(db, cfg)
    assert any(f["strategy"] == "pullback" for f in found)
    assert "pullback" in fatigue.suspended(db)
    fatigue.reinstate(db, "pullback")
    assert "pullback" not in fatigue.suspended(db)

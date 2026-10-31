"""اجرای کامل موتور روی بروکر شبیه‌ساز با داده‌ی مصنوعی (بدون MT5)."""
import json

from conftest import make_candles

from ntpro import MAGIC
from ntpro.broker.paper import PaperBroker
from ntpro.engine import Engine


def test_engine_runs_end_to_end(tmp_path):
    data = make_candles(2600, seed=11)
    cfgdir = tmp_path / "d"
    broker = PaperBroker(None)
    eng = Engine(cfgdir, broker=broker)
    broker.cfg = eng.cfg
    eng.cfg.update({"bot_enabled": True, "mode": "paper", "symbols": ["EURUSD"],
                    "confluence": {"min_score": 55}})
    eng.executor.X["prefer_limit"] = False
    eng.cfg.data["execution"]["prefer_limit"] = False
    for i in range(1600, 2600):
        window = data.iloc[: i + 1]
        broker.fake_candles["EURUSD"] = window
        last = window.iloc[-1]
        broker.fake_ticks["EURUSD"] = {"bid": float(last.close), "ask": float(last.close) + 0.00008,
                                       "time": int(window.index[-1].timestamp()), "spread_points": 8}
        # برخورد SL/TP درون کندل
        broker.tick("EURUSD")
        eng.step()
    sigs = eng.db.query("SELECT COUNT(*) n FROM signals")[0]["n"]
    assert sigs > 0
    trades = eng.db.query("SELECT * FROM trades")
    for t in trades:
        assert t["sl"] and t["initial_sl"], "هر معامله باید حد ضرر داشته باشد"
        assert t["reason_open"]
    closed = [t for t in trades if t["status"] == "closed"]
    for t in closed:
        assert t["reason_close"]
    snap = eng.snapshot()
    assert snap["mode"] == "paper" and "EURUSD" in snap["market"]
    assert json.dumps(snap, default=str)
    assert MAGIC == 31102026


def test_magic_differs_from_old_engine():
    from ntpro import MAGIC
    assert MAGIC != 26102026

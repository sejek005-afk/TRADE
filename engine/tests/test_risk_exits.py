import pytest

from ntpro.config import Config
from ntpro.exits import manage, plan_tp
from ntpro.risk import ProhibitedAction, RiskManager, default_spec, exposures


@pytest.fixture
def rm(tmp_path):
    return RiskManager(Config(tmp_path / "c.json"))


def base_kwargs(spec, **kw):
    d = dict(symbol="EURUSD", direction=1, entry=1.1000, sl=1.0980, tp=1.1050, spec=spec, balance=10000, equity=10000,
             spread_points=8, open_trades=[], today_closed=[], recent_closed=[], kill_switch=None)
    d.update(kw)
    return d


def test_position_size_respects_risk(rm):
    spec = default_spec("EURUSD")
    vol = rm.position_size(spec, 10000, 1.1000, 1.0980, 0.5)
    risk_cash = spec.value_per_price_unit(vol) * 0.0020 + 7 * vol
    assert risk_cash <= 50.0 + 1e-6
    assert vol > 0


def test_pre_trade_ok_and_rr(rm):
    spec = default_spec("EURUSD")
    r = rm.pre_trade(**base_kwargs(spec))
    assert r.ok, r.reason
    assert r.rr_net >= 1.5
    bad = rm.pre_trade(**base_kwargs(spec, tp=1.1022))
    assert not bad.ok and "ریوارد" in bad.reason


def test_no_sl_is_prohibited(rm):
    with pytest.raises(ProhibitedAction):
        RiskManager.require_sl(1, 1.1, 0)
    with pytest.raises(ProhibitedAction):
        RiskManager.require_sl(1, 1.1, 1.2)


def test_sl_can_only_tighten():
    RiskManager.validate_sl_change(1, 1.0980, 1.0990)
    with pytest.raises(ProhibitedAction):
        RiskManager.validate_sl_change(1, 1.0980, 1.0970)
    with pytest.raises(ProhibitedAction):
        RiskManager.validate_sl_change(-1, 1.1020, 1.1030)
    with pytest.raises(ProhibitedAction):
        RiskManager.validate_sl_change(1, 1.0980, 0)


def test_no_grid_and_no_martingale(rm):
    spec = default_spec("EURUSD")
    r = rm.pre_trade(**base_kwargs(spec, open_trades=[{"symbol": "EURUSD", "direction": 1}]))
    assert not r.ok and "گرید" in r.reason
    with pytest.raises(ProhibitedAction):
        rm.no_martingale(5.0, [])
    losses = [{"pnl": -10}] * 3
    assert rm.no_martingale(0.5, losses) == pytest.approx(0.25)


def test_currency_correlation(rm):
    spec = default_spec("XAUUSD")
    r = rm.pre_trade(**base_kwargs(spec, symbol="XAUUSD", entry=2000, sl=1995, tp=2015,
                                   open_trades=[{"symbol": "EURUSD", "direction": 1}]))
    assert not r.ok and "USD" in r.reason
    r2 = rm.pre_trade(**base_kwargs(spec, symbol="XAUUSD", entry=2000, sl=1995, tp=2015,
                                    open_trades=[{"symbol": "EURUSD", "direction": -1}]))
    assert "همبستگی" not in r2.reason
    assert exposures("EURUSD", 1) == {"EUR": 1, "USD": -1}
    assert exposures("XAUUSD", -1) == {"XAU": -1, "USD": 1}


def test_daily_loss_and_kill(rm):
    spec = default_spec("EURUSD")
    r = rm.pre_trade(**base_kwargs(spec, today_closed=[{"pnl": -250}]))
    assert not r.ok and "روزانه" in r.reason
    r = rm.pre_trade(**base_kwargs(spec, kill_switch={"active": True, "reason": "x"}))
    assert not r.ok


def test_exits_partial_be_trail_timestop():
    cfg = Config.__new__(Config)
    ex = {"partial_tp_r": 1.0, "partial_close_pct": 50, "move_be_after_tp1": True, "trail_atr_mult": 1.2,
          "time_stop_bars": 24, "time_stop_min_r": 0.3, "use_liquidity_tp": True}
    t = {"direction": 1, "entry_price": 1.1000, "sl": 1.0980, "initial_sl": 1.0980, "volume": 0.2, "tp1": 1.1020,
         "tp1_hit": 0}
    acts = manage(t, 1.1021, 0.0005, 3, ex, 0.01, 0.01)
    kinds = [a.kind for a in acts]
    assert "partial" in kinds and "modify_sl" in kinds
    assert all(a.sl >= 1.1000 for a in acts if a.kind == "modify_sl")
    stale = manage({**t, "tp1": 1.1050}, 1.1002, 0.0005, 30, ex, 0.01, 0.01)
    assert any(a.kind == "close" for a in stale)
    tp1, tp = plan_tp(1.1, 1.098, 1, [], ex, 1.5, 0.0001)
    assert tp1 == pytest.approx(1.102) and (tp - 1.1) >= 1.5 * 0.0021

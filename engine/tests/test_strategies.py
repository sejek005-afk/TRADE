from datetime import timezone

import numpy as np

from ntpro import frame, indicators as ind, regime as rg
from ntpro.confluence import combine
from ntpro.sessions import SessionClock
from ntpro.config import DEFAULTS
from ntpro.strategies import ALL, Context, Signal
from ntpro.strategies.reversal import is_engulfing, is_pinbar
from ntpro import traps


def test_indicators_shapes(candles):
    f = frame.compute(candles)
    assert len(f) == len(candles)
    assert f["rsi"].between(0, 100).all()
    assert (f["atr"].dropna() > 0).all()
    assert set(f["st_dir"].unique()) <= {1.0, -1.0}


def test_no_lookahead_in_frame(candles):
    full = frame.compute(candles)
    part = frame.compute(candles.iloc[:2000])
    cols = ["ema9", "ema200", "atr", "rsi", "macd_hist", "adx", "st_dir", "vwap"]
    np.testing.assert_allclose(full[cols].iloc[1999].to_numpy(), part[cols].iloc[-1].to_numpy(), rtol=1e-9)


def test_all_strategies_run_and_score_in_range(candles):
    f = frame.compute(candles)
    clock = SessionClock(DEFAULTS["sessions"])
    found = 0
    for i in range(400, len(candles), 7):
        df, ff = candles.iloc[: i + 1], f.iloc[: i + 1]
        now = df.index[-1].to_pydatetime().astimezone(timezone.utc)
        ctx = Context("EURUSD", df, ff, rg.detect(df.iloc[-300:]), clock.state("EURUSD", now), now)
        for s in ALL.values():
            sig = s.evaluate(ctx)
            if sig:
                found += 1
                assert 0 <= sig.score <= 100
                assert sig.direction in (1, -1)
                assert (ctx.price - sig.sl) * sig.direction > 0, f"{s.name} SL wrong side"
    assert found > 20
    assert len(ALL) == 12


def test_candle_patterns():
    assert is_pinbar(1.0, 1.02, 0.90, 1.01) == 1
    assert is_pinbar(1.0, 1.10, 0.99, 0.995) == -1
    assert is_engulfing(1.02, 1.00, 0.995, 1.03) == 1


def test_confluence_requires_agreement():
    cfg = DEFAULTS["confluence"]
    one = [Signal("ema_cross", 1, 90, 1.0, "x")]
    d = combine(one, {}, cfg)
    assert d and not d.accepted
    two = one + [Signal("smc", 1, 80, 1.0, "y")]
    d = combine(two, {}, cfg)
    assert d.accepted and d.direction == 1 and len(d.strategies) == 2
    d = combine(two, {}, cfg, ml_prob=0.2)
    assert not d.accepted and "مدل" in d.reject_reason


def test_trap_spread_blocks(candles):
    f = frame.compute(candles)
    df, ff = candles.iloc[:800], f.iloc[:800]
    now = df.index[-1].to_pydatetime()
    ctx = Context("EURUSD", df, ff, rg.detect(df), SessionClock(DEFAULTS["sessions"]).state("EURUSD", now), now)
    r = traps.check(ctx, 1, ["smc"], 99, DEFAULTS["traps"], "EURUSD")
    assert r.blocked and any("اسپرد" in x for x in r.reasons)


def test_regime_labels(candles):
    r = rg.detect(candles.iloc[-500:])
    assert r.label in rg.ALLOWED

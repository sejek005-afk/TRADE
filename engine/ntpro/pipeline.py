"""خط تصمیم‌گیری مشترک بین موتور زنده و بک‌تستر (هر دو دقیقاً همین منطق را اجرا می‌کنند).

سشن → خبر → Regime → استراتژی‌های فعال → سیگنال‌ها → تله‌ها → مدل‌ها → Confluence → حد ضرر/سود → ریسک
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from . import exits, regime as rg
from .confluence import Decision, combine
from .learning import features as feats
from .learning.bandit import bucket_key
from .risk import RiskCheck, RiskManager, SymbolSpec
from .sessions import SessionClock, SessionState, bucket_session
from .strategies import ALL, Context
from . import traps


@dataclass
class AccountState:
    balance: float
    equity: float
    open_trades: list[dict] = field(default_factory=list)
    today_closed: list[dict] = field(default_factory=list)
    recent_closed: list[dict] = field(default_factory=list)
    kill_switch: dict | None = None


@dataclass
class Plan:
    direction: int
    entry: float
    sl: float
    tp1: float
    tp: float
    volume: float
    risk: RiskCheck


@dataclass
class Evaluation:
    symbol: str
    time: datetime
    session: SessionState
    regime: rg.Regime | None = None
    blocked: str = ""
    decision: Decision | None = None
    trap_reasons: list[str] = field(default_factory=list)
    ml_prob: float | None = None
    nn_prob: float | None = None
    shadow_prob: float | None = None
    plan: Plan | None = None
    tab: dict | None = None
    news_flag: bool = False

    @property
    def trade(self) -> bool:
        return self.plan is not None and self.plan.risk.ok


class Pipeline:
    def __init__(self, cfg, risk: RiskManager, *, weights_fn=None, models=None, shadow_models=None,
                 news_guard=None, intermarket=None, suspended_fn=None):
        self.cfg, self.risk = cfg, risk
        self.clock = SessionClock(cfg.get("sessions"))
        self.weights_fn = weights_fn or (lambda bucket, names: {n: 1.0 for n in names})
        self.models, self.shadow_models = models, shadow_models
        self.news_guard, self.intermarket = news_guard, intermarket
        self.suspended_fn = suspended_fn or (lambda: set())
        self.levels_cache: dict[str, tuple[int, list]] = {}

    def _levels(self, symbol: str, df: pd.DataFrame, refresh_every: int = 6) -> list:
        from . import levels as lv
        n = len(df)
        cached = self.levels_cache.get(symbol)
        if cached and 0 <= n - cached[0] < refresh_every:
            return cached[1]
        levels = lv.all_levels(df.iloc[-400:])
        self.levels_cache[symbol] = (n, levels)
        return levels

    def evaluate(self, symbol: str, df: pd.DataFrame, f: pd.DataFrame, now: datetime, *, spread_points: float,
                 spec: SymbolSpec, account: AccountState, ts: float | None = None,
                 only: set[str] | None = None, skip_risk: bool = False) -> Evaluation:
        ts = ts if ts is not None else _time.time()
        session = self.clock.state(symbol, now)
        ev = Evaluation(symbol, now, session)
        if not session.can_open:
            ev.blocked = session.block_reason
            return ev
        if self.news_guard is not None:
            nb = self.news_guard.blocked(symbol, ts)
            if nb:
                ev.blocked, ev.news_flag = nb, True
                return ev
        reg = rg.from_frame(f)
        ev.regime = reg
        enabled = dict(self.cfg.get("strategies"))
        for s in self.suspended_fn():
            enabled[s] = False
        allowed = rg.allowed_strategies(reg, enabled)
        if only is not None:
            allowed &= only
        if not allowed:
            ev.blocked = "هیچ استراتژی فعالی برای این وضعیت بازار نیست"
            return ev
        levels = self._levels(symbol, df)
        ctx = Context(symbol, df, f, reg, session, now, spec.point, levels_cache=levels)
        signals = [sig for name in allowed if (sig := ALL[name].evaluate(ctx)) is not None]
        if not signals:
            return ev

        conf = self.cfg.get("confluence")
        if only is not None and len(only) == 1:          # بک‌تست تک‌استراتژی
            conf = {**conf, "min_strategies": 1}
        bucket = bucket_key(reg.label, bucket_session(session.primary))
        weights = self.weights_fn(bucket, [s.strategy for s in signals])
        pre = combine(signals, weights, conf)
        direction = pre.direction

        trap = traps.check(ctx, direction, pre.strategies, spread_points, self.cfg.get("traps"), symbol)
        ev.trap_reasons = trap.reasons
        if trap.blocked:
            if not trap.reverse:
                ev.decision = pre
                pre.accepted, pre.reject_reason = False, "تله: " + "، ".join(trap.reasons)
                return ev

        im_bias, im_note = (self.intermarket.bias_for(symbol) if self.intermarket else (0.0, ""))
        news_bias, news_note = 0.0, ""
        mins_news = 9999.0
        if self.news_guard is not None:
            news_bias, news_note = self.news_guard.surprise_bias(symbol, ts)
            news_bias += self.news_guard.headline_bias(symbol)
            mins_news = self.news_guard.minutes_to_next(symbol, ts)
        kz_bonus = float(self.cfg.get("sessions", "kill_zone_bonus") or 0) if session.kill_zone else 0.0

        # مدل‌ها
        ml_prob = None
        if self.models is not None or self.shadow_models is not None:
            tab = feats.tabular(df, f, direction=direction, strategies=pre.strategies, score=pre.score,
                                regime=reg.label, session=session.primary, minutes_to_news=mins_news,
                                intermarket_bias=im_bias, spread_points=spread_points, point=spec.point,
                                levels=levels)
            seq = feats.sequence(df, f, direction)
            ev.tab = tab
            if self.models is not None:
                ml_prob, ev.nn_prob = self.models.predict_one(tab, seq)
                ev.ml_prob = ml_prob
            if self.shadow_models is not None:
                ev.shadow_prob = self.shadow_models.predict_one(tab, seq)[0]

        d = combine(signals, weights, conf, intermarket_bias=im_bias, intermarket_note=im_note,
                    news_bias=news_bias, kill_zone_bonus=kz_bonus, ml_prob=ml_prob, trap_penalty=trap.penalty)
        if trap.blocked and trap.reverse:                 # معامله‌ی برعکسِ تله
            d.direction = -direction
            d.sl = ctx.swing_high(6) + 0.2 * ctx.atr if d.direction < 0 else ctx.swing_low(6) - 0.2 * ctx.atr
            d.tp = None
            d.reasons_fa = ["معکوس تله: " + "، ".join(trap.reasons)]
            d.strategies = d.strategies + ["trap_reverse"] if "trap_reverse" not in d.strategies else d.strategies
        if news_note:
            d.reasons_fa.append(f"خبر: {news_note}")
        ev.decision = d
        if not d.accepted:
            return ev

        # حد ضرر: ساختاری، محدود به ۰.۸ تا ۳ ATR
        entry = ctx.price
        a = ctx.atr
        dist = abs(entry - d.sl)
        dist = min(max(dist, 0.8 * a), 3.0 * a)
        sl = entry - d.direction * dist
        cost = self.risk.cost_in_price(spec, spec.volume_min, spread_points)
        tp1, tp = exits.plan_tp(entry, sl, d.direction, levels, self.cfg.get("exits"),
                                float(self.cfg.get("risk", "min_rr_after_costs")), cost, d.tp)
        if skip_risk:
            ev.plan = Plan(d.direction, entry, sl, tp1, tp, spec.volume_min, RiskCheck(True, volume=spec.volume_min))
            return ev
        chk = self.risk.pre_trade(symbol=symbol, direction=d.direction, entry=entry, sl=sl, tp=tp, spec=spec,
                                  balance=account.balance, equity=account.equity, spread_points=spread_points,
                                  open_trades=account.open_trades, today_closed=account.today_closed,
                                  recent_closed=account.recent_closed, kill_switch=account.kill_switch)
        ev.plan = Plan(d.direction, entry, sl, tp1, tp, chk.volume, chk)
        if not chk.ok:
            d.accepted, d.reject_reason = False, chk.reason
        return ev

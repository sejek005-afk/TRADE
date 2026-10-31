"""بک‌تستر واقعی (ماژول ۸): کمیسیون ECN، اسپرد متغیر، اسلیپیج، داده‌ی تیک.

- همان Pipeline موتور زنده اجرا می‌شود (بدون نگاه به آینده: تصمیم روی کندل بسته‌شده، ورود در باز شدن کندل بعد).
- اگر داده‌ی تیک داده شود، برخورد حد ضرر/سود تیک‌به‌تیک بررسی می‌شود؛ وگرنه مسیر محافظه‌کارانه‌ی درون کندل
  (اگر هر دو در یک کندل بودند، اول حد ضرر).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np
import pandas as pd

from .. import exits, frame
from ..pipeline import AccountState, Pipeline
from ..risk import RiskManager, SymbolSpec

log = logging.getLogger("ntpro.backtest")


@dataclass
class BTTrade:
    id: int
    symbol: str
    direction: int
    entry_time: pd.Timestamp
    entry_price: float
    volume: float
    initial_volume: float
    sl: float
    initial_sl: float
    tp: float
    tp1: float
    strategies: list[str]
    regime: str
    session: str
    score: float
    spread_points: float
    slippage_points: float
    ml_prob: float | None = None
    tab: dict | None = None
    tp1_hit: bool = False
    bars_held: int = 0
    realized: float = 0.0
    commission: float = 0.0
    exit_time: pd.Timestamp | None = None
    exit_price: float | None = None
    reason_close: str = ""
    reason_open: str = ""
    r_multiple: float = 0.0

    @property
    def risk_amount(self) -> float:
        return abs(self.entry_price - self.initial_sl)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["pnl"] = self.realized - self.commission
        d["status"] = "closed" if self.exit_time is not None else "open"
        return d


@dataclass
class BTResult:
    symbol: str
    trades: list[dict]
    equity: pd.Series
    initial_balance: float
    signals: int = 0
    label: str = ""
    meta: dict = field(default_factory=dict)


class Backtester:
    def __init__(self, cfg, symbol: str, candles: pd.DataFrame, spec: SymbolSpec, *, ticks: pd.DataFrame | None = None,
                 balance: float = 10000.0, slippage_sd_points: float | None = None, seed: int = 1,
                 models=None, news_guard=None, intermarket=None, weights_fn=None):
        self.cfg, self.symbol, self.df, self.spec = cfg, symbol, candles, spec
        self.ticks = ticks
        self.balance0 = balance
        self.rng = np.random.default_rng(seed)
        lim = cfg.get("execution", "max_slippage_points")
        self.slip_sd = slippage_sd_points if slippage_sd_points is not None else lim.get(symbol, lim["default"]) / 4
        self.risk = RiskManager(cfg)
        self.pipe = Pipeline(cfg, self.risk, models=models, news_guard=news_guard, intermarket=intermarket,
                             weights_fn=weights_fn)
        self.f = frame.compute(candles)

    # ---------- هزینه‌ها ----------
    def _slip(self) -> float:
        return abs(float(self.rng.normal(0, self.slip_sd)))

    def _commission(self, volume: float) -> float:
        return float(self.cfg.get("risk", "commission_per_lot_usd")) * volume

    def _pnl(self, t: BTTrade, price: float, volume: float) -> float:
        return (price - t.entry_price) * t.direction * self.spec.value_per_price_unit(volume)

    # ---------- مسیر قیمت درون کندل ----------
    def _path(self, i: int, direction: int) -> list[tuple[float, float]]:
        """لیست (bid, ask) به ترتیب زمانی درون کندل i."""
        row = self.df.iloc[i]
        sp = float(row.get("spread", 0) or 0) * self.spec.point
        if self.ticks is not None:
            t0 = self.df.index[i]
            seg = self.ticks.loc[t0: t0 + timedelta(minutes=5) - timedelta(microseconds=1)]
            if len(seg):
                return list(zip(seg["bid"].to_numpy(), seg["ask"].to_numpy()))
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        # محافظه‌کارانه: اول به سمت حد ضرر
        seq = [o, l, h, c] if direction > 0 else [o, h, l, c]
        return [(p, p + sp) for p in seq]

    def run(self, only: set[str] | None = None, warmup: int = 300, label: str = "") -> BTResult:
        df, f, spec = self.df, self.f, self.spec
        balance = self.balance0
        open_t: BTTrade | None = None
        pending = None
        closed: list[BTTrade] = []
        equity = []
        signals = 0
        tid = 0
        cfg_exits = self.cfg.get("exits")
        for i in range(warmup, len(df)):
            ts = df.index[i]
            # ۱) ورود سفارشِ تصمیم کندل قبل در باز شدن این کندل
            if pending is not None and open_t is None:
                ev = pending
                pending = None
                row = df.iloc[i]
                sp_pts = float(row.get("spread", 0) or 0)
                slip = self._slip()
                d = ev.plan.direction
                price = row["open"] + (sp_pts * spec.point if d > 0 else 0) + d * slip * spec.point
                if (price - ev.plan.sl) * d > 0 and (ev.plan.tp - price) * d > 0:
                    tid += 1
                    open_t = BTTrade(tid, self.symbol, d, ts, float(price), ev.plan.volume, ev.plan.volume,
                                     ev.plan.sl, ev.plan.sl, ev.plan.tp, ev.plan.tp1, ev.decision.strategies,
                                     ev.regime.label, ev.session.primary, ev.decision.score, sp_pts, slip,
                                     ev.ml_prob, ev.tab, reason_open="؛ ".join(ev.decision.reasons_fa))
            # ۲) شبیه‌سازی درون کندل
            if open_t is not None:
                t = open_t
                for bid, ask in self._path(i, t.direction):
                    px = bid if t.direction > 0 else ask        # قیمت خروج
                    if (px - t.sl) * t.direction <= 0:
                        slip = self._slip() * spec.point
                        fill = t.sl - t.direction * slip
                        self._close(t, fill, t.volume, ts, "حد ضرر" if not t.tp1_hit else "حد ضرر سربه‌سر/متحرک")
                        break
                    if not t.tp1_hit and (px - t.tp1) * t.direction >= 0:
                        part = round(int(t.volume * cfg_exits["partial_close_pct"] / 100 / spec.volume_step)
                                     * spec.volume_step, 8)
                        if part >= spec.volume_min and t.volume - part >= spec.volume_min:
                            self._close(t, t.tp1, part, ts, "هدف اول", final=False)
                        t.tp1_hit = True
                        if cfg_exits.get("move_be_after_tp1", True):
                            t.sl = max(t.sl, t.entry_price) if t.direction > 0 else min(t.sl, t.entry_price)
                    if (px - t.tp) * t.direction >= 0:
                        self._close(t, t.tp, t.volume, ts, "حد سود (ناحیه‌ی نقدینگی)")
                        break
                if t.exit_time is not None:
                    balance += t.realized - t.commission
                    closed.append(t)
                    open_t = None
                else:
                    t.bars_held += 1
                    acts = exits.manage({"direction": t.direction, "entry_price": t.entry_price, "sl": t.sl,
                                         "initial_sl": t.initial_sl, "volume": t.volume, "tp1": t.tp1,
                                         "tp1_hit": t.tp1_hit}, float(df["close"].iloc[i]), float(f["atr"].iloc[i]),
                                        t.bars_held, cfg_exits, spec.volume_step, spec.volume_min)
                    for a in acts:
                        if a.kind == "modify_sl":
                            t.sl = a.sl
                        elif a.kind == "close":
                            px = float(df["close"].iloc[i])
                            if t.direction < 0:
                                px += float(df["spread"].iloc[i] or 0) * spec.point
                            self._close(t, px, t.volume, ts, a.reason)
                    if t.exit_time is not None:
                        balance += t.realized - t.commission
                        closed.append(t)
                        open_t = None

            open_pnl = self._pnl(open_t, float(df["close"].iloc[i]), open_t.volume) + open_t.realized if open_t else 0
            equity.append((ts, balance + open_pnl))

            # ۳) تصمیم روی کندل بسته‌شده
            if open_t is None and pending is None and i < len(df) - 1:
                now = (ts + timedelta(minutes=5)).to_pydatetime()
                day = ts.floor("D")
                today = [c.as_dict() for c in closed if c.exit_time is not None and c.exit_time >= day]
                acct = AccountState(balance, balance, [], today, [c.as_dict() for c in reversed(closed[-5:])])
                ev = self.pipe.evaluate(self.symbol, df.iloc[: i + 1], f.iloc[: i + 1], now,
                                        spread_points=float(df["spread"].iloc[i] or 0), spec=spec, account=acct,
                                        ts=now.timestamp(), only=only)
                if ev.decision is not None:
                    signals += 1
                if ev.trade:
                    pending = ev
        if open_t is not None:
            self._close(open_t, float(df["close"].iloc[-1]), open_t.volume, df.index[-1], "پایان داده")
            closed.append(open_t)
        eq = pd.Series([e for _, e in equity], index=[t for t, _ in equity], dtype=float)
        return BTResult(self.symbol, [t.as_dict() for t in closed], eq, self.balance0, signals, label)

    def _close(self, t: BTTrade, price: float, volume: float, ts, reason: str, final: bool = True) -> None:
        t.realized += self._pnl(t, price, volume)
        t.commission += self._commission(volume)
        t.volume = round(t.volume - volume, 8)
        if final or t.volume <= 1e-9:
            t.exit_time, t.exit_price, t.reason_close = ts, float(price), reason
            risk_cash = self.spec.value_per_price_unit(t.initial_volume) * t.risk_amount
            t.r_multiple = (t.realized - t.commission) / risk_cash if risk_cash > 0 else 0.0

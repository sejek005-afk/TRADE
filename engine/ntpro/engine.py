"""موتور اصلی: حلقه‌ی ۲۴/۷ روی VPS، کاملاً مستقل از اپ و اینترنت کاربر.

رشته‌ها:
  main   — اتصال/Watchdog، کندل‌های جدید، تصمیم و اجرا، مدیریت پوزیشن‌ها، همگام‌سازی با بروکر
  news   — تقویم اقتصادی و تیترها
  slow   — بین‌بازاری، بکاپ، فرسودگی، برچسب‌گذاری سیگنال‌ها، Shadow، آموزش هفتگی، گزارش هفتگی
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import MAGIC, __version__, exits, frame, journal
from . import config as config_mod
from .backup import run_backup
from .broker.base import Broker
from .db import DB
from .execution import Executor
from .intermarket import Intermarket, synthetic_dxy
from .learning import fatigue, guard, trainer
from .learning.bandit import StrategyBandit
from .learning.registry import ModelRegistry
from .news.calendar import Calendar
from .news.headlines import HeadlineFeed
from .news.rules import NewsGuard
from .notify import Notifier
from .pipeline import AccountState, Pipeline
from .regime import REGIME_FA
from .risk import RiskManager
from .security.vault import Vault
from .sessions import SessionClock, bucket_session, to_tehran

log = logging.getLogger("ntpro.engine")
UTC = timezone.utc
DEAL_REASON_FA = {4: "حد ضرر", 5: "حد سود", 6: "Stop Out بروکر", 0: "بستن دستی", 1: "بستن از موبایل", 2: "بستن از وب",
                  3: "بسته شد توسط موتور"}


class Engine:
    def __init__(self, data_dir: Path | None = None, broker: Broker | None = None):
        self.data_dir = Path(data_dir or config_mod.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db = DB(self.data_dir / "ntpro.sqlite")
        self.vault = Vault(self.data_dir / "master.key")
        self.cfg = config_mod.Config(self.data_dir / "config.json", vault=self.vault, db=self.db)
        self.notifier = Notifier(self.cfg, self.db)
        self.risk = RiskManager(self.cfg, self.db)
        self.bandit = StrategyBandit(self.db, self.cfg)
        self.registry = ModelRegistry(self.db, self.data_dir / "models")
        self.calendar = Calendar(self.cfg, self.db)
        self.feed = HeadlineFeed(self.cfg, self.db)
        self.news = NewsGuard(self.cfg, self.calendar, self.feed)
        self.intermarket = Intermarket()
        self.broker = broker or self._make_broker()
        self.executor = Executor(self.cfg, self.db, self.broker, self.notifier)
        self.clock = SessionClock(self.cfg.get("sessions"))
        self.pipeline = Pipeline(self.cfg, self.risk, weights_fn=self.bandit.weights, news_guard=self.news,
                                 intermarket=self.intermarket, suspended_fn=lambda: fatigue.suspended(self.db))
        self.reload_models()
        self.market: dict[str, dict] = {}
        self.last_bar: dict[str, pd.Timestamp] = {}
        self.specs: dict = {}
        self.account_info: dict = {}
        self.health: dict = {"mt5": False, "ping_ms": None, "last_tick": {}, "reconnects": 0, "started": time.time(),
                             "version": __version__, "magic": MAGIC}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._timers: dict[str, float] = {}
        self._fail_count = 0
        self.training = {"running": False, "last": self.db.kv_get("last_training")}
        self.backtest_state = {"running": False, "last": self.db.kv_get("last_backtest")}

    # ---------- ساخت بروکر ----------
    def _make_broker(self) -> Broker:
        from .broker.mt5 import MT5Broker
        from .broker.paper import PaperBroker
        mt5b = MT5Broker(self.cfg, lambda: self.vault.load_secret("mt5"))
        if self.cfg.get("mode") == "paper":
            return PaperBroker(self.cfg, mt5b, commission_per_lot=float(self.cfg.get("risk", "commission_per_lot_usd")))
        return mt5b

    def reload_models(self) -> None:
        _, champ = self.registry.champion()
        _, chall = self.registry.challenger()
        self.pipeline.models, self.pipeline.shadow_models = champ, chall

    # ---------- چرخه‌ی حیات ----------
    def start(self) -> None:
        log.info("NeuroTrader Pro %s starting (magic=%s, port=%s, mode=%s)", __version__, MAGIC,
                 self.cfg.get("api", "port"), self.cfg.get("mode"))
        for name, fn in (("main", self._main_loop), ("news", self._news_loop), ("slow", self._slow_loop)):
            t = threading.Thread(target=self._guarded, args=(name, fn), name=name, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=10)
        try:
            self.broker.shutdown()
        except Exception:
            pass

    def _guarded(self, name: str, fn) -> None:
        """اگر یک رشته کرش کند، لاگ می‌شود و دوباره شروع می‌شود (Watchdog داخلی)."""
        while not self._stop.is_set():
            try:
                fn()
            except Exception as e:
                log.error("thread %s crashed: %s\n%s", name, e, traceback.format_exc())
                self.notifier.send("warning", "thread_crash", f"خطا در بخش {name}: {e}. راه‌اندازی مجدد…")
                self._stop.wait(5)

    def _every(self, key: str, seconds: float) -> bool:
        now = time.time()
        if now - self._timers.get(key, 0) >= seconds:
            self._timers[key] = now
            return True
        return False

    # ---------- حلقه‌ی اصلی ----------
    def _main_loop(self) -> None:
        while not self._stop.is_set():
            self.step()
            self._stop.wait(2)

    def step(self) -> None:
        self._heartbeat()
        if not self._ensure_connected():
            return
        if self._every("account", 30):
            self._update_account()
        for sym in self.cfg.get("symbols"):
            try:
                self._process_symbol(sym)
            except Exception as e:
                log.error("symbol %s: %s\n%s", sym, e, traceback.format_exc())
        self.sync_positions()

    def _heartbeat(self) -> None:
        now = time.time()
        self.db.kv_set("heartbeat", now)
        try:
            (self.data_dir / "heartbeat").write_text(str(int(now)))
        except OSError:
            pass

    def _ensure_connected(self) -> bool:
        ok = False
        try:
            ok = self.broker.connected()
        except Exception:
            ok = False
        if ok:
            if not self.health["mt5"]:
                self.health["mt5"] = True
                if self._fail_count:
                    self.notifier.send("info", "mt5", "اتصال به متاتریدر برقرار شد؛ همگام‌سازی پوزیشن‌ها…")
                self._fail_count = 0
                self._on_connected()
            return True
        self.health["mt5"] = False
        backoff = min(300, 5 * (2 ** min(self._fail_count, 6)))
        if not self._every("reconnect", backoff):
            return False
        self._fail_count += 1
        self.health["reconnects"] += 1
        log.warning("connecting to broker (attempt %d)…", self._fail_count)
        if self.broker.connect():
            return self._ensure_connected()
        err = getattr(self.broker, "last_error", "")
        if self._fail_count in (3, 10, 30):
            self.notifier.send("critical", "mt5", f"اتصال به متاتریدر برقرار نشد ({self._fail_count} تلاش): {err}")
        return False

    def _on_connected(self) -> None:
        for sym in self.cfg.get("symbols"):
            try:
                self.specs[sym] = self.broker.spec(sym)
            except Exception as e:
                self.notifier.send("warning", "symbol", f"نماد {sym}: {e}")
        self._update_account()
        mode = self.cfg.get("mode")
        if mode == "demo" and self.broker.name == "mt5" and not self.broker.is_demo():
            self.db.kv_set("mode_violation", True)
            self.notifier.send("critical", "mode", "حالت «دمو» انتخاب شده ولی حساب متصل واقعی است. معامله انجام نمی‌شود.")
        else:
            self.db.kv_set("mode_violation", False)
        self.sync_positions(adopt=True)
        # ذخیره‌ی تاریخچه‌ی اخیر برای برچسب‌گذاری و آموزش
        for sym in self.cfg.get("symbols"):
            try:
                self.db.save_candles(sym, "M5", self.broker.candles(sym, "M5", 3000))
            except Exception:
                pass

    def _update_account(self) -> None:
        try:
            a = self.broker.account()
        except Exception:
            return
        if not a:
            return
        self.account_info = a
        now = int(time.time())
        self.db.execute("INSERT OR REPLACE INTO equity(time,balance,equity) VALUES(?,?,?)", (now, a["balance"], a["equity"]))
        dd, killed = self.risk.update_drawdown(float(a["equity"]))
        self.account_info["drawdown_pct"] = round(dd, 2)
        guard.check_brake(self.db, self.cfg, self.bandit, self.registry, dd)
        try:
            self.health["ping_ms"] = self.broker.ping_ms()
            if self.health["ping_ms"] and self.health["ping_ms"] > float(self.cfg.get("execution", "max_ping_ms")):
                if self._every("ping_alert", 1800):
                    self.notifier.send("warning", "ping", f"پینگ بالا تا سرور بروکر: {self.health['ping_ms']}ms")
        except Exception:
            pass
        self.db.execute("INSERT OR REPLACE INTO health(time,ping_ms,mt5,feed_age,news_age) VALUES(?,?,?,?,?)",
                        (now, self.health["ping_ms"], int(self.health["mt5"]), self._feed_age(),
                         time.time() - self.feed.last_ok if self.feed.last_ok else None))

    def _feed_age(self) -> float | None:
        ts = [v for v in self.health["last_tick"].values() if v]
        return round(time.time() - max(ts), 1) if ts else None

    # ---------- هر نماد ----------
    def _process_symbol(self, sym: str) -> None:
        tick = self.broker.tick(sym)
        st = self.market.setdefault(sym, {"symbol": sym})
        if tick:
            prev = st.get("tick_time")
            st.update(bid=tick["bid"], ask=tick["ask"], spread_points=tick["spread_points"], tick_time=tick["time"])
            if prev != tick["time"]:
                self.health["last_tick"][sym] = time.time()
        # لایه‌ی ۱: درک وضعیت (هر دقیقه)
        if self._every(f"layer1_{sym}", 60):
            self._layer1(sym)
        df = self.broker.candles(sym, "M5", 1500)
        if df is None or len(df) < 300:
            return
        last = df.index[-1]
        if self.last_bar.get(sym) == last:
            return
        self.last_bar[sym] = last
        self.db.save_candles(sym, "M5", df.iloc[-5:])
        self.on_new_bar(sym, df, tick)

    def _layer1(self, sym: str) -> None:
        st = self.market.setdefault(sym, {"symbol": sym})
        now = datetime.now(UTC)
        s = self.clock.state(sym, now)
        st.update(session=s.primary, session_fa=s.primary_fa, kill_zone=s.kill_zone, can_open=s.can_open,
                  block_reason=s.block_reason, minutes_to_news=round(self.news.minutes_to_next(sym), 1),
                  news_block=self.news.blocked(sym))
        b, note = self.intermarket.bias_for(sym)
        st.update(intermarket_bias=round(b, 2), intermarket_note=note)

    def on_new_bar(self, sym: str, df: pd.DataFrame, tick: dict | None) -> None:
        f = frame.compute(df)
        spec = self.specs.get(sym) or self.broker.spec(sym)
        self.specs[sym] = spec
        st = self.market.setdefault(sym, {"symbol": sym})
        from .regime import from_frame
        reg = from_frame(f)
        st.update(regime=reg.label, regime_fa=REGIME_FA[reg.label], adx=round(reg.adx, 1), atr=reg.atr,
                  atr_pct=round(reg.atr_pct, 2), htf_dir=reg.htf_dir, last_bar=int(df.index[-1].timestamp()),
                  price=float(df["close"].iloc[-1]))
        self.manage_positions(sym, df, f)
        if not self._can_trade():
            return
        spread = float(tick["spread_points"]) if tick else float(df["spread"].iloc[-1] or 0)
        now = (df.index[-1] + timedelta(minutes=5)).to_pydatetime()
        ev = self.pipeline.evaluate(sym, df, f, now, spread_points=spread, spec=spec, account=self._account_state(),
                                    ts=time.time())
        if ev.decision is not None:
            self._log_signal(ev, f)
            st.update(last_signal={"time": int(time.time()), "direction": ev.decision.direction,
                                   "score": ev.decision.score, "accepted": ev.decision.accepted,
                                   "reason": ev.decision.reject_reason, "strategies": ev.decision.strategies,
                                   "ml_prob": ev.ml_prob, "nn_prob": ev.nn_prob})
        if ev.trade:
            self._open_trade(sym, ev, spec, float(f["atr"].iloc[-1]), spread)

    def _can_trade(self) -> bool:
        if not self.cfg.get("bot_enabled"):
            return False
        if (self.db.kv_get("kill_switch") or {}).get("active"):
            return False
        if self.executor.halted():
            return False
        if self.db.kv_get("mode_violation"):
            return False
        mode = self.cfg.get("mode")
        if mode == "live" and not self.cfg.get("allow_live"):
            return False
        return True

    def _account_state(self) -> AccountState:
        a = self.account_info or {"balance": 0, "equity": 0}
        day = int(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        mode = self.cfg.get("mode")
        return AccountState(float(a.get("balance", 0)), float(a.get("equity", 0)),
                            self.db.query("SELECT * FROM trades WHERE status IN ('open','pending') AND mode=?", (mode,)),
                            self.db.query("SELECT * FROM trades WHERE status='closed' AND mode=? AND exit_time>=?", (mode, day)),
                            self.db.query("SELECT * FROM trades WHERE status='closed' AND mode=? ORDER BY exit_time DESC LIMIT 5", (mode,)),
                            self.db.kv_get("kill_switch"))

    def _log_signal(self, ev, f) -> None:
        d = ev.decision
        a = float(f["atr"].iloc[-1])
        price = float(ev.plan.entry) if ev.plan else None
        payload = {"score_parts": d.parts, "reasons": d.reasons_fa, "traps": ev.trap_reasons,
                   "sl_dist": abs(ev.plan.entry - ev.plan.sl) if ev.plan else min(max(abs((price or 0) - d.sl), .8 * a), 3 * a),
                   "tp_dist": abs(ev.plan.tp - ev.plan.entry) if ev.plan else None}
        if payload["tp_dist"] is None:
            payload["tp_dist"] = payload["sl_dist"] * float(self.cfg.get("risk", "min_rr_after_costs")) * 1.2
        self.db.execute("INSERT INTO signals(time,symbol,direction,combined_score,accepted,reject_reason,regime,session,"
                        "ml_prob,nn_prob,shadow_prob,strategies,payload) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (int(time.time()), ev.symbol, d.direction, d.score, int(ev.trade), d.reject_reason,
                         ev.regime.label if ev.regime else "", ev.session.primary, ev.ml_prob, ev.nn_prob,
                         ev.shadow_prob, json.dumps(d.strategies), json.dumps(payload, ensure_ascii=False)))
        level = logging.INFO if ev.trade else logging.DEBUG
        log.log(level, "signal %s %s score=%.0f accepted=%s %s", ev.symbol, "BUY" if d.direction > 0 else "SELL",
                d.score, ev.trade, d.reject_reason)

    def _open_trade(self, sym: str, ev, spec, atr: float, spread: float) -> None:
        p, d = ev.plan, ev.decision
        res, client_id, slip = self.executor.open(symbol=sym, direction=p.direction, volume=p.volume, entry=p.entry,
                                                  sl=p.sl, tp=p.tp, spec=spec, atr=atr, strategies=d.strategies,
                                                  regime=ev.regime.label)
        if not res.ok:
            self.notifier.send("warning", "order", f"سفارش {sym} ارسال نشد: {res.error}")
            return
        risk_pct = float(self.cfg.get("risk", "risk_per_trade_pct"))
        why = journal.explain_open(symbol=sym, direction=p.direction, score=d.score, strategies=d.strategies,
                                   regime=ev.regime.label, session=ev.session.primary, reasons=d.reasons_fa,
                                   ml_prob=ev.ml_prob, rr=p.risk.rr_net, risk_pct=risk_pct)
        risk_cash = spec.value_per_price_unit(p.volume) * abs(p.entry - p.sl)
        fill = res.price or p.entry
        tid = self.db.insert_trade({
            "client_id": client_id, "ticket": res.ticket, "mode": self.cfg.get("mode"), "symbol": sym,
            "direction": p.direction, "volume": p.volume, "initial_volume": p.volume, "entry_time": int(time.time()),
            "entry_price": fill, "requested_price": p.entry, "sl": p.sl, "initial_sl": p.sl, "tp": p.tp, "tp1": p.tp1,
            "slippage_points": slip, "spread_points": spread, "atr": atr, "regime": ev.regime.label,
            "session": bucket_session(ev.session.primary), "strategies": d.strategies, "score": d.score,
            "ml_prob": ev.ml_prob, "nn_prob": ev.nn_prob, "news_flag": int(self.news.minutes_to_next(sym) < 60),
            "reason_open": why, "status": "pending" if res.pending else "open",
            "features": {"tab": ev.tab, "risk_cash": risk_cash, "score_parts": d.parts, "shadow_prob": ev.shadow_prob,
                         "pending_expiry": int(time.time()) + int(self.cfg.get("execution", "limit_expiry_bars")) * 300
                         if res.pending else None}})
        side = "خرید" if p.direction > 0 else "فروش"
        kind = "سفارش لیمیت" if res.pending else "معامله"
        self.notifier.send("trade", "open", f"{kind} {side} {sym} حجم {p.volume} — امتیاز {d.score:.0f}\n{why}")
        log.info("trade #%s opened %s %s vol=%s @%s sl=%s tp=%s", tid, side, sym, p.volume, fill, p.sl, p.tp)

    # ---------- مدیریت پوزیشن ----------
    def manage_positions(self, sym: str, df: pd.DataFrame, f: pd.DataFrame) -> None:
        mode = self.cfg.get("mode")
        trades = self.db.query("SELECT * FROM trades WHERE status='open' AND symbol=? AND mode=?", (sym, mode))
        if not trades:
            return
        spec = self.specs[sym]
        price = float(df["close"].iloc[-1])
        atr = float(f["atr"].iloc[-1])
        upcoming = self.news.upcoming_soon(sym)
        for t in trades:
            bars = int(t["bars_held"] or 0) + 1
            r_now = (price - t["entry_price"]) * t["direction"] / max(abs(t["entry_price"] - t["initial_sl"]), 1e-12)
            self.db.update_trade(t["id"], bars_held=bars, mfe_r=max(float(t["mfe_r"] or 0), r_now))
            t["bars_held"] = bars
            acts = exits.manage(t, price, atr, bars, self.cfg.get("exits"), spec.volume_step, spec.volume_min)
            # قبل از خبر مهم
            if upcoming and not json.loads(t["features"] or "{}").get("pre_news_done"):
                n = self.cfg.get("news")
                if n["pre_news_action"] == "breakeven" and (price - t["entry_price"]) * t["direction"] > 0:
                    acts.append(exits.ExitAction("modify_sl", sl=t["entry_price"],
                                                 reason=f"قبل از خبر {upcoming.title}: حد ضرر به سربه‌سر"))
                elif n["pre_news_action"] == "partial":
                    part = round(int(t["volume"] * n["pre_news_partial_pct"] / 100 / spec.volume_step) * spec.volume_step, 8)
                    if part >= spec.volume_min and t["volume"] - part >= spec.volume_min:
                        acts.append(exits.ExitAction("partial", volume=part, reason=f"قبل از خبر {upcoming.title}"))
                feats = json.loads(t["features"] or "{}")
                feats["pre_news_done"] = True
                self.db.update_trade(t["id"], features=feats)
            # تیتر فوری شدیداً مخالف
            h = self.news.adverse_headline(sym, t["direction"], t["entry_time"])
            if h:
                action = self.cfg.get("news", "adverse_headline_action")
                if action == "close":
                    acts.append(exits.ExitAction("close", reason=f"خبر فوری مخالف: {h['headline'][:80]}"))
                elif action == "tighten":
                    tight = price - t["direction"] * 0.5 * atr
                    acts.append(exits.ExitAction("modify_sl", sl=tight, reason=f"خبر فوری مخالف — محدود کردن ضرر"))
            self._apply_actions(t, acts)

    def _apply_actions(self, t: dict, acts: list) -> None:
        for a in acts:
            try:
                if a.kind == "modify_sl":
                    if (a.sl - t["sl"]) * t["direction"] <= 0:
                        continue      # فقط نزدیک‌تر کردن
                    r = self.executor.modify_sl(t, a.sl)
                    if r.ok:
                        self.db.update_trade(t["id"], sl=a.sl)
                        t["sl"] = a.sl
                        log.info("trade #%s SL -> %s (%s)", t["id"], a.sl, a.reason)
                elif a.kind == "partial":
                    r = self.executor.close(t, a.volume, "partial")
                    if r.ok:
                        t["volume"] = round(t["volume"] - a.volume, 8)
                        self.db.update_trade(t["id"], volume=t["volume"], tp1_hit=1)
                        self.notifier.send("trade", "partial", f"{t['symbol']}: {a.reason}")
                elif a.kind == "close":
                    r = self.executor.close(t, None, a.reason)
                    if r.ok:
                        feats = json.loads(t["features"] or "{}")
                        feats["close_reason"] = a.reason
                        self.db.update_trade(t["id"], features=feats)
            except Exception as e:
                log.error("action %s on trade %s failed: %s", a.kind, t["id"], e)

    def close_trade_manual(self, trade_id: int, user: str) -> bool:
        t = self.db.one("SELECT * FROM trades WHERE id=? AND status='open'", (trade_id,))
        if not t:
            return False
        r = self.executor.close(t, None, "manual")
        if r.ok:
            feats = json.loads(t["features"] or "{}")
            feats["close_reason"] = f"بستن دستی از اپ توسط {user}"
            self.db.update_trade(t["id"], features=feats)
        return r.ok

    # ---------- همگام‌سازی با بروکر ----------
    def sync_positions(self, adopt: bool = False) -> None:
        try:
            live = {p.ticket: p for p in self.broker.positions()}
        except Exception:
            return
        mode = self.cfg.get("mode")
        # سفارش‌های لیمیت در انتظار
        for t in self.db.query("SELECT * FROM trades WHERE status='pending' AND mode=?", (mode,)):
            pos = self.broker.find_by_client_id(t["client_id"])
            feats = json.loads(t["features"] or "{}")
            if pos:
                self.db.update_trade(t["id"], status="open", ticket=pos.ticket, entry_price=pos.price_open,
                                     entry_time=pos.time, slippage_points=0)
                self.notifier.send("trade", "fill", f"سفارش لیمیت {t['symbol']} اجرا شد @ {pos.price_open}")
            elif time.time() > (feats.get("pending_expiry") or 0) + 30:
                self.broker.cancel(int(t["ticket"]))
                self.db.update_trade(t["id"], status="cancelled", reason_close="سفارش لیمیت در زمان مقرر اجرا نشد")
        open_trades = self.db.query("SELECT * FROM trades WHERE status='open' AND mode=?", (mode,))
        known = {t["ticket"] for t in open_trades}
        for t in open_trades:
            if t["ticket"] in live:
                p = live[t["ticket"]]
                if abs(p.volume - float(t["volume"])) > 1e-9:
                    self.db.update_trade(t["id"], volume=p.volume)
                continue
            self._record_close(t)
        if adopt:
            for tk, p in live.items():
                if tk not in known:
                    self.db.insert_trade({"client_id": f"adopt-{tk}", "ticket": tk, "mode": mode, "symbol": p.symbol,
                                          "direction": p.direction, "volume": p.volume, "initial_volume": p.volume,
                                          "entry_time": p.time, "entry_price": p.price_open, "sl": p.sl,
                                          "initial_sl": p.sl, "tp": p.tp, "tp1": None, "strategies": [],
                                          "regime": "", "session": "", "status": "open",
                                          "reason_open": "پوزیشن باز موجود هنگام راه‌اندازی موتور (همگام‌سازی)",
                                          "features": {"risk_cash": 0}})
                    log.info("adopted position %s", tk)

    def _record_close(self, t: dict) -> None:
        deals = [d for d in self.broker.closed_deals(int(t["entry_time"]) - 60) if d["position_id"] == t["ticket"]]
        if not deals:
            return        # هنوز در تاریخچه نیامده؛ دفعه‌ی بعد
        pnl = sum(d["profit"] + d["commission"] + d["swap"] + d.get("fee", 0) for d in deals)
        comm = sum(d["commission"] for d in deals)
        last = max(enumerate(deals), key=lambda x: (x[1]["time"], x[0]))[1]
        feats = json.loads(t["features"] or "{}")
        reason = feats.get("close_reason") or DEAL_REASON_FA.get(last["reason"], "بسته شد")
        if last["reason"] == 4 and (t["sl"] - t["initial_sl"]) * t["direction"] > 0:
            reason = "حد ضرر متحرک/سربه‌سر"
        risk_cash = float(feats.get("risk_cash") or 0)
        r = pnl / risk_cash if risk_cash > 0 else 0.0
        why = journal.explain_close(reason, r, pnl)
        self.db.update_trade(t["id"], status="closed", exit_time=last["time"], exit_price=last["price"],
                             pnl=round(pnl, 2), commission=comm, r_multiple=round(r, 3), reason_close=why,
                             tp1_hit=int(t["tp1_hit"] or 0))
        t.update(status="closed", pnl=pnl, r_multiple=r, exit_time=last["time"])
        self.notifier.send("trade", "close", f"{t['symbol']} بسته شد — {why}")
        log.info("trade #%s closed pnl=%.2f R=%.2f (%s)", t["id"], pnl, r, reason)
        if t["strategies"] and t["strategies"] != "[]" and t["mode"] != "backtest":
            changes = self.bandit.update(t)
            if changes:
                log.info("weights updated: %s", changes)
            self.db.update_trade(t["id"], learned=1)

    # ---------- اخبار ----------
    def _news_loop(self) -> None:
        while not self._stop.is_set():
            if self._every("calendar", 1800):
                self.calendar.refresh()
            if self._every("headlines", 60):
                for h in self.feed.fetch():
                    if h["impact"] == "high":
                        eff = ", ".join(f"{s}:{v:+.1f}" for s, v in h["effects"].items() if abs(v) > 0.2)
                        self.notifier.send("info", "news", f"خبر مهم: {h['headline']} ({eff})")
            self._stop.wait(10)

    # ---------- کارهای کند ----------
    def _slow_loop(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(UTC)
            if self.health["mt5"] and self._every("intermarket", 300):
                self._refresh_intermarket()
            if self._every("staleness", 120):
                self._check_staleness(now)
            if self._every("label_signals", 3600):
                horizon = int(self.cfg.get("exits", "time_stop_bars")) * 2
                trainer.label_signal_outcomes(self.db, lambda s, since: self.db.load_candles(s, "M5", since), horizon)
            if now.hour == int(self.cfg.get("backup", "daily_hour_utc")) and self._daily("backup"):
                p = run_backup(self.db, self.data_dir, int(self.cfg.get("backup", "keep_days")))
                log.info("backup written %s", p)
            if self._daily("fatigue"):
                found = fatigue.check(self.db, self.cfg)
                res = trainer.evaluate_shadow(self.cfg, self.db, self.registry)
                if res is not None:
                    self.reload_models()
                    log.info("shadow evaluation: %s", res)
            if now.weekday() == 5 and now.hour >= 4 and self._weekly("train") and self.cfg.get("learning", "enabled"):
                threading.Thread(target=self.run_training, daemon=True, name="training").start()
            if now.weekday() == 5 and now.hour >= 8 and self._weekly("report"):
                rep = journal.weekly_report(self.db)
                self.db.kv_set("weekly_report", rep)
                self.notifier.send("info", "weekly", rep["text"])
            self._stop.wait(20)

    def _daily(self, key: str) -> bool:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if self.db.kv_get(f"daily_{key}") == today:
            return False
        self.db.kv_set(f"daily_{key}", today)
        return True

    def _weekly(self, key: str) -> bool:
        wk = datetime.now(UTC).strftime("%G-%V")
        if self.db.kv_get(f"weekly_{key}") == wk:
            return False
        self.db.kv_set(f"weekly_{key}", wk)
        return True

    def _check_staleness(self, now: datetime) -> None:
        market_open = not (now.weekday() == 5 or (now.weekday() == 6 and now.hour < 22) or (now.weekday() == 4 and now.hour >= 21))
        age = self._feed_age()
        if market_open and self.health["mt5"] and age is not None and age > 180 and self._every("feed_alert", 1800):
            self.notifier.send("warning", "feed", f"قیمت {age:.0f} ثانیه است به‌روز نشده")
        if self.feed.last_ok and time.time() - self.feed.last_ok > 1800 and self._every("news_alert", 3600):
            self.notifier.send("warning", "news_feed", "فید اخبار بیش از ۳۰ دقیقه است قطع است")
        if self.calendar.last_ok and time.time() - self.calendar.last_ok > 6 * 3600 and self._every("cal_alert", 6 * 3600):
            self.notifier.send("warning", "calendar", "تقویم اقتصادی به‌روز نمی‌شود (همه‌ی منابع قطع‌اند)")

    def _refresh_intermarket(self) -> None:
        im = self.cfg.get("intermarket")
        for key in ("dxy", "us10y", "vix", "nasdaq"):
            sym = im.get(key)
            if not sym:
                continue
            try:
                df = self.broker.candles(sym, "M5", 300)
                if df is not None and len(df):
                    self.intermarket.update(key, df["close"])
            except Exception:
                pass
        if "dxy" not in self.intermarket.series and im.get("synthetic_dxy"):
            closes = {}
            for s in ("EURUSD", "USDJPY", "GBPUSD", "USDCAD", "USDSEK", "USDCHF"):
                try:
                    df = self.broker.candles(s, "M5", 300)
                    if df is not None and len(df):
                        closes[s] = df["close"]
                except Exception:
                    pass
            dxy = synthetic_dxy(pd.DataFrame(closes).dropna().to_dict("series")) if closes else None
            self.intermarket.update("dxy", dxy)

    # ---------- آموزش و بک‌تست ----------
    def _history(self, sym: str, days: int) -> pd.DataFrame:
        end = datetime.now(UTC)
        df = self.broker.candles_range(sym, "M5", end - timedelta(days=days), end)
        if df is None or len(df) < 500:
            df = self.db.load_candles(sym, "M5", int((end - timedelta(days=days)).timestamp()))
        return df

    def run_training(self) -> dict:
        if self.training["running"]:
            return {"ok": False, "reason": "آموزش در حال اجراست"}
        self.training["running"] = True
        try:
            _lower_priority()
            hist = {s: self._history(s, 180) for s in self.cfg.get("symbols")}
            specs = {s: self.specs.get(s) or self.broker.spec(s) for s in hist}
            snap_models = {"champion": self.registry.champion()[0]}
            dd = float(self.account_info.get("drawdown_pct", 0) or 0)
            self.bandit.snapshot("قبل از آموزش هفتگی", snap_models,
                                 healthy=dd < float(self.cfg.get("learning", "drawdown_brake_pct")))
            res = trainer.train_weekly(self.cfg, self.db, self.registry, hist, specs)
            self.reload_models()
            self.training["last"] = {"time": int(time.time()), **{k: v for k, v in res.items() if k != "metrics"},
                                     "metrics": res.get("metrics")}
            self.db.kv_set("last_training", self.training["last"])
            return res
        except Exception as e:
            log.error("training failed: %s\n%s", e, traceback.format_exc())
            return {"ok": False, "reason": str(e)}
        finally:
            self.training["running"] = False

    def run_backtest(self, days: int = 60, symbols: list[str] | None = None, per_strategy: bool = True,
                     use_ticks: bool = False) -> dict:
        from .backtest import report
        from .backtest.engine import Backtester
        from .strategies import ALL
        self.backtest_state["running"] = True
        out = {"time": int(time.time()), "days": days, "results": {}}
        try:
            _lower_priority()
            for sym in symbols or self.cfg.get("symbols"):
                df = self._history(sym, days)
                spec = self.specs.get(sym) or self.broker.spec(sym)
                ticks = None
                if use_ticks:
                    ticks = self.broker.ticks_range(sym, df.index[0].to_pydatetime(), df.index[-1].to_pydatetime())
                bt = Backtester(self.cfg, sym, df, spec, ticks=ticks, models=self.pipeline.models)
                combined = report.full_report(bt.run(label="ترکیبی"))
                per = {}
                if per_strategy:
                    for name in ALL:
                        rep = report.full_report(bt.run(only={name}, label=name), mc_runs=300)
                        per[name] = {k: rep[k] for k in ("trades", "win_rate", "profit_factor", "expectancy_r",
                                                         "net_profit", "max_drawdown_pct", "sharpe")}
                out["results"][sym] = {"combined": combined, "per_strategy": per, "text": report.to_text_fa(combined)}
            self.backtest_state["last"] = out
            self.db.kv_set("last_backtest", json.loads(json.dumps(out, default=str)))
            return out
        finally:
            self.backtest_state["running"] = False

    # ---------- وضعیت برای اپ ----------
    def snapshot(self) -> dict:
        mode = self.cfg.get("mode")
        day = int(datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        closed = self.db.query("SELECT pnl, r_multiple FROM trades WHERE status='closed' AND mode=?", (mode,))
        today = self.db.query("SELECT pnl FROM trades WHERE status='closed' AND mode=? AND exit_time>=?", (mode, day))
        wins = [c["pnl"] for c in closed if (c["pnl"] or 0) > 0]
        losses = [-c["pnl"] for c in closed if (c["pnl"] or 0) <= 0]
        open_t = self.db.query("SELECT * FROM trades WHERE status IN ('open','pending') AND mode=? ORDER BY entry_time DESC", (mode,))
        live = {}
        try:
            live = {p.ticket: p for p in self.broker.positions()} if self.health["mt5"] else {}
        except Exception:
            pass
        for t in open_t:
            p = live.get(t["ticket"])
            t["profit"] = round(p.profit, 2) if p else None
            t["strategies"] = json.loads(t["strategies"] or "[]")
            t.pop("features", None)
            t["entry_time_tehran"] = to_tehran(t["entry_time"])
        lp = self.db.kv_get("learning_paused") or {}
        return {
            "time": int(time.time()), "version": __version__, "mode": mode, "bot_enabled": bool(self.cfg.get("bot_enabled")),
            "kill_switch": self.db.kv_get("kill_switch") or {"active": False},
            "execution_halt": self.db.kv_get("execution_halt") or {"active": False},
            "account": self.account_info,
            "stats": {"day_pnl": round(sum(t["pnl"] or 0 for t in today), 2), "trades": len(closed),
                      "win_rate": round(100 * len(wins) / len(closed), 1) if closed else 0.0,
                      "profit_factor": round(sum(wins) / sum(losses), 2) if losses and sum(losses) > 0 else None,
                      "expectancy_r": round(sum(c["r_multiple"] or 0 for c in closed) / len(closed), 3) if closed else 0.0,
                      "drawdown_pct": self.account_info.get("drawdown_pct", 0)},
            "positions": open_t, "market": self.market,
            "health": {**self.health, "feed_age": self._feed_age(),
                       "news_age": round(time.time() - self.feed.last_ok) if self.feed.last_ok else None,
                       "calendar_source": self.calendar.source, "uptime": round(time.time() - self.health["started"])},
            "learning": {"paused": bool(lp.get("paused")), "reason": lp.get("reason", ""),
                         "training": self.training["running"]},
        }


def _lower_priority() -> None:
    """فقط همین رشته (آموزش/بک‌تست) اولویت پایین می‌گیرد تا موتور معاملات هیچ‌وقت کند نشود."""
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetThreadPriority(k.GetCurrentThread(), -2)      # THREAD_PRIORITY_LOWEST
        else:
            os.nice(10)                                         # در لینوکس روی همین رشته اثر دارد
    except Exception:
        pass

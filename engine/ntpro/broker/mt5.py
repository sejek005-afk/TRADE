"""اتصال به متاتریدر ۵ با پکیج MetaTrader5.

نکات هم‌زیستی با برنامه‌ی دیگر روی سرور:
- حالت پیش‌فرض (shared_terminal): به همان ترمینالی وصل می‌شود که باز است، بدون ورود مجدد و بدون تغییر حساب.
  اگر حساب ترمینال با login تنظیم‌شده فرق داشته باشد، فقط قطع می‌شود (ترمینال و برنامه‌ی دیگر دست نمی‌خورند).
- حالت جدا: ترمینال مستقل (mt5.path) با ورود به حساب خودش.
- فقط پوزیشن‌ها/سفارش‌هایی را تغییر می‌دهد که Magic = ntpro.MAGIC دارند؛ پوزیشن‌های دیگر فقط خوانده می‌شوند.
- زمان سرور بروکر به UTC تبدیل می‌شود (اختلاف خودکار محاسبه می‌شود).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import pandas as pd

from .. import MAGIC
from ..risk import SymbolSpec
from .base import Broker, OrderRequest, OrderResult, Position

log = logging.getLogger("ntpro.mt5")

TF = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 16385, "H4": 16388, "D1": 16408}
RETRYABLE = {10004, 10020, 10021, 10012, 10031, 10024}   # Requote, Price changed, Off quotes, Timeout, No connection, Too many requests


def comment_for(client_id: str) -> str:
    return f"NTP{client_id[:12]}"


class MT5Broker(Broker):
    name = "mt5"

    def __init__(self, cfg, password_provider):
        self.cfg = cfg
        self.password_provider = password_provider     # تابعی که رمز رمزگشایی‌شده را برمی‌گرداند
        self.mt5 = None
        self._lock = threading.RLock()
        self.offset_sec = 0
        self._specs: dict[str, SymbolSpec] = {}
        self.last_error = ""

    # ---------- اتصال ----------
    def connect(self) -> bool:
        with self._lock:
            try:
                import MetaTrader5 as mt5
            except ImportError:
                self.last_error = "پکیج MetaTrader5 نصب نیست"
                return False
            self.mt5 = mt5
            c = self.cfg.get("mt5")
            shared = bool(c.get("shared_terminal", True))
            kwargs = {"timeout": 60000}
            if c.get("path"):
                kwargs["path"] = c["path"]
            if not shared:
                kwargs["portable"] = bool(c.get("portable", False))
                pwd = self.password_provider()
                if c.get("login") and pwd:
                    kwargs.update(login=int(c["login"]), password=pwd, server=c.get("server", ""))
            # در حالت مشترک هیچ‌وقت login/password فرستاده نمی‌شود تا حساب ترمینال عوض نشود
            ok = mt5.initialize(**kwargs)
            if not ok:
                self.last_error = f"initialize failed: {mt5.last_error()}"
                log.error(self.last_error)
                return False
            acc = mt5.account_info()
            if acc is None:
                self.last_error = "اطلاعات حساب در دسترس نیست (ورود ناموفق؟)"
                return False
            if c.get("login") and int(acc.login) != int(c["login"]):
                self.last_error = (f"ترمینال به حساب {acc.login} وصل است، نه {c['login']}. "
                                   "موتور معامله نمی‌کند و به ترمینال دست نمی‌زند.")
                log.error(self.last_error)
                mt5.shutdown()      # فقط اتصال همین فرایند قطع می‌شود؛ ترمینال باز می‌ماند
                return False
            for s in self.cfg.get("symbols"):
                mt5.symbol_select(self.broker_symbol(s), True)
            self._calc_offset()
            self.last_error = ""
            log.info("MT5 connected: %s @ %s (offset %+d h)", acc.login, acc.server, self.offset_sec // 3600)
            return True

    def connected(self) -> bool:
        if self.mt5 is None:
            return False
        try:
            ti = self.mt5.terminal_info()
            return bool(ti and ti.connected and self.mt5.account_info() is not None)
        except Exception:
            return False

    def shutdown(self) -> None:
        if self.mt5:
            self.mt5.shutdown()

    def broker_symbol(self, symbol: str) -> str:
        return self.cfg.get("symbol_map", default={}).get(symbol, symbol)

    def _calc_offset(self) -> None:
        """اختلاف ساعت سرور بروکر با UTC (مضرب ۱ ساعت)."""
        for s in self.cfg.get("symbols"):
            t = self.mt5.symbol_info_tick(self.broker_symbol(s))
            if t and t.time:
                diff = t.time - time.time()
                if abs(diff) < 14 * 3600:
                    self.offset_sec = int(round(diff / 3600.0)) * 3600
                    return

    # ---------- اطلاعات ----------
    def account(self) -> dict:
        a = self.mt5.account_info()
        if a is None:
            return {}
        return {"login": a.login, "server": a.server, "currency": a.currency, "balance": a.balance, "equity": a.equity,
                "margin": a.margin, "free_margin": a.margin_free, "leverage": a.leverage,
                "trade_allowed": bool(a.trade_allowed), "demo": a.trade_mode == 0}

    def is_demo(self) -> bool:
        a = self.mt5.account_info()
        return bool(a and a.trade_mode == 0)

    def spec(self, symbol: str) -> SymbolSpec:
        bs = self.broker_symbol(symbol)
        i = self.mt5.symbol_info(bs)
        if i is None:
            raise RuntimeError(f"نماد {bs} نزد بروکر پیدا نشد")
        sp = SymbolSpec(symbol, point=i.point, digits=i.digits, tick_size=i.trade_tick_size or i.point,
                        tick_value=i.trade_tick_value, contract_size=i.trade_contract_size, volume_min=i.volume_min,
                        volume_max=i.volume_max, volume_step=i.volume_step, stops_level=i.trade_stops_level)
        self._specs[symbol] = sp
        return sp

    def _rates_df(self, rates) -> pd.DataFrame:
        if rates is None or len(rates) == 0:
            return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume", "spread"])
        df = pd.DataFrame(rates)
        df.index = pd.to_datetime(df["time"] - self.offset_sec, unit="s", utc=True)
        return df[["open", "high", "low", "close", "tick_volume", "spread"]].astype(float)

    def candles(self, symbol: str, tf: str, count: int) -> pd.DataFrame:
        with self._lock:
            # از کندل ۱ (بسته‌شده) شروع می‌کنیم، نه کندل در حال تشکیل
            return self._rates_df(self.mt5.copy_rates_from_pos(self.broker_symbol(symbol), TF[tf], 1, count))

    def candles_range(self, symbol: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
        with self._lock:
            s = datetime.fromtimestamp(start.timestamp() + self.offset_sec, timezone.utc)
            e = datetime.fromtimestamp(end.timestamp() + self.offset_sec, timezone.utc)
            return self._rates_df(self.mt5.copy_rates_range(self.broker_symbol(symbol), TF[tf], s, e))

    def ticks_range(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame | None:
        with self._lock:
            s = datetime.fromtimestamp(start.timestamp() + self.offset_sec, timezone.utc)
            e = datetime.fromtimestamp(end.timestamp() + self.offset_sec, timezone.utc)
            t = self.mt5.copy_ticks_range(self.broker_symbol(symbol), s, e, self.mt5.COPY_TICKS_ALL)
            if t is None or len(t) == 0:
                return None
            df = pd.DataFrame(t)
            df.index = pd.to_datetime(df["time_msc"] - self.offset_sec * 1000, unit="ms", utc=True)
            return df[["bid", "ask"]].astype(float)

    def tick(self, symbol: str) -> dict | None:
        t = self.mt5.symbol_info_tick(self.broker_symbol(symbol))
        if t is None or not t.bid:
            return None
        sp = self._specs.get(symbol) or self.spec(symbol)
        return {"bid": t.bid, "ask": t.ask, "time": t.time - self.offset_sec,
                "spread_points": round((t.ask - t.bid) / sp.point, 1)}

    def positions(self) -> list[Position]:
        out = []
        rev = {v: k for k, v in self.cfg.get("symbol_map", default={}).items()}
        for p in self.mt5.positions_get() or []:
            if p.magic != MAGIC:
                continue                     # پوزیشن‌های برنامه‌ی دیگر/دستی دست نمی‌خورند
            out.append(Position(p.ticket, rev.get(p.symbol, p.symbol), 1 if p.type == 0 else -1, p.volume,
                                p.price_open, p.sl, p.tp, p.profit, int(p.time - self.offset_sec), p.comment))
        return out

    def foreign_positions(self) -> list[dict]:
        rev = {v: k for k, v in self.cfg.get("symbol_map", default={}).items()}
        return [{"symbol": rev.get(p.symbol, p.symbol), "direction": 1 if p.type == 0 else -1, "volume": p.volume}
                for p in (self.mt5.positions_get() or []) if p.magic != MAGIC]

    def pending_orders(self) -> list[dict]:
        return [{"ticket": o.ticket, "symbol": o.symbol, "comment": o.comment, "price": o.price_open}
                for o in (self.mt5.orders_get() or []) if o.magic == MAGIC]

    def find_by_client_id(self, client_id: str) -> Position | None:
        c = comment_for(client_id)
        return next((p for p in self.positions() if p.comment.startswith(c)), None)

    # ---------- سفارش ----------
    def _filling(self, bs: str) -> int:
        fm = self.mt5.symbol_info(bs).filling_mode
        if fm & 1:
            return self.mt5.ORDER_FILLING_FOK
        if fm & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def place(self, req: OrderRequest) -> OrderResult:
        if not req.sl:
            return OrderResult(False, error="سفارش بدون حد ضرر ارسال نمی‌شود")
        m = self.mt5
        bs = self.broker_symbol(req.symbol)
        sp = self._specs.get(req.symbol) or self.spec(req.symbol)
        r = lambda x: round(x, sp.digits)  # noqa: E731
        with self._lock:
            tick = m.symbol_info_tick(bs)
            if req.kind == "limit":
                request = {"action": m.TRADE_ACTION_PENDING, "symbol": bs, "volume": req.volume,
                           "type": m.ORDER_TYPE_BUY_LIMIT if req.direction > 0 else m.ORDER_TYPE_SELL_LIMIT,
                           "price": r(req.price), "sl": r(req.sl), "tp": r(req.tp), "magic": MAGIC,
                           "comment": comment_for(req.client_id), "type_filling": m.ORDER_FILLING_RETURN,
                           "type_time": m.ORDER_TIME_SPECIFIED if req.expiry_seconds else m.ORDER_TIME_GTC}
                if req.expiry_seconds:
                    request["expiration"] = int(time.time() + self.offset_sec + req.expiry_seconds)
            else:
                price = tick.ask if req.direction > 0 else tick.bid
                request = {"action": m.TRADE_ACTION_DEAL, "symbol": bs, "volume": req.volume,
                           "type": m.ORDER_TYPE_BUY if req.direction > 0 else m.ORDER_TYPE_SELL,
                           "price": price, "sl": r(req.sl), "tp": r(req.tp),
                           "deviation": int(self.cfg.get("mt5", "deviation_points")), "magic": MAGIC,
                           "comment": comment_for(req.client_id), "type_filling": self._filling(bs),
                           "type_time": m.ORDER_TIME_GTC}
            res = m.order_send(request)
        if res is None:
            return OrderResult(False, error=f"order_send None: {m.last_error()}", retryable=True)
        if res.retcode in (m.TRADE_RETCODE_DONE, m.TRADE_RETCODE_PLACED):
            return OrderResult(True, res.order if req.kind == "limit" else (res.deal and self._pos_ticket(res) or res.order),
                               res.price or req.price, res.volume, pending=req.kind == "limit", raw=res._asdict())
        return OrderResult(False, error=f"{res.retcode} {res.comment}", retryable=res.retcode in RETRYABLE,
                           raw=res._asdict())

    def _pos_ticket(self, res) -> int:
        d = self.mt5.history_deals_get(ticket=res.deal)
        return int(d[0].position_id) if d else int(res.order)

    def modify(self, ticket: int, sl: float, tp: float) -> OrderResult:
        m = self.mt5
        with self._lock:
            p = m.positions_get(ticket=ticket)
            if not p or p[0].magic != MAGIC:
                return OrderResult(False, error="پوزیشن پیدا نشد یا متعلق به این موتور نیست")
            sp = self._specs.get(self._norm(p[0].symbol)) or self.spec(self._norm(p[0].symbol))
            res = m.order_send({"action": m.TRADE_ACTION_SLTP, "position": ticket, "symbol": p[0].symbol,
                                "sl": round(sl, sp.digits), "tp": round(tp, sp.digits), "magic": MAGIC})
        if res and res.retcode == m.TRADE_RETCODE_DONE:
            return OrderResult(True, ticket)
        return OrderResult(False, error=f"{getattr(res, 'retcode', None)} {getattr(res, 'comment', m.last_error())}",
                           retryable=bool(res and res.retcode in RETRYABLE))

    def _norm(self, broker_sym: str) -> str:
        rev = {v: k for k, v in self.cfg.get("symbol_map", default={}).items()}
        return rev.get(broker_sym, broker_sym)

    def close(self, ticket: int, volume: float | None = None, comment: str = "") -> OrderResult:
        m = self.mt5
        with self._lock:
            p = m.positions_get(ticket=ticket)
            if not p or p[0].magic != MAGIC:
                return OrderResult(False, error="پوزیشن پیدا نشد یا متعلق به این موتور نیست")
            p = p[0]
            tick = m.symbol_info_tick(p.symbol)
            buy = p.type == 0
            res = m.order_send({"action": m.TRADE_ACTION_DEAL, "symbol": p.symbol, "position": ticket,
                                "volume": volume or p.volume, "type": m.ORDER_TYPE_SELL if buy else m.ORDER_TYPE_BUY,
                                "price": tick.bid if buy else tick.ask,
                                "deviation": int(self.cfg.get("mt5", "deviation_points")), "magic": MAGIC,
                                "comment": (comment or "NTP close")[:30], "type_filling": self._filling(p.symbol)})
        if res and res.retcode == m.TRADE_RETCODE_DONE:
            return OrderResult(True, ticket, res.price, res.volume)
        return OrderResult(False, error=f"{getattr(res, 'retcode', None)} {getattr(res, 'comment', m.last_error())}",
                           retryable=bool(res and res.retcode in RETRYABLE))

    def cancel(self, ticket: int) -> OrderResult:
        m = self.mt5
        res = m.order_send({"action": m.TRADE_ACTION_REMOVE, "order": ticket})
        return OrderResult(bool(res and res.retcode == m.TRADE_RETCODE_DONE), ticket)

    def closed_deals(self, since: int) -> list[dict]:
        """معاملات خروج (DEAL_ENTRY_OUT) این موتور از زمان since (UTC)."""
        m = self.mt5
        s = datetime.fromtimestamp(since + self.offset_sec - 60, timezone.utc)
        e = datetime.fromtimestamp(time.time() + self.offset_sec + 3600, timezone.utc)
        out = []
        for d in m.history_deals_get(s, e) or []:
            if d.magic != MAGIC or d.entry not in (m.DEAL_ENTRY_OUT, m.DEAL_ENTRY_OUT_BY):
                continue
            out.append({"position_id": d.position_id, "price": d.price, "volume": d.volume, "profit": d.profit,
                        "commission": d.commission, "swap": d.swap, "fee": getattr(d, "fee", 0.0),
                        "time": int(d.time - self.offset_sec), "reason": d.reason, "comment": d.comment})
        return out

    def ping_ms(self) -> float | None:
        ti = self.mt5.terminal_info() if self.mt5 else None
        return round(ti.ping_last / 1000.0, 1) if ti and ti.ping_last else None

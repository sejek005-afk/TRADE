"""کیفیت اجرای سفارش: Market/Limit، تلاش مجدد کنترل‌شده بدون سفارش تکراری، ثبت اسلیپیج، پایش پینگ."""
from __future__ import annotations

import logging
import time
import uuid

from .broker.base import Broker, OrderRequest, OrderResult
from .regime import VOLATILE
from .risk import RiskManager, SymbolSpec

log = logging.getLogger("ntpro.exec")

LIMIT_FRIENDLY = {"pullback", "vwap", "bb_rsi_reversal", "break_retest", "candle_patterns", "smc"}


class Executor:
    def __init__(self, cfg, db, broker: Broker, notifier=None):
        self.cfg, self.db, self.broker, self.notifier = cfg, db, broker, notifier

    @property
    def X(self) -> dict:
        return self.cfg.get("execution")

    def halted(self) -> str:
        h = self.db.kv_get("execution_halt") or {}
        return h.get("reason", "") if h.get("active") else ""

    def choose_kind(self, strategies: list[str], regime: str) -> str:
        if not self.X.get("prefer_limit", True) or regime == VOLATILE:
            return "market"
        return "limit" if set(strategies) and set(strategies) <= LIMIT_FRIENDLY else "market"

    def open(self, *, symbol: str, direction: int, volume: float, entry: float, sl: float, tp: float,
             spec: SymbolSpec, atr: float, strategies: list[str], regime: str) -> tuple[OrderResult, str, float]:
        """خروجی: (نتیجه، client_id، اسلیپیج بر حسب پوینت — مثبت یعنی بدتر از قیمت درخواستی)."""
        RiskManager.require_sl(direction, entry, sl)
        client_id = uuid.uuid4().hex
        kind = self.choose_kind(strategies, regime)
        price = entry
        expiry = 0
        if kind == "limit":
            price = entry - direction * float(self.X["limit_offset_atr"]) * atr
            expiry = int(self.X["limit_expiry_bars"]) * 300
        req = OrderRequest(client_id, symbol, direction, volume, price, sl, tp, kind, expiry)
        res = OrderResult(False, error="not sent")
        for attempt in range(int(self.X["max_retries"]) + 1):
            # قبل از تلاش مجدد: آیا سفارش قبلی در واقع اجرا شده؟ (جلوگیری از سفارش تکراری)
            if attempt > 0:
                existing = self.broker.find_by_client_id(client_id)
                if existing:
                    res = OrderResult(True, existing.ticket, existing.price_open, existing.volume)
                    break
                time.sleep(0.5 * attempt)
                t = self.broker.tick(symbol)
                if t and kind == "market":
                    req.price = t["ask"] if direction > 0 else t["bid"]
                    # اگر قیمت آن‌قدر حرکت کرده که حد ضرر رد شده، منصرف شو
                    if (req.price - sl) * direction <= 0 or (tp - req.price) * direction <= 0:
                        return OrderResult(False, error="قیمت از محدوده‌ی معامله خارج شد"), client_id, 0.0
            res = self.broker.place(req)
            if res.ok or not res.retryable:
                break
            log.warning("order retry %d for %s: %s", attempt + 1, symbol, res.error)
        slip = 0.0
        if res.ok and not res.pending and res.price:
            slip = (res.price - entry) * direction / spec.point
            self._track_slippage(symbol, slip)
        return res, client_id, round(slip, 1)

    def _track_slippage(self, symbol: str, slip_points: float) -> None:
        lim = self.X["max_slippage_points"]
        limit = float(lim.get(symbol, lim["default"]))
        if slip_points <= limit:
            self.db.kv_set(f"slip_breach_{symbol}", 0)
            return
        n = int(self.db.kv_get(f"slip_breach_{symbol}", 0) or 0) + 1
        self.db.kv_set(f"slip_breach_{symbol}", n)
        msg = f"اسلیپیج بالا روی {symbol}: {slip_points:.0f} پوینت (حد {limit:.0f})"
        if self.notifier:
            self.notifier.send("warning", "slippage", msg)
        if n >= int(self.X["slippage_breach_limit"]):
            self.db.kv_set("execution_halt", {"active": True, "reason": f"اسلیپیج مکرر روی {symbol}", "time": int(time.time())})
            if self.notifier:
                self.notifier.send("critical", "execution_halt", f"معامله‌ی جدید متوقف شد: {n} بار اسلیپیج بیش از حد روی {symbol}")

    def modify_sl(self, trade: dict, new_sl: float) -> OrderResult:
        RiskManager.validate_sl_change(int(trade["direction"]), float(trade["sl"]), new_sl)
        res = self.broker.modify(int(trade["ticket"]), new_sl, float(trade["tp"] or 0))
        for i in range(int(self.X["max_retries"])):
            if res.ok or not res.retryable:
                break
            time.sleep(0.5 * (i + 1))
            res = self.broker.modify(int(trade["ticket"]), new_sl, float(trade["tp"] or 0))
        return res

    def close(self, trade: dict, volume: float | None = None, reason: str = "") -> OrderResult:
        res = self.broker.close(int(trade["ticket"]), volume, reason[:30])
        for i in range(int(self.X["max_retries"])):
            if res.ok or not res.retryable:
                break
            time.sleep(0.5 * (i + 1))
            res = self.broker.close(int(trade["ticket"]), volume, reason[:30])
        return res

"""بروکر شبیه‌ساز (Paper): قیمت از منبع داده (MT5 یا داده‌ی تست)، اجرای سفارش‌ها داخلی.

برای تست‌ها و برای وقتی که بخواهید بدون ارسال هیچ سفارشی به بروکر، عملکرد را زنده ببینید.
"""
from __future__ import annotations

import itertools
import threading
import time

import pandas as pd

from ..risk import SymbolSpec, default_spec
from .base import Broker, OrderRequest, OrderResult, Position


class PaperBroker(Broker):
    name = "paper"

    def __init__(self, cfg, data_source: Broker | None = None, balance: float = 10000.0, commission_per_lot: float = 7.0):
        self.cfg, self.data = cfg, data_source
        self.balance = balance
        self.commission = commission_per_lot
        self._pos: dict[int, Position] = {}
        self._client: dict[str, int] = {}
        self._deals: list[dict] = []
        self._ids = itertools.count(1000)
        self._lock = threading.RLock()
        self.fake_ticks: dict[str, dict] = {}     # برای تست
        self.fake_candles: dict[str, pd.DataFrame] = {}

    def connect(self) -> bool:
        return self.data.connect() if self.data else True

    def connected(self) -> bool:
        return self.data.connected() if self.data else True

    def shutdown(self) -> None:
        if self.data:
            self.data.shutdown()

    def is_demo(self) -> bool:
        return True

    def spec(self, symbol: str) -> SymbolSpec:
        return self.data.spec(symbol) if self.data else default_spec(symbol)

    def candles(self, symbol, tf, count):
        if symbol in self.fake_candles:
            return self.fake_candles[symbol].iloc[-count:]
        return self.data.candles(symbol, tf, count)

    def candles_range(self, symbol, tf, start, end):
        return self.data.candles_range(symbol, tf, start, end) if self.data else self.fake_candles.get(symbol)

    def ticks_range(self, symbol, start, end):
        return self.data.ticks_range(symbol, start, end) if self.data else None

    def tick(self, symbol):
        t = self.fake_ticks.get(symbol) or (self.data.tick(symbol) if self.data else None)
        if t:
            self._check_stops(symbol, t)
        return t

    def _equity(self) -> float:
        eq = self.balance
        for p in self._pos.values():
            t = self.fake_ticks.get(p.symbol) or (self.data.tick(p.symbol) if self.data else None)
            if t:
                px = t["bid"] if p.direction > 0 else t["ask"]
                eq += (px - p.price_open) * p.direction * self.spec(p.symbol).value_per_price_unit(p.volume)
        return eq

    def account(self) -> dict:
        return {"login": 0, "server": "paper", "currency": "USD", "balance": round(self.balance, 2),
                "equity": round(self._equity(), 2), "margin": 0, "free_margin": self.balance, "leverage": 100,
                "trade_allowed": True, "demo": True}

    def positions(self) -> list[Position]:
        with self._lock:
            return list(self._pos.values())

    def pending_orders(self):
        return []

    def find_by_client_id(self, client_id: str):
        tid = self._client.get(client_id)
        return self._pos.get(tid) if tid else None

    def place(self, req: OrderRequest) -> OrderResult:
        if not req.sl:
            return OrderResult(False, error="سفارش بدون حد ضرر ارسال نمی‌شود")
        t = self.tick(req.symbol)
        if not t:
            return OrderResult(False, error="قیمت در دسترس نیست", retryable=True)
        with self._lock:
            if req.client_id in self._client:
                return OrderResult(True, self._client[req.client_id], self._pos[self._client[req.client_id]].price_open)
            price = t["ask"] if req.direction > 0 else t["bid"]
            tid = next(self._ids)
            self._pos[tid] = Position(tid, req.symbol, req.direction, req.volume, price, req.sl, req.tp, 0.0,
                                      int(time.time()), f"NTP{req.client_id[:12]}")
            self._client[req.client_id] = tid
            return OrderResult(True, tid, price, req.volume)

    def modify(self, ticket, sl, tp):
        with self._lock:
            p = self._pos.get(ticket)
            if not p:
                return OrderResult(False, error="not found")
            p.sl, p.tp = sl, tp
            return OrderResult(True, ticket)

    def close(self, ticket, volume=None, comment=""):
        with self._lock:
            p = self._pos.get(ticket)
            if not p:
                return OrderResult(False, error="not found")
            t = self.fake_ticks.get(p.symbol) or self.data.tick(p.symbol)
            px = t["bid"] if p.direction > 0 else t["ask"]
            return self._close(p, px, volume or p.volume, 3)   # 3 = بسته شدن توسط اکسپرت

    def _close(self, p: Position, px: float, volume: float, reason: int) -> OrderResult:
        spec = self.spec(p.symbol)
        profit = (px - p.price_open) * p.direction * spec.value_per_price_unit(volume)
        comm = -self.commission * volume
        self.balance += profit + comm
        self._deals.append({"position_id": p.ticket, "price": px, "volume": volume, "profit": profit,
                            "commission": comm, "swap": 0.0, "fee": 0.0, "time": int(time.time()), "reason": reason,
                            "comment": ""})
        p.volume = round(p.volume - volume, 8)
        if p.volume <= 1e-9:
            self._pos.pop(p.ticket, None)
        return OrderResult(True, p.ticket, px, volume)

    def _check_stops(self, symbol: str, t: dict) -> None:
        with self._lock:
            for p in [p for p in self._pos.values() if p.symbol == symbol]:
                px = t["bid"] if p.direction > 0 else t["ask"]
                if p.sl and (px - p.sl) * p.direction <= 0:
                    self._close(p, p.sl, p.volume, 4)      # 4 = SL در MT5
                elif p.tp and (px - p.tp) * p.direction >= 0:
                    self._close(p, p.tp, p.volume, 5)      # 5 = TP

    def cancel(self, ticket):
        return OrderResult(True, ticket)

    def closed_deals(self, since: int):
        return [d for d in self._deals if d["time"] >= since]

    def ping_ms(self):
        return self.data.ping_ms() if self.data else 1.0

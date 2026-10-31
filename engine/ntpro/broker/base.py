"""رابط بروکر. موتور فقط با این رابط کار می‌کند (MT5 واقعی، یا شبیه‌ساز Paper)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..risk import SymbolSpec


@dataclass
class OrderRequest:
    client_id: str
    symbol: str
    direction: int
    volume: float
    price: float            # قیمت درخواستی (برای Limit: قیمت لیمیت)
    sl: float
    tp: float
    kind: str = "market"    # market | limit
    expiry_seconds: int = 0
    comment: str = ""


@dataclass
class OrderResult:
    ok: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    error: str = ""
    retryable: bool = False
    pending: bool = False
    raw: dict = field(default_factory=dict)


@dataclass
class Position:
    ticket: int
    symbol: str
    direction: int
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    time: int
    comment: str = ""


class Broker:
    name = "base"

    def connect(self) -> bool: ...
    def connected(self) -> bool: ...
    def shutdown(self) -> None: ...
    def account(self) -> dict: ...
    def is_demo(self) -> bool: ...
    def spec(self, symbol: str) -> SymbolSpec: ...
    def candles(self, symbol: str, tf: str, count: int) -> pd.DataFrame: ...
    def candles_range(self, symbol: str, tf: str, start, end) -> pd.DataFrame: ...
    def ticks_range(self, symbol: str, start, end) -> pd.DataFrame | None: ...
    def tick(self, symbol: str) -> dict | None: ...
    def positions(self) -> list[Position]: ...
    def pending_orders(self) -> list[dict]: ...
    def place(self, req: OrderRequest) -> OrderResult: ...
    def modify(self, ticket: int, sl: float, tp: float) -> OrderResult: ...
    def close(self, ticket: int, volume: float | None = None, comment: str = "") -> OrderResult: ...
    def cancel(self, ticket: int) -> OrderResult: ...
    def find_by_client_id(self, client_id: str) -> Position | None: ...
    def closed_deals(self, since: int) -> list[dict]: ...
    def ping_ms(self) -> float | None: ...

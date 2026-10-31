"""ماژول ۶: مدیریت ریسک — غیرقابل دور زدن توسط استراتژی‌ها، مدل‌ها و یادگیری.

ممنوعیت‌های قطعی در همین فایل به‌صورت کد نوشته شده‌اند و هیچ کلید تنظیماتی برای فعال‌کردنشان وجود ندارد:
  - مارتینگل / افزایش حجم بعد از ضرر (Revenge Trading)
  - گرید / میانگین‌گیری / اضافه کردن به پوزیشن هم‌جهت روی همان نماد
  - معامله بدون حد ضرر
  - حذف یا دورتر کردن حد ضرر بعد از ورود
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass


class ProhibitedAction(Exception):
    """تلاش برای انجام یکی از ممنوعیت‌های قطعی."""


@dataclass
class SymbolSpec:
    name: str
    point: float = 0.00001
    digits: int = 5
    tick_size: float = 0.00001
    tick_value: float = 1.0          # ارزش یک تیک برای ۱ لات به ارز حساب
    contract_size: float = 100000
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    stops_level: int = 0             # حداقل فاصله‌ی حد ضرر از قیمت (پوینت)

    def value_per_price_unit(self, volume: float) -> float:
        """سود/زیان به ارز حساب برای حرکت ۱ واحد قیمت با حجم volume."""
        return self.tick_value / self.tick_size * volume


def default_spec(symbol: str) -> SymbolSpec:
    s = symbol.upper()
    if s.startswith("XAU"):
        return SymbolSpec(symbol, point=0.01, digits=2, tick_size=0.01, tick_value=1.0, contract_size=100)
    if "JPY" in s:
        return SymbolSpec(symbol, point=0.001, digits=3, tick_size=0.001, tick_value=0.65, contract_size=100000)
    if s.startswith("BTC"):
        return SymbolSpec(symbol, point=0.01, digits=2, tick_size=0.01, tick_value=0.01, contract_size=1)
    return SymbolSpec(symbol)


CURRENCIES = ("USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD", "XAU", "XAG", "BTC", "SEK")


def exposures(symbol: str, direction: int) -> dict[str, int]:
    """خرید EURUSD → {EUR:+1, USD:-1}"""
    s = symbol.upper()
    base = next((c for c in CURRENCIES if s.startswith(c)), s[:3])
    rest = s[len(base):]
    quote = next((c for c in CURRENCIES if rest.startswith(c)), rest[:3] or "USD")
    return {base: direction, quote: -direction}


@dataclass
class RiskCheck:
    ok: bool
    reason: str = ""
    volume: float = 0.0
    risk_amount: float = 0.0
    rr_net: float = 0.0
    cost_price: float = 0.0


class RiskManager:
    def __init__(self, cfg, db=None):
        self.cfg = cfg          # ntpro.config.Config
        self.db = db

    @property
    def r(self) -> dict:
        return self.cfg.get("risk")

    # ---------- حجم و هزینه ----------
    def position_size(self, spec: SymbolSpec, balance: float, entry: float, sl: float, risk_pct: float) -> float:
        dist = abs(entry - sl)
        if dist <= 0:
            raise ProhibitedAction("حد ضرر نامعتبر")
        risk_amount = balance * risk_pct / 100.0
        per_lot = spec.value_per_price_unit(1.0) * dist
        commission = float(self.r.get("commission_per_lot_usd", 0))
        raw = risk_amount / (per_lot + commission)
        steps = math.floor(raw / spec.volume_step + 1e-9)
        vol = round(steps * spec.volume_step, 8)
        return min(vol, spec.volume_max)

    def cost_in_price(self, spec: SymbolSpec, volume: float, spread_points: float) -> float:
        """اسپرد + کمیسیون رفت‌وبرگشت، بر حسب واحد قیمت."""
        spread = spread_points * spec.point
        comm = float(self.r.get("commission_per_lot_usd", 0)) * volume
        return spread + comm / max(spec.value_per_price_unit(volume), 1e-12)

    @staticmethod
    def rr_net(entry: float, sl: float, tp: float, cost: float) -> float:
        reward = abs(tp - entry) - cost
        risk = abs(entry - sl) + cost
        return reward / risk if risk > 0 else 0.0

    # ---------- ممنوعیت‌های قطعی ----------
    @staticmethod
    def require_sl(direction: int, entry: float, sl: float | None) -> None:
        if not sl or sl <= 0:
            raise ProhibitedAction("معامله بدون حد ضرر ممنوع است")
        if (entry - sl) * direction <= 0:
            raise ProhibitedAction("حد ضرر در سمت اشتباه قیمت است")

    @staticmethod
    def validate_sl_change(direction: int, old_sl: float, new_sl: float | None) -> None:
        """حد ضرر فقط می‌تواند نزدیک‌تر (به نفع معامله) شود؛ حذف یا دورتر کردن ممنوع."""
        if not new_sl or new_sl <= 0:
            raise ProhibitedAction("حذف حد ضرر ممنوع است")
        if (new_sl - old_sl) * direction < -1e-12:
            raise ProhibitedAction("دورتر کردن حد ضرر ممنوع است")

    @staticmethod
    def no_grid(symbol: str, direction: int, open_trades: list[dict]) -> None:
        if any(t["symbol"] == symbol for t in open_trades):
            raise ProhibitedAction("پوزیشن باز روی این نماد وجود دارد (گرید/میانگین‌گیری/پیرامیدینگ ممنوع)")

    def no_martingale(self, risk_pct: float, recent_closed: list[dict]) -> float:
        """ریسک هرگز بیشتر از ریسک پایه نمی‌شود؛ بعد از ضرر ریسک ثابت می‌ماند یا کم می‌شود."""
        base = float(self.r["risk_per_trade_pct"])
        cap = min(base, float(self.r["max_risk_per_trade_pct"]))
        if risk_pct > cap + 1e-12:
            raise ProhibitedAction("افزایش ریسک بالاتر از ریسک پایه ممنوع است")
        losses = 0
        for t in recent_closed:          # جدیدترین اول
            if (t.get("pnl") or 0) < 0:
                losses += 1
            else:
                break
        if losses >= 3:                   # بعد از ۳ ضرر متوالی ریسک نصف می‌شود (هرگز زیاد نمی‌شود)
            return cap * 0.5
        return min(risk_pct, cap)

    # ---------- چک قبل از معامله ----------
    def pre_trade(self, *, symbol: str, direction: int, entry: float, sl: float, tp: float | None,
                  spec: SymbolSpec, balance: float, equity: float, spread_points: float,
                  open_trades: list[dict], today_closed: list[dict], recent_closed: list[dict],
                  kill_switch: dict | None, foreign_positions: list[dict] | None = None) -> RiskCheck:
        r = self.r
        if kill_switch and kill_switch.get("active"):
            return RiskCheck(False, f"Kill Switch فعال است: {kill_switch.get('reason', '')}")
        try:
            self.require_sl(direction, entry, sl)
            self.no_grid(symbol, direction, open_trades)
            risk_pct = self.no_martingale(float(r["risk_per_trade_pct"]), recent_closed)
        except ProhibitedAction as e:
            return RiskCheck(False, str(e))

        if spec.stops_level and abs(entry - sl) < spec.stops_level * spec.point:
            return RiskCheck(False, "فاصله‌ی حد ضرر کمتر از حداقل بروکر")
        day_pnl = sum(t.get("pnl") or 0 for t in today_closed)
        if day_pnl <= -balance * float(r["max_daily_loss_pct"]) / 100:
            return RiskCheck(False, f"سقف ضرر روزانه پر شد ({day_pnl:.2f})")
        if len(today_closed) + len(open_trades) >= int(r["max_trades_per_day"]):
            return RiskCheck(False, "سقف تعداد معاملات روزانه پر شد")
        if len(open_trades) >= int(r["max_open_positions"]):
            return RiskCheck(False, "حداکثر پوزیشن هم‌زمان باز است")

        # کنترل همبستگی/هم‌جهتی ارزها
        limit = int(r["max_same_currency_exposure"])
        load: dict[str, int] = {}
        for t in list(open_trades) + list(foreign_positions or []):
            for cur, d in exposures(t["symbol"], int(t["direction"])).items():
                load[cur] = load.get(cur, 0) + d
        for cur, d in exposures(symbol, direction).items():
            if abs(load.get(cur, 0) + d) > limit and abs(load.get(cur, 0) + d) > abs(load.get(cur, 0)):
                return RiskCheck(False, f"همبستگی: پوزیشن هم‌جهت روی {cur} از قبل باز است"
                                        + (" (شامل پوزیشن‌های برنامه‌ی دیگر)" if foreign_positions else ""))

        volume = self.position_size(spec, balance, entry, sl, risk_pct)
        if volume < spec.volume_min:
            return RiskCheck(False, "حجم محاسبه‌شده کمتر از حداقل لات است (ریسک بیش از حد مجاز می‌شد)")
        cost = self.cost_in_price(spec, volume, spread_points)
        if tp is None:
            return RiskCheck(False, "حد سود تعیین نشده")
        rr = self.rr_net(entry, sl, tp, cost)
        if rr < float(r["min_rr_after_costs"]):
            return RiskCheck(False, f"ریسک به ریوارد بعد از هزینه‌ها کم است (1:{rr:.2f})", rr_net=rr)
        risk_amount = spec.value_per_price_unit(volume) * abs(entry - sl) + float(r["commission_per_lot_usd"]) * volume
        return RiskCheck(True, "", volume, risk_amount, rr, cost)

    # ---------- Kill Switch خودکار ----------
    def update_drawdown(self, equity: float) -> tuple[float, bool]:
        """به‌روزرسانی سقف Equity و بررسی رسیدن به حداکثر Drawdown. خروجی: (dd%, kill)"""
        if self.db is None:
            return 0.0, False
        peak = float(self.db.kv_get("equity_peak", equity) or equity)
        if equity > peak:
            peak = equity
            self.db.kv_set("equity_peak", peak)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        kill = dd >= float(self.r["max_drawdown_pct"])
        if kill and not (self.db.kv_get("kill_switch") or {}).get("active"):
            self.db.kv_set("kill_switch", {"active": True, "reason": f"Drawdown {dd:.1f}٪", "time": int(time.time())})
            self.db.alert("critical", "kill_switch", f"Kill Switch خودکار: افت سرمایه {dd:.1f}٪")
        return dd, kill

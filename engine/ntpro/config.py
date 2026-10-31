"""تنظیمات موتور: پیش‌فرض‌ها + فایل config.json + نسخه‌بندی تغییرات.

همه‌ی تغییرات تنظیمات (از اپ یا فایل) با زمان، کاربر و تفاوت در جدول config_versions ذخیره می‌شوند
تا قابل ردیابی و برگشت باشند.
"""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

BASE_DIR = Path(os.environ.get("NTPRO_HOME", Path(__file__).resolve().parent.parent))
DATA_DIR = Path(os.environ.get("NTPRO_DATA", BASE_DIR / "data"))

DEFAULTS: dict[str, Any] = {
    "mode": "demo",                 # demo = سفارش واقعی روی حساب دمو | paper = شبیه‌سازی داخلی با قیمت زنده | live = حساب واقعی
    "allow_live": False,            # تا وقتی دستی true نشود، روی حساب واقعی معامله نمی‌شود
    "bot_enabled": False,           # ربات بعد از نصب خاموش است؛ از اپ روشن کنید
    "symbols": ["XAUUSD", "EURUSD"],
    "symbol_map": {},               # اگر نام نماد نزد بروکر فرق دارد: {"XAUUSD": "XAUUSD.ecn"}
    "timeframes": {"entry": "M5", "filters": ["M15", "H1"]},
    "mt5": {
        "path": r"C:\NeuroTraderPro\MT5\terminal64.exe",   # نصب جداگانه‌ی MT5؛ به ترمینال برنامه‌ی دیگر وصل نمی‌شود
        "server": "LiteFinance-MT5-Demo",
        "login": 0,
        "portable": True,
        "deviation_points": 20,
    },
    "api": {
        "host": "0.0.0.0",
        "port": 8810,               # NeuroTrader قدیمی روی 8765 است
        "tls": True,
        "ip_allowlist": [],         # خالی = همه؛ مثلاً ["5.0.0.0/8"]
        "rate_limit_per_min": 60,
        "access_token_minutes": 30,
        "refresh_token_days": 30,
    },
    "strategies": {
        "ema_cross": True, "supertrend_ema": True, "pullback": True, "macd_momentum": True,
        "orb": True, "asia_london": True, "break_retest": True, "squeeze": True,
        "bb_rsi_reversal": True, "vwap": True, "smc": True, "candle_patterns": True,
    },
    "confluence": {
        "min_strategies": 2,        # حداقل تعداد استراتژی هم‌جهت
        "min_score": 62,            # آستانه‌ی امتیاز ترکیبی (۰ تا ۱۰۰)
        "intermarket_weight": 0.10,
        "ml_weight": 0.20,
        "ml_reject_below": 0.42,    # اگر احتمال مدل کمتر بود، سیگنال رد می‌شود
        "ml_boost_above": 0.58,
    },
    "risk": {
        "risk_per_trade_pct": 0.5,  # ۰.۵ تا ۱ درصد
        "max_risk_per_trade_pct": 1.0,
        "min_rr_after_costs": 1.5,
        "sl_atr_mult": 1.5,
        "max_daily_loss_pct": 2.0,
        "max_trades_per_day": 6,
        "max_open_positions": 3,
        "max_same_currency_exposure": 1,   # مثلاً هم‌زمان بیش از یک پوزیشن «خرید دلار» نه
        "max_drawdown_pct": 8.0,           # Kill Switch خودکار
        "commission_per_lot_usd": 7.0,     # کمیسیون رفت‌وبرگشت حساب ECN (قابل تنظیم)
    },
    "exits": {
        "partial_tp_r": 1.0,        # هدف اول بر حسب R
        "partial_close_pct": 50,
        "move_be_after_tp1": True,
        "trail_atr_mult": 1.2,
        "time_stop_bars": 24,       # ۲ ساعت روی ۵ دقیقه
        "time_stop_min_r": 0.3,
        "use_liquidity_tp": True,
    },
    "intermarket": {               # نام نمادها نزد بروکر؛ خالی = غیرفعال (DXY در نبودِ نماد، مصنوعی ساخته می‌شود)
        "dxy": "USDX", "us10y": "", "vix": "", "nasdaq": "NAS100",
        "synthetic_dxy": True,
    },
    "traps": {
        "max_spread_points": {"XAUUSD": 45, "EURUSD": 15, "default": 25},
        "spike_atr_mult": 3.0,
        "min_relative_volume": 0.6,
        "check_divergence": True,
        "reverse_on_trap": False,   # در صورت تشخیص تله، به‌جای رد کردن، برعکس وارد شود (پیش‌فرض خاموش)
    },
    "sessions": {
        "symbol_hours_utc": {"XAUUSD": [[7, 20]], "EURUSD": [[6, 19]], "default": [[7, 19]]},
        "friday_cutoff_utc": 19,
        "rollover_block_minutes": [-20, 20],  # حول ساعت ۱۷:۰۰ نیویورک
        "kill_zone_only": False,
        "kill_zone_bonus": 5,
        "holidays": [],             # تاریخ‌های اضافه به‌صورت "2026-12-25"
    },
    "news": {
        "finnhub_key": "",          # روی سرور رمزنگاری می‌شود
        "fmp_key": "",
        "te_key": "",
        "block_before_min": 30,
        "block_after_min": 30,
        "pre_news_action": "breakeven",  # breakeven | partial | none
        "pre_news_partial_pct": 50,
        "pre_news_minutes": 10,
        "surprise_bias_points": 8,
        "adverse_headline_action": "tighten",  # close | tighten | none
        "use_finbert": False,
    },
    "learning": {
        "enabled": True,
        "min_trades_per_bucket": 30,
        "max_step": 0.05,
        "min_weight": 0.10,
        "half_life_trades": 100,
        "news_trade_weight": 0.3,
        "drawdown_brake_pct": 5.0,
        "shadow_days": 10,
        "fatigue_weeks": 4,
        "fatigue_pvalue": 0.05,
        "nn_enabled": True,
        "max_train_threads": 2,
    },
    "execution": {
        "max_slippage_points": {"XAUUSD": 40, "EURUSD": 8, "default": 20},
        "slippage_breach_limit": 3,
        "prefer_limit": True,
        "limit_offset_atr": 0.1,
        "limit_expiry_bars": 2,
        "max_retries": 3,
        "max_ping_ms": 250,
    },
    "notify": {
        "email": {"enabled": False, "smtp_host": "", "smtp_port": 587, "user": "", "password": "", "to": ""},
        "fcm": {"enabled": False, "server_key": ""},
    },
    "backup": {"daily_hour_utc": 22, "keep_days": 14},
}

SECRET_PATHS = [
    ("news", "finnhub_key"), ("news", "fmp_key"), ("news", "te_key"),
    ("notify", "email", "password"), ("notify", "fcm", "server_key"),
]


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def diff(old: Any, new: Any, prefix: str = "") -> list[str]:
    changes: list[str] = []
    if isinstance(old, dict) and isinstance(new, dict):
        for k in sorted(set(old) | set(new)):
            changes += diff(old.get(k), new.get(k), f"{prefix}.{k}" if prefix else str(k))
    elif old != new:
        changes.append(f"{prefix}: {old!r} -> {new!r}")
    return changes


def _get(d: dict, path: tuple) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _set(d: dict, path: tuple, value: Any) -> None:
    for p in path[:-1]:
        d = d.setdefault(p, {})
    d[path[-1]] = value


class Config:
    """تنظیمات thread-safe. اسرار (کلید API و ...) رمزنگاری‌شده روی دیسک ذخیره می‌شوند."""

    def __init__(self, path: Path | None = None, vault=None, db=None):
        self.path = Path(path or DATA_DIR / "config.json")
        self.vault = vault
        self.db = db
        self._lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self) -> None:
        with self._lock:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if self.vault:
                    for sp in SECRET_PATHS:
                        v = _get(raw, sp)
                        if isinstance(v, str) and v.startswith("enc:"):
                            _set(raw, sp, self.vault.decrypt(v[4:]))
                self.data = deep_merge(DEFAULTS, raw)
            else:
                self.save(user="system", reason="ایجاد اولیه")

    def save(self, user: str = "system", reason: str = "") -> None:
        with self._lock:
            out = copy.deepcopy(self.data)
            if self.vault:
                for sp in SECRET_PATHS:
                    v = _get(out, sp)
                    if v:
                        _set(out, sp, "enc:" + self.vault.encrypt(str(v)))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def get(self, *path: str, default: Any = None) -> Any:
        with self._lock:
            v = _get(self.data, tuple(path))
            return default if v is None else v

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def public(self) -> dict:
        """نسخه‌ی بدون اسرار برای ارسال به اپ."""
        with self._lock:
            out = copy.deepcopy(self.data)
        for sp in SECRET_PATHS:
            if _get(out, sp):
                _set(out, sp, "••••••")
        return out

    def update(self, patch: dict, user: str = "system", reason: str = "") -> list[str]:
        """اعمال تغییرات + ثبت نسخه. ممنوعیت‌های قطعی (مارتینگل و ...) اصلاً کلید تنظیماتی ندارند."""
        with self._lock:
            for sp in SECRET_PATHS:                 # «••••••» یعنی تغییر نکرده
                if _get(patch, sp) == "••••••":
                    _set(patch, sp, _get(self.data, sp))
            new = deep_merge(self.data, patch)
            _validate(new)
            changes = diff(self.data, new)
            if not changes:
                return []
            self.data = new
            self.save(user, reason)
            if self.db is not None:
                masked = [c for c in changes if not any(".".join(sp) in c for sp in SECRET_PATHS)]
                self.db.add_config_version(user, reason, masked, self.public())
            return changes


def _validate(cfg: dict) -> None:
    r = cfg["risk"]
    if not 0.05 <= float(r["risk_per_trade_pct"]) <= float(r["max_risk_per_trade_pct"]) <= 2.0:
        raise ValueError("ریسک هر معامله باید بین ۰.۰۵ و حداکثر مجاز (≤۲٪) باشد")
    if float(r["min_rr_after_costs"]) < 1.0:
        raise ValueError("حداقل ریسک به ریوارد نمی‌تواند کمتر از ۱ باشد")
    if int(r["max_open_positions"]) < 1 or int(r["max_trades_per_day"]) < 1:
        raise ValueError("سقف پوزیشن/معامله نامعتبر است")
    lr = cfg["learning"]
    if not 0 < float(lr["max_step"]) <= 0.05:
        raise ValueError("حداکثر تغییر وزن در هر معامله ۵٪ است")
    if float(lr["min_weight"]) < 0.10:
        raise ValueError("حداقل وزن هر استراتژی ۱۰٪ است")
    if cfg["mode"] not in ("paper", "demo", "live"):
        raise ValueError("mode نامعتبر")
    if cfg["mode"] == "live" and not cfg.get("allow_live"):
        raise ValueError("برای حساب واقعی ابتدا allow_live را فعال کنید")
    if int(cfg["api"]["port"]) == 8765:
        raise ValueError("پورت 8765 مال برنامه‌ی دیگر روی سرور است؛ پورت دیگری انتخاب کنید")

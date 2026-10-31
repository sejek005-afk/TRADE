"""سشن‌های معاملاتی با محاسبه‌ی خودکار ساعت تابستانی (zoneinfo)، Kill Zone، رول‌اور، جمعه و تعطیلات."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
TEHRAN = ZoneInfo("Asia/Tehran")

SESSION_FA = {"asia": "آسیا", "london": "لندن", "newyork": "نیویورک", "overlap": "هم‌پوشانی لندن-نیویورک",
              "off": "خارج از سشن"}


def _in_local(now: datetime, tz: ZoneInfo, start: time, end: time) -> bool:
    t = now.astimezone(tz).time()
    return start <= t < end


def easter(year: int) -> date:
    """الگوریتم گاوس برای عید پاک (برای Good Friday)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def bank_holidays(year: int) -> set[date]:
    """تعطیلات اصلی بانکی آمریکا/انگلیس که نقدینگی را به‌شدت کم می‌کنند."""
    gf = easter(year) - timedelta(days=2)
    return {
        date(year, 1, 1), gf, gf + timedelta(days=3),      # سال نو، Good Friday، Easter Monday
        date(year, 7, 4),                                   # استقلال آمریکا
        _nth_weekday(year, 11, 3, 4),                       # Thanksgiving
        date(year, 12, 24), date(year, 12, 25), date(year, 12, 26), date(year, 12, 31),
    }


@dataclass
class SessionState:
    names: list[str]
    primary: str
    kill_zone: str | None
    can_open: bool
    block_reason: str = ""
    minutes_to_rollover: float = 0.0
    tags: list[str] = field(default_factory=list)

    @property
    def primary_fa(self) -> str:
        return SESSION_FA.get(self.primary, self.primary)


class SessionClock:
    def __init__(self, cfg_sessions: dict):
        self.cfg = cfg_sessions

    @staticmethod
    def active_sessions(now: datetime) -> list[str]:
        out = []
        if _in_local(now, TOKYO, time(9), time(18)):
            out.append("asia")
        if _in_local(now, LONDON, time(8), time(17)):
            out.append("london")
        if _in_local(now, NEW_YORK, time(8), time(17)):
            out.append("newyork")
        return out

    @staticmethod
    def kill_zone(now: datetime) -> str | None:
        if _in_local(now, LONDON, time(7), time(10)):
            return "london"
        if _in_local(now, NEW_YORK, time(7), time(10)):
            return "newyork"
        return None

    @staticmethod
    def rollover_time(now: datetime) -> datetime:
        """رول‌اور ساعت ۱۷:۰۰ نیویورک (نزدیک‌ترین وقوع به now)."""
        ny = now.astimezone(NEW_YORK)
        candidates = [datetime.combine(ny.date() + timedelta(days=d), time(17), NEW_YORK) for d in (-1, 0, 1)]
        return min(candidates, key=lambda c: abs((c - now).total_seconds()))

    def is_holiday(self, now: datetime) -> bool:
        d = now.astimezone(NEW_YORK).date()
        extra = {date.fromisoformat(x) for x in self.cfg.get("holidays", [])}
        return d in bank_holidays(d.year) or d in extra

    def symbol_hours_ok(self, symbol: str, now: datetime) -> bool:
        hours = self.cfg.get("symbol_hours_utc", {})
        ranges = hours.get(symbol, hours.get("default", [[0, 24]]))
        h = now.astimezone(UTC).hour + now.astimezone(UTC).minute / 60
        return any(a <= h < b for a, b in ranges)

    def state(self, symbol: str, now: datetime | None = None) -> SessionState:
        now = now or datetime.now(UTC)
        names = self.active_sessions(now)
        if "london" in names and "newyork" in names:
            primary = "overlap"
        elif names:
            primary = names[-1]
        else:
            primary = "off"
        kz = self.kill_zone(now)
        roll = self.rollover_time(now)
        mins = (roll - now).total_seconds() / 60
        lo, hi = self.cfg.get("rollover_block_minutes", [-20, 20])

        utc = now.astimezone(UTC)
        reason = ""
        if utc.weekday() == 5 or (utc.weekday() == 6 and utc.hour < 22):
            reason = "بازار تعطیل است (آخر هفته)"
        elif utc.weekday() == 4 and utc.hour >= int(self.cfg.get("friday_cutoff_utc", 19)):
            reason = "جمعه بعد از ساعت مجاز"
        elif self.is_holiday(now):
            reason = "تعطیلات بانکی"
        elif -hi <= mins <= -lo:
            reason = "ساعت رول‌اور"
        elif not self.symbol_hours_ok(symbol, now):
            reason = "خارج از ساعات مجاز این نماد"
        elif self.cfg.get("kill_zone_only") and kz is None:
            reason = "خارج از Kill Zone"
        tags = [f"session:{primary}"] + ([f"kz:{kz}"] if kz else [])
        return SessionState(names, primary, kz, reason == "", reason, mins, tags)


def bucket_session(primary: str) -> str:
    """سشن برای کلید یادگیری (Regime+سشن)."""
    return {"overlap": "newyork", "off": "asia"}.get(primary, primary)


def to_tehran(ts: int | float | datetime) -> str:
    if not isinstance(ts, datetime):
        ts = datetime.fromtimestamp(float(ts), UTC)
    return ts.astimezone(TEHRAN).strftime("%Y-%m-%d %H:%M")

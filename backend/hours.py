"""US stock market hours: regular sessions 9:30 am to 4 pm Eastern, minus NYSE holidays and
early closes (1 pm on the day after Thanksgiving, Christmas Eve and the day before July 4th)."""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
OPEN, CLOSE, EARLY_CLOSE = time(9, 30), time(16, 0), time(13, 0)


def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(y, month, (h + l - 7 * m + 114) % 31 + 1)


def _nth_weekday(y, month, weekday, n):
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y, month, weekday):
    d = date(y + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """A holiday on Saturday is observed Friday; on Sunday, Monday."""
    return d - timedelta(days=1) if d.weekday() == 5 else d + timedelta(days=1) if d.weekday() == 6 else d


@lru_cache(maxsize=None)
def holidays(y: int) -> frozenset:
    days = {
        _nth_weekday(y, 1, 0, 3),               # Martin Luther King Jr. Day
        _nth_weekday(y, 2, 0, 3),               # Washington's Birthday
        _easter(y) - timedelta(days=2),         # Good Friday
        _last_weekday(y, 5, 0),                 # Memorial Day
        _observed(date(y, 7, 4)),               # Independence Day
        _nth_weekday(y, 9, 0, 1),               # Labor Day
        _nth_weekday(y, 11, 3, 4),              # Thanksgiving
        _observed(date(y, 12, 25)),             # Christmas
    }
    if y >= 2022:
        days.add(_observed(date(y, 6, 19)))     # Juneteenth
    # New Year's Day; when it falls on a Saturday the NYSE does not close the Friday before.
    if date(y, 1, 1).weekday() != 5:
        days.add(_observed(date(y, 1, 1)))
    return frozenset(days)


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def _early_close(d: date) -> bool:
    if d == _nth_weekday(d.year, 11, 3, 4) + timedelta(days=1):
        return True
    if d.month == 12 and d.day == 24 and d.weekday() < 5:
        return True
    return d.month == 7 and d.day == 3 and d.weekday() < 5 and date(d.year, 7, 4).weekday() not in (5, 6)


def session(d: date):
    """(open, close) of the regular session on trading day d, as aware datetimes."""
    close = EARLY_CLOSE if _early_close(d) else CLOSE
    return datetime.combine(d, OPEN, ET), datetime.combine(d, close, ET)


def _now(now=None) -> datetime:
    return (now or datetime.now(timezone.utc)).astimezone(ET)


def is_open(now: datetime | None = None) -> bool:
    t = _now(now)
    if not is_trading_day(t.date()):
        return False
    o, c = session(t.date())
    return o <= t < c


def next_session(now: datetime | None = None):
    """The session that is open now, or else the next one to open: (open, close)."""
    t = _now(now)
    d = t.date()
    while True:
        if is_trading_day(d):
            o, c = session(d)
            if t < c:
                return o, c
        d += timedelta(days=1)


def status(now: datetime | None = None) -> dict:
    o, c = next_session(now)
    return {
        "is_open": is_open(now),
        "opens_at": o.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "closes_at": c.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

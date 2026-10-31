"""Time helpers: clock override, timezone handling, parsing and formatting."""

import datetime as dt
import os
import re

from .errors import CtlError

UTC = dt.timezone.utc
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def now():
    value = os.environ.get("USAGECTL_NOW")
    if value:
        try:
            return parse_ts(value, Zone("+00:00"))
        except CtlError:
            raise CtlError("USAGECTL_NOW is not a valid ISO timestamp: %r" % value)
    return dt.datetime.now(UTC).replace(microsecond=0)


class Zone:
    """A configured timezone: 'local', a fixed offset like +05:30, or an IANA name."""

    def __init__(self, name):
        self.name = name
        self.tz = None
        if name == "local":
            return
        m = re.fullmatch(r"([+-])(\d\d):(\d\d)", name or "")
        if m:
            hours, minutes = int(m.group(2)), int(m.group(3))
            if hours > 14 or minutes > 59:
                raise CtlError("timezone offset out of range: %s" % name)
            delta = dt.timedelta(hours=hours, minutes=minutes)
            self.tz = dt.timezone(-delta if m.group(1) == "-" else delta)
            return
        try:
            from zoneinfo import ZoneInfo
            self.tz = ZoneInfo(name)
        except Exception:
            raise CtlError(
                "timezone %r is not available here; use a fixed offset such as +05:30, \"local\", "
                "or run: pip install tzdata" % (name,))

    def to_local(self, d):
        return d.astimezone(self.tz) if self.tz is not None else d.astimezone()

    def localize(self, naive):
        if self.tz is None:
            return naive.astimezone()
        return naive.replace(tzinfo=self.tz)

    def local_date(self, d):
        return self.to_local(d).date()

    def day_bounds(self, date):
        """UTC start of this local date and of the next one."""
        start = self.localize(dt.datetime.combine(date, dt.time.min)).astimezone(UTC)
        end = self.localize(dt.datetime.combine(date + dt.timedelta(days=1), dt.time.min)).astimezone(UTC)
        return start, end

    def day_fraction(self, moment):
        """Fraction of the local day (that contains moment) elapsed before moment."""
        start, end = self.day_bounds(self.local_date(moment))
        return (moment - start) / (end - start)


def parse_ts(value, zone):
    """Parse an ISO timestamp. Naive values are read in zone. Returns aware UTC datetime."""
    if not isinstance(value, str) or isinstance(value, bool):
        raise CtlError("timestamp must be a string, got %r" % (value,))
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        raise CtlError("invalid timestamp: %r" % value)
    if parsed.tzinfo is None:
        parsed = zone.localize(parsed)
    return parsed.astimezone(UTC).replace(microsecond=0)


def fmt_utc(d):
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_local(d, zone):
    local = zone.to_local(d)
    off = local.strftime("%z")
    if len(off) == 5:
        off = off[:3] + ":" + off[3:]
    return local.strftime("%Y-%m-%d %H:%M") + off


def parse_duration(text):
    m = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", text or "")
    if not m or not any(m.groups()):
        raise CtlError("invalid duration %r (examples: 3h20m, 45m, 1d2h)" % (text,))
    days, hours, minutes = (int(g) if g else 0 for g in m.groups())
    delta = dt.timedelta(days=days, hours=hours, minutes=minutes)
    if delta <= dt.timedelta(0):
        raise CtlError("duration must be positive: %r" % text)
    return delta


def parse_date(text):
    try:
        return dt.date.fromisoformat(text)
    except (ValueError, TypeError):
        raise CtlError("invalid date %r (use YYYY-MM-DD)" % (text,))

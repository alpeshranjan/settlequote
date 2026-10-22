"""Banking-day calendar. Dates come from the transcribed Fed holiday file."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def as_et(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError("timestamps must include an offset")
    return moment.astimezone(ET)


def at_local(day: date, hhmm: str) -> datetime:
    hour, minute = (int(part) for part in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)


def exclusive_end_of_minute(moment: datetime) -> datetime:
    """Cutoff minutes on the Fed pages are inclusive of that minute."""
    start = moment.replace(second=0, microsecond=0)
    return start + timedelta(minutes=1)


class Calendar:
    def __init__(self, observed_closures: set[date]) -> None:
        self.observed_closures = observed_closures

    def is_banking_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.observed_closures

    def on_or_after(self, day: date) -> date:
        cursor = day
        while not self.is_banking_day(cursor):
            cursor += timedelta(days=1)
        return cursor

    def next_after(self, day: date) -> date:
        return self.on_or_after(day + timedelta(days=1))

"""Load the transcribed rule files. The pages, not this module, are the source."""

import json
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from settlequote.engine.calendar import Calendar

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STALE_AFTER_DAYS = 400


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text())


@lru_cache(maxsize=1)
def load_rules() -> dict:
    holidays = _load("holidays.json")
    windows = _load("windows.json")
    fees = _load("fee_bands.json")
    closures = {date.fromisoformat(day) for day in holidays["observed_closures"]}
    return {
        "holidays": holidays,
        "windows": windows,
        "fees": fees,
        "calendar": Calendar(closures),
        "rules_version": windows["rules_version"],
        "reviewed_on": date.fromisoformat(windows["reviewed_on"]),
    }


def is_stale(submitted_on: date, reviewed_on: date) -> bool:
    return (submitted_on - reviewed_on).days > STALE_AFTER_DAYS


def money(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    return Decimal(raw)


def iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.isoformat()

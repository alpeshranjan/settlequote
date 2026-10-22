from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def friday_payload() -> dict:
    submitted = datetime(2026, 10, 23, 16, 50, tzinfo=ET)
    deadline = datetime(2026, 10, 23, 19, 0, tzinfo=ET)
    return {
        "amount_usd": "12000.00",
        "submitted_at": submitted.isoformat(),
        "deadline": deadline.isoformat(),
        "receiver": "us_bank_account",
    }

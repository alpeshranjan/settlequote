"""Frozen-clock tests. Each docstring quotes the Fed or NACHA sentence it locks."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from settlequote.engine.calendar import ET
from settlequote.engine.gas import StaticGas
from settlequote.engine.quote import QuoteError, _recommend, quote
from settlequote.engine.quote import RailResult
from settlequote.engine.rules import load_rules


def at(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=ET)


def rail(result: dict, name: str) -> dict:
    return next(item for item in result["rails"] if item["rail"] == name)


def test_source_sentences_match_the_live_pages():
    """6:45 p.m. ET Customer Transfers, pacs.008 CTRC, inclusive of that minute.
    Same-day last transmission deadline is 4:45 p.m. ET.
    FedACH forward item is $0.0035. Fedwire tier-1 pre-incentive is $0.97.
    FedNow pacs.008 origination is $0.045.
    """
    rules = load_rules()
    fedwire = rules["windows"]["fedwire"]["source_sentence"]
    assert "6:45 p.m. ET" in fedwire
    assert "pacs.008" in fedwire
    assert "CTRC" in fedwire
    assert "inclusive of the minute" in fedwire
    assert "4:45 p.m. ET" in rules["windows"]["same_day_ach"]["source_sentence"]
    assert "$1,000,000" in rules["windows"]["same_day_ach"]["amount_cap_sentence"]
    assert rules["fees"]["ach"]["operator_fee_usd"] == "0.0035"
    assert rules["fees"]["fedwire"]["operator_fee_usd"] == "0.97"
    assert rules["fees"]["fednow"]["operator_fee_usd"] == "0.045"
    assert "6:45" not in rules["windows"]["fedwire"]["source_sentence"].replace("6:45 p.m. ET", "")


def test_saturday_holiday_does_not_close_friday_and_sunday_holiday_closes_monday():
    """For holidays falling on Saturday, Federal Reserve Banks are open the preceding Friday.
    For holidays falling on Sunday, they are closed the following Monday.
    """
    calendar = load_rules()["calendar"]
    assert at(2026, 7, 3, 12, 0).strftime("%A") == "Friday"
    assert calendar.is_banking_day(at(2026, 7, 3, 12, 0).date())
    assert not calendar.is_banking_day(at(2027, 7, 5, 12, 0).date())
    assert at(2027, 7, 5, 12, 0).strftime("%A") == "Monday"


def test_friday_afternoon_misses_same_day_and_fedwire_is_still_open():
    """Same Day Eligible Forward Items: 4:45 p.m. ET is the last transmission deadline.
    6:45 p.m. ET is the core customer-transfer cutoff, so 4:50 p.m. is still inside it.
    """
    submitted = at(2026, 10, 23, 16, 50)
    assert submitted.strftime("%A") == "Friday"
    result = quote(
        {
            "amount_usd": "12000.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 23, 19, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    assert rail(result, "same_day_ach")["meets_deadline"] is False
    wire = rail(result, "fedwire")
    assert wire["meets_deadline"] is True
    assert wire["window"]["status"] == "open"
    assert result["recommendation"]["rail"] == "fedwire"
    assert result["recommendation"]["skipped_conditional"] == ["fednow", "rtp"]
    assert result["cost_rank_basis"] == "operator_fee"


def test_customer_wire_cutoff_is_inclusive_of_645_and_closed_at_646():
    """The cutoff times are inclusive of the minute listed, so 6:45 p.m. is in and 6:46 p.m. is out.
    After Friday's close, the next funds-transfer business day opens at 9:00 p.m. ET Sunday.
    """
    open_at = at(2026, 10, 23, 18, 45, 30)
    closed_at = at(2026, 10, 23, 18, 46)
    still_open = quote(
        {
            "amount_usd": "100.00",
            "submitted_at": open_at.isoformat(),
            "deadline": at(2026, 10, 23, 19, 0).isoformat(),
            "receiver": "us_bank_account",
            "rails": ["fedwire"],
        }
    )
    missed = quote(
        {
            "amount_usd": "100.00",
            "submitted_at": closed_at.isoformat(),
            "deadline": at(2026, 10, 23, 20, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    assert rail(still_open, "fedwire")["window"]["status"] == "open"
    wire = rail(missed, "fedwire")
    assert wire["meets_deadline"] is False
    assert wire["window"]["status"] == "closed"
    assert wire["window"]["next_open"] == at(2026, 10, 25, 21, 0).isoformat()
    assert wire["settlement_eta"] == at(2026, 10, 26, 9, 0).isoformat()
    assert wire["funds_availability_eta"] == wire["settlement_eta"]
    assert missed["recommendation"]["rail"] == "fednow"
    assert missed["recommendation"]["conditional"] is True


def test_sunday_network_open_is_not_treated_as_a_sending_bank_open():
    """The network opens Sunday at 9:00 p.m. ET. No sending bank is modeled as originating then.
    A Monday 8:00 a.m. deadline is before the assumed desk open, so Fedwire does not meet it.
    """
    submitted = at(2026, 10, 24, 12, 0)
    result = quote(
        {
            "amount_usd": "500.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 26, 8, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    wire = rail(result, "fedwire")
    assert wire["window"]["network_settlement"] == at(2026, 10, 25, 21, 0).isoformat()
    assert wire["settlement_eta"] == at(2026, 10, 26, 9, 0).isoformat()
    assert wire["funds_availability_eta"] == wire["settlement_eta"]
    assert wire["meets_deadline"] is False
    assert rail(result, "ach")["meets_deadline"] is False
    open_local = load_rules()["windows"]["fedwire"]["originator_open_local"]
    from settlequote.engine.quote import _clock_phrase

    assert _clock_phrase(open_local) in " ".join(wire["caveats"])
    assert result["recommendation"]["conditional"] is True


def test_saturday_rolls_to_the_next_banking_day():
    """Fedwire and FedACH do not run a funds-transfer business day on Saturday.
    Monday's Fedwire cycle opens Sunday at 9:00 p.m. ET. Next-day ACH settles at 8:30 a.m. ET.
    """
    submitted = at(2026, 10, 24, 12, 0)
    assert submitted.strftime("%A") == "Saturday"
    result = quote(
        {
            "amount_usd": "500.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 26, 12, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    assert rail(result, "ach")["settlement_eta"] == at(2026, 10, 26, 8, 30).isoformat()
    assert rail(result, "same_day_ach")["settlement_eta"] == at(2026, 10, 26, 13, 0).isoformat()
    assert rail(result, "fedwire")["window"]["next_open"] == at(2026, 10, 25, 21, 0).isoformat()
    assert rail(result, "fedwire")["settlement_eta"] == at(2026, 10, 26, 9, 0).isoformat()


def test_fed_holiday_is_not_a_settlement_day():
    """Juneteenth 2026 is Friday, June 19, on the Federal Reserve holiday schedule.
    """
    holiday = at(2026, 6, 19, 12, 0)
    assert holiday.strftime("%A") == "Friday"
    assert load_rules()["calendar"].is_banking_day(holiday.date()) is False
    submitted = at(2026, 6, 18, 17, 0)
    result = quote(
        {
            "amount_usd": "1000.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 6, 22, 18, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    assert rail(result, "ach")["settlement_eta"] == at(2026, 6, 22, 8, 30).isoformat()
    assert rail(result, "same_day_ach")["settlement_eta"] == at(2026, 6, 22, 13, 0).isoformat()
    assert rail(result, "fedwire")["meets_deadline"] is True
    assert rail(result, "fedwire")["window"]["status"] == "open"


def test_same_day_cap_is_one_million():
    """Transactions above $1,000,000 are excluded from same-day eligibility.
    """
    submitted = at(2026, 10, 21, 9, 0)
    result = quote(
        {
            "amount_usd": "1000001.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 21, 20, 0).isoformat(),
            "receiver": "us_bank_account",
            "rails": ["ach", "same_day_ach"],
        }
    )
    assert rail(result, "same_day_ach")["eligible"] is False
    assert rail(result, "same_day_ach")["ineligible_reason"] == "amount_above_same_day_cap"
    assert rail(result, "ach")["eligible"] is True


def test_impossible_deadline_has_no_recommendation():
    """Base confirmation is 20 seconds in the transcribed window file, so a 5-second deadline cannot be met.
    """
    submitted = at(2026, 10, 23, 16, 50)
    result = quote(
        {
            "amount_usd": "25.00",
            "submitted_at": submitted.isoformat(),
            "deadline": (submitted + timedelta(seconds=5)).isoformat(),
            "receiver": "base_address",
        }
    )
    assert rail(result, "usdc_base")["meets_deadline"] is False
    assert rail(result, "ach")["ineligible_reason"] == "receiver_is_wallet"
    assert result["recommendation"] is None


def test_usdc_on_base_wins_a_ten_minute_deadline_when_its_operator_fee_is_lowest():
    """Chain confirmation is not a bank credit. With this fixture, Base gas is the lowest operator fee that still arrives inside ten minutes.
    """
    submitted = at(2026, 10, 23, 16, 50)
    result = quote(
        {
            "amount_usd": "250.00",
            "submitted_at": submitted.isoformat(),
            "deadline": (submitted + timedelta(minutes=10)).isoformat(),
            "receiver": "either",
        },
        gas=StaticGas(usdc_base_usd=Decimal("0.001"), usdc_solana_usd=Decimal("0.02")),
    )
    assert rail(result, "usdc_base")["meets_deadline"] is True
    assert rail(result, "usdc_base")["data_status"] == "static"
    assert result["recommendation"]["rail"] == "usdc_base"
    assert "not a credit to a bank account" in " ".join(rail(result, "usdc_base")["caveats"]).lower() or any(
        "not a bank credit" in item.lower() or "not a credit" in item.lower()
        for item in rail(result, "usdc_base")["caveats"]
    )


def test_operator_fee_tie_breaks_to_the_earlier_arrival():
    """Equal operator fees break toward the earlier settlement time."""
    sooner = RailResult(
        rail="ach",
        eligible=True,
        meets_deadline=True,
        settlement_eta=at(2026, 10, 26, 8, 30),
        funds_availability_eta=at(2026, 10, 26, 9, 0),
        operator_fee_usd=Decimal("0.01"),
    )
    later = RailResult(
        rail="fedwire",
        eligible=True,
        meets_deadline=True,
        settlement_eta=at(2026, 10, 26, 12, 0),
        funds_availability_eta=at(2026, 10, 26, 12, 0),
        operator_fee_usd=Decimal("0.01"),
    )
    assert _recommend([later, sooner])["rail"] == "ach"


def test_deadline_before_submission_and_bad_amount_are_errors():
    submitted = at(2026, 10, 23, 16, 50)
    with pytest.raises(QuoteError) as before:
        quote(
            {
                "amount_usd": "10.00",
                "submitted_at": submitted.isoformat(),
                "deadline": submitted.isoformat(),
                "receiver": "us_bank_account",
            }
        )
    assert before.value.code == "deadline_before_submission"
    with pytest.raises(QuoteError) as amount:
        quote(
            {
                "amount_usd": "0",
                "submitted_at": submitted.isoformat(),
                "deadline": at(2026, 10, 23, 18, 0).isoformat(),
                "receiver": "us_bank_account",
            }
        )
    assert amount.value.code == "invalid_amount"


def test_json_number_amount_is_accepted_when_it_is_cents():
    submitted = at(2026, 10, 23, 16, 50)
    result = quote(
        {
            "amount_usd": 12000,
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 23, 19, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    assert result["recommendation"]["rail"] == "fedwire"


@pytest.mark.parametrize("raw", ["NaN", "sNaN", "Infinity", "1e-30", "0.001", "0.00", "1.001"])
def test_non_cent_amounts_are_rejected(raw):
    with pytest.raises(QuoteError) as exc:
        quote(
            {
                "amount_usd": raw,
                "submitted_at": at(2026, 10, 23, 16, 50).isoformat(),
                "deadline": at(2026, 10, 23, 19, 0).isoformat(),
                "receiver": "us_bank_account",
            }
        )
    assert exc.value.code == "invalid_amount"


def test_missing_and_malformed_timestamps_have_their_own_codes():
    submitted = at(2026, 10, 23, 16, 50)
    deadline = at(2026, 10, 23, 19, 0).isoformat()
    with pytest.raises(QuoteError) as missing:
        quote({"amount_usd": "10.00", "deadline": deadline, "receiver": "us_bank_account"})
    assert missing.value.code == "missing_submitted_at"
    with pytest.raises(QuoteError) as bad_deadline:
        quote(
            {
                "amount_usd": "10.00",
                "submitted_at": submitted.isoformat(),
                "deadline": "Friday",
                "receiver": "us_bank_account",
            }
        )
    assert bad_deadline.value.code == "invalid_deadline"
    with pytest.raises(QuoteError) as bad_submitted:
        quote(
            {
                "amount_usd": "10.00",
                "submitted_at": "noon",
                "deadline": deadline,
                "receiver": "us_bank_account",
            }
        )
    assert bad_submitted.value.code == "invalid_submitted_at"


def test_fedwire_caveat_uses_the_json_cutoff():
    from settlequote.engine.quote import _clock_phrase

    submitted = at(2026, 10, 23, 16, 50)
    result = quote(
        {
            "amount_usd": "12000.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 23, 19, 0).isoformat(),
            "receiver": "us_bank_account",
        }
    )
    cutoff = load_rules()["windows"]["fedwire"]["customer_cutoff_local"]
    expected = f"A sending bank's own cutoff is earlier than {_clock_phrase(cutoff)}."
    assert expected in rail(result, "fedwire")["caveats"]
    assert _clock_phrase("18:45") == "6:45 p.m. ET"
    with pytest.raises(QuoteError) as unknown:
        quote(
            {
                "amount_usd": "10.00",
                "submitted_at": submitted.isoformat(),
                "deadline": at(2026, 10, 23, 18, 0).isoformat(),
                "receiver": "us_bank_account",
                "rails": ["sepa"],
            }
        )
    assert unknown.value.code == "unknown_rail"


def test_disclaimer_is_on_every_quote():
    submitted = at(2026, 10, 23, 12, 0)
    result = quote(
        {
            "amount_usd": "10.00",
            "submitted_at": submitted.isoformat(),
            "deadline": at(2026, 10, 23, 18, 0).isoformat(),
            "receiver": "us_bank_account",
            "rails": ["ach"],
        }
    )
    assert "not financial, legal, or payments advice" in result["disclaimer"]
    assert result["rules_version"] == "2026-10-21"


def test_receiver_timezone_moves_ach_availability_only():
    """Next-day credits are due by 9:00 a.m. RDFI local time.
    9:00 a.m. Pacific is later than 10:00 a.m. Eastern, so the same deadline misses.
    """
    from zoneinfo import ZoneInfo

    submitted = at(2026, 10, 25, 15, 0)
    payload = {
        "amount_usd": "500.00",
        "submitted_at": submitted.isoformat(),
        "deadline": at(2026, 10, 26, 10, 0).isoformat(),
        "receiver": "us_bank_account",
    }
    eastern = quote(payload)
    western = quote({**payload, "receiver_timezone": "America/Los_Angeles"})
    assert rail(eastern, "ach")["meets_deadline"] is True
    assert rail(western, "ach")["meets_deadline"] is False
    assert rail(western, "ach")["settlement_eta"] == at(2026, 10, 26, 8, 30).isoformat()
    ready = datetime(2026, 10, 26, 9, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert rail(western, "ach")["funds_availability_eta"] == ready.isoformat()
    assert eastern["receiver_timezone"] == "America/New_York"
    assert western["receiver_timezone"] == "America/Los_Angeles"
    with pytest.raises(QuoteError) as bad_zone:
        quote({**payload, "receiver_timezone": "Not/AZone"})
    assert bad_zone.value.code == "invalid_receiver_timezone"
    for raw in ("../x", "UTC", "Asia/Tokyo", "EST"):
        with pytest.raises(QuoteError) as rejected:
            quote({**payload, "receiver_timezone": raw})
        assert rejected.value.code == "invalid_receiver_timezone"
    linked = quote({**payload, "receiver_timezone": "US/Eastern"})
    assert rail(linked, "ach")["meets_deadline"] == rail(eastern, "ach")["meets_deadline"]
    assert rail(linked, "ach")["funds_availability_eta"] == rail(eastern, "ach")["funds_availability_eta"]


def test_date_outside_holiday_coverage_is_rejected():
    """The Fed holiday file covers 2026 through 2030. Christmas 2025 is not in it."""
    with pytest.raises(QuoteError) as before:
        quote(
            {
                "amount_usd": "500.00",
                "submitted_at": at(2025, 12, 25, 10, 0).isoformat(),
                "deadline": at(2025, 12, 25, 18, 0).isoformat(),
                "receiver": "us_bank_account",
            }
        )
    assert before.value.code == "outside_holiday_coverage"
    with pytest.raises(QuoteError) as after:
        quote(
            {
                "amount_usd": "500.00",
                "submitted_at": at(2031, 1, 2, 10, 0).isoformat(),
                "deadline": at(2031, 1, 2, 18, 0).isoformat(),
                "receiver": "us_bank_account",
            }
        )
    assert after.value.code == "outside_holiday_coverage"

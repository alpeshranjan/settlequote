"""Deadline quote across US rails.

Recommendation ignores RTP and FedNow even when their list price is lower.
Those rails are 24/7 only if both institutions participate, and this tool
does not check that. They stay in the response, marked conditional.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from settlequote.engine.calendar import ET, as_et, at_local, exclusive_end_of_minute
from settlequote.engine.gas import StaticGas
from settlequote.engine.rules import iso, is_stale, load_rules, money

DISCLAIMER = (
    "Network-window estimate, not a quote from a bank, and not financial, legal, "
    "or payments advice. Originating-bank cutoffs are earlier than Fed deadlines. "
    "Receiver availability is not checked."
)

FIAT = ("ach", "same_day_ach", "fedwire", "rtp", "fednow")
USDC = ("usdc_base", "usdc_solana")
ALL_RAILS = FIAT + USDC
CONDITIONAL = {"rtp", "fednow"}
MAX_AMOUNT = Decimal("100000000")

RECEIVER_RAILS = {
    "us_bank_account": set(FIAT),
    "base_address": {"usdc_base"},
    "solana_address": {"usdc_solana"},
    "either": set(ALL_RAILS),
}


class QuoteError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class RailResult:
    rail: str
    eligible: bool
    ineligible_reason: str | None = None
    meets_deadline: bool = False
    settlement_eta: datetime | None = None
    funds_availability_eta: datetime | None = None
    operator_fee_usd: Decimal | None = None
    customer_fee_band_usd: dict | None = None
    window: dict = field(default_factory=dict)
    data_status: str = "ok"
    caveats: list[str] = field(default_factory=list)
    conditional: bool = False

    def as_dict(self) -> dict:
        band = self.customer_fee_band_usd
        return {
            "rail": self.rail,
            "eligible": self.eligible,
            "ineligible_reason": self.ineligible_reason,
            "conditional": self.conditional,
            "meets_deadline": self.meets_deadline,
            "settlement_eta": iso(self.settlement_eta),
            "funds_availability_eta": iso(self.funds_availability_eta),
            "operator_fee_usd": None
            if self.operator_fee_usd is None
            else format(self.operator_fee_usd, "f"),
            "customer_fee_band_usd": band,
            "window": self.window,
            "data_status": self.data_status,
            "caveats": self.caveats,
        }


def quote(
    payload: dict,
    *,
    now: datetime | None = None,
    gas: StaticGas | None = None,
) -> dict:
    rules = load_rules()
    gas = gas or StaticGas()
    amount = _amount(payload.get("amount_usd"))
    submitted = _submitted(payload, now)
    deadline = _deadline(payload.get("deadline"), submitted)
    receiver = _receiver(payload.get("receiver"))
    requested = _requested(payload.get("rails"))
    allowed = RECEIVER_RAILS[receiver]

    results = [
        _one(
            rail,
            amount=amount,
            submitted=submitted,
            deadline=deadline,
            allowed=allowed,
            receiver=receiver,
            rules=rules,
            gas=gas,
        )
        for rail in requested
    ]
    recommendation = _recommend(results)
    caveats = []
    if is_stale(as_et(submitted).date(), rules["reviewed_on"]):
        caveats.append("rules_stale")

    return {
        "quote_id": str(uuid4()),
        "as_of": iso(submitted),
        "rules_version": rules["rules_version"],
        "cost_rank_basis": "operator_fee",
        "deadline_basis": "funds_availability",
        "disclaimer": DISCLAIMER,
        "caveats": caveats,
        "recommendation": recommendation,
        "rails": [item.as_dict() for item in results],
    }


def _amount(raw: object) -> Decimal:
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise QuoteError("invalid_amount", "amount_usd must be a decimal string.") from exc
    if amount <= 0:
        raise QuoteError("invalid_amount", "amount_usd must be greater than 0.")
    if amount > MAX_AMOUNT:
        raise QuoteError("amount_too_large", "amount_usd exceeds 100000000.")
    return amount


def _submitted(payload: dict, now: datetime | None) -> datetime:
    raw = payload.get("submitted_at")
    if raw is None:
        if now is None:
            raise QuoteError("missing_submitted_at", "submitted_at or now is required.")
        moment = now
    else:
        moment = _parse_time(raw, "submitted_at")
    return as_et(moment)


def _deadline(raw: object, submitted: datetime) -> datetime:
    deadline = _parse_time(raw, "deadline")
    deadline = as_et(deadline)
    if deadline <= submitted:
        raise QuoteError(
            "deadline_before_submission",
            "deadline must be after submitted_at.",
        )
    return deadline


def _parse_time(raw: object, field_name: str) -> datetime:
    code = f"invalid_{field_name}"
    if not isinstance(raw, str):
        raise QuoteError(code, f"{field_name} must be an ISO-8601 timestamp.")
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise QuoteError(code, f"{field_name} must be an ISO-8601 timestamp.") from exc
    if moment.tzinfo is None:
        raise QuoteError(code, f"{field_name} must include a timezone offset.")
    return moment


def _clock_phrase(hhmm: str) -> str:
    """Format a 24-hour HH:MM from windows.json as a Fed-style clock time."""
    hour, minute = (int(part) for part in hhmm.split(":"))
    suffix = "a.m." if hour < 12 else "p.m."
    hour12 = hour % 12 or 12
    return f"{hour12}:{minute:02d} {suffix} ET"


def _receiver(raw: object) -> str:
    if raw not in RECEIVER_RAILS:
        raise QuoteError(
            "unknown_receiver",
            "receiver must be us_bank_account, base_address, solana_address, or either.",
        )
    return str(raw)


def _requested(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ALL_RAILS
    if not isinstance(raw, list) or not raw:
        raise QuoteError("unknown_rail", "rails must be a non-empty list of rail names.")
    unknown = [name for name in raw if name not in ALL_RAILS]
    if unknown:
        raise QuoteError("unknown_rail", f"Unknown rail: {unknown[0]}.")
    return tuple(raw)


def _one(
    rail: str,
    *,
    amount: Decimal,
    submitted: datetime,
    deadline: datetime,
    allowed: set[str],
    receiver: str,
    rules: dict,
    gas: StaticGas,
) -> RailResult:
    if rail not in allowed:
        reason = (
            "receiver_is_bank_account" if receiver == "us_bank_account" else "receiver_is_wallet"
        )
        return RailResult(rail=rail, eligible=False, ineligible_reason=reason, conditional=rail in CONDITIONAL)

    if rail == "ach":
        return _ach(submitted, deadline, rules)
    if rail == "same_day_ach":
        return _same_day(submitted, deadline, amount, rules)
    if rail == "fedwire":
        return _fedwire(submitted, deadline, rules)
    if rail in CONDITIONAL:
        return _instant(rail, submitted, deadline, rules)
    return _usdc(rail, submitted, deadline, rules, gas)


def _band(rules: dict, rail: str) -> dict | None:
    raw = rules["fees"].get(rail, {}).get("customer_fee_band_usd")
    return None if raw is None else dict(raw)


def _operator(rules: dict, rail: str) -> Decimal | None:
    return money(rules["fees"].get(rail, {}).get("operator_fee_usd"))


def _finish(
    rail: str,
    *,
    submitted: datetime,
    deadline: datetime,
    settlement: datetime,
    availability: datetime,
    operator: Decimal | None,
    rules: dict,
    window: dict,
    caveats: list[str],
    data_status: str = "ok",
    conditional: bool = False,
) -> RailResult:
    return RailResult(
        rail=rail,
        eligible=True,
        conditional=conditional,
        meets_deadline=availability <= deadline,
        settlement_eta=settlement,
        funds_availability_eta=availability,
        operator_fee_usd=operator,
        customer_fee_band_usd=_band(rules, rail),
        window=window,
        data_status=data_status,
        caveats=caveats,
    )


def _ach(submitted: datetime, deadline: datetime, rules: dict) -> RailResult:
    spec = rules["windows"]["ach"]
    calendar = rules["calendar"]
    start = as_et(submitted).date()
    settlement = None
    for offset in range(21):
        day = start + timedelta(days=offset)
        if not calendar.is_banking_day(day):
            continue
        file_deadline = exclusive_end_of_minute(at_local(day, spec["file_deadline_local"]))
        candidate = at_local(day, spec["settlement_local"])
        if submitted < file_deadline and candidate > submitted:
            settlement = candidate
            availability = at_local(day, spec["funds_availability_local"])
            break
    if settlement is None:
        raise QuoteError("internal", "No ACH settlement day inside the search window.")
    return _finish(
        "ach",
        submitted=submitted,
        deadline=deadline,
        settlement=settlement,
        availability=availability,
        operator=_operator(rules, "ach"),
        rules=rules,
        window={"status": "next_banking_day", "cutoff": iso(file_deadline - timedelta(minutes=1))},
        caveats=[
            "Originating-bank file cutoff is earlier than this FedACH deadline.",
            spec["funds_availability_sentence"],
            rules["fees"]["ach"]["operator_fee_sentence"],
        ],
    )


def _same_day(
    submitted: datetime, deadline: datetime, amount: Decimal, rules: dict
) -> RailResult:
    spec = rules["windows"]["same_day_ach"]
    cap = Decimal(spec["amount_cap_usd"])
    if amount > cap:
        return RailResult(
            rail="same_day_ach",
            eligible=False,
            ineligible_reason="amount_above_same_day_cap",
            caveats=[spec["amount_cap_sentence"], "IAT and ENR entries are also ineligible. V1 checks the amount cap only."],
        )
    calendar = rules["calendar"]
    day = calendar.on_or_after(as_et(submitted).date())
    chosen = None
    for _ in range(10):
        for window in spec["windows"]:
            cutoff = at_local(day, window["transmission_deadline_local"])
            if submitted < exclusive_end_of_minute(cutoff):
                chosen = window
                break
        if chosen is not None:
            break
        day = calendar.next_after(day)
    if chosen is None:
        raise QuoteError("internal", "No same-day window inside the search window.")
    settlement = at_local(day, chosen["settlement_local"])
    availability = at_local(day, chosen["funds_availability_local"])
    return _finish(
        "same_day_ach",
        submitted=submitted,
        deadline=deadline,
        settlement=settlement,
        availability=availability,
        operator=_operator(rules, "same_day_ach"),
        rules=rules,
        window={"status": "next_window", "cutoff": iso(at_local(day, chosen["transmission_deadline_local"]))},
        caveats=[
            "Originating-bank file cutoff is earlier than this FedACH deadline.",
            spec["amount_cap_sentence"],
            "IAT and ENR entries are also ineligible. V1 checks the amount cap only.",
            chosen["funds_availability_sentence"],
            rules["fees"]["same_day_ach"]["operator_fee_sentence"],
        ],
    )


def _fedwire(submitted: datetime, deadline: datetime, rules: dict) -> RailResult:
    spec = rules["windows"]["fedwire"]
    calendar = rules["calendar"]
    start = as_et(submitted).date() - timedelta(days=1)
    settlement = None
    status = "closed"
    cutoff_shown = None
    next_open = None
    for offset in range(16):
        day = start + timedelta(days=offset)
        if not calendar.is_banking_day(day):
            continue
        open_at = at_local(day - timedelta(days=1), spec["opens_prior_calendar_day_local"])
        cutoff = at_local(day, spec["customer_cutoff_local"])
        close_at = exclusive_end_of_minute(cutoff)
        if open_at <= submitted < close_at:
            settlement = submitted
            status = "open"
            cutoff_shown = cutoff
            break
        if submitted < open_at:
            settlement = open_at
            status = "closed"
            cutoff_shown = cutoff
            next_open = open_at
            break
    if settlement is None:
        raise QuoteError("internal", "No Fedwire customer window inside the search window.")
    return _finish(
        "fedwire",
        submitted=submitted,
        deadline=deadline,
        settlement=settlement,
        availability=settlement,
        operator=_operator(rules, "fedwire"),
        rules=rules,
        window={"status": status, "cutoff": iso(cutoff_shown), "next_open": iso(next_open)},
        caveats=[
            spec["models"],
            (
                "A sending bank's own cutoff is earlier than "
                f"{_clock_phrase(spec['customer_cutoff_local'])}."
            ),
            spec["source_sentence"],
            rules["fees"]["fedwire"]["operator_fee_sentence"],
        ],
    )


def _instant(rail: str, submitted: datetime, deadline: datetime, rules: dict) -> RailResult:
    spec = rules["windows"][rail]
    settlement = submitted + timedelta(seconds=int(spec["settlement_seconds"]))
    return _finish(
        rail,
        submitted=submitted,
        deadline=deadline,
        settlement=settlement,
        availability=settlement,
        operator=_operator(rules, rail),
        rules=rules,
        window={"status": "always_on", "cutoff": None},
        caveats=[
            spec["source_sentence"],
            "Not used as the recommendation while participation is unchecked, unless no other rail meets the deadline.",
            rules["fees"][rail]["operator_fee_sentence"],
        ],
        conditional=True,
    )


def _usdc(
    rail: str, submitted: datetime, deadline: datetime, rules: dict, gas: StaticGas
) -> RailResult:
    spec = rules["windows"][rail]
    settlement = submitted + timedelta(seconds=int(spec["inclusion_seconds"]))
    availability = submitted + timedelta(seconds=int(spec["confirmation_seconds"]))
    fee = gas.fee_usd(rail)
    return _finish(
        rail,
        submitted=submitted,
        deadline=deadline,
        settlement=settlement,
        availability=availability,
        operator=fee,
        rules=rules,
        window={"status": "always_on", "cutoff": None},
        data_status=gas.data_status,
        caveats=[
            spec["source_sentence"],
            "Chain confirmation is not a credit to a bank account.",
        ],
    )


def _recommend(results: list[RailResult]) -> dict | None:
    meeting = [item for item in results if item.eligible and item.meets_deadline]
    firm = [
        item
        for item in meeting
        if not item.conditional and item.operator_fee_usd is not None
    ]
    if firm:
        firm.sort(key=lambda item: (item.operator_fee_usd, item.settlement_eta))
        chosen = firm[0]
        skipped = sorted(item.rail for item in meeting if item.conditional)
        reason = (
            "Meets the deadline at the lowest operator fee among rails that do not "
            "depend on an unchecked participant list."
        )
        if skipped:
            reason += (
                " A conditional rail may list a lower fee, but participation was not checked."
            )
        return {
            "rail": chosen.rail,
            "reason": reason,
            "conditional": False,
            "skipped_conditional": skipped,
        }

    conditional = [item for item in meeting if item.conditional]
    if not conditional:
        return None
    conditional.sort(
        key=lambda item: (
            item.operator_fee_usd is None,
            item.operator_fee_usd if item.operator_fee_usd is not None else Decimal("Infinity"),
            item.settlement_eta,
        )
    )
    chosen = conditional[0]
    return {
        "rail": chosen.rail,
        "reason": (
            "No rail with a checked operating window meets the deadline. "
            "This one does only if both institutions participate, which was not checked."
        ),
        "conditional": True,
        "skipped_conditional": [],
    }

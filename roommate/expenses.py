"""Validate shared costs and calculate who owes whom.

Money stays in integer cents. Equal splits give any remaining cents to the
first participants in the saved order, so every cent belongs to someone.
Settlement suggestions describe the current ledger; they do not send money.
"""

from __future__ import annotations

from datetime import date
from calendar import monthrange
import re
from typing import Any

from .geometry import ValidationError


MAX_MEMBERS = 20
MAX_EXPENSES = 500
MAX_AMOUNT_CENTS = 100_000_000
CATEGORIES = ("groceries", "rent", "utilities", "household", "other")
EXPENSE_FIELDS = {
    "id", "title", "amount_cents", "paid_by", "split_between", "date",
    "category", "notes",
    "bill_id", "bill_month",
}
REPAYMENT_FIELDS = {"id", "from_id", "to_id", "amount_cents", "date", "notes"}
MONTHLY_BILL_FIELDS = (EXPENSE_FIELDS - {"date", "bill_id", "bill_month"}) | {"due_day", "active"}


def _identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) is None:
        raise ValidationError(f"{label} must use 1–64 letters, numbers, underscores or hyphens.")
    return value


def _text(value: Any, label: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValidationError(f"{label} must be text of at most {maximum} characters.")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{label} cannot be empty.")
    return value


def _amount(value: Any, label: str = "Expense") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{label} amount must be a whole number of cents.")
    if not 1 <= value <= MAX_AMOUNT_CENTS:
        raise ValidationError(f"{label} amount must be between €0.01 and €1,000,000.")
    return value


def _date(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValidationError(f"{label} date must use YYYY-MM-DD.")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise ValidationError(f"{label} date must be a real calendar date.") from error
    return value


def _participants(value: Any) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_MEMBERS:
        raise ValidationError("Choose 1–20 members to split the expense between.")
    participants = [_identity(member_id, "Participant ID") for member_id in value]
    if len(set(participants)) != len(participants):
        raise ValidationError("An expense cannot include the same participant twice.")
    return participants


def _members(values: Any) -> list[dict]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_MEMBERS:
        raise ValidationError("The flat must have 1–20 members.")
    members = []
    seen = set()
    for value in values:
        if not isinstance(value, dict):
            raise ValidationError("Each member must be an object.")
        identity = _identity(value.get("id"), "Member ID")
        if identity in seen:
            raise ValidationError("Member IDs must be unique.")
        seen.add(identity)
        members.append({
            "id": identity,
            "name": _text(value.get("name"), "Member name", 80, required=True),
        })
    return members


def validate_expense(data: Any, members: Any) -> dict:
    """Return a clean expense, rejecting malformed amounts and missing members.

    The payer need not take a share: one member can pay for the others. Referenced
    members must still exist, so deleting a member cannot silently alter history.
    """
    member_ids = {member["id"] for member in _members(members)}
    if not isinstance(data, dict):
        raise ValidationError("Each expense must be an object.")
    unknown = set(data) - EXPENSE_FIELDS
    if unknown:
        fields = ", ".join(sorted(str(field) for field in unknown))
        raise ValidationError(f"Unknown expense fields: {fields}.")

    payer = _identity(data.get("paid_by"), "Payer ID")
    participants = _participants(data.get("split_between"))
    if payer not in member_ids or any(member_id not in member_ids for member_id in participants):
        raise ValidationError("Every expense payer and participant must be a current flat member.")

    expense_date = _date(data.get("date"), "Expense")

    category = data.get("category", "other")
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValidationError(f"Expense category must be one of: {', '.join(CATEGORIES)}.")

    result = {
        "id": _identity(data.get("id"), "Expense ID"),
        "title": _text(data.get("title"), "Expense title", 120, required=True),
        "amount_cents": _amount(data.get("amount_cents")),
        "paid_by": payer,
        "split_between": participants,
        "date": expense_date,
        "category": category,
        "notes": _text(data.get("notes", ""), "Expense notes", 2000),
    }
    if "bill_id" in data or "bill_month" in data:
        result["bill_id"] = _identity(data.get("bill_id"), "Monthly bill ID")
        if data.get("bill_month") != expense_date[:7]:
            raise ValidationError("The monthly bill period must match the expense date's month.")
        result["bill_month"] = data["bill_month"]
    return result


def validate_repayment(data: Any, members: Any) -> dict:
    """A record of money already sent between two members, not another expense."""
    member_ids = {member["id"] for member in _members(members)}
    if not isinstance(data, dict) or set(data) - REPAYMENT_FIELDS:
        raise ValidationError("A repayment must contain only its ID, people, amount, date and notes.")
    sender = _identity(data.get("from_id"), "Sender ID")
    recipient = _identity(data.get("to_id"), "Recipient ID")
    if sender not in member_ids or recipient not in member_ids:
        raise ValidationError("Both repayment people must be current flat members.")
    if sender == recipient:
        raise ValidationError("Choose two different people for a repayment.")
    return {
        "id": _identity(data.get("id"), "Repayment ID"),
        "from_id": sender, "to_id": recipient,
        "amount_cents": _amount(data.get("amount_cents"), "Repayment"),
        "date": _date(data.get("date"), "Repayment"),
        "notes": _text(data.get("notes", ""), "Repayment notes", 1000),
    }


def validate_monthly_bill(data: Any, members: Any) -> dict:
    """Save reusable bill details without creating a charge or assuming payment."""
    if not isinstance(data, dict) or set(data) - MONTHLY_BILL_FIELDS:
        raise ValidationError("The monthly bill contains unsupported fields.")
    base = {key: value for key, value in data.items() if key not in ("due_day", "active")}
    base["date"] = "2000-01-01"
    result = validate_expense(base, members)
    result.pop("date")
    day = data.get("due_day")
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 31:
        raise ValidationError("The monthly due day must be a whole number from 1 to 31.")
    active = data.get("active", True)
    if not isinstance(active, bool):
        raise ValidationError("The monthly bill's active flag must be true or false.")
    result.update(due_day=day, active=active)
    return result


def monthly_bill_status(bills: list[dict], expenses: list[dict], on: date | None = None) -> list[dict]:
    """Show this month's due date and recorded bill; short months use their last day."""
    on = on or date.today()
    period = f"{on.year:04d}-{on.month:02d}"
    recorded = {entry["bill_id"]: entry["id"] for entry in expenses
                if entry.get("bill_month") == period}
    return [{"bill_id": bill["id"],
             "due_date": f"{period}-{min(bill['due_day'], monthrange(on.year, on.month)[1]):02d}",
             "expense_id": recorded.get(bill["id"])} for bill in bills]


def expense_shares(expense: dict) -> dict[str, int]:
    """Return each participant's share in cents, preserving participant order."""
    if not isinstance(expense, dict):
        raise ValidationError("Each expense must be an object.")
    amount = _amount(expense.get("amount_cents"))
    participants = _participants(expense.get("split_between"))
    share, remainder = divmod(amount, len(participants))
    return {
        member_id: share + (index < remainder)
        for index, member_id in enumerate(participants)
    }


def summarize_expenses(expenses: Any, members: Any, repayments: Any = None) -> dict:
    """Calculate balances and deterministic transfers that clear those balances.

    Positive balances are money owed to a member; negative balances are money
    that member owes. Largest balances are matched first. This is a simple
    settlement suggestion, not a claim to find the fewest possible transfers.
    """
    member_records = _members(members)
    if not isinstance(expenses, list) or len(expenses) > MAX_EXPENSES:
        raise ValidationError("Expenses must be a list of at most 500 entries.")
    repayments = [] if repayments is None else repayments
    if not isinstance(repayments, list) or len(repayments) > 500:
        raise ValidationError("Repayments must be a list of at most 500 entries.")

    balances = {
        member["id"]: {
            "member_id": member["id"], "name": member["name"],
            "paid_cents": 0, "share_cents": 0, "balance_cents": 0,
        }
        for member in member_records
    }
    total = 0
    expense_ids = set()
    bill_periods = set()
    for value in expenses:
        expense = validate_expense(value, member_records)
        if expense["id"] in expense_ids:
            raise ValidationError("Expense IDs must be unique.")
        expense_ids.add(expense["id"])
        if "bill_id" in expense:
            period = (expense["bill_id"], expense["bill_month"])
            if period in bill_periods:
                raise ValidationError("This monthly bill has already been recorded for that month.")
            bill_periods.add(period)
        total += expense["amount_cents"]
        balances[expense["paid_by"]]["paid_cents"] += expense["amount_cents"]
        for member_id, share in expense_shares(expense).items():
            balances[member_id]["share_cents"] += share

    for balance in balances.values():
        balance["balance_cents"] = balance["paid_cents"] - balance["share_cents"]

    repayment_ids = set()
    for value in repayments:
        repayment = validate_repayment(value, member_records)
        if repayment["id"] in repayment_ids:
            raise ValidationError("Repayment IDs must be unique.")
        repayment_ids.add(repayment["id"])
        balances[repayment["from_id"]]["balance_cents"] += repayment["amount_cents"]
        balances[repayment["to_id"]]["balance_cents"] -= repayment["amount_cents"]

    debtors = sorted(
        [[entry["member_id"], -entry["balance_cents"]] for entry in balances.values()
         if entry["balance_cents"] < 0],
        key=lambda entry: (-entry[1], entry[0]),
    )
    creditors = sorted(
        [[entry["member_id"], entry["balance_cents"]] for entry in balances.values()
         if entry["balance_cents"] > 0],
        key=lambda entry: (-entry[1], entry[0]),
    )
    settlements = []
    debtor_index = creditor_index = 0
    while debtor_index < len(debtors) and creditor_index < len(creditors):
        debtor, creditor = debtors[debtor_index], creditors[creditor_index]
        amount = min(debtor[1], creditor[1])
        settlements.append({"from_id": debtor[0], "to_id": creditor[0], "amount_cents": amount})
        debtor[1] -= amount
        creditor[1] -= amount
        if debtor[1] == 0:
            debtor_index += 1
        if creditor[1] == 0:
            creditor_index += 1

    return {"total_cents": total, "balances": list(balances.values()), "settlements": settlements}

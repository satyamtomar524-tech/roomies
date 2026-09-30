"""Validate shared costs and calculate who owes whom.

Money stays in integer cents. Equal splits give any remaining cents to the
first participants in the saved order, so every cent belongs to someone.
Settlement suggestions describe the current ledger; they do not send money.
"""

from __future__ import annotations

from datetime import date
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
}


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


def _amount(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("Expense amount must be a whole number of cents.")
    if not 1 <= value <= MAX_AMOUNT_CENTS:
        raise ValidationError("Expense amount must be between €0.01 and €1,000,000.")
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

    expense_date = data.get("date")
    if not isinstance(expense_date, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", expense_date) is None:
        raise ValidationError("Expense date must use YYYY-MM-DD.")
    try:
        date.fromisoformat(expense_date)
    except ValueError as error:
        raise ValidationError("Expense date must be a real calendar date.") from error

    category = data.get("category", "other")
    if not isinstance(category, str) or category not in CATEGORIES:
        raise ValidationError(f"Expense category must be one of: {', '.join(CATEGORIES)}.")

    return {
        "id": _identity(data.get("id"), "Expense ID"),
        "title": _text(data.get("title"), "Expense title", 120, required=True),
        "amount_cents": _amount(data.get("amount_cents")),
        "paid_by": payer,
        "split_between": participants,
        "date": expense_date,
        "category": category,
        "notes": _text(data.get("notes", ""), "Expense notes", 2000),
    }


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


def summarize_expenses(expenses: Any, members: Any) -> dict:
    """Calculate balances and deterministic transfers that clear those balances.

    Positive balances are money owed to a member; negative balances are money
    that member owes. Largest balances are matched first. This is a simple
    settlement suggestion, not a claim to find the fewest possible transfers.
    """
    member_records = _members(members)
    if not isinstance(expenses, list) or len(expenses) > MAX_EXPENSES:
        raise ValidationError("Expenses must be a list of at most 500 entries.")

    balances = {
        member["id"]: {
            "member_id": member["id"], "name": member["name"],
            "paid_cents": 0, "share_cents": 0, "balance_cents": 0,
        }
        for member in member_records
    }
    total = 0
    expense_ids = set()
    for value in expenses:
        expense = validate_expense(value, member_records)
        if expense["id"] in expense_ids:
            raise ValidationError("Expense IDs must be unique.")
        expense_ids.add(expense["id"])
        total += expense["amount_cents"]
        balances[expense["paid_by"]]["paid_cents"] += expense["amount_cents"]
        for member_id, share in expense_shares(expense).items():
            balances[member_id]["share_cents"] += share

    for balance in balances.values():
        balance["balance_cents"] = balance["paid_cents"] - balance["share_cents"]

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

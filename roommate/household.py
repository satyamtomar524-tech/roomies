"""Validate a flat's possessions and food list separately from its room plan."""

from __future__ import annotations

from datetime import date
import re
from typing import Any

from .expenses import summarize_expenses, validate_expense
from .geometry import ValidationError


FLAT_FIELDS = {"name", "is_demo", "members", "inventory", "fridge", "expenses"}
INVENTORY_FIELDS = {"id", "name", "category", "location", "spot", "owner_id", "quantity", "notes"}
FRIDGE_FIELDS = {"id", "name", "quantity", "storage", "owner_id", "status", "best_before", "notes"}


def _object(value: Any, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be an object.")
    if set(value) - fields:
        raise ValidationError(f"Unknown {label.lower()} fields: {', '.join(sorted(set(value) - fields))}.")
    return value


def _text(value: Any, label: str, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValidationError(f"{label} must be text of at most {maximum} characters.")
    result = value.strip()
    if required and not result:
        raise ValidationError(f"{label} cannot be empty.")
    return result


def _id(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value) is None:
        raise ValidationError(f"{label} must use 1 to 64 letters, numbers, underscores or hyphens.")
    return value


def _list(value: Any, label: str, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValidationError(f"{label} must be a list of at most {maximum} entries.")
    return value


def _owner(value: Any, identities: set[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in identities:
        raise ValidationError("Choose an existing member as the owner, or Shared.")
    return value


def _choice(value: Any, label: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValidationError(f"{label} must be one of: {', '.join(choices)}.")
    return value


def _best_before(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is None:
        raise ValidationError("Best-before date must be YYYY-MM-DD or empty.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValidationError("Best-before date must be a real calendar date.") from error


def default_flat() -> dict:
    """An empty starter, with no invented possessions, groceries or debts."""
    return {"name": "My flat", "is_demo": True, "members": [{"id": "me", "name": "Me"}], "inventory": [], "fridge": [], "expenses": []}


def validate_flat(data: Any) -> dict:
    """Return normalized data without mutating inputs or dropping unknown fields."""
    data = _object(data, FLAT_FIELDS, "Flat")
    is_demo = data.get("is_demo", False)
    if not isinstance(is_demo, bool):
        raise ValidationError("The flat's sample flag must be true or false.")
    result = {
        "name": _text(data.get("name", "My flat"), "Flat name", 120, True),
        "is_demo": is_demo, "members": [], "inventory": [], "fridge": [], "expenses": [],
    }
    members = _list(data.get("members", []), "Members", 20)
    if not members:
        raise ValidationError("The flat needs at least one member.")
    identities = set()
    for entry in members:
        entry = _object(entry, {"id", "name"}, "Member")
        identity = _id(entry.get("id"), "Member ID")
        if identity in identities:
            raise ValidationError("Member IDs must be unique.")
        identities.add(identity)
        result["members"].append({"id": identity, "name": _text(entry.get("name"), "Member name", 80, True)})

    for field, allowed, maximum in (("inventory", INVENTORY_FIELDS, 500), ("fridge", FRIDGE_FIELDS, 300)):
        seen = set()
        for entry in _list(data.get(field, []), field.capitalize(), maximum):
            entry = _object(entry, allowed, field.capitalize() + " item")
            identity = _id(entry.get("id"), "Item ID")
            if identity in seen:
                raise ValidationError(f"{field.capitalize()} item IDs must be unique.")
            seen.add(identity)
            item = {"id": identity, "name": _text(entry.get("name"), "Item name", 120, True),
                    "owner_id": _owner(entry.get("owner_id"), identities),
                    "notes": _text(entry.get("notes", ""), "Item notes", 1000)}
            if field == "inventory":
                quantity = entry.get("quantity", 1)
                if isinstance(quantity, bool) or not isinstance(quantity, int) or not 1 <= quantity <= 100000:
                    raise ValidationError("Inventory quantity must be a whole number between 1 and 100000.")
                item.update(category=_text(entry.get("category", "other"), "Category", 50, True),
                            location=_text(entry.get("location", "Unsorted"), "Location", 100, True),
                            spot=_text(entry.get("spot", ""), "Exact spot", 200), quantity=quantity)
            else:
                item.update(quantity=_text(entry.get("quantity", ""), "Food quantity", 80),
                            storage=_choice(entry.get("storage", "fridge"), "Food storage", ("fridge", "freezer", "pantry")),
                            status=_choice(entry.get("status", "stocked"), "Food status", ("stocked", "low", "out")),
                            best_before=_best_before(entry.get("best_before")))
            result[field].append(item)

    seen = set()
    for entry in _list(data.get("expenses", []), "Expenses", 500):
        expense = validate_expense(entry, result["members"])
        if expense["id"] in seen:
            raise ValidationError("Expense IDs must be unique.")
        seen.add(expense["id"])
        result["expenses"].append(expense)
    return result


def summarize_flat(flat: dict) -> dict:
    """Counts and a separate expense calculation; no inferred food-safety advice."""
    flat = validate_flat(flat)
    locations = sorted({item["location"] for item in flat["inventory"]}, key=str.casefold)
    return {
        "inventory_count": len(flat["inventory"]),
        "inventory_quantity": sum(item["quantity"] for item in flat["inventory"]),
        "locations": locations,
        "fridge_count": len(flat["fridge"]),
        "fridge_counts": {status: sum(item["status"] == status for item in flat["fridge"]) for status in ("stocked", "low", "out")},
        "expenses": summarize_expenses(flat["expenses"], flat["members"]),
    }

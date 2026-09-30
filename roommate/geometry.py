"""Room measurements, placement checks and a small suggestion search.

Coordinates and dimensions use centimetres. The origin is the top-left corner
of the plan (north-west); x goes right and y goes down. This module does not
change its input, and it does not claim architectural or accessibility approval.
"""

from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any


class ValidationError(ValueError):
    """Input cannot be represented safely in a room plan."""


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} must be a number.")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValidationError(f"{name} must be between {low:g} and {high:g}.")
    return round(float(value), 3)


def _text(value: Any, name: str, maximum: int = 1000) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ValidationError(f"{name} must be text of at most {maximum} characters.")
    return value.strip()


def _choice(value: Any, name: str, choices: tuple) -> Any:
    if value not in choices or isinstance(value, bool):
        raise ValidationError(f"{name} must be one of: {', '.join(map(str, choices))}.")
    return value


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValidationError(f"{name} must be true or false.")
    return value


def _color(value: Any, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", value) is None:
        raise ValidationError(f"{name} must be a six-digit hex color such as #a4b497.")
    return value.lower()


def _known(data: dict, allowed: set, name: str) -> None:
    extra = set(data) - allowed
    if extra:
        raise ValidationError(f"Unknown {name} fields: {', '.join(sorted(extra))}.")


ROOM_FIELDS = set("id name width_cm depth_cm height_cm budget_eur style wall_color floor_color notes is_demo openings items".split())
ITEM_FIELDS = set("id name category width_cm depth_cm height_cm x_cm y_cm rotation status placement parent_id color locked clearance_cm target_eur notes".split())
OPENING_FIELDS = set("id kind wall offset_cm width_cm depth_cm swing".split())


def validate_room(data: Any) -> dict:
    """Return a normalized room; geometric mistakes remain editable warnings.

    Unknown fields, duplicate identities and malformed values are rejected.
    Furniture outside the room or overlapping is kept so the UI can explain it.
    """
    if not isinstance(data, dict):
        raise ValidationError("The room must be an object.")
    _known(data, ROOM_FIELDS, "room")
    room = {
        "id": _text(data.get("id", "room"), "Room ID", 100),
        "name": _text(data.get("name", "My room"), "Room name", 120),
        "width_cm": _number(data.get("width_cm"), "Room width", 30, 10000),
        "depth_cm": _number(data.get("depth_cm"), "Room depth", 30, 10000),
        "height_cm": _number(data.get("height_cm", 250), "Room height", 100, 1000),
        "budget_eur": _number(data.get("budget_eur", 0), "Budget", 0, 1000000),
        "style": _text(data.get("style", ""), "Style", 120),
        "wall_color": _color(data.get("wall_color", "#a4b497"), "Wall color"),
        "floor_color": _color(data.get("floor_color", "#f4f6ed"), "Floor color"),
        "notes": _text(data.get("notes", ""), "Room notes", 4000),
        "is_demo": _boolean(data.get("is_demo", False), "Demo flag"),
        "openings": [],
        "items": [],
    }
    if not room["id"] or not room["name"]:
        raise ValidationError("Room ID and name cannot be empty.")
    for field, maximum in (("openings", 40), ("items", 100)):
        values = data.get(field, [])
        if not isinstance(values, list) or len(values) > maximum:
            raise ValidationError(f"{field} must be a list of at most {maximum} entries.")
        identities = set()
        for entry in values:
            if not isinstance(entry, dict):
                raise ValidationError(f"Each {field} entry must be an object.")
            _known(entry, OPENING_FIELDS if field == "openings" else ITEM_FIELDS, field)
            identity = _text(entry.get("id"), f"{field} ID", 100)
            if not identity or identity in identities:
                raise ValidationError(f"{field} IDs must be nonempty and unique.")
            identities.add(identity)
            if field == "openings":
                kind = _choice(entry.get("kind"), "Opening kind", ("door", "window", "obstacle"))
                value = {
                    "id": identity,
                    "kind": kind,
                    "wall": _choice(entry.get("wall"), "Wall", ("north", "east", "south", "west")),
                    "offset_cm": _number(entry.get("offset_cm", 0), "Wall offset", 0, 10000),
                    "width_cm": _number(entry.get("width_cm"), "Opening width", 0.1, 10000),
                    "depth_cm": _number(entry.get("depth_cm", entry.get("width_cm") if kind == "door" else 0), "Opening depth", 0, 10000),
                    "swing": _choice(entry.get("swing", "in" if kind == "door" else "none"), "Door swing", ("in", "out", "none")),
                }
                if kind != "door" and value["swing"] != "none":
                    raise ValidationError("Only doors can have a swing direction.")
                if kind == "obstacle" and value["depth_cm"] == 0:
                    raise ValidationError("A fixed obstacle needs a positive depth.")
                if kind == "door" and value["swing"] == "in" and value["depth_cm"] == 0:
                    raise ValidationError("An inward door needs a positive clearance depth.")
            else:
                parent = entry.get("parent_id")
                if parent is not None:
                    parent = _text(parent, "Parent ID", 100)
                value = {
                    "id": identity,
                    "name": _text(entry.get("name"), "Item name", 120),
                    "category": _text(entry.get("category", "other"), "Category", 60),
                    "width_cm": _number(entry.get("width_cm"), "Item width", 0.1, 10000),
                    "depth_cm": _number(entry.get("depth_cm"), "Item depth", 0.1, 10000),
                    "height_cm": _number(entry.get("height_cm", 0), "Item height", 0, 10000),
                    "x_cm": _number(entry.get("x_cm", 0), "X position", -10000, 20000),
                    "y_cm": _number(entry.get("y_cm", 0), "Y position", -10000, 20000),
                    "rotation": _choice(entry.get("rotation", 0), "Rotation", (0, 90)),
                    "status": _choice(entry.get("status", "owned"), "Item status", ("owned", "planned")),
                    "placement": _choice(entry.get("placement", "floor"), "Placement", ("floor", "surface", "wall", "overlay")),
                    "parent_id": parent,
                    "color": _text(entry.get("color", "#d8b99b"), "Color", 40),
                    "locked": _boolean(entry.get("locked", False), "Locked flag"),
                    "clearance_cm": _number(entry.get("clearance_cm", 0), "Preferred clearance", 0, 300),
                    "target_eur": _number(entry.get("target_eur", 0), "Target price", 0, 1000000),
                    "notes": _text(entry.get("notes", ""), "Item notes", 2000),
                }
                if not value["name"]:
                    raise ValidationError("Item names cannot be empty.")
                if value["placement"] != "surface" and parent is not None:
                    raise ValidationError("Only surface items can have a parent item.")
            room[field].append(value)
    return room


def footprint(item: dict) -> tuple[float, float, float, float]:
    width, depth = item["width_cm"], item["depth_cm"]
    if item["rotation"] == 90:
        width, depth = depth, width
    return item["x_cm"], item["y_cm"], width, depth


def opening_rectangle(room: dict, opening: dict) -> tuple:
    width, depth = opening["width_cm"], opening["depth_cm"]
    offset, wall = opening["offset_cm"], opening["wall"]
    if wall == "north":
        return offset, 0, width, depth
    if wall == "south":
        return offset, room["depth_cm"] - depth, width, depth
    if wall == "east":
        return room["width_cm"] - depth, offset, depth, width
    return 0, offset, depth, width


def _intersects(first: tuple, second: tuple) -> bool:
    x, y, width, depth = first
    a, b, other_width, other_depth = second
    # Touching edges have no area; a tiny tolerance avoids float rounding noise.
    return min(x + width, a + other_width) - max(x, a) > 1e-6 and min(y + depth, b + other_depth) - max(y, b) > 1e-6


def _within(rectangle: tuple, width: float, depth: float) -> bool:
    x, y, item_width, item_depth = rectangle
    return x >= -1e-6 and y >= -1e-6 and x + item_width <= width + 1e-6 and y + item_depth <= depth + 1e-6


def _issue(severity: str, code: str, item_id: str | None, message: str) -> dict:
    return {"severity": severity, "code": code, "item_id": item_id, "message": message}


def _placement_issues(room: dict, item: dict) -> list[dict]:
    issues = []
    identity, name = item["id"], item["name"]
    rectangle = footprint(item)
    if item["placement"] == "surface":
        parent = next((candidate for candidate in room["items"] if candidate["id"] == item["parent_id"]), None)
        if parent is None or parent["id"] == identity or parent["placement"] != "floor":
            return [_issue("error", "surface_parent", identity, f"{name} needs an existing floor item as its surface.")]
        _, _, parent_width, parent_depth = footprint(parent)
        if parent["height_cm"] + item["height_cm"] > room["height_cm"]:
            issues.append(_issue("error", "too_tall", identity, f"{name} on {parent['name']} would extend above the room height."))
        if not _within(rectangle, parent_width, parent_depth):
            issues.append(_issue("error", "surface_bounds", identity, f"{name} extends beyond the surface of {parent['name']}."))
        for other in room["items"]:
            if other["id"] != identity and other["placement"] == "surface" and other["parent_id"] == parent["id"] and _intersects(rectangle, footprint(other)):
                issues.append(_issue("error", "surface_overlap", identity, f"{name} overlaps {other['name']} on {parent['name']}."))
        return issues
    if not _within(rectangle, room["width_cm"], room["depth_cm"]):
        issues.append(_issue("error", "out_of_bounds", identity, f"{name} extends beyond the room boundary."))
    if item["height_cm"] > room["height_cm"]:
        issues.append(_issue("error", "too_tall", identity, f"{name} is taller than the room height."))
    if item["placement"] != "floor":
        return issues
    for other in room["items"]:
        if other["id"] == identity or other["placement"] != "floor":
            continue
        other_rectangle = footprint(other)
        if _intersects(rectangle, other_rectangle):
            issues.append(_issue("error", "overlap", identity, f"{name} overlaps {other['name']}."))
        else:
            gap = max(item["clearance_cm"], other["clearance_cm"])
            x, y, width, depth = rectangle
            if gap and _intersects((x - gap, y - gap, width + gap * 2, depth + gap * 2), other_rectangle):
                issues.append(_issue("warning", "preferred_clearance", identity, f"{name} and {other['name']} have less than {gap:g} cm of preferred clearance."))
    for opening in room["openings"]:
        if opening["kind"] == "obstacle" and _intersects(rectangle, opening_rectangle(room, opening)):
            issues.append(_issue("error", "fixed_obstacle", identity, f"{name} overlaps a fixed obstacle."))
        elif opening["kind"] == "door" and opening["swing"] == "in" and _intersects(rectangle, opening_rectangle(room, opening)):
            issues.append(_issue("error", "door_clearance", identity, f"{name} enters the conservative clearance rectangle for an inward door."))
    return issues


def _union_area(rectangles: list[tuple], room_width: float, room_depth: float) -> float:
    """Sweep clipped rectangles so overlaps never inflate the occupied area."""
    clipped = []
    for x, y, width, depth in rectangles:
        left, right = max(0, x), min(room_width, x + width)
        top, bottom = max(0, y), min(room_depth, y + depth)
        if right > left and bottom > top:
            clipped.append((left, top, right, bottom))
    xs = sorted({value for rect in clipped for value in (rect[0], rect[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((top, bottom) for x, top, end, bottom in clipped if x < right and end > left)
        covered = 0.0
        if intervals:
            start, finish = intervals[0]
            for top, bottom in intervals[1:]:
                if top > finish:
                    covered += finish - start
                    start, finish = top, bottom
                else:
                    finish = max(finish, bottom)
            covered += finish - start
        area += (right - left) * covered
    return area


def analyse_room(room: dict) -> dict:
    room = validate_room(room)
    issues = []
    for opening in room["openings"]:
        length = room["width_cm"] if opening["wall"] in ("north", "south") else room["depth_cm"]
        if opening["offset_cm"] + opening["width_cm"] > length + 1e-6:
            issues.append(_issue("error", "opening_bounds", None, f"The {opening['kind']} on the {opening['wall']} wall extends beyond that wall."))
        if opening["kind"] == "obstacle" and not _within(opening_rectangle(room, opening), room["width_cm"], room["depth_cm"]):
            issues.append(_issue("error", "obstacle_bounds", None, "A fixed obstacle extends beyond the room boundary."))
    for item in room["items"]:
        issues.extend(_placement_issues(room, item))
    obstacles = [opening_rectangle(room, opening) for opening in room["openings"] if opening["kind"] == "obstacle"]
    owned = obstacles + [footprint(item) for item in room["items"] if item["placement"] == "floor" and item["status"] == "owned"]
    all_floor = owned + [footprint(item) for item in room["items"] if item["placement"] == "floor" and item["status"] == "planned"]
    width, depth = room["width_cm"], room["depth_cm"]
    area = width * depth
    occupied = _union_area(owned, width, depth)
    used = _union_area(all_floor, width, depth)
    return {
        "valid": not any(issue["severity"] == "error" for issue in issues),
        "issues": issues,
        "area_m2": round(area / 10000, 4),
        "occupied_m2": round(occupied / 10000, 4),
        "reserved_m2": round((used - occupied) / 10000, 4),
        "free_m2": round((area - used) / 10000, 4),
    }


def find_positions(room: dict, item_id: str) -> list[dict]:
    """Find up to five useful placements; this is a heuristic, not an optimum."""
    room = validate_room(room)
    original = next((item for item in room["items"] if item["id"] == item_id), None)
    if original is None:
        raise ValidationError("That item does not exist.")
    if original["locked"]:
        raise ValidationError("Unlock the item before requesting another position.")
    width, depth = room["width_cm"], room["depth_cm"]
    if original["placement"] == "surface":
        parent = next((item for item in room["items"] if item["id"] == original["parent_id"] and item["placement"] == "floor"), None)
        if parent is None:
            return []
        _, _, width, depth = footprint(parent)
    candidates = []
    for rotation in (0, 90):
        item = deepcopy(original)
        item["rotation"] = rotation
        _, _, item_width, item_depth = footprint(item)
        if item_width > width or item_depth > depth or item["height_cm"] > room["height_cm"]:
            continue
        step = max(25.0, max(width, depth) / 40)
        xs = {0.0, width - item_width}
        ys = {0.0, depth - item_depth}
        xs.update(min(width - item_width, value * step) for value in range(int((width - item_width) / step) + 1))
        ys.update(min(depth - item_depth, value * step) for value in range(int((depth - item_depth) / step) + 1))
        for other in room["items"]:
            if other["id"] == item_id or other["placement"] != item["placement"]:
                continue
            if item["placement"] == "surface" and other["parent_id"] != item["parent_id"]:
                continue
            x, y, other_width, other_depth = footprint(other)
            gap = max(item["clearance_cm"], other["clearance_cm"])
            xs.update((x - item_width - gap, x + other_width + gap))
            ys.update((y - item_depth - gap, y + other_depth + gap))
        for x in sorted(value for value in xs if 0 <= value <= width - item_width):
            for y in sorted(value for value in ys if 0 <= value <= depth - item_depth):
                item["x_cm"], item["y_cm"] = x, y
                problems = _placement_issues(room, item)
                children = [child for child in room["items"] if child["placement"] == "surface" and child["parent_id"] == item_id]
                if children:
                    # A desk rotation changes its usable surface. Suggesting it
                    # is only useful if its reserved objects still fit there.
                    candidate_room = {**room, "items": [item if other["id"] == item_id else other for other in room["items"]]}
                    for child in children:
                        problems.extend(_placement_issues(candidate_room, child))
                if any(problem["severity"] == "error" for problem in problems):
                    continue
                wall_distance = min(x, y, width - x - item_width, depth - y - item_depth)
                warnings = len(problems)
                score = max(0, round(100 - 20 * wall_distance / max(width, depth) - 15 * warnings, 1))
                candidates.append({
                    "x_cm": round(x, 3), "y_cm": round(y, 3), "rotation": rotation,
                    "score": score,
                    "reason": "Fits the measured bounds and avoids furniture, obstacles and inward-door rectangles." + (" Preferred clearance needs review." if warnings else " Keeps your preferred furniture clearance."),
                })
    candidates.sort(key=lambda value: (-value["score"], value["rotation"], value["y_cm"], value["x_cm"]))
    result = []
    for candidate in candidates:
        if all(candidate["rotation"] != existing["rotation"] or math.hypot(candidate["x_cm"] - existing["x_cm"], candidate["y_cm"] - existing["y_cm"]) >= 25 for existing in result):
            result.append(candidate)
        if len(result) == 5:
            break
    return result

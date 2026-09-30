"""SQLite storage for a local flat, room, wishlist and price history."""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import csv
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sqlite3
import uuid

from .geometry import ValidationError, analyse_room, validate_room
from .household import default_flat, summarize_flat, validate_flat
from .expenses import expense_shares
from .pricing import evaluate_product, product_signature, validate_observation, validate_product


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def demo_room() -> dict:
    """Illustrative measurements, deliberately separate from the user's room."""
    def item(identity, name, width, depth, height, x, y, **extra):
        return {
            "id": identity, "name": name, "category": identity,
            "width_cm": width, "depth_cm": depth, "height_cm": height,
            "x_cm": x, "y_cm": y, "rotation": 0, "status": "owned",
            "placement": "floor", "parent_id": None, "color": "#c8ab91",
            "locked": False, "clearance_cm": 0, "target_eur": 0,
            "notes": "Illustrative sample dimensions; replace with full external measurements.",
            **extra,
        }
    return validate_room({
        "id": "sample-room", "name": "A small room, a fresh start",
        "width_cm": 300, "depth_cm": 350, "height_cm": 250,
        "budget_eur": 300, "style": "Warm and simple", "is_demo": True,
        "notes": "Sample room: 10.5 m². These are made-up measurements, not a map of your actual room.",
        "openings": [
            {"id": "door", "kind": "door", "wall": "north", "offset_cm": 15, "width_cm": 80, "depth_cm": 80, "swing": "in"},
            {"id": "window", "kind": "window", "wall": "east", "offset_cm": 140, "width_cm": 100, "depth_cm": 0, "swing": "none"},
        ],
        "items": [
            item("bed", "Bed", 120, 200, 50, 0, 125, color="#b7c5bd"),
            item("wardrobe", "Wardrobe", 80, 50, 200, 215, 0),
            item("desk", "Future desk", 110, 55, 75, 185, 285, status="planned", target_eur=100, color="#d2aa77"),
            item("lamp", "Future desk lamp", 20, 20, 35, 85, 5, status="planned", placement="surface", parent_id="desk", target_eur=25, color="#d7b962"),
        ],
    })


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS room (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS flat (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS products (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL,
                    last_checked_at TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    data TEXT NOT NULL, sequence INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS observations_product ON observations(product_id, sequence);
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                    observation_id TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL,
                    read INTEGER NOT NULL DEFAULT 0, type TEXT NOT NULL DEFAULT 'target_ready',
                    UNIQUE(product_id, observation_id)
                );
            """)
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(notifications)")}
            if "type" not in columns:
                connection.execute("ALTER TABLE notifications ADD COLUMN type TEXT NOT NULL DEFAULT 'target_ready'")
            if connection.execute("SELECT 1 FROM room WHERE id=1").fetchone() is None:
                connection.execute("INSERT INTO room VALUES (1, ?)", (json.dumps(demo_room()),))
            if connection.execute("SELECT 1 FROM flat WHERE id=1").fetchone() is None:
                connection.execute("INSERT INTO flat VALUES (1, ?)", (json.dumps(default_flat()),))

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _room(connection) -> dict:
        return validate_room(json.loads(connection.execute("SELECT data FROM room WHERE id=1").fetchone()["data"]))

    @staticmethod
    def _flat(connection) -> dict:
        return validate_flat(json.loads(connection.execute("SELECT data FROM flat WHERE id=1").fetchone()["data"]))

    @staticmethod
    def _observations(connection, product_id: str) -> list[dict]:
        records = []
        for row in connection.execute("SELECT * FROM observations WHERE product_id=?", (product_id,)):
            observation = json.loads(row["data"])
            records.append((datetime.fromisoformat(observation["observed_at"]), row["sequence"], {**observation, "id": row["id"], "product_id": product_id}))
        records.sort(key=lambda value: (value[0], value[1]), reverse=True)
        return [value[2] for value in records]

    @staticmethod
    def _products(connection, room) -> list[dict]:
        products = []
        for row in connection.execute("SELECT * FROM products ORDER BY rowid"):
            product = json.loads(row["data"])
            observations = Storage._observations(connection, row["id"])
            latest = observations[0] if observations else None
            evaluation = evaluate_product(room, product, latest)
            if row["error"]:
                evaluation["eligible"] = False
                evaluation["can_price_drop_notice"] = False
                evaluation["reasons"].append("The latest live check failed. Add a fresh manual quote or retry before treating this as a current match.")
            product.update({
                "observations": observations,
                "latest_observation": latest,
                "evaluation": evaluation,
                "last_checked_at": row["last_checked_at"],
                "error": row["error"],
            })
            products.append(product)
        return products

    def state(self) -> dict:
        with self._connect() as connection:
            room = self._room(connection)
            flat = self._flat(connection)
            products = self._products(connection, room)
            notifications = [dict(row) for row in connection.execute("SELECT id,product_id,message,created_at,read,type FROM (SELECT rowid AS sequence,id,product_id,message,created_at,read,type FROM notifications ORDER BY created_at DESC,rowid DESC LIMIT 200) ORDER BY created_at ASC,sequence ASC")]
            for notification in notifications:
                notification["read"] = bool(notification["read"])
        return {
            "room": room, "products": products, "notifications": notifications,
            "flat": flat, "flat_summary": summarize_flat(flat),
            "summary": analyse_room(room),
            "tracker": {
                "mode": "manual", "background_running": False,
                "description": "Prices update when you add a quote or press Check price. No background service is running.",
                "currency": "EUR", "max_quote_age_hours": 24,
            },
        }

    def save_room(self, data: dict) -> dict:
        room = validate_room(data)
        with self._connect() as connection:
            connection.execute("UPDATE room SET data=? WHERE id=1", (json.dumps(room),))
        return room

    def save_flat(self, data: dict) -> dict:
        flat = validate_flat(data)
        with self._connect() as connection:
            connection.execute("UPDATE flat SET data=? WHERE id=1", (json.dumps(flat),))
        return flat

    def save_product(self, data: dict) -> dict:
        with self._connect() as connection:
            room = self._room(connection)
            payload = deepcopy(data)
            payload.setdefault("id", uuid.uuid4().hex)
            product = validate_product(payload, room)
            if not product.get("id"):
                product["id"] = payload["id"]
            existing = connection.execute("SELECT data FROM products WHERE id=?", (product["id"],)).fetchone()
            previous = json.loads(existing["data"]) if existing else None
            connection.execute("INSERT INTO products(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (product["id"], json.dumps(product)))
            # A user-entered quote is useful immediately, with explicitly entered shipping.
            quote_changed = previous is None or any(product.get(field) != previous.get(field) for field in ("price_eur", "shipping_eur", "availability"))
            if product.get("price_eur") is not None and quote_changed:
                observation = validate_observation({
                    "price_eur": product["price_eur"], "shipping_eur": product.get("shipping_eur"),
                    "availability": product.get("availability", "unknown"), "source": "manual",
                    "source_url": product.get("url", ""), "observed_at": timestamp(),
                    "note": "Quote entered with the product.",
                    "variant_confirmed": product.get("variant_confirmed", False),
                    "product_signature": product_signature(product),
                    "requested_product_url": product.get("url", ""),
                })
                self._insert_observation(connection, room, product, observation)
                connection.execute("UPDATE products SET last_checked_at=?,error=NULL WHERE id=?", (observation["observed_at"], product["id"]))
        return self.product(product["id"])

    def product(self, identity: str) -> dict:
        for product in self.state()["products"]:
            if product["id"] == identity:
                return product
        raise KeyError("That product does not exist.")

    def delete_product(self, identity: str) -> None:
        with self._connect() as connection:
            if not connection.execute("DELETE FROM products WHERE id=?", (identity,)).rowcount:
                raise KeyError("That product does not exist.")

    @staticmethod
    def _insert_observation(connection, room, product, observation, notify=True) -> dict:
        observations = Storage._observations(connection, product["id"])
        previous = evaluate_product(room, product, observations[0]) if observations else None
        sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0)+1 AS value FROM observations").fetchone()["value"]
        identity = uuid.uuid4().hex
        connection.execute("INSERT INTO observations VALUES (?,?,?,?)", (identity, product["id"], json.dumps(observation), sequence))
        latest = Storage._observations(connection, product["id"])[0]
        current = evaluate_product(room, product, latest)
        changed = previous is None or not previous.get("eligible") or previous.get("delivered_eur") != current.get("delivered_eur")
        notification_type, message = None, None
        if current.get("eligible") and changed:
            notification_type = "target_ready"
            message = f"{product['name']} fits its reserved dimensions and meets its target at €{current['delivered_eur']:.2f} delivered. Review the current quote before buying."
        elif current.get("can_price_drop_notice"):
            signature = product_signature(product)
            baseline = next((previous_quote for previous_quote in observations if previous_quote.get("product_signature") == signature and previous_quote.get("source") != "demo"), None)
            if baseline is not None and latest["price_eur"] < baseline["price_eur"]:
                notification_type = "price_drop_info"
                message = f"{product['name']}: item price fell from €{baseline['price_eur']:.2f} to €{latest['price_eur']:.2f}. Confirm delivery before deciding; this is not a delivered-price recommendation."
        if notify and latest["id"] == identity and product.get("monitor") and notification_type:
            connection.execute("INSERT INTO notifications(id,product_id,observation_id,message,created_at,read,type) VALUES (?,?,?,?,?,0,?)", (uuid.uuid4().hex, product["id"], identity, message, timestamp(), notification_type))
        return {**observation, "id": identity, "product_id": product["id"]}

    def add_observation(self, product_id: str, data: dict) -> dict:
        with self._connect() as connection:
            row = connection.execute("SELECT data FROM products WHERE id=?", (product_id,)).fetchone()
            if row is None:
                raise KeyError("That product does not exist.")
            product = json.loads(row["data"])
            payload = deepcopy(data)
            payload["product_signature"] = product_signature(product)
            observation = validate_observation(payload)
            recorded = self._insert_observation(connection, self._room(connection), product, observation)
            if self._observations(connection, product_id)[0]["id"] == recorded["id"]:
                connection.execute("UPDATE products SET last_checked_at=?,error=NULL WHERE id=?", (observation["observed_at"], product_id))
        return recorded

    def record_check_error(self, product_id: str, message: str) -> None:
        with self._connect() as connection:
            if not connection.execute("UPDATE products SET last_checked_at=?,error=? WHERE id=?", (timestamp(), str(message)[:1000], product_id)).rowcount:
                raise KeyError("That product does not exist.")

    def mark_notification(self, identity: str) -> None:
        with self._connect() as connection:
            if not connection.execute("UPDATE notifications SET read=1 WHERE id=?", (identity,)).rowcount:
                raise KeyError("That notification does not exist.")

    def export(self) -> dict:
        state = self.state()
        products = []
        dynamic = {"observations", "latest_observation", "evaluation", "last_checked_at", "error"}
        for product in state["products"]:
            plain = {key: value for key, value in product.items() if key not in dynamic}
            plain["observations"] = [{key: value for key, value in observation.items() if key not in ("id", "product_id")} for observation in reversed(product["observations"])]
            products.append(plain)
        return {"schema_version": 2, "room": state["room"], "products": products, "flat": state["flat"]}

    def export_csv(self) -> str:
        output = io.StringIO(newline="")
        fields = ["product_id", "name", "item_id", "url", "variant", "observed_at", "price_eur", "shipping_eur", "availability", "source", "note"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for product in self.state()["products"]:
            for observation in reversed(product["observations"]):
                row = {
                    "product_id": product["id"], "name": product["name"], "item_id": product.get("item_id"),
                    "url": product.get("url"), "variant": product.get("variant"),
                    **{field: observation.get(field) for field in fields if field in observation},
                }
                # Spreadsheet applications can interpret cells beginning with these characters as formulas.
                for key, value in row.items():
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                        row[key] = "'" + value
                writer.writerow(row)
        return output.getvalue()

    def import_data(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValidationError("The backup must be an object.")
        version = payload.get("schema_version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version not in (1, 2):
            raise ValidationError("This export version is not supported.")
        allowed_fields = {"schema_version", "room", "products"} | ({"flat"} if version == 2 else set())
        if set(payload) - allowed_fields:
            raise ValidationError("The backup contains unknown fields for its version.")
        if version == 2 and "flat" not in payload:
            raise ValidationError("A version 2 backup must include the flat.")
        flat = validate_flat(payload["flat"]) if version == 2 else None
        room = validate_room(payload.get("room"))
        entries = payload.get("products", [])
        if not isinstance(entries, list) or len(entries) > 100:
            raise ValidationError("Import supports at most 100 wishlist products.")
        prepared = []
        identities = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValidationError("Imported products must be objects.")
            product_data = deepcopy(entry)
            allowed = {"id", "name", "url", "item_id", "width_cm", "depth_cm", "height_cm", "rotation_allow90", "variant", "sku", "color", "retailer", "identity_notes", "variant_confirmed", "price_eur", "shipping_eur", "target_eur", "availability", "monitor", "is_demo", "observations"}
            if set(product_data) - allowed:
                raise ValidationError("An imported product contains unknown fields.")
            observations = product_data.pop("observations", [])
            product_data.setdefault("id", uuid.uuid4().hex)
            product = validate_product(product_data, room)
            identity = product.get("id") or product_data["id"]
            if identity in identities:
                raise ValidationError("Imported product IDs must be unique.")
            product["id"] = identity
            identities.add(identity)
            if not isinstance(observations, list) or len(observations) > 1000:
                raise ValidationError("Each product supports at most 1000 imported observations.")
            allowed_observation = {"price_eur", "shipping_eur", "availability", "source", "source_url", "observed_at", "note", "notes", "currency", "variant_confirmed", "is_demo", "product_name", "sku", "color", "product_signature", "requested_product_url"}
            if any(not isinstance(observation, dict) or set(observation) - allowed_observation for observation in observations):
                raise ValidationError("An imported observation contains unknown fields.")
            prepared.append((product, [validate_observation(observation) for observation in observations]))
        # Validate everything before this transaction so a failed import cannot erase a room.
        with self._connect() as connection:
            connection.execute("DELETE FROM products")
            connection.execute("UPDATE room SET data=? WHERE id=1", (json.dumps(room),))
            if flat is not None:
                connection.execute("UPDATE flat SET data=? WHERE id=1", (json.dumps(flat),))
            for product, observations in prepared:
                connection.execute("INSERT INTO products(id,data) VALUES(?,?)", (product["id"], json.dumps(product)))
                for observation in observations:
                    self._insert_observation(connection, room, product, observation, notify=False)
        return self.state()

    def reset(self) -> dict:
        return self.import_data({"room": demo_room(), "products": []})

    def export_expenses_csv(self) -> str:
        """One row per participant's share; expense totals repeat on its rows."""
        flat = self.state()["flat"]
        names = {member["id"]: member["name"] for member in flat["members"]}
        output = io.StringIO(newline="")
        fields = ["expense_id", "title", "date", "category", "amount_cents", "paid_by", "payer_name", "participant_id", "participant_name", "share_cents", "notes"]
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for expense in flat["expenses"]:
            for participant, share in expense_shares(expense).items():
                row = {key: expense[key] for key in ("title", "date", "category", "amount_cents", "paid_by", "notes")}
                row.update(expense_id=expense["id"], payer_name=names[expense["paid_by"]], participant_id=participant,
                           participant_name=names[participant], share_cents=share)
                for key, value in row.items():
                    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                        row[key] = "'" + value
                writer.writerow(row)
        return output.getvalue()

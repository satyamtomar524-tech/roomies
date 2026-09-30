"""Browser transport for the same rules and SQLite storage as the local app.

Pyodide runs this module in a worker. JavaScript persists the database in the
visitor's IndexedDB before acknowledging a write. There is no public write API.
"""

import json
from urllib.parse import parse_qs, unquote, urlsplit

from .geometry import analyse_room, find_positions
from .household import summarize_flat
from .storage import Storage


class BrowserWorkspace:
    def __init__(self, path):
        self.storage = Storage(path)

    def state(self, state=None):
        result = state if state is not None else self.storage.state()
        result["tracker"] = {
            "mode": "browser", "background_running": False,
            "description": "Open the shop link and record the price you see. Automatic price checks are available only in the downloaded local app.",
            "currency": "EUR", "max_quote_age_hours": 24,
        }
        return result

    def request(self, path, method="GET", body=None):
        parsed = urlsplit(path)
        route = parsed.path
        storage = self.storage
        payload = json.loads(body) if body else {}
        if not isinstance(payload, dict):
            raise ValueError("The request must be an object.")
        if method == "GET" and route == "/api/state":
            return self.state()
        if method == "GET" and route == "/api/export":
            format = parse_qs(parsed.query).get("format", ["json"])[0]
            exports = {
                "csv": (storage.export_csv, "roomies-price-history.csv"),
                "expenses": (storage.export_expenses_csv, "roomies-expense-shares.csv"),
                "repayments": (storage.export_repayments_csv, "roomies-repayments.csv"),
            }
            if format == "json":
                return {"text": json.dumps(storage.export(), indent=2, ensure_ascii=False),
                        "filename": "roomies-backup.json", "type": "application/json"}
            if format in exports:
                export, filename = exports[format]
                return {"text": "\ufeff" + export(), "filename": filename, "type": "text/csv;charset=utf-8"}
            raise ValueError("Unknown export format.")
        if method == "PUT" and route == "/api/room":
            room = storage.save_room(payload)
            return {"room": room, "summary": analyse_room(room)}
        if method == "PUT" and route == "/api/flat":
            flat = storage.save_flat(payload)
            return {"flat": flat, "flat_summary": summarize_flat(flat)}
        if method == "POST" and route == "/api/suggest":
            if set(payload) != {"item_id"} or not isinstance(payload["item_id"], str):
                raise ValueError("Provide the item_id to suggest a position.")
            return {"placements": find_positions(storage.state()["room"], payload["item_id"])}
        if method == "POST" and route == "/api/products":
            if not payload.get("id") and len(storage.state()["products"]) >= 100:
                raise ValueError("The wishlist supports at most 100 products.")
            return {"product": storage.save_product(payload)}
        parts = route.split("/")
        if route.startswith("/api/products/") and len(parts) in (4, 5):
            identity = unquote(parts[3])
            if method == "DELETE" and len(parts) == 4:
                storage.delete_product(identity)
                return {"deleted": identity}
            if method == "POST" and len(parts) == 5 and parts[4] == "observations":
                observation = storage.add_observation(identity, payload)
                return {"product": storage.product(identity), "observation": observation}
            if method == "POST" and len(parts) == 5 and parts[4] == "check":
                raise ValueError("Open the shop link and record the price. Automatic checks need the local app.")
        if method == "POST" and route == "/api/check-all":
            raise ValueError("Automatic checks need the local app. You can record prices here.")
        if method == "POST" and len(parts) == 5 and parts[1:3] == ["api", "notifications"] and parts[4] == "read":
            storage.mark_notification(unquote(parts[3]))
            return {"read": parts[3]}
        if method == "POST" and route == "/api/import":
            return self.state(storage.import_data(payload))
        if method == "POST" and route == "/api/reset":
            return self.state(storage.reset())
        raise ValueError("That action does not exist.")

    def dispatch(self, path, method="GET", body=None):
        try:
            return json.dumps({"data": self.request(path, method, body)}, ensure_ascii=False)
        except (ValueError, KeyError) as error:
            return json.dumps({"error": str(error)})

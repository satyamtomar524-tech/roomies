"""A loopback-only HTTP application with a deliberately small API."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .geometry import analyse_room, find_positions
from .household import summarize_flat
from .pricing import fetch_price
from .storage import MAX_BACKUP_BYTES, Storage


SOURCE_ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = SOURCE_ROOT / "web"
if not WEB_ROOT.exists():
    WEB_ROOT = Path(sys.prefix) / "share" / "roommate" / "web"

STATIC_FILES = {
    "/": "index.html", "/index.html": "index.html", "/guide": "guide.html",
    "/guide.html": "guide.html", "/style.css": "style.css", "/guide.css": "guide.css",
    "/app.js": "app.js", "/flat.js": "flat.js", "/costs.js": "costs.js",
}
MAX_BODY_BYTES = 2 * 1024 * 1024


def check_product(storage: Storage, identity: str, check_lock=None) -> dict:
    """Share one guarded check path between the UI and the local scheduler."""
    with check_lock if check_lock is not None else nullcontext():
        product = storage.product(identity)
        try:
            observation = fetch_price(product["url"])
            observation["requested_product_url"] = product["url"]
            recorded = storage.add_observation(identity, observation)
        except ValueError as error:
            storage.record_check_error(identity, str(error))
            raise
        return {"product": storage.product(identity), "observation": recorded}


class RoomMateServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], storage: Storage, web_root: Path | None = None):
        if address[0] not in ("127.0.0.1", "localhost"):
            raise ValueError("Roomies must bind to localhost.")
        self.storage = storage
        self.web_root = Path(web_root) if web_root else WEB_ROOT
        self.check_lock = threading.Lock()
        self.tracker = None
        super().__init__(address, RequestHandler)

    def state(self, state: dict | None = None) -> dict:
        state = state if state is not None else self.storage.state()
        if self.tracker is not None:
            state["tracker"] = self.tracker.status(state["products"])
        return state


class RequestHandler(BaseHTTPRequestHandler):
    server: RoomMateServer
    server_version = "Roomies/2.2"

    def log_message(self, format, *args):
        # Keep request bodies, room details and shopping URLs out of logs.
        return

    def _allowed_request(self) -> bool:
        port = self.server.server_port
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        allowed_origins = {f"http://{host}" for host in allowed_hosts}
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            self._json(403, {"error": "Only requests addressed to this local Roomies server are accepted."})
            return False
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0].lower() not in allowed_origins):
            self._json(403, {"error": "Cross-origin access to your room is blocked."})
            return False
        if self.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            self._json(403, {"error": "Cross-site access to your room is blocked."})
            return False
        return True

    def _reply(self, status: int, body: bytes, content_type: str, filename: str | None = None):
        if status >= 400 and not getattr(self, "_body_consumed", False):
            # Windows may reset a closed socket with unread request bytes before
            # its error response arrives. Drain only a small, bounded body.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length > 0:
                    self.connection.settimeout(.25)
                    self.rfile.read1(min(length, 4096))
            except (ValueError, OSError):
                pass
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict):
        self._reply(status, json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"), "application/json; charset=utf-8")

    def _body(self, maximum: int = MAX_BODY_BYTES) -> dict:
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("Send this request as application/json.")
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("Chunked request bodies are not supported.")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1:
            raise ValueError("A single Content-Length is required.")
        try:
            length = int(lengths[0])
        except ValueError as error:
            raise ValueError("Content-Length is invalid.") from error
        if not 0 < length <= maximum:
            raise ValueError(f"The request must contain JSON no larger than {maximum // (1024 * 1024)} MiB.")
        self.connection.settimeout(15)
        raw = self.rfile.read(length)
        self._body_consumed = True
        if len(raw) != length:
            raise ValueError("The request body was incomplete.")
        try:
            payload = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Invalid JSON number: {value}")))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("The request does not contain valid UTF-8 JSON.") from error
        if not isinstance(payload, dict):
            raise ValueError("The request body must be a JSON object.")
        return payload

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def _dispatch(self, method: str):
        if not self._allowed_request():
            return
        try:
            self._route(method)
        except KeyError as error:
            self._json(404, {"error": str(error).strip("'")})
        except (ValueError, TypeError) as error:
            self._json(400, {"error": str(error)})
        except (TimeoutError, ConnectionError):
            self._json(408, {"error": "The request timed out. Please try again."})
        except Exception:
            self._json(500, {"error": "Roomies could not complete this request. Your previously saved data is preserved."})

    def _check_product(self, identity: str) -> dict:
        return check_product(self.server.storage, identity, self.server.check_lock)

    def _route(self, method: str):
        parsed = urlsplit(self.path)
        path = parsed.path
        storage = self.server.storage
        if method == "GET" and path in STATIC_FILES:
            filename = STATIC_FILES[path]
            target = self.server.web_root / filename
            if not target.is_file():
                self._json(404, {"error": "This application file is unavailable."})
                return
            content_type = "text/html; charset=utf-8" if filename.endswith(".html") else "text/css; charset=utf-8" if filename.endswith(".css") else "text/javascript; charset=utf-8"
            self._reply(200, target.read_bytes(), content_type)
        elif method == "GET" and path == "/api/state":
            self._json(200, self.server.state())
        elif method == "GET" and path == "/api/export":
            format = parse_qs(parsed.query).get("format", ["json"])[0]
            if format == "csv":
                self._reply(200, storage.export_csv().encode("utf-8-sig"), "text/csv; charset=utf-8", "roomies-price-history.csv")
            elif format == "expenses":
                self._reply(200, storage.export_expenses_csv().encode("utf-8-sig"), "text/csv; charset=utf-8", "roomies-expense-shares.csv")
            elif format == "repayments":
                self._reply(200, storage.export_repayments_csv().encode("utf-8-sig"), "text/csv; charset=utf-8", "roomies-repayments.csv")
            elif format == "json":
                self._reply(200, json.dumps(storage.export(), indent=2, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", "roomies-backup.json")
            else:
                raise ValueError("Export format must be json, csv, expenses or repayments.")
        elif method == "PUT" and path == "/api/room":
            room = storage.save_room(self._body())
            self._json(200, {"room": room, "summary": analyse_room(room)})
        elif method == "PUT" and path == "/api/flat":
            flat = storage.save_flat(self._body())
            self._json(200, {"flat": flat, "flat_summary": summarize_flat(flat)})
        elif method == "POST" and path == "/api/suggest":
            payload = self._body()
            if set(payload) != {"item_id"} or not isinstance(payload["item_id"], str):
                raise ValueError("Provide the item_id to suggest a position.")
            self._json(200, {"placements": find_positions(storage.state()["room"], payload["item_id"])})
        elif method == "POST" and path == "/api/products":
            payload = self._body()
            if not payload.get("id") and len(storage.state()["products"]) >= 100:
                raise ValueError("The wishlist supports at most 100 products.")
            self._json(201, {"product": storage.save_product(payload)})
        elif path.startswith("/api/products/"):
            parts = path.split("/")
            identity = unquote(parts[3])
            if not identity:
                raise KeyError("That product does not exist.")
            if method == "DELETE" and len(parts) == 4:
                storage.delete_product(identity)
                self._json(200, {"deleted": identity})
            elif method == "POST" and len(parts) == 5 and parts[4] == "observations":
                observation = storage.add_observation(identity, self._body())
                self._json(201, {"product": storage.product(identity), "observation": observation})
            elif method == "POST" and len(parts) == 5 and parts[4] == "check":
                self._body()
                self._json(200, self._check_product(identity))
            else:
                self._json(404, {"error": "That endpoint does not exist."})
        elif method == "POST" and path == "/api/check-all":
            self._body()
            errors, checked = [], 0
            products = [product for product in storage.state()["products"] if product.get("monitor")]
            if len(products) > 20:
                raise ValueError("Check all supports up to 20 monitored products. Check other products individually.")
            for product in products:
                try:
                    self._check_product(product["id"])
                    checked += 1
                except ValueError as error:
                    errors.append({"product_id": product["id"], "message": str(error)})
            self._json(200, {"checked": checked, "errors": errors, "state": self.server.state()})
        elif method == "POST" and path.startswith("/api/notifications/") and path.endswith("/read"):
            parts = path.split("/")
            if len(parts) != 5:
                raise KeyError("That notification does not exist.")
            self._body()
            storage.mark_notification(unquote(parts[3]))
            self._json(200, {"read": parts[3]})
        elif method == "POST" and path == "/api/import":
            self._json(200, self.server.state(storage.import_data(self._body(MAX_BACKUP_BYTES))))
        elif method == "POST" and path == "/api/reset":
            self._body()
            self._json(200, self.server.state(storage.reset()))
        else:
            self._json(404, {"error": "That endpoint does not exist."})


def main():
    parser = argparse.ArgumentParser(description="Roomies: keep track of your flat, room and shared expenses.")
    parser.add_argument("--port", type=int, default=8840, help="Local HTTP port (default: 8840).")
    default_db = os.environ.get("ROOMMATE_DB") or str(Path.cwd() / "data" / "roommate.sqlite3")
    parser.add_argument("--db", default=default_db, help="SQLite database path (or ROOMMATE_DB environment variable).")
    parser.add_argument("--check-interval", type=int, default=21600, help="Seconds between local monitored-price checks (minimum: 60; default: 21600).")
    parser.add_argument("--no-tracker", action="store_true", help="Keep automatic price checks stopped for offline planning.")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("The port must be between 1 and 65535.")
    if args.check_interval < 60:
        parser.error("The check interval must be at least 60 seconds.")
    storage = Storage(args.db)
    server = RoomMateServer(("127.0.0.1", args.port), storage)
    from .tracker import Tracker
    server.tracker = Tracker(storage, lambda identity: check_product(storage, identity, server.check_lock), interval_seconds=args.check_interval)
    if not args.no_tracker:
        server.tracker.start()
    print(f"Roomies is ready: http://127.0.0.1:{server.server_port}", flush=True)
    print("Your data stays in the local database. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.tracker.stop()
        server.server_close()


if __name__ == "__main__":
    main()

"""Run opted-in price checks while the local server is open."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import threading


def _stamp(value):
    if not value:
        return None
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


class Tracker:
    """A small scheduler, not a cloud service.

    The server supplies the check function and serializes live checks with its
    manual-check lock. Product state is reread on each cycle so disabling a
    watch does not require restarting the application.
    """

    def __init__(self, storage, check_fn, interval_seconds=21600):
        if isinstance(interval_seconds, bool) or not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("The check interval must be positive.")
        self.storage = storage
        self.check_fn = check_fn
        self.interval_seconds = float(interval_seconds)
        self._stop = threading.Event()
        self._thread = None
        self._products = []
        self._last_cycle = None
        self._last_result = {"checked": 0, "failed": 0}

    def due(self, product, now=None):
        if not product.get("monitor") or not product.get("url") or product.get("is_demo"):
            return False
        now = now or datetime.now(timezone.utc)
        checked_at = _stamp(product.get("last_checked_at"))
        return checked_at is None or now - checked_at >= timedelta(seconds=self.interval_seconds)

    def run_cycle(self, now=None):
        now = now or datetime.now(timezone.utc)
        products = self.storage.state()["products"]
        self._products = products
        result = {"checked": 0, "failed": 0}
        due = [product for product in products if self.due(product, now)]
        # A bounded cycle keeps one large wishlist from occupying the worker.
        for product in due[:20]:
            if self._stop.is_set():
                break
            try:
                # Recheck consent in case the watch was disabled during this cycle.
                current = next((value for value in self.storage.state()["products"] if value["id"] == product["id"]), None)
                if current is None or not self.due(current, now):
                    continue
                self.check_fn(current["id"])
                result["checked"] += 1
            except Exception:
                # The check function records its product-level failure. One source
                # failure must not stop the other explicitly enabled watches.
                result["failed"] += 1
        self._products = self.storage.state()["products"]
        self._last_cycle = now.isoformat()
        self._last_result = result
        return result

    def _run(self):
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception:
                self._last_result = {"checked": 0, "failed": 1}
            self._stop.wait(min(30, self.interval_seconds))

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="roommate-price-checks", daemon=True)
        self._thread.start()

    def stop(self, timeout=2):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=timeout)

    def status(self, products=None):
        products = self._products if products is None else products
        now = datetime.now(timezone.utc)
        due_dates = []
        for product in products:
            if not product.get("monitor") or not product.get("url") or product.get("is_demo"):
                continue
            stamp = _stamp(product.get("last_checked_at"))
            due_dates.append(max(now, stamp + timedelta(seconds=self.interval_seconds)) if stamp else now)
        hours = self.interval_seconds / 3600
        interval = f"{hours:g} hours" if hours >= 1 else f"{self.interval_seconds:g} seconds"
        running = bool(self._thread and self._thread.is_alive() and not self._stop.is_set())
        description = f"Enabled watches are checked every {interval} while the local server is running. New watches are picked up within 30 seconds." if running else "Scheduled checks are stopped. You can record a price or use Check price manually."
        return {
            "mode": "local", "background_running": running,
            "interval_seconds": self.interval_seconds,
            "next_check_at": min(due_dates).isoformat() if due_dates else None,
            "last_cycle_at": self._last_cycle,
            "last_cycle_result": self._last_result.copy(),
            "description": description,
            "currency": "EUR", "max_quote_age_hours": 24,
        }

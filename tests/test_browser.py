import json
from pathlib import Path
import tempfile
import unittest

from roommate.browser import BrowserWorkspace


class BrowserWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = BrowserWorkspace(Path(self.temp.name) / "room.sqlite3")

    def call(self, path, method="GET", payload=None):
        return self.app.request(path, method, json.dumps(payload) if payload is not None else None)

    def test_same_room_rules_and_suggestions(self):
        current = self.call("/api/state")
        self.assertEqual(current["summary"]["area_m2"], 10.5)
        self.assertEqual(current["tracker"]["mode"], "browser")
        self.assertFalse(current["tracker"]["background_running"])
        room = current["room"]
        room["items"][0]["x_cm"] = -20
        self.assertFalse(self.call("/api/room", "PUT", room)["summary"]["valid"])
        self.assertTrue(self.call("/api/suggest", "POST", {"item_id": "desk"})["placements"])

    def test_expense_rounding_backup_and_restore(self):
        flat = self.call("/api/state")["flat"]
        flat["members"] = [{"id": "a", "name": "Alice"}, {"id": "b", "name": "Bob"}]
        flat["expenses"] = [{"id": "e", "title": "Lunch", "amount_cents": 3001,
                             "paid_by": "a", "split_between": ["b", "a"],
                             "date": "2026-09-30", "category": "groceries", "notes": ""}]
        saved = self.call("/api/flat", "PUT", flat)
        self.assertEqual(saved["flat_summary"]["expenses"]["settlements"][0]["amount_cents"], 1501)
        backup = self.call("/api/export")
        self.assertEqual(backup["filename"], "roomies-backup.json")
        self.call("/api/reset", "POST")
        restored = self.call("/api/import", "POST", json.loads(backup["text"]))
        self.assertEqual(restored["flat"], saved["flat"])
        for format in ("csv", "expenses", "repayments"):
            exported = self.call(f"/api/export?format={format}")
            self.assertTrue(exported["filename"].endswith(".csv"))
            self.assertTrue(exported["text"].startswith("\ufeff"))

    def test_invalid_restore_keeps_existing_data(self):
        before = self.app.storage.export()
        response = json.loads(self.app.dispatch("/api/import", "POST", '{"schema_version":3}'))
        self.assertIn("error", response)
        self.assertEqual(self.app.storage.export()["room"], before["room"])
        self.assertEqual(self.app.storage.export()["flat"], before["flat"])

    def test_unsupported_network_actions_are_clear(self):
        for route in ("/api/check-all", "/api/products/a/check"):
            result = json.loads(self.app.dispatch(route, "POST", "{}"))
            self.assertIn("local app", result["error"])
        self.assertIn("error", json.loads(self.app.dispatch("/api/unknown")))
        self.assertIn("error", json.loads(self.app.dispatch("/api/room", "PUT", "[]")))

import copy
import csv
import io
from datetime import datetime, timedelta, timezone
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from roommate.storage import Storage
from tests.test_household import household_data


def product_data(**extra):
    return {"name": "A practical desk", "item_id": "desk", "url": "https://example.com/desk", "width_cm": 100, "depth_cm": 50, "height_cm": 70, "price_eur": 70, "shipping_eur": 5, "target_eur": 100, "availability": "in_stock", "variant_confirmed": True, "monitor": True, **extra}


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "room.sqlite3"
        self.storage = Storage(self.path)
        room = self.storage.state()["room"]
        room["is_demo"] = False
        self.storage.save_room(room)

    def tearDown(self):
        self.temp.cleanup()

    def test_seed_has_no_fake_prices_or_notifications(self):
        state = self.storage.state()
        self.assertEqual(state["products"], [])
        self.assertEqual(state["notifications"], [])
        self.assertFalse(state["tracker"]["background_running"])
        self.assertEqual(state["flat"]["inventory"], [])
        self.assertEqual(state["flat"]["fridge"], [])
        self.assertEqual(state["flat"]["expenses"], [])

    def test_flat_migration_keeps_existing_room_and_price_history(self):
        product = self.storage.save_product(product_data())
        before_room = self.storage.state()["room"]
        with self.storage._connect() as connection:
            connection.execute("DROP TABLE flat")
        reopened = Storage(self.path)
        state = reopened.state()
        self.assertEqual(state["room"], before_room)
        self.assertEqual(state["products"][0]["id"], product["id"])
        self.assertEqual(state["products"][0]["latest_observation"]["price_eur"], 70)
        self.assertEqual(state["flat"]["members"], [{"id": "me", "name": "Me"}])
        self.assertEqual(state["flat"]["expenses"], [])

    def test_flat_survives_reopen_and_is_separate_from_room(self):
        original_room = self.storage.state()["room"]
        saved = self.storage.save_flat(household_data())
        reopened = Storage(self.path)
        self.assertEqual(reopened.state()["flat"], saved)
        self.assertEqual(reopened.state()["room"], original_room)
        self.assertEqual(reopened.state()["flat_summary"]["expenses"]["total_cents"], 1001)

    def test_legacy_import_and_room_reset_preserve_flat(self):
        saved_flat = self.storage.save_flat(household_data())
        legacy = self.storage.export()
        legacy["schema_version"] = 1
        legacy.pop("flat")
        legacy["room"]["name"] = "Restored older room"
        state = self.storage.import_data(legacy)
        self.assertEqual(state["room"]["name"], "Restored older room")
        self.assertEqual(state["flat"], saved_flat)
        self.assertEqual(self.storage.reset()["flat"], saved_flat)

    def test_version_two_round_trip_keeps_flat_and_exact_cents(self):
        self.storage.save_product(product_data())
        self.storage.save_flat(household_data())
        before = self.storage.export()
        self.assertEqual(before["schema_version"], 2)
        self.storage.save_flat({"members": [{"id": "me", "name": "Me"}]})
        self.storage.import_data(before)
        self.assertEqual(self.storage.export(), before)
        self.assertIsInstance(self.storage.state()["flat"]["expenses"][0]["amount_cents"], int)

    def test_invalid_flat_or_schema_in_backup_preserves_entire_database(self):
        self.storage.save_product(product_data())
        self.storage.save_flat(household_data())
        before = self.storage.export()
        invalid = []
        missing_flat = copy.deepcopy(before)
        missing_flat.pop("flat")
        invalid.append(missing_flat)
        bad_owner = copy.deepcopy(before)
        bad_owner["flat"]["inventory"][0]["owner_id"] = "missing"
        invalid.append(bad_owner)
        fractional_cents = copy.deepcopy(before)
        fractional_cents["flat"]["expenses"][0]["amount_cents"] = 1001.0
        invalid.append(fractional_cents)
        for version in (True, 1.0, 3, "2"):
            bad_version = copy.deepcopy(before)
            bad_version["schema_version"] = version
            invalid.append(bad_version)
        for payload in invalid:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    self.storage.import_data(payload)
                self.assertEqual(self.storage.export(), before)

    def test_transaction_failure_rolls_back_flat_room_and_products(self):
        self.storage.save_product(product_data())
        self.storage.save_flat(household_data())
        before = self.storage.export()
        replacement = copy.deepcopy(before)
        replacement["room"]["name"] = "Replacement room"
        replacement["flat"]["name"] = "Replacement flat"
        with patch.object(self.storage, "_insert_observation", side_effect=RuntimeError("Fixture write failure")):
            with self.assertRaises(RuntimeError):
                self.storage.import_data(replacement)
        self.assertEqual(self.storage.export(), before)

    def test_invalid_flat_write_preserves_saved_flat(self):
        before = self.storage.save_flat(household_data())
        invalid = copy.deepcopy(before)
        invalid["members"] = []
        with self.assertRaises(ValueError):
            self.storage.save_flat(invalid)
        self.assertEqual(self.storage.state()["flat"], before)

    def test_expense_csv_cent_shares_and_formula_text_are_safe(self):
        flat = household_data()
        flat["members"][0]["name"] = "=Me"
        flat["expenses"][0]["title"] = "+Groceries"
        flat["expenses"][0]["notes"] = "  @a formula"
        self.storage.save_flat(flat)
        rows = list(csv.DictReader(io.StringIO(self.storage.export_expenses_csv())))
        self.assertEqual([row["participant_id"] for row in rows], ["me", "amy"])
        self.assertEqual([int(row["share_cents"]) for row in rows], [501, 500])
        self.assertEqual([int(row["amount_cents"]) for row in rows], [1001, 1001])
        self.assertEqual(rows[0]["payer_name"], "'=Me")
        self.assertEqual(rows[0]["title"], "'+Groceries")
        self.assertEqual(rows[0]["notes"], "'@a formula")

    def test_notification_type_is_migrated_for_existing_local_databases(self):
        with self.storage._connect() as connection:
            connection.execute("DROP TABLE notifications")
            connection.execute("CREATE TABLE notifications (id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE, observation_id TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, UNIQUE(product_id, observation_id))")
        self.storage = Storage(self.path)
        self.storage.save_product(product_data())
        self.assertEqual(self.storage.state()["notifications"][0]["type"], "target_ready")

    def test_notification_timestamp_ties_preserve_insertion_order_not_uuid_order(self):
        same_second = datetime.now(timezone.utc).isoformat(timespec="seconds")
        identities = [SimpleNamespace(hex=value) for value in ("product", "old-quote", "z-old-alert", "new-quote", "a-new-alert")]
        with patch("roommate.storage.timestamp", return_value=same_second), patch("roommate.storage.uuid.uuid4", side_effect=identities):
            product = self.storage.save_product(product_data())
            self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True})
        alerts = self.storage.state()["notifications"]
        self.assertEqual([alert["created_at"] for alert in alerts], [same_second, same_second])
        self.assertEqual([alert["id"] for alert in alerts], ["z-old-alert", "a-new-alert"])
        self.assertEqual([alert["type"] for alert in alerts], ["target_ready", "price_drop_info"])

    def test_room_and_quotes_survive_reopening(self):
        product = self.storage.save_product(product_data())
        reopened = Storage(self.path)
        self.assertEqual(reopened.product(product["id"])["latest_observation"]["price_eur"], 70)
        self.assertTrue(reopened.product(product["id"])["evaluation"]["eligible"])

    def test_room_colors_survive_backup_and_legacy_backups_get_defaults(self):
        room = self.storage.state()["room"]
        room.update(wall_color="#ABC123", floor_color="#f6ead1")
        self.storage.save_room(room)
        exported = self.storage.export()
        self.storage.reset()
        restored = self.storage.import_data(exported)["room"]
        self.assertEqual(restored["wall_color"], "#abc123")
        self.assertEqual(restored["floor_color"], "#f6ead1")
        exported["room"].pop("wall_color")
        exported["room"].pop("floor_color")
        legacy = self.storage.import_data(exported)["room"]
        self.assertEqual(legacy["wall_color"], "#a4b497")
        self.assertEqual(legacy["floor_color"], "#f4f6ed")

    def test_import_validation_preserves_all_saved_data(self):
        self.storage.save_product(product_data())
        before = self.storage.export()
        bad = copy.deepcopy(before)
        bad["products"][0]["width_cm"] = -1
        with self.assertRaises(ValueError):
            self.storage.import_data(bad)
        self.assertEqual(self.storage.export(), before)

    def test_unknown_import_fields_are_rejected(self):
        product = self.storage.save_product(product_data())
        bad = self.storage.export()
        bad["products"][0]["password"] = "not allowed"
        with self.assertRaises(ValueError):
            self.storage.import_data(bad)
        self.assertEqual(self.storage.product(product["id"])["name"], "A practical desk")

    def test_export_round_trip_keeps_history(self):
        product = self.storage.save_product(product_data())
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": 5, "availability": "in_stock", "variant_confirmed": True})
        exported = self.storage.export()
        self.storage.reset()
        self.storage.import_data(exported)
        self.assertEqual(self.storage.export(), exported)

    def test_unchanged_product_edit_does_not_refresh_quote(self):
        product = self.storage.save_product(product_data())
        original = product["latest_observation"]
        data = self.storage.export()["products"][0]
        data.pop("observations")
        data["identity_notes"] = "One new note."
        changed = self.storage.save_product(data)
        self.assertEqual(changed["latest_observation"], original)
        self.assertEqual(len(changed["observations"]), 1)

    def test_historical_quote_does_not_replace_current_evidence(self):
        product = self.storage.save_product(product_data())
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        self.storage.add_observation(product["id"], {"price_eur": 20, "shipping_eur": 0, "availability": "in_stock", "variant_confirmed": True, "observed_at": old_time})
        current = self.storage.product(product["id"])
        self.assertEqual(current["latest_observation"]["price_eur"], 70)
        self.assertTrue(current["evaluation"]["eligible"])
        self.assertEqual(len(self.storage.state()["notifications"]), 1)

    def test_backdated_quote_does_not_clear_a_failed_current_check(self):
        product = self.storage.save_product(product_data())
        self.storage.record_check_error(product["id"], "The latest live source was unavailable.")
        checked_at = self.storage.product(product["id"])["last_checked_at"]
        old_time = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        self.storage.add_observation(product["id"], {"price_eur": 20, "shipping_eur": 0, "availability": "in_stock", "variant_confirmed": True, "observed_at": old_time})
        current = self.storage.product(product["id"])
        self.assertFalse(current["evaluation"]["eligible"])
        self.assertIn("unavailable", current["error"])
        self.assertEqual(current["last_checked_at"], checked_at)

    def test_identity_edit_invalidates_previous_quote(self):
        product = self.storage.save_product(product_data())
        data = self.storage.export()["products"][0]
        data.pop("observations")
        data["variant"] = "A different version"
        changed = self.storage.save_product(data)
        self.assertFalse(changed["evaluation"]["eligible"])
        self.assertEqual(len(changed["observations"]), 1)

    def test_repeat_price_does_not_create_another_alert_but_drop_does(self):
        product = self.storage.save_product(product_data())
        quote = {"price_eur": 70, "shipping_eur": 5, "availability": "in_stock", "variant_confirmed": True}
        self.storage.add_observation(product["id"], quote)
        self.assertEqual(len(self.storage.state()["notifications"]), 1)
        self.storage.add_observation(product["id"], {**quote, "price_eur": 65})
        self.assertEqual(len(self.storage.state()["notifications"]), 2)

    def test_unknown_shipping_drop_is_informational_with_no_target_ready_alert(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        self.assertEqual(self.storage.state()["notifications"], [])
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True})
        state = self.storage.state()
        self.assertFalse(state["products"][0]["evaluation"]["eligible"])
        self.assertEqual([alert["type"] for alert in state["notifications"]], ["price_drop_info"])
        self.assertIn("Confirm delivery", state["notifications"][0]["message"])
        self.assertIn("€70.00 to €60.00", state["notifications"][0]["message"])

    def test_first_quote_without_delivery_has_no_price_drop_baseline(self):
        self.storage.save_product(product_data(shipping_eur=None))
        self.assertEqual(self.storage.state()["notifications"], [])

    def test_repeated_unknown_shipping_quote_does_not_duplicate_drop_notice(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        quote = {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True}
        self.storage.add_observation(product["id"], quote)
        self.storage.add_observation(product["id"], quote)
        self.assertEqual(len(self.storage.state()["notifications"]), 1)

    def test_sample_room_blocks_all_purchase_and_price_drop_alerts(self):
        room = self.storage.state()["room"]
        room["is_demo"] = True
        self.storage.save_room(room)
        product = self.storage.save_product(product_data())
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True})
        self.assertEqual(self.storage.state()["notifications"], [])

    def test_changed_identity_cannot_supply_price_drop_baseline(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        data = self.storage.export()["products"][0]
        data.pop("observations")
        data["variant"] = "Another desk version"
        self.storage.save_product(data)
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True})
        self.assertEqual(self.storage.state()["notifications"], [])

    def test_backdated_insertion_cannot_create_price_drop_notice(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True, "observed_at": old_time})
        self.assertEqual(self.storage.state()["notifications"], [])

    def test_delivered_target_ready_takes_precedence_over_price_drop_info(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": 5, "availability": "in_stock", "variant_confirmed": True})
        self.assertEqual([alert["type"] for alert in self.storage.state()["notifications"]], ["target_ready"])

    def test_import_does_not_replay_historical_notifications(self):
        product = self.storage.save_product(product_data(shipping_eur=None))
        self.storage.add_observation(product["id"], {"price_eur": 60, "shipping_eur": None, "availability": "in_stock", "variant_confirmed": True})
        exported = self.storage.export()
        self.assertEqual(len(self.storage.state()["notifications"]), 1)
        self.storage.import_data(exported)
        self.assertEqual(self.storage.state()["notifications"], [])

    def test_delete_cascades_quotes_and_alerts(self):
        product = self.storage.save_product(product_data())
        self.storage.delete_product(product["id"])
        state = self.storage.state()
        self.assertEqual(state["products"], [])
        self.assertEqual(state["notifications"], [])
        with self.assertRaises(KeyError):
            self.storage.product(product["id"])

    def test_mark_notification_and_missing_record(self):
        self.storage.save_product(product_data())
        alert = self.storage.state()["notifications"][0]
        self.storage.mark_notification(alert["id"])
        self.assertTrue(self.storage.state()["notifications"][0]["read"])
        with self.assertRaises(KeyError):
            self.storage.mark_notification("missing")

    def test_csv_neutralizes_spreadsheet_formulas(self):
        self.storage.save_product(product_data(name="=SUM(1,1)"))
        self.assertIn("'=SUM(1,1)", self.storage.export_csv())

    def test_geometry_conflicts_can_be_saved_and_fixed(self):
        room = self.storage.state()["room"]
        room["items"][0]["x_cm"] = -25
        self.storage.save_room(room)
        self.assertFalse(self.storage.state()["summary"]["valid"])
        room["items"][0]["x_cm"] = 0
        self.storage.save_room(room)
        self.assertTrue(self.storage.state()["summary"]["valid"])


if __name__ == "__main__":
    unittest.main()

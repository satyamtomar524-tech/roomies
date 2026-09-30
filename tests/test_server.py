import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from roommate.server import MAX_BODY_BYTES, RoomMateServer
from roommate.storage import Storage
from tests.test_household import household_data


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        directory = Path(self.temp.name)
        self.storage = Storage(directory / "room.sqlite3")
        self.web = directory / "web"
        self.web.mkdir()
        (self.web / "index.html").write_text("<h1>RoomMate</h1>", encoding="utf-8")
        (self.web / "guide.html").write_text("<h1>A useful guide</h1>", encoding="utf-8")
        (self.web / "guide.css").write_text("body{}", encoding="utf-8")
        (self.web / "flat.js").write_text("console.log('flat');", encoding="utf-8")
        (self.web / "costs.js").write_text("console.log('costs');", encoding="utf-8")
        self.server = RoomMateServer(("127.0.0.1", 0), self.storage, self.web)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, payload, request_headers)
        response = connection.getresponse()
        content = response.read()
        result = (response.status, dict(response.getheaders()), content)
        connection.close()
        return result

    def test_state_and_exact_static_files(self):
        status, headers, content = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["summary"]["area_m2"], 10.5)
        self.assertEqual(json.loads(content)["flat"]["expenses"], [])
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(self.request("GET", "/guide")[0], 200)
        self.assertEqual(self.request("GET", "/guide.css")[0], 200)
        self.assertEqual(self.request("GET", "/flat.js")[0], 200)
        self.assertEqual(self.request("GET", "/costs.js")[0], 200)
        self.assertEqual(self.request("GET", "/../roommate/storage.py")[0], 404)
        self.assertEqual(self.request("GET", "/%2e%2e/roommate/storage.py")[0], 404)
        self.assertEqual(self.request("GET", "/data/room.sqlite3")[0], 404)

    def test_repayment_export_and_duplicate_monthly_bill_rejection(self):
        flat = household_data()
        flat["repayments"] = [{"id": "repay", "from_id": "amy", "to_id": "me", "amount_cents": 500,
                               "date": "2026-09-30", "notes": "Test transfer"}]
        status, _, content = self.request("PUT", "/api/flat", flat)
        self.assertEqual(status, 200)
        saved = json.loads(content)
        self.assertEqual(saved["flat_summary"]["expenses"]["settlements"], [])
        status, headers, content = self.request("GET", "/api/export?format=repayments")
        self.assertEqual(status, 200)
        self.assertIn("roomies-repayments.csv", headers["Content-Disposition"])
        self.assertIn("sender_name", content.decode("utf-8-sig"))
        self.assertIn("Test transfer", content.decode("utf-8-sig"))
        flat["expenses"][0].update(bill_id="internet", bill_month="2026-09")
        flat["expenses"].append(dict(flat["expenses"][0], id="again"))
        self.assertEqual(self.request("PUT", "/api/flat", flat)[0], 400)
        self.assertEqual(self.storage.state()["flat"], saved["flat"])

    def test_cross_origin_read_and_write_are_blocked_before_mutation(self):
        before = self.storage.export()
        for method, path, body in (("GET", "/api/state", None), ("POST", "/api/reset", {})):
            self.assertEqual(self.request(method, path, body, {"Origin": "https://malicious.example"})[0], 403)
        self.assertEqual(self.storage.export(), before)

    def test_untrusted_host_and_fetch_site_are_blocked(self):
        self.assertEqual(self.request("POST", "/api/reset", {}, {"Host": "malicious.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_own_origin_is_accepted(self):
        origin = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("GET", "/api/state", headers={"Origin": origin})[0], 200)

    def test_json_write_requires_expected_content_type(self):
        self.assertEqual(self.request("POST", "/api/reset", {}, {"Content-Type": "text/plain"})[0], 400)

    def test_malformed_json_and_nonfinite_numbers_are_rejected(self):
        for payload in (b"{", b'{"width_cm": NaN}'):
            connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
            connection.request("PUT", "/api/room", payload, {"Content-Type": "application/json"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn("error", json.loads(response.read()))
            connection.close()

    def test_large_declared_body_is_rejected_without_reading_it(self):
        status, _, body = self.request("POST", "/api/reset", {}, {"Content-Length": str(3 * 1024 * 1024)})
        self.assertEqual(status, 400)
        self.assertIn("2 MiB", json.loads(body)["error"])

    def test_large_own_json_export_restores_through_import_endpoint(self):
        flat = household_data()
        flat["inventory"] = [
            {"id": f"item-{index}", "name": f"Item {index}", "notes": "漢" * 1000,
             "location": "Room", "quantity": 1, "category": "other", "owner_id": None}
            for index in range(500)
        ]
        flat["expenses"] = [
            {"id": f"expense-{index}", "title": f"Expense {index}", "amount_cents": 100,
             "paid_by": "me", "split_between": ["me", "amy"], "date": "2026-09-30",
             "category": "other", "notes": "x" * 2000}
            for index in range(500)
        ]
        self.storage.save_flat(flat)
        status, _, exported = self.request("GET", "/api/export")
        self.assertEqual(status, 200)
        self.assertGreater(len(exported), MAX_BODY_BYTES)
        payload = json.loads(exported)
        self.storage.save_flat({"members": [{"id": "me", "name": "Me"}]})
        status, _, content = self.request("POST", "/api/import", payload)
        self.assertEqual(status, 200, content.decode())
        self.assertEqual(self.storage.export(), payload)

    def test_import_limit_is_bounded_independently_of_normal_writes(self):
        declared = str(33 * 1024 * 1024)
        status, _, body = self.request("POST", "/api/import", {}, {"Content-Length": declared})
        self.assertEqual(status, 400)
        self.assertIn("32 MiB", json.loads(body)["error"])

    def test_product_endpoint_rejects_new_explicit_ids_at_capacity(self):
        backup = self.storage.export()
        backup["products"] = [{"id": f"product-{index}", "name": f"Product {index}"} for index in range(100)]
        self.storage.import_data(backup)
        status, _, content = self.request("POST", "/api/products", {"id": "bypass", "name": "An extra product"})
        self.assertEqual(status, 400)
        self.assertIn("at most 100 products", json.loads(content)["error"])
        self.assertEqual(self.request("POST", "/api/products", {"id": "product-0", "name": "An existing product edit"})[0], 201)
        self.assertEqual(len(self.storage.state()["products"]), 100)

    def test_geometric_errors_are_saved_and_reported(self):
        room = self.storage.state()["room"]
        room["items"][0]["x_cm"] = -5
        status, _, content = self.request("PUT", "/api/room", room)
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(content)["summary"]["valid"])
        self.assertEqual(self.storage.state()["room"]["items"][0]["x_cm"], -5)

    def test_product_crud_and_quote_journal(self):
        product = {"name": "A desk", "item_id": "desk", "width_cm": 100, "depth_cm": 50, "height_cm": 70, "target_eur": 100}
        status, _, content = self.request("POST", "/api/products", product)
        self.assertEqual(status, 201)
        identity = json.loads(content)["product"]["id"]
        status, _, content = self.request("POST", f"/api/products/{identity}/observations", {"price_eur": 60, "shipping_eur": 0, "availability": "in_stock", "variant_confirmed": True})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(content)["observation"]["price_eur"], 60)
        self.assertEqual(self.request("DELETE", f"/api/products/{identity}")[0], 200)
        self.assertEqual(self.request("DELETE", f"/api/products/{identity}")[0], 404)

    def test_flat_write_is_separate_and_summary_uses_exact_cent_shares(self):
        before_room = self.storage.state()["room"]
        status, _, content = self.request("PUT", "/api/flat", household_data())
        self.assertEqual(status, 200)
        result = json.loads(content)
        self.assertEqual(result["flat"]["inventory"][0]["spot"], "Upper shelf")
        self.assertEqual(result["flat_summary"]["expenses"]["total_cents"], 1001)
        self.assertEqual(self.storage.state()["room"], before_room)
        status, _, content = self.request("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(content)["flat"], result["flat"])

    def test_invalid_or_cross_origin_flat_write_cannot_replace_saved_data(self):
        flat = self.storage.save_flat(household_data())
        before = self.storage.export()
        invalid = {**flat, "members": []}
        self.assertEqual(self.request("PUT", "/api/flat", invalid)[0], 400)
        self.assertEqual(self.request("PUT", "/api/flat", flat, {"Origin": "https://malicious.example"})[0], 403)
        self.assertEqual(self.storage.export(), before)

    def test_expense_csv_and_version_two_json_are_downloadable(self):
        self.storage.save_flat(household_data())
        status, headers, content = self.request("GET", "/api/export?format=expenses")
        self.assertEqual(status, 200)
        self.assertIn("roomies-expense-shares.csv", headers["Content-Disposition"])
        self.assertIn("share_cents", content.decode("utf-8-sig"))
        status, headers, content = self.request("GET", "/api/export?format=json")
        result = json.loads(content)
        self.assertEqual(result["schema_version"], 3)
        self.assertEqual(result["flat"]["expenses"][0]["amount_cents"], 1001)
        self.assertIn("roomies-backup.json", headers["Content-Disposition"])

    def test_encoded_product_ids_round_trip_without_path_confusion(self):
        product = self.storage.save_product({"id": "my desk/one", "name": "Desk with imported ID", "item_id": "desk"})
        encoded = "my%20desk%2Fone"
        status, _, content = self.request("POST", f"/api/products/{encoded}/observations", {"price_eur": 65, "shipping_eur": 5, "availability": "in_stock"})
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(content)["product"]["id"], product["id"])
        self.assertEqual(self.request("DELETE", f"/api/products/{encoded}")[0], 200)

    def test_live_check_uses_adapter_and_failure_preserves_quote(self):
        product = self.storage.save_product({"name": "A desk", "url": "https://example.com/desk", "item_id": "desk", "width_cm": 100, "depth_cm": 50, "height_cm": 70, "monitor": True})
        with patch("roommate.server.fetch_price", return_value={"price_eur": 72, "shipping_eur": None, "availability": "in_stock", "source": "jsonld", "source_url": product["url"], "variant_confirmed": False}):
            self.assertEqual(self.request("POST", f"/api/products/{product['id']}/check", {})[0], 200)
        with patch("roommate.server.fetch_price", side_effect=ValueError("This store needs a manual quote.")):
            self.assertEqual(self.request("POST", f"/api/products/{product['id']}/check", {})[0], 400)
        saved = self.storage.product(product["id"])
        self.assertEqual(saved["latest_observation"]["price_eur"], 72)
        self.assertIn("manual quote", saved["error"])

    def test_import_is_atomic_and_exports_have_download_headers(self):
        before = self.storage.export()
        self.assertEqual(self.request("POST", "/api/import", {"room": {"width_cm": -1}})[0], 400)
        self.assertEqual(self.storage.export(), before)
        for format in ("json", "csv"):
            status, headers, _ = self.request("GET", f"/api/export?format={format}")
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers["Content-Disposition"])

    def test_suggestions_do_not_save_a_move(self):
        before = self.storage.export()
        status, _, content = self.request("POST", "/api/suggest", {"item_id": "desk"})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(content)["placements"])
        self.assertEqual(self.storage.export(), before)

    def test_binding_to_external_interfaces_is_rejected(self):
        with self.assertRaises(ValueError):
            RoomMateServer(("0.0.0.0", 0), self.storage)


if __name__ == "__main__":
    unittest.main()

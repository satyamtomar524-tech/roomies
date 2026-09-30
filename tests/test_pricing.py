"""Fixtures verify decision rules and the adapter without contacting retailers."""

import copy
from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import Mock, patch

from roommate.geometry import validate_room
from roommate import pricing


def room_fixture():
    return validate_room({"width_cm": 300, "depth_cm": 350, "is_demo": False, "items": [{
        "id": "desk-space", "name": "Future desk", "width_cm": 120,
        "depth_cm": 60, "height_cm": 80, "x_cm": 20, "y_cm": 20,
        "status": "planned", "target_eur": 100,
    }]})


def product_fixture():
    return pricing.validate_product({
        "id": "desk", "name": "Small desk", "item_id": "desk-space",
        "width_cm": 110, "depth_cm": 55, "height_cm": 75,
        "variant_confirmed": True, "target_eur": 100,
    }, room_fixture())


def quote_fixture(**overrides):
    quote = {"price_eur": 79.99, "shipping_eur": 9.99, "availability": "in_stock",
             "source": "manual", "observed_at": datetime.now(timezone.utc).isoformat()}
    quote.update(overrides)
    return pricing.validate_observation(quote)


def jsonld_fixture():
    return {"@context": "https://schema.org", "@type": "Product", "name": "Small desk",
            "sku": "DESK-OAK-110", "color": "oak", "offers": {
                "@type": "Offer", "price": "79.99", "priceCurrency": "EUR",
                "availability": "https://schema.org/InStock"}}


class DecisionTests(unittest.TestCase):
    def test_full_current_quote_is_eligible(self):
        result = pricing.evaluate_product(room_fixture(), product_fixture(), quote_fixture())
        self.assertTrue(result["eligible"])
        self.assertEqual(result["delivered_eur"], 89.98)
        self.assertEqual(result["fit"], "pass")

    def test_unknown_delivery_is_not_free_delivery(self):
        result = pricing.evaluate_product(room_fixture(), product_fixture(), quote_fixture(shipping_eur=None))
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["delivered_eur"])
        self.assertIsNone(result["below_target"])
        self.assertTrue(result["can_price_drop_notice"])

    def test_sample_plan_does_not_recommend_real_product(self):
        room = room_fixture()
        room["is_demo"] = True
        result = pricing.evaluate_product(room, product_fixture(), quote_fixture())
        self.assertFalse(result["eligible"])
        self.assertFalse(result["can_price_drop_notice"])
        self.assertTrue(any("room measurements" in reason for reason in result["reasons"]))

    def test_price_drop_notice_needs_fit_identity_stock_and_fresh_quote(self):
        for changes, quote_changes in (({"variant_confirmed": False}, {}), ({"width_cm": 200}, {}), ({}, {"availability": "unknown"}), ({}, {"source": "demo"}), ({}, {"observed_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()})):
            with self.subTest(changes=changes, quote_changes=quote_changes):
                product = product_fixture()
                product.update(changes)
                self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote_fixture(**quote_changes))["can_price_drop_notice"])

    def test_live_matching_confirmed_sku_can_notice_drop_without_delivery_inference(self):
        product = product_fixture()
        product.update(sku="DESK-OAK-110", url="https://shop.example.org/desk")
        quote = quote_fixture(source="jsonld", sku="DESK-OAK-110", requested_product_url=product["url"], product_signature=pricing.product_signature(product), shipping_eur=None)
        result = pricing.evaluate_product(room_fixture(), product, quote)
        self.assertTrue(result["can_price_drop_notice"])
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["delivered_eur"])

    def test_live_quote_requires_saved_matching_sku_url_signature_and_variant(self):
        cases = (({"sku": ""}, {}), ({}, {"sku": "OTHER"}), ({}, {"sku": ""}),
                 ({"variant_confirmed": False}, {}), ({}, {"requested_product_url": ""}),
                 ({}, {"product_signature": ""}), ({}, {"variant_confirmed": True, "sku": "OTHER"}))
        for product_changes, quote_changes in cases:
            with self.subTest(product_changes=product_changes, quote_changes=quote_changes):
                product = product_fixture()
                product.update(sku="DESK-OAK-110", url="https://shop.example.org/desk")
                product.update(product_changes)
                quote = quote_fixture(source="jsonld", sku="DESK-OAK-110", requested_product_url=product["url"], product_signature=pricing.product_signature(product), shipping_eur=None)
                quote.update(quote_changes)
                self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote)["can_price_drop_notice"])

    def test_sku_change_changes_product_identity(self):
        product = product_fixture()
        original = pricing.product_signature(product)
        product["sku"] = "NEW-VARIANT"
        self.assertNotEqual(pricing.product_signature(product), original)

    def test_dimensions_and_variant_must_be_confirmed(self):
        for field, value in (("width_cm", None), ("height_cm", None), ("variant_confirmed", False)):
            with self.subTest(field=field):
                product = product_fixture()
                product[field] = value
                self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote_fixture())["eligible"])

    def test_quote_variant_confirmation_can_block_saved_confirmation(self):
        self.assertFalse(pricing.evaluate_product(room_fixture(), product_fixture(), quote_fixture(variant_confirmed=False))["eligible"])

    def test_manual_quote_confirmation_is_sufficient_for_this_quote(self):
        product = product_fixture()
        product["variant_confirmed"] = False
        self.assertTrue(pricing.evaluate_product(room_fixture(), product, quote_fixture(variant_confirmed=True, shipping_eur=0))["eligible"])

    def test_changed_identity_requires_new_quote(self):
        product = product_fixture()
        quote = quote_fixture(product_signature=pricing.product_signature(product))
        product["width_cm"] = 90
        self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote)["eligible"])

    def test_old_product_url_is_not_reused(self):
        product = product_fixture()
        product["url"] = "https://shop.example.org/current"
        quote = quote_fixture(source_url="https://shop.example.org/old")
        self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote)["eligible"])

    def test_verified_redirect_source_preserves_original_link(self):
        product = product_fixture()
        product["url"] = "https://shop.example.org/desk"
        quote = quote_fixture(source_url="https://second.example.org/desk", requested_product_url=product["url"])
        self.assertTrue(pricing.evaluate_product(room_fixture(), product, quote)["eligible"])

    def test_stock_and_target_are_required(self):
        for overrides in ({"availability": "unknown"}, {"availability": "out_of_stock"}, {"price_eur": 150}):
            with self.subTest(overrides=overrides):
                self.assertFalse(pricing.evaluate_product(room_fixture(), product_fixture(), quote_fixture(**overrides))["eligible"])

    def test_rotation_is_explicit(self):
        product = product_fixture()
        product.update(width_cm=55, depth_cm=110)
        self.assertEqual(pricing.evaluate_product(room_fixture(), product, quote_fixture())["fit"], "pass")
        product["rotation_allow90"] = False
        self.assertEqual(pricing.evaluate_product(room_fixture(), product, quote_fixture())["fit"], "fail")

    def test_wall_product_does_not_rotate_flat(self):
        room = room_fixture()
        room["items"][0]["placement"] = "wall"
        product = product_fixture()
        product.update(width_cm=55, depth_cm=110)
        self.assertEqual(pricing.evaluate_product(room, product, quote_fixture())["fit"], "fail")

    def test_linked_conflict_blocks_upgrade(self):
        room = room_fixture()
        room["items"][0]["x_cm"] = 250
        result = pricing.evaluate_product(room, product_fixture(), quote_fixture())
        self.assertEqual(result["fit"], "fail")
        self.assertFalse(result["eligible"])

    def test_unrelated_conflict_does_not_block_valid_reservation(self):
        room = room_fixture()
        other = copy.deepcopy(room["items"][0])
        other.update(id="other", name="Other owned item", status="owned", x_cm=900)
        room["items"].append(other)
        self.assertTrue(pricing.evaluate_product(room, product_fixture(), quote_fixture())["eligible"])

    def test_surface_parent_conflict_blocks_its_product(self):
        room = room_fixture()
        parent = room["items"][0]
        parent.update(id="parent", x_cm=900, status="owned")
        lamp = copy.deepcopy(parent)
        lamp.update(id="lamp-space", name="Lamp", placement="surface", parent_id="parent", status="planned", x_cm=0, y_cm=0, width_cm=20, depth_cm=20, height_cm=50)
        room["items"].append(lamp)
        product = product_fixture()
        product.update(item_id="lamp-space", width_cm=15, depth_cm=15, height_cm=40)
        self.assertFalse(pricing.evaluate_product(room, product, quote_fixture())["eligible"])

    def test_supporting_product_is_blocked_by_its_surface_child_conflict(self):
        room = room_fixture()
        room["items"].append({"id": "lamp", "name": "Lamp", "placement": "surface",
                              "parent_id": "desk-space", "status": "planned",
                              "x_cm": 115, "y_cm": 0, "width_cm": 20, "depth_cm": 20, "height_cm": 30})
        result = pricing.evaluate_product(room, product_fixture(), quote_fixture())
        self.assertEqual(result["fit"], "fail")
        self.assertFalse(result["eligible"])
        self.assertFalse(result["can_price_drop_notice"])

    def test_smaller_supporting_product_must_preserve_surface_locations(self):
        for rotation in (0, 90):
            with self.subTest(rotation=rotation):
                room = room_fixture()
                room["items"][0]["rotation"] = rotation
                room["items"].append({"id": "lamp", "name": "Lamp", "placement": "surface",
                                      "parent_id": "desk-space", "status": "planned",
                                      "x_cm": 105 if rotation == 0 else 0,
                                      "y_cm": 0 if rotation == 0 else 105,
                                      "width_cm": 15, "depth_cm": 15, "height_cm": 30})
                before = copy.deepcopy(room)
                result = pricing.evaluate_product(room, product_fixture(), quote_fixture())
                self.assertEqual(result["fit"], "fail")
                self.assertFalse(result["eligible"])
                self.assertFalse(result["can_price_drop_notice"])
                self.assertEqual(room, before)

    def test_supporting_product_uses_an_allowed_orientation_that_keeps_children(self):
        room = room_fixture()
        room["items"][0]["depth_cm"] = 120
        room["items"].append({"id": "lamp", "name": "Lamp", "placement": "surface",
                              "parent_id": "desk-space", "status": "planned",
                              "x_cm": 20, "y_cm": 80, "width_cm": 20, "depth_cm": 20, "height_cm": 30})
        product = product_fixture()
        self.assertTrue(pricing.evaluate_product(room, product, quote_fixture())["eligible"])
        product["rotation_allow90"] = False
        self.assertFalse(pricing.evaluate_product(room, product, quote_fixture())["eligible"])

    def test_smaller_supporting_product_keeps_valid_surface_layout_eligible(self):
        room = room_fixture()
        room["items"].append({"id": "lamp", "name": "Lamp", "placement": "surface",
                              "parent_id": "desk-space", "status": "planned",
                              "x_cm": 80, "y_cm": 5, "width_cm": 20, "depth_cm": 20, "height_cm": 30})
        before = copy.deepcopy(room)
        self.assertTrue(pricing.evaluate_product(room, product_fixture(), quote_fixture())["eligible"])
        self.assertEqual(room, before)

    def test_demo_never_becomes_live_recommendation(self):
        product = product_fixture()
        product["is_demo"] = True
        self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote_fixture())["eligible"])
        product["is_demo"] = False
        self.assertFalse(pricing.evaluate_product(room_fixture(), product, quote_fixture(source="demo"))["eligible"])

    def test_stale_quote_is_not_an_alert(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.assertFalse(pricing.evaluate_product(room_fixture(), product_fixture(), quote_fixture(observed_at=old))["eligible"])

    def test_no_observation_does_not_reuse_product_quote(self):
        product = product_fixture()
        product.update(price_eur=10, shipping_eur=0, availability="in_stock")
        self.assertFalse(pricing.evaluate_product(room_fixture(), product)["eligible"])

    def test_observation_validation_rejects_untrusted_money(self):
        for value in (True, float("nan"), float("inf"), -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    quote_fixture(price_eur=value)
        with self.assertRaises(ValueError):
            quote_fixture(currency="USD")

    def test_invalid_link_and_boolean_are_rejected(self):
        with self.assertRaises(ValueError):
            pricing.validate_product({"name": "Desk", "item_id": "missing"}, room_fixture())
        with self.assertRaises(ValueError):
            pricing.validate_product({"name": "Desk", "monitor": "false"}, room_fixture())
        with self.assertRaises(ValueError):
            quote_fixture(source_url="javascript:alert(1)")


class JSONLDTests(unittest.TestCase):
    def test_html_offer_without_delivery_inference(self):
        html = '<html><script type="application/ld+json">' + json.dumps(jsonld_fixture()) + '</script><p>SALE was 199</p></html>'
        result = pricing.parse_product_jsonld(html, "https://shop.example.org/desk")
        self.assertEqual(result["price_eur"], 79.99)
        self.assertEqual(result["availability"], "in_stock")
        self.assertIsNone(result["shipping_eur"])
        self.assertEqual(result["sku"], "DESK-OAK-110")

    def test_unrelated_script_with_valueless_type_is_ignored(self):
        html = '<script type>let price=1;</script><script type="application/ld+json">' + json.dumps(jsonld_fixture()) + '</script>'
        self.assertEqual(pricing.parse_product_jsonld(html)["price_eur"], 79.99)

    def test_graph_offer_reference(self):
        product = jsonld_fixture()
        offer = product.pop("offers")
        offer["@id"] = "#offer"
        product["offers"] = {"@id": "#offer"}
        result = pricing.parse_product_jsonld({"@graph": [product, offer]})
        self.assertEqual(result["price_eur"], 79.99)

    def test_nested_graph_and_single_offer_list(self):
        product = jsonld_fixture()
        product["offers"] = [product["offers"]]
        self.assertEqual(pricing.parse_product_jsonld({"wrapper": {"@graph": [product]}})["price_eur"], 79.99)

    def test_multiple_offers_and_products_are_ambiguous(self):
        product = jsonld_fixture()
        product["offers"] = [product["offers"], copy.deepcopy(product["offers"])]
        for fixture in (product, [jsonld_fixture(), jsonld_fixture()]):
            with self.subTest(fixture=fixture):
                with self.assertRaises(pricing.PriceFetchError):
                    pricing.parse_product_jsonld(fixture)

    def test_aggregate_variant_and_old_price_rejected(self):
        for change in ({"@type": "AggregateOffer", "lowPrice": 1}, {"price": None, "listPrice": 99}, {"priceValidUntil": "2020-01-01"}, {"availabilityStarts": "2099-01-01"}, {"validFrom": "2099-01-01"}, {"priceCurrency": "USD"}, {"price": "79,99"}):
            with self.subTest(change=change):
                product = jsonld_fixture()
                product["offers"].update(change)
                with self.assertRaises(pricing.PriceFetchError):
                    pricing.parse_product_jsonld(product)
        product = jsonld_fixture()
        product["@type"] = "ProductGroup"
        with self.assertRaises(pricing.PriceFetchError):
            pricing.parse_product_jsonld(product)

    def test_unsupported_stock_is_unknown(self):
        fixture = jsonld_fixture()
        fixture["offers"]["availability"] = "https://schema.org/PreOrder"
        self.assertEqual(pricing.parse_product_jsonld(fixture)["availability"], "unknown")

    def test_visible_prices_are_not_scraped(self):
        with self.assertRaises(pricing.PriceFetchError):
            pricing.parse_product_jsonld('<h1>Desk</h1><strong>Only 29.99 EUR</strong>')


class NetworkPolicyTests(unittest.TestCase):
    def setUp(self):
        pricing._last_fetch.clear()
        self.public_dns = [(2, 1, 6, "", ("93.184.216.34", 443))]

    def test_unsafe_urls_fail_before_dns(self):
        urls = ["http://retailer.example.org/item", "https://127.0.0.1/item", "https://[::1]/item",
                "https://localhost/item", "https://store.local/item", "https://user:secret@retailer.example.org/item",
                "https://retailer.example.org:8080/item", "https://retailer.example.org\\@localhost/item",
                "https://retailer.example.org/\nitem", "https://2130706433/item"]
        with patch.object(pricing.socket, "getaddrinfo") as dns:
            for url in urls:
                with self.subTest(url=url):
                    with self.assertRaises(pricing.PriceFetchError):
                        pricing.fetch_price(url)
            dns.assert_not_called()

    def test_mixed_public_and_private_dns_is_rejected(self):
        mixed = self.public_dns + [(2, 1, 6, "", ("10.0.0.5", 443))]
        with patch.object(pricing.socket, "getaddrinfo", return_value=mixed), patch.object(pricing, "_request_once") as request:
            with self.assertRaises(pricing.PriceFetchError):
                pricing.fetch_price("https://shop.example.org/item")
            request.assert_not_called()

    def test_multicast_dns_is_not_a_public_retailer(self):
        multicast = [(2, 1, 6, "", ("224.0.0.1", 443))]
        with patch.object(pricing.socket, "getaddrinfo", return_value=multicast), patch.object(pricing, "_request_once") as request:
            with self.assertRaises(pricing.PriceFetchError):
                pricing.fetch_price("https://shop.example.org/item")
            request.assert_not_called()

    def test_public_product_flow_checks_robots_and_pins_dns(self):
        calls = []
        def request(url, host, ip):
            calls.append((url, host, ip))
            if url.endswith("/robots.txt"):
                return pricing._Response(url, 200, {"content-type": "text/plain"}, b"User-agent: *\nAllow: /\n")
            return pricing._Response(url, 200, {"content-type": "text/html"}, ('<script type="application/ld+json">' + json.dumps(jsonld_fixture()) + '</script>').encode())
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=request):
            result = pricing.fetch_price("https://shop.example.org/item")
        self.assertEqual(result["price_eur"], 79.99)
        self.assertEqual([call[0] for call in calls], ["https://shop.example.org/robots.txt", "https://shop.example.org/item"])
        self.assertTrue(all(call[2] == "93.184.216.34" for call in calls))

    def test_robots_disallow_prevents_product_request(self):
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=lambda url, host, ip: pricing._Response(url, 200, {}, b"User-agent: *\nDisallow: /\n")) as request:
            with self.assertRaises(pricing.PriceFetchError):
                pricing.fetch_price("https://shop.example.org/item")
            self.assertEqual(request.call_count, 1)

    def test_robots_404_permits_but_unavailable_policy_blocks(self):
        def request(url, host, ip):
            if url.endswith("robots.txt"):
                return pricing._Response(url, 404, {}, b"")
            return pricing._Response(url, 200, {"content-type": "application/ld+json"}, json.dumps(jsonld_fixture()).encode())
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=request):
            self.assertEqual(pricing.fetch_price("https://shop.example.org/item")["price_eur"], 79.99)
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=lambda url, host, ip: pricing._Response(url, 503, {}, b"")):
            with self.assertRaises(pricing.PriceFetchError):
                pricing.fetch_price("https://shop.example.org/item")

    def test_redirect_to_private_address_is_blocked(self):
        def request(url, host, ip):
            return pricing._Response(url, 302, {"location": "https://127.0.0.1/private"}, b"")
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=request) as getter:
            with self.assertRaises(pricing.PriceFetchError):
                pricing._safe_get("https://shop.example.org/item")
            self.assertEqual(getter.call_count, 1)

    def test_product_redirect_checks_new_hosts_robots(self):
        calls = []
        def request(url, host, ip):
            calls.append(url)
            if url.endswith("robots.txt"):
                return pricing._Response(url, 200, {}, b"User-agent: *\nAllow: /\n")
            if host == "shop.example.org":
                return pricing._Response(url, 302, {"location": "https://second.example.org/desk"}, b"")
            return pricing._Response(url, 200, {"content-type": "application/json"}, json.dumps(jsonld_fixture()).encode())
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=request):
            result = pricing.fetch_price("https://shop.example.org/item")
        self.assertEqual(result["source_url"], "https://second.example.org/desk")
        self.assertEqual(calls, ["https://shop.example.org/robots.txt", "https://shop.example.org/item", "https://second.example.org/robots.txt", "https://second.example.org/desk"])

    def test_excessive_redirects_stop(self):
        with patch.object(pricing.socket, "getaddrinfo", return_value=self.public_dns), patch.object(pricing, "_request_once", side_effect=lambda url, host, ip: pricing._Response(url, 302, {"location": "/again"}, b"")) as request:
            with self.assertRaises(pricing.PriceFetchError):
                pricing._safe_get("https://shop.example.org/item")
            self.assertEqual(request.call_count, 4)

    def test_robots_crawl_delay_is_respected(self):
        with patch.object(pricing, "_safe_get", return_value=pricing._Response("", 200, {}, b"User-agent: *\nAllow: /\nCrawl-delay: 600\n")):
            pricing._robots_allowed("https://shop.example.org/item")
            with self.assertRaises(pricing.PriceFetchError):
                pricing._robots_allowed("https://shop.example.org/another")

    def test_robots_html_challenge_200_is_not_permission(self):
        for headers, body in (({"content-type": "text/html"}, b"<html>Checking your browser</html>"),
                              ({"content-type": "text/plain"}, b"<!DOCTYPE html><html>Challenge</html>"),
                              ({}, b"Please enable JavaScript and cookies"),
                              ({"content-type": "application/json"}, b'{"error":"blocked"}')):
            with self.subTest(headers=headers, body=body):
                with patch.object(pricing, "_safe_get", return_value=pricing._Response("", 200, headers, body)):
                    with self.assertRaises(pricing.PriceFetchError):
                        pricing._robots_allowed("https://shop.example.org/item")

    def test_empty_and_comment_only_plain_robots_are_valid(self):
        for body in (b"", b"# No crawler restrictions\n", b"\xef\xbb\xbfUser-agent: *\nAllow: /\n"):
            with self.subTest(body=body):
                with patch.object(pricing, "_safe_get", return_value=pricing._Response("", 200, {"content-type": "text/plain; charset=utf-8"}, body)):
                    pricing._robots_allowed("https://shop.example.org/item")

    def test_transport_does_not_send_cookies_or_credentials(self):
        response = Mock(status=200)
        response.getheaders.return_value = [("Content-Type", "text/html")]
        response.read1.side_effect = [b"hello", b""]
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(pricing, "_PinnedHTTPSConnection", return_value=connection):
            result = pricing._request_once("https://shop.example.org/item", "shop.example.org", "93.184.216.34")
        headers = connection.request.call_args.kwargs["headers"]
        self.assertNotIn("Cookie", headers)
        self.assertNotIn("Authorization", headers)
        self.assertEqual(result.body, b"hello")
        connection.close.assert_called_once()

    def test_transport_rejects_compressed_and_oversized_responses(self):
        for headers in ([("Content-Encoding", "gzip")], [("Content-Length", str(pricing.MAX_BYTES + 1))]):
            with self.subTest(headers=headers):
                response = Mock(status=200)
                response.getheaders.return_value = headers
                connection = Mock()
                connection.getresponse.return_value = response
                with patch.object(pricing, "_PinnedHTTPSConnection", return_value=connection):
                    with self.assertRaises(pricing.PriceFetchError):
                        pricing._request_once("https://shop.example.org/item", "shop.example.org", "93.184.216.34")
                response.read1.assert_not_called()
                connection.close.assert_called_once()

    def test_unknown_response_length_still_has_a_size_limit(self):
        response = Mock(status=200)
        response.getheaders.return_value = []
        response.read1.side_effect = lambda size: b"x" * size
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(pricing, "_PinnedHTTPSConnection", return_value=connection):
            with self.assertRaises(pricing.PriceFetchError):
                pricing._request_once("https://shop.example.org/item", "shop.example.org", "93.184.216.34")
        self.assertEqual(sum(call.args[0] for call in response.read1.call_args_list), pricing.MAX_BYTES + 1)

    def test_body_timeout_is_an_overall_deadline(self):
        response = Mock(status=200)
        response.getheaders.return_value = []
        connection = Mock()
        connection.getresponse.return_value = response
        with patch.object(pricing, "_PinnedHTTPSConnection", return_value=connection), patch.object(pricing.time, "monotonic", side_effect=[0, 11]):
            with self.assertRaises(pricing.PriceFetchError):
                pricing._request_once("https://shop.example.org/item", "shop.example.org", "93.184.216.34")
        response.read1.assert_not_called()

    def test_connection_close_keeps_deadline_on_response_socket(self):
        response = Mock(status=200)
        response.getheaders.return_value = []
        response.read1.side_effect = [b"hello", b""]
        connection = Mock()
        retained_socket = connection.sock
        def getresponse():
            connection.sock = None
            return response
        connection.getresponse.side_effect = getresponse
        with patch.object(pricing, "_PinnedHTTPSConnection", return_value=connection), patch.object(pricing.time, "monotonic", side_effect=[0, 3, 4]):
            self.assertEqual(pricing._request_once("https://shop.example.org/item", "shop.example.org", "93.184.216.34").body, b"hello")
        self.assertEqual([call.args[0] for call in retained_socket.settimeout.call_args_list], [7, 6])

    def test_tls_uses_pinned_ip_with_original_hostname(self):
        connection = pricing._PinnedHTTPSConnection("shop.example.org", "93.184.216.34")
        context = Mock()
        connection._context = context
        raw_socket = Mock()
        with patch.object(pricing.socket, "create_connection", return_value=raw_socket) as connect:
            connection.connect()
        connect.assert_called_once_with(("93.184.216.34", 443), 10)
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="shop.example.org")


if __name__ == "__main__":
    unittest.main()

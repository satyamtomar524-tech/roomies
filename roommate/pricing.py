"""A small price journal: explicit evidence in, explained decisions out.

The live adapter reads public Product/Offer JSON-LD only. It never signs in,
executes page scripts, guesses a delivery charge, or selects a product variant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import hashlib
import http.client
import ipaddress
import json
import math
import re
import socket
import ssl
import threading
import time
from typing import Any, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import uuid


USER_AGENT = "Roomies/2.0 (local student-flat price journal)"
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
MAX_QUOTE_AGE = timedelta(hours=24)
_rate_lock = threading.Lock()
_last_fetch: dict[str, float] = {}


class PriceFetchError(ValueError):
    """The source did not provide a safe, unambiguous current quote."""


def _text(value: Any, field: str, *, required: bool = False, limit: int = 500) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text.")
    value = value.strip()
    if len(value) > limit or any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise ValueError(f"{field} is too long or contains control characters.")
    if required and not value:
        raise ValueError(f"{field} is required.")
    return value


def _number(value: Any, field: str, *, positive: bool = False) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number.")
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{field} must be a number.") from error
    if not math.isfinite(result) or result < 0 or result > 100000:
        raise ValueError(f"{field} must be between 0 and 100000.")
    if positive and result == 0:
        raise ValueError(f"{field} must be greater than zero.")
    return round(result, 4)


def _boolean(value: Any, field: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be true or false.")
    return value


def _availability(value: Any) -> str:
    if value not in ("in_stock", "out_of_stock", "unknown"):
        raise ValueError("availability must be in_stock, out_of_stock, or unknown.")
    return value


def _public_url(url: str) -> tuple[str, str]:
    """Validate syntax before DNS; HTTPS alone is not an SSRF boundary."""
    if not isinstance(url, str) or not url or len(url) > 4096:
        raise PriceFetchError("Enter a public HTTPS product URL.")
    if any(ord(char) <= 32 for char in url) or "\\" in url:
        raise PriceFetchError("The product URL contains unsafe characters.")
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port
    except ValueError as error:
        raise PriceFetchError("The product URL is invalid.") from error
    if parts.scheme.lower() != "https" or not host or port not in (None, 443):
        raise PriceFetchError("Only public HTTPS URLs on port 443 are supported.")
    if parts.username is not None or parts.password is not None:
        raise PriceFetchError("Product URLs cannot contain credentials.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise PriceFetchError("IP-address product URLs are not supported.")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise PriceFetchError("The product hostname is invalid.") from error
    if (
        len(host) > 253
        or "." not in host
        or host.endswith((".local", ".localhost", ".internal", ".home", ".lan", ".test", ".invalid", ".example", ".onion"))
        or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split("."))
    ):
        raise PriceFetchError("The product must be on a public retailer hostname.")
    clean = urlunsplit(("https", host, parts.path or "/", parts.query, ""))
    return clean, host


def validate_product(data: dict[str, Any], room: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Product must be an object.")
    item_id = _text(data.get("item_id"), "item_id", limit=100)
    if item_id and not any(item.get("id") == item_id for item in room.get("items", [])):
        raise ValueError("Choose a reservation that exists in this room.")
    url = _text(data.get("url"), "url", limit=4096)
    if url:
        url, _ = _public_url(url)
    monitor = _boolean(data.get("monitor"), "monitor")
    if monitor and not url:
        raise ValueError("A public product URL is required to monitor a product.")
    result = {
        "id": _text(data.get("id") or uuid.uuid4().hex, "id", required=True, limit=100),
        "name": _text(data.get("name"), "name", required=True, limit=150),
        "url": url,
        "item_id": item_id or None,
        "retailer": _text(data.get("retailer"), "retailer", limit=100),
        "variant": _text(data.get("variant"), "variant", limit=150),
        "sku": _text(data.get("sku"), "sku", limit=150),
        "color": _text(data.get("color"), "color", limit=100),
        "identity_notes": _text(data.get("identity_notes", data.get("notes")), "identity_notes", limit=1000),
        "variant_confirmed": _boolean(data.get("variant_confirmed"), "variant_confirmed"),
        "rotation_allow90": _boolean(data.get("rotation_allow90"), "rotation_allow90", True),
        "monitor": monitor,
        "is_demo": _boolean(data.get("is_demo"), "is_demo"),
        "availability": _availability(data.get("availability", "unknown")),
    }
    for field in ("width_cm", "depth_cm", "height_cm"):
        result[field] = _number(data.get(field), field, positive=True)
    for field in ("price_eur", "shipping_eur", "target_eur"):
        result[field] = _number(data.get(field), field)
    return result


def validate_observation(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Observation must be an object.")
    price = _number(data.get("price_eur"), "price_eur")
    if price is None:
        raise ValueError("An observation needs an explicit price in EUR.")
    if data.get("currency", "EUR") != "EUR":
        raise ValueError("Only explicit EUR observations are supported.")
    source = data.get("source", "manual")
    if source not in ("manual", "jsonld", "demo"):
        raise ValueError("Unknown observation source.")
    observed_at = data.get("observed_at") or datetime.now(timezone.utc).isoformat()
    try:
        stamp = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observed_at must be an ISO timestamp with a timezone.") from error
    if stamp.tzinfo is None:
        raise ValueError("observed_at must include a timezone.")
    if stamp > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("An observation cannot be dated in the future.")
    result = {
        "price_eur": round(price, 2),
        "shipping_eur": _number(data.get("shipping_eur"), "shipping_eur"),
        "availability": _availability(data.get("availability", "unknown")),
        "source": source,
        "source_url": _text(data.get("source_url"), "source_url", limit=4096),
        "observed_at": stamp.astimezone(timezone.utc).isoformat(),
        "note": _text(data.get("note", data.get("notes")), "note", limit=1000),
    }
    if result["source_url"]:
        result["source_url"], _ = _public_url(result["source_url"])
    if "variant_confirmed" in data:
        result["variant_confirmed"] = _boolean(data.get("variant_confirmed"), "variant_confirmed")
    if data.get("is_demo") is True:
        result["source"] = "demo"
    for field in ("product_name", "sku", "color"):
        if field in data:
            result[field] = _text(data[field], field, limit=250)
    if data.get("product_signature"):
        signature = _text(data["product_signature"], "product_signature", limit=64)
        if not re.fullmatch(r"[a-f0-9]{64}", signature):
            raise ValueError("The observation's product identity is invalid.")
        result["product_signature"] = signature
    if data.get("requested_product_url"):
        result["requested_product_url"], _ = _public_url(data["requested_product_url"])
    return result


def product_signature(product: dict[str, Any]) -> str:
    """Bind quote confirmation to the saved product identity, rather than its editable label."""
    fields = ("item_id", "url", "width_cm", "depth_cm", "height_cm", "variant", "sku", "color", "retailer")
    identity = {field: product.get(field) for field in fields}
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def evaluate_product(room: dict[str, Any], product: dict[str, Any], observation: dict[str, Any] | None = None) -> dict[str, Any]:
    from .geometry import analyse_room

    reasons: list[str] = []
    fit = "unknown"
    item = next((value for value in room.get("items", []) if value.get("id") == product.get("item_id")), None)
    if item is None:
        reasons.append("Link this product to a planned space before checking its fit.")
    elif item.get("status") != "planned":
        fit = "fail"
        reasons.append("This space belongs to an owned item; choose a planned reservation.")
    else:
        dimensions = ("width_cm", "depth_cm", "height_cm")
        if any(product.get(field) is None or item.get(field) is None for field in dimensions):
            reasons.append("Confirm the product's full width, depth, and height, and the reservation's limits.")
        else:
            width, depth, height = (product[field] for field in dimensions)
            slot_width, slot_depth, slot_height = (item[field] for field in dimensions)
            straight = width <= slot_width and depth <= slot_depth
            rotated = product.get("rotation_allow90", True) and item.get("placement") != "wall" and depth <= slot_width and width <= slot_depth
            fit = "pass" if (straight or rotated) and height <= slot_height else "fail"
            reasons.append("Fits the reserved dimensions." if fit == "pass" else "The product exceeds this reservation's dimensions.")
        relevant_ids = {item.get("id"), item.get("parent_id")}
        errors = [issue for issue in analyse_room(room)["issues"] if issue.get("severity") == "error" and (issue.get("item_id") in relevant_ids or issue.get("item_id") is None)]
        if errors:
            fit = "fail"
            reasons.append("Resolve this reservation's layout conflict before buying: " + errors[0]["message"])

    quote = observation or {}
    price, shipping = quote.get("price_eur"), quote.get("shipping_eur")
    delivered = round(price + shipping, 2) if price is not None and shipping is not None else None
    target = product.get("target_eur")
    if target is None and item:
        target = item.get("target_eur")
    below = delivered <= target if delivered is not None and target is not None else None
    availability = quote.get("availability", "unknown")
    if price is None:
        reasons.append("Record a current price.")
    if shipping is None:
        reasons.append("Confirm delivery cost for your address; unknown delivery is not free delivery.")
    if target is None:
        reasons.append("Set a delivered-price target.")
    elif below is False:
        reasons.append("The delivered price is above your target.")
    if availability != "in_stock":
        reasons.append("The item is out of stock." if availability == "out_of_stock" else "Confirm the exact variant is in stock.")
    # Manual confirmation applies to that quote. A fetched offer needs the saved retailer SKU as evidence.
    if quote.get("source") == "jsonld":
        confirmed = (
            product.get("variant_confirmed") is True
            and bool(product.get("sku"))
            and product.get("sku") == quote.get("sku")
            and bool(product.get("url"))
            and quote.get("requested_product_url") == product.get("url")
            and quote.get("product_signature") == product_signature(product)
        )
        if not confirmed:
            reasons.append("For live notices, confirm the saved variant and retailer SKU; the fetched SKU and product link must match.")
    else:
        confirmed = quote.get("variant_confirmed", product.get("variant_confirmed", False)) is True
    identity_matches = True
    if quote.get("product_signature") and quote["product_signature"] != product_signature(product):
        identity_matches = False
        confirmed = False
        reasons.append("The product identity changed after this quote. Record a quote for the current variant.")
    quoted_url = quote.get("requested_product_url") or quote.get("source_url")
    if product.get("url") and quoted_url:
        try:
            identity_matches = identity_matches and _public_url(product["url"])[0] == _public_url(quoted_url)[0]
        except PriceFetchError:
            identity_matches = False
        if not identity_matches:
            confirmed = False
            reasons.append("This quote's product link does not match the saved product link.")
    if product.get("color") and quote.get("color") and product["color"].casefold() != quote["color"].casefold():
        confirmed = False
        reasons.append("The page's product color differs from the saved variant.")
    if not confirmed:
        reasons.append("Confirm the product link, dimensions, and selected variant match.")
    fresh = False
    if quote.get("observed_at"):
        try:
            stamp = datetime.fromisoformat(str(quote["observed_at"]).replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - stamp
            fresh = stamp.tzinfo is not None and -timedelta(minutes=5) <= age <= MAX_QUOTE_AGE
        except (ValueError, TypeError):
            pass
    if not fresh:
        reasons.append("Log or check a fresh quote; prices older than 24 hours cannot trigger an upgrade alert.")
    room_demo = room.get("is_demo") is True
    demo = room_demo or product.get("is_demo") is True or quote.get("source") == "demo"
    if room_demo:
        reasons.append("Confirm your room measurements and turn off the sample-room flag before using upgrade recommendations.")
    if product.get("is_demo") is True or quote.get("source") == "demo":
        reasons.append("Example product and prices: this is not a shopping recommendation.")
    eligible = fit == "pass" and below is True and availability == "in_stock" and confirmed and fresh and not demo
    can_price_drop_notice = fit == "pass" and price is not None and availability == "in_stock" and confirmed and fresh and not demo
    if eligible:
        reasons.append("Fits your plan and delivered-price target. Recheck the retailer before purchasing.")
    return {"fit": fit, "eligible": eligible, "can_price_drop_notice": can_price_drop_notice, "reasons": reasons, "delivered_eur": delivered, "below_target": below, "availability": availability, "variant_confirmed": confirmed, "fresh": fresh}


class _JSONLDScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.active = False
        self.chunks: list[str] = []
        self.documents: list[Any] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            self.active = (dict(attrs).get("type") or "").lower().split(";")[0].strip() == "application/ld+json"
            self.chunks = []

    def handle_data(self, data: str) -> None:
        if self.active:
            self.chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.active:
            self.active = False
            try:
                self.documents.append(json.loads("".join(self.chunks)))
            except (ValueError, RecursionError):
                raise PriceFetchError("The page contains invalid Product JSON-LD.")


def _type(node: dict[str, Any], name: str) -> bool:
    value = node.get("@type", [])
    values = value if isinstance(value, list) else [value]
    return any(isinstance(entry, str) and entry.rsplit("/", 1)[-1].rsplit(":", 1)[-1] == name for entry in values)


def _price(value: Any) -> float:
    if isinstance(value, bool) or not re.fullmatch(r"\d+(?:\.\d{1,4})?", str(value)):
        raise PriceFetchError("The offer does not contain one explicit numeric EUR price.")
    try:
        price = Decimal(str(value))
    except InvalidOperation as error:
        raise PriceFetchError("The offer price is invalid.") from error
    if not price.is_finite() or price < 0 or price > 100000:
        raise PriceFetchError("The offer price is outside the supported range.")
    return float(price.quantize(Decimal("0.01")))


def parse_product_jsonld(document: str | dict[str, Any] | list[Any], source_url: str = "") -> dict[str, Any]:
    """Accept HTML or decoded JSON-LD; never scrape visible sale labels."""
    if isinstance(document, str):
        if len(document.encode("utf-8")) > MAX_BYTES:
            raise PriceFetchError("The product page exceeds the 2 MB limit.")
        if document.lstrip().startswith(("{", "[")):
            try:
                documents = [json.loads(document)]
            except (ValueError, RecursionError) as error:
                raise PriceFetchError("Invalid JSON-LD.") from error
        else:
            parser = _JSONLDScripts()
            parser.feed(document)
            documents = parser.documents
    else:
        documents = [document]
    nodes: list[dict[str, Any]] = []
    stack: list[Any] = list(documents)
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            nodes.append(node)
            stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
        elif isinstance(node, list):
            stack.extend(node)
        if len(nodes) + len(stack) > 10000:
            raise PriceFetchError("Product metadata is too complex.")
    by_id = {node["@id"]: node for node in nodes if isinstance(node.get("@id"), str) and len(node) > 1}
    products = [node for node in nodes if _type(node, "Product")]
    if len(products) != 1 or any(_type(node, "ProductGroup") for node in nodes):
        raise PriceFetchError("The page must describe exactly one Product, without a variant group.")
    product = products[0]
    offers = product.get("offers")
    if isinstance(offers, list):
        if len(offers) != 1:
            raise PriceFetchError("Multiple offers or variants need a manual quote.")
        offers = offers[0]
    if isinstance(offers, dict) and set(offers) == {"@id"}:
        offers = by_id.get(offers["@id"])
    if not isinstance(offers, dict) or not _type(offers, "Offer") or _type(offers, "AggregateOffer"):
        raise PriceFetchError("A single explicit Offer is required; price ranges are not supported.")
    if offers.get("priceCurrency") != "EUR":
        raise PriceFetchError("Only explicit EUR offers are supported.")
    for field in ("priceValidUntil", "validThrough", "availabilityEnds", "validFrom", "availabilityStarts"):
        if not offers.get(field):
            continue
        try:
            stamp = datetime.fromisoformat(str(offers[field]).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            end = field in ("priceValidUntil", "validThrough", "availabilityEnds")
            if end and len(str(offers[field])) == 10:
                stamp += timedelta(days=1)
        except ValueError as error:
            raise PriceFetchError("The offer's validity date cannot be verified.") from error
        now = datetime.now(timezone.utc)
        if (end and stamp < now) or (not end and stamp > now):
            raise PriceFetchError("This published offer is not currently valid.")
    availability = str(offers.get("availability", "")).rsplit("/", 1)[-1]
    stock = "in_stock" if availability == "InStock" else "out_of_stock" if availability in ("OutOfStock", "SoldOut", "Discontinued") else "unknown"
    return validate_observation({
        "price_eur": _price(offers.get("price")),
        "shipping_eur": None,
        "availability": stock,
        "source": "jsonld",
        "source_url": source_url,
        "note": "Public structured offer. Delivery cost and the exact variant must be checked by you.",
        "product_name": product.get("name", ""),
        "sku": str(product.get("sku", "")),
        "color": product.get("color", "") if isinstance(product.get("color", ""), str) else "",
    })


@dataclass(frozen=True)
class _Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, hostname: str, ip: str) -> None:
        super().__init__(hostname, 443, timeout=10, context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self) -> None:
        # Validate DNS once and connect to that address; SNI/certificate still use the retailer's hostname.
        raw = socket.create_connection((self.pinned_ip, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _resolve_public(host: str) -> list[str]:
    try:
        addresses = list(dict.fromkeys(entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    except OSError as error:
        raise PriceFetchError("The retailer hostname could not be resolved.") from error
    parsed = [ipaddress.ip_address(address) for address in addresses]
    if not parsed or any(not address.is_global or address.is_multicast or address.is_reserved for address in parsed):
        raise PriceFetchError("The retailer hostname resolves to a non-public address.")
    return addresses


def _request_once(url: str, host: str, ip: str) -> _Response:
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    connection = _PinnedHTTPSConnection(host, ip)
    try:
        connection.request("GET", path, headers={"Host": host, "User-Agent": USER_AGENT, "Accept": "text/html,application/ld+json,text/plain", "Accept-Encoding": "identity", "Connection": "close"})
        # getresponse() may clear connection.sock for Connection: close while its file keeps it alive.
        read_socket = connection.sock
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        if headers.get("content-encoding", "identity").lower() != "identity":
            raise PriceFetchError("Compressed product responses are not supported.")
        length = headers.get("content-length")
        if length and (not length.isdigit() or int(length) > MAX_BYTES):
            raise PriceFetchError("The response exceeds the 2 MB limit.")
        chunks = []
        received = 0
        deadline = time.monotonic() + 10
        while received <= MAX_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PriceFetchError("The public page exceeded the 10-second body timeout.")
            # read1 performs one buffered/socket read; a slow stream cannot reset the overall deadline.
            if read_socket is None:
                raise PriceFetchError("The response stream has no supported socket timeout.")
            read_socket.settimeout(remaining)
            chunk = response.read1(min(65536, MAX_BYTES + 1 - received))
            if not chunk:
                break
            chunks.append(chunk)
            received += len(chunk)
        body = b"".join(chunks)
        if len(body) > MAX_BYTES:
            raise PriceFetchError("The response exceeds the 2 MB limit.")
        return _Response(url, response.status, headers, body)
    except (OSError, http.client.HTTPException, UnicodeError) as error:
        raise PriceFetchError("The public page could not be read safely. Record a manual quote instead.") from error
    finally:
        connection.close()


def _safe_get(url: str, *, authorize: Callable[[str], None] | None = None) -> _Response:
    for hop in range(MAX_REDIRECTS + 1):
        url, host = _public_url(url)
        addresses = _resolve_public(host)
        if authorize:
            authorize(url)
        response = _request_once(url, host, addresses[0])
        if response.status not in (301, 302, 303, 307, 308):
            return response
        location = response.headers.get("location")
        if not location or hop == MAX_REDIRECTS:
            raise PriceFetchError("The page has too many redirects or an invalid redirect.")
        url = urljoin(url, location)
    raise PriceFetchError("The page has too many redirects.")


def _robots_allowed(url: str) -> None:
    parts = urlsplit(url)
    origin = f"https://{parts.netloc}"
    robots = _safe_get(origin + "/robots.txt")
    if robots.status == 404:
        return
    if robots.status != 200:
        raise PriceFetchError("The retailer's robots policy could not be checked; use a manual quote.")
    content_type = robots.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("", "text/plain"):
        raise PriceFetchError("The retailer returned an unsupported robots policy response; use a manual quote.")
    try:
        policy = robots.body.decode("utf-8-sig")
    except UnicodeError as error:
        raise PriceFetchError("The retailer's robots policy is not supported UTF-8 text.") from error
    lines = policy.splitlines()
    active_lines = [line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()]
    recognized = ("user-agent", "allow", "disallow", "crawl-delay", "request-rate", "sitemap", "host")
    if active_lines and (
        any(line.startswith(("<", "{", "[")) for line in active_lines)
        or not any(line.split(":", 1)[0].strip().lower() in recognized and ":" in line for line in active_lines)
    ):
        raise PriceFetchError("The retailer returned a challenge or invalid robots policy; use a manual quote.")
    parser = RobotFileParser(origin + "/robots.txt")
    parser.parse(lines)
    if not parser.can_fetch(USER_AGENT, url):
        raise PriceFetchError("This retailer disallows automated access to this page.")
    delay = float(parser.crawl_delay(USER_AGENT) or 0)
    rate = parser.request_rate(USER_AGENT)
    if rate and rate.requests:
        delay = max(delay, rate.seconds / rate.requests)
    with _rate_lock:
        now = time.monotonic()
        wait = delay - (now - _last_fetch.get(origin, -math.inf))
        if wait > 0:
            raise PriceFetchError(f"The retailer asks for a slower check rate. Retry in {math.ceil(wait)} seconds.")
        _last_fetch[origin] = now


def fetch_price(url: str) -> dict[str, Any]:
    response = _safe_get(url, authorize=_robots_allowed)
    if response.status != 200:
        raise PriceFetchError(f"The retailer returned HTTP {response.status}. Record a manual quote instead.")
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("text/html", "application/xhtml+xml", "application/ld+json", "application/json"):
        raise PriceFetchError("The response is not an HTML or JSON-LD product page.")
    try:
        document = response.body.decode("utf-8")
    except UnicodeError as error:
        raise PriceFetchError("The page does not provide supported UTF-8 metadata.") from error
    observation = parse_product_jsonld(document, response.url)
    observation["requested_product_url"] = _public_url(url)[0]
    return observation


def check_price(product: dict[str, Any] | str) -> dict[str, Any]:
    """Convenience adapter for the local tracker."""
    return fetch_price(product["url"] if isinstance(product, dict) else product)

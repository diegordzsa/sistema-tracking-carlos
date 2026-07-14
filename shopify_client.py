"""Shopify Admin API client — orders, UTM attribution, COD detection, fulfillment."""
import logging
import time
from urllib.parse import urlparse, parse_qs
from typing import Any

import requests

import config

logger = logging.getLogger(__name__)

_cached_token: str | None = None


def _get_access_token() -> str:
    global _cached_token
    if _cached_token:
        return _cached_token

    url = f"https://{config.SHOPIFY_STORE_DOMAIN}/admin/oauth/access_token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": config.SHOPIFY_CLIENT_ID,
        "client_secret": config.SHOPIFY_CLIENT_SECRET,
    }, timeout=10)
    resp.raise_for_status()
    _cached_token = resp.json()["access_token"]
    return _cached_token


def _api_get(endpoint: str, params: dict[str, Any] | None = None) -> requests.Response:
    token = _get_access_token()
    url = f"https://{config.SHOPIFY_STORE_DOMAIN}/admin/api/{config.SHOPIFY_API_VERSION}/{endpoint}"
    resp = requests.get(url, headers={
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
    }, params=params, timeout=30)
    resp.raise_for_status()
    return resp


def fetch_orders(start_date: str, end_date: str) -> list[dict]:
    """Fetch all orders in a date range. Dates in ISO 8601 format."""
    all_orders: list[dict] = []
    params = {
        "created_at_min": start_date,
        "created_at_max": end_date,
        "status": "any",
        "limit": 250,
    }

    while True:
        resp = _api_get("orders.json", params)
        data = resp.json()
        orders = data.get("orders", [])
        all_orders.extend(orders)

        link_header = resp.headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break

        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split("<")[1].split(">")[0]
                parsed = urlparse(next_url)
                params = dict(parse_qs(parsed.query))
                params = {k: v[0] for k, v in params.items()}
                break

        time.sleep(0.5)

    return all_orders


def _get_utm_params(order: dict) -> dict[str, str]:
    """Parse UTM parameters from landing_site."""
    landing = order.get("landing_site") or ""
    try:
        qs = parse_qs(urlparse(landing).query)
        return {k: v[0] for k, v in qs.items() if k.startswith("utm_")}
    except Exception:
        return {}


def is_carlos_order(order: dict) -> bool:
    """Check if the order is attributed to Carlos.

    Detection methods (in priority order):
    1. UTM: utm_campaign contains 'carlos' (excluding Klaviyo/email sources)
    2. Tags: order tagged with closer tag matching CLOSER_TAG config
    3. Draft orders with matching closer tag
    """
    utms = _get_utm_params(order)
    campaign = (utms.get("utm_campaign") or "").lower()
    source = (utms.get("utm_source") or "").lower()

    if "carlos" in campaign and source not in ("klaviyo",):
        return True

    tags = (order.get("tags") or "").lower()
    if config.CLOSER_TAG.lower() in tags:
        return True

    return False


def get_utm_medium(order: dict) -> str | None:
    """Extract utm_medium from the order's landing_site."""
    return _get_utm_params(order).get("utm_medium")


def filter_carlos_orders(orders: list[dict]) -> list[dict]:
    """Filter orders attributed to Carlos via UTM or tags."""
    return [o for o in orders if is_carlos_order(o)]


def classify_payment_type(order: dict) -> str:
    """Returns 'cod' for cash on delivery, 'paid' for prepaid orders.

    COD detection: draft orders with empty gateways, or pending financial status
    on fulfilled orders.
    """
    gateways = order.get("payment_gateway_names", [])

    if not gateways and order.get("source_name") == "shopify_draft_order":
        return "cod"

    if order.get("financial_status") == "pending" and not gateways:
        return "cod"

    return "paid"


def is_cod_delivered(order: dict) -> bool:
    """Check if a COD order has been delivered and paid.

    Correos Express doesn't report shipment_status to Shopify,
    so we check if financial_status changed from pending to paid.
    """
    if classify_payment_type(order) != "cod":
        return False
    return order.get("financial_status") == "paid"


def is_cod_returned(order: dict) -> bool:
    """Check if a COD order was returned."""
    tags = (order.get("tags") or "").lower()
    if "pagado devuelto" in tags:
        return True
    if classify_payment_type(order) == "cod" and float(order.get("total_price", "0")) == 0:
        return True
    return False


def get_fulfillment_info(order: dict) -> dict:
    """Extract fulfillment and shipment status from an order."""
    fulfillments = order.get("fulfillments", [])
    if not fulfillments:
        return {
            "fulfillment_status": order.get("fulfillment_status"),
            "shipment_status": None,
            "tracking_company": None,
            "tracking_number": None,
            "tracking_url": None,
        }

    latest = fulfillments[-1]
    return {
        "fulfillment_status": order.get("fulfillment_status"),
        "shipment_status": latest.get("shipment_status"),
        "tracking_company": latest.get("tracking_company"),
        "tracking_number": (latest.get("tracking_numbers") or [None])[0],
        "tracking_url": (latest.get("tracking_urls") or [None])[0],
    }


def get_cod_delivery_status(order: dict) -> str:
    """Determine COD delivery status based on Shopify data.

    Returns: 'delivered', 'returned', 'pending', 'shipped', or 'unknown'.
    """
    if is_cod_returned(order):
        return "returned"

    financial = order.get("financial_status", "")
    fulfillment = order.get("fulfillment_status")

    if financial == "paid":
        return "delivered"

    if fulfillment == "fulfilled" and financial == "pending":
        return "shipped"

    if financial == "pending" and fulfillment is None:
        return "pending"

    return "unknown"


def fetch_order_by_id(order_id: int) -> dict | None:
    """Fetch a single order by ID to get updated data."""
    try:
        resp = _api_get(f"orders/{order_id}.json")
        return resp.json().get("order")
    except requests.HTTPError as e:
        logger.warning("Failed to fetch order %s: %s", order_id, e)
        return None


def build_order_record(order: dict) -> dict:
    """Build a normalized record from a Shopify order for storage."""
    fulfillment = get_fulfillment_info(order)
    payment_type = classify_payment_type(order)

    line_items = [
        f"{li['title']} x{li['quantity']}"
        for li in order.get("line_items", [])
    ]

    cod_status = get_cod_delivery_status(order) if payment_type == "cod" else None

    return {
        "order_id": order["id"],
        "order_number": order.get("name", ""),
        "created_at": order.get("created_at", ""),
        "customer_name": _customer_name(order),
        "landing_site": order.get("landing_site") or "",
        "source_name": order.get("source_name", ""),
        "tags": order.get("tags", ""),
        "utm_medium": get_utm_medium(order),
        "utm_campaign": _get_utm_params(order).get("utm_campaign"),
        "payment_type": payment_type,
        "payment_gateway": ", ".join(order.get("payment_gateway_names", [])),
        "financial_status": order.get("financial_status", ""),
        "total_price": order.get("total_price", "0.00"),
        "currency": order.get("currency", config.CURRENCY),
        "line_items": line_items,
        "fulfillment_status": fulfillment["fulfillment_status"],
        "shipment_status": fulfillment["shipment_status"],
        "tracking_company": fulfillment["tracking_company"],
        "tracking_number": fulfillment["tracking_number"],
        "tracking_url": fulfillment["tracking_url"],
        "cod_delivery_status": cod_status,
        "cod_verified": cod_status == "delivered",
    }


def _customer_name(order: dict) -> str:
    customer = order.get("customer") or {}
    first = customer.get("first_name", "")
    last = customer.get("last_name", "")
    return f"{first} {last}".strip() or "N/A"

"""Zadarma API client — call statistics, recordings, phone correlation."""
import base64
import hashlib
import hmac
import logging
import re
import time
from collections import Counter
from urllib.parse import urlencode

import requests

import config

logger = logging.getLogger(__name__)

API_BASE = "https://api.zadarma.com"


def _build_signature(method: str, params: dict) -> str:
    sorted_params = sorted(params.items())
    param_str = urlencode(sorted_params)
    sign_str = method + param_str + hashlib.md5(param_str.encode("utf-8")).hexdigest()
    hmac_h = hmac.new(
        config.ZADARMA_API_SECRET.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha1,
    )
    signature = base64.b64encode(hmac_h.hexdigest().encode("utf-8")).decode()
    return signature


def _api_request(method: str, params: dict | None = None) -> dict:
    params = params or {}
    signature = _build_signature(method, params)
    url = f"{API_BASE}{method}"
    resp = requests.get(url, params=params, headers={
        "Authorization": f"{config.ZADARMA_API_KEY}:{signature}",
    }, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") == "error":
        raise RuntimeError(f"Zadarma API error: {data.get('message', 'unknown')}")
    return data


def fetch_calls(start: str, end: str) -> list[dict]:
    """Fetch call statistics for Carlos's SIP extension.

    start/end format: YYYY-MM-DD HH:MM:SS
    """
    all_calls: list[dict] = []
    skip = 0
    limit = 1000

    while True:
        params = {
            "start": start,
            "end": end,
            "sip": config.ZADARMA_SIP,
            "skip": str(skip),
            "limit": str(limit),
        }
        data = _api_request("/v1/statistics/", params)
        stats = data.get("stats", [])
        all_calls.extend(stats)

        if len(stats) < limit:
            break

        skip += limit
        time.sleep(20)

    logger.info("Fetched %d calls from Zadarma (%s to %s)", len(all_calls), start, end)
    return all_calls


def get_recording_url(call_id: str) -> str | None:
    """Request a temporary download link for a call recording."""
    try:
        data = _api_request("/v1/pbx/record/request/", {"call_id": call_id})
        return data.get("link") or (data.get("links") or [None])[0]
    except Exception as e:
        logger.debug("No recording for call %s: %s", call_id, e)
        return None


def normalize_phone(number) -> str:
    """Normalize a phone number to E.164 format (+34XXXXXXXXX for Spain)."""
    if not number:
        return ""
    number = str(number)
    cleaned = re.sub(r"[\s\-\(\)\.]", "", number)
    if cleaned.startswith("0034"):
        cleaned = "+" + cleaned[2:]
    elif cleaned.startswith("34") and len(cleaned) >= 11:
        cleaned = "+" + cleaned
    elif cleaned.startswith(("6", "7", "9")) and len(cleaned) == 9:
        cleaned = "+34" + cleaned
    if not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    return cleaned


def _detect_company_number(raw_calls: list[dict]) -> str:
    """Detect the company outgoing number (most frequent 'from' value)."""
    if not raw_calls:
        return ""
    from_counter = Counter(str(c.get("from", "")) for c in raw_calls)
    return from_counter.most_common(1)[0][0]


def build_call_records(raw_calls: list[dict]) -> list[dict]:
    """Convert a batch of raw Zadarma entries to internal format.

    Uses the batch to auto-detect the company outgoing number for direction.
    """
    company_phone = normalize_phone(_detect_company_number(raw_calls))
    return [_build_single_record(raw, company_phone) for raw in raw_calls]


def _build_single_record(raw: dict, company_phone: str) -> dict:
    caller = normalize_phone(raw.get("from", ""))
    callee = normalize_phone(raw.get("to", ""))

    if caller == company_phone:
        direction = "outbound"
        customer_phone = callee
    else:
        direction = "inbound"
        customer_phone = caller

    disposition = raw.get("disposition", "").lower().replace(" ", "_")

    return {
        "call_id": str(raw.get("id", "")),
        "sip": str(raw.get("sip", "")),
        "direction": direction,
        "caller": caller,
        "callee": callee,
        "customer_phone": customer_phone,
        "started_at": raw.get("callstart", ""),
        "duration_seconds": int(raw.get("billseconds", 0)),
        "disposition": disposition,
        "cost": float(raw.get("billcost", 0)),
        "recording_available": False,
        "matched_order_id": None,
        "matched_order_number": None,
    }


def correlate_calls_with_orders(calls: list[dict], orders: list[dict]) -> list[dict]:
    """Match calls to orders by customer phone number."""
    phone_to_order: dict[str, dict] = {}
    for order in orders:
        phone = normalize_phone(order.get("customer_phone", ""))
        if phone:
            phone_to_order[phone] = order

    matched = 0
    for call in calls:
        customer_phone = call.get("customer_phone", "")
        if customer_phone and customer_phone in phone_to_order:
            order = phone_to_order[customer_phone]
            call["matched_order_id"] = order.get("order_id")
            call["matched_order_number"] = order.get("order_number")
            matched += 1

    logger.info("Correlated %d/%d calls with orders", matched, len(calls))
    return calls

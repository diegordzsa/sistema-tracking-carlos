"""Correos Express tracking scraper — checks real delivery status."""
import html
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

TRACKING_URL = "https://s.correosexpress.com/SeguimientoSinCP/search"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

STATUS_MAP = {
    "ENTREGADO": "delivered",
    "EN REPARTO": "out_for_delivery",
    "EN DESTINO": "at_destination",
    "EN RUTA": "in_transit",
    "ADMITIDO": "shipped",
    "INFORMADO": "info_received",
    "DEVUELTO": "returned",
    "EN ALMAC": "returned",
    "REHUSADO": "returned",
    "PARADO": "returned",
    "INCIDENCIA": "incident",
    "AUSENTE": "failed_attempt",
}


def check_tracking(tracking_number: str) -> dict | None:
    """Fetch tracking status from Correos Express.

    Returns dict with keys: status, status_raw, progress, location,
    date, events_count, description. Returns None on failure.
    """
    try:
        resp = requests.get(
            TRACKING_URL,
            params={"n": tracking_number},
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("Failed to fetch tracking %s: %s", tracking_number, e)
        return None

    page = resp.text

    progress_match = re.search(r"data-progress='(\d+)'", page)
    progress = int(progress_match.group(1)) if progress_match else None

    rows = re.findall(
        r"<tr>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>",
        page,
    )

    if not rows:
        logger.warning("No tracking events found for %s", tracking_number)
        return None

    date_raw, location, description_raw = [html.unescape(c.strip()) for c in rows[0]]
    status_raw = description_raw.split(".")[0].strip()

    status = "unknown"
    for keyword, mapped in STATUS_MAP.items():
        if keyword in status_raw.upper():
            status = mapped
            break

    return {
        "status": status,
        "status_raw": status_raw,
        "progress": progress,
        "location": location,
        "date": date_raw,
        "description": description_raw,
        "events_count": len(rows),
    }


def check_multiple(tracking_numbers: list[str], delay: float = 1.0) -> dict[str, dict]:
    """Check multiple tracking numbers with rate limiting."""
    results = {}
    for tn in tracking_numbers:
        result = check_tracking(tn)
        if result:
            results[tn] = result
        time.sleep(delay)
    return results

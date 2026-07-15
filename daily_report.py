"""Daily report: fetch yesterday's orders, filter by UTM, report to Slack."""
import logging
from collections import Counter
from datetime import datetime, timedelta

import config
import shopify_client
import order_store
import slack_client
import zadarma_client
import call_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _fetch_and_store_calls(start, end, order_records):
    """Fetch calls from Zadarma, correlate with orders, store, and return summary."""
    start_str = start.strftime("%Y-%m-%d 00:00:00")
    end_str = end.strftime("%Y-%m-%d 23:59:59")

    try:
        raw_calls = zadarma_client.fetch_calls(start_str, end_str)
    except Exception as e:
        logger.warning("Failed to fetch Zadarma calls: %s", e)
        return {"total": 0}

    calls = zadarma_client.build_call_records(raw_calls)
    all_orders = order_store.read_log()
    calls = zadarma_client.correlate_calls_with_orders(calls, all_orders)
    call_store.append_calls(calls)

    answered = [c for c in calls if c["disposition"] == "answered"]
    missed = [c for c in calls if c["disposition"] in ("no_answer", "cancel")]
    busy = [c for c in calls if c["disposition"] == "busy"]
    total_dur = sum(c["duration_seconds"] for c in answered)
    avg_dur = total_dur // len(answered) if answered else 0
    linked = sum(1 for c in calls if c.get("matched_order_id"))

    return {
        "total": len(calls),
        "answered": len(answered),
        "missed": len(missed),
        "busy": len(busy),
        "total_duration": total_dur,
        "avg_duration": avg_dur,
        "linked_orders": linked,
    }


def run(target_date: str | None = None):
    config.validate_config()

    if target_date:
        day = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=config.TIMEZONE)
    else:
        day = datetime.now(config.TIMEZONE) - timedelta(days=1)

    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=0)

    logger.info("Fetching orders for %s", day.date())
    all_orders = shopify_client.fetch_orders(start.isoformat(), end.isoformat())
    logger.info("Total orders in range: %d", len(all_orders))

    carlos_orders = shopify_client.filter_carlos_orders(all_orders)
    logger.info("Carlos-attributed orders: %d", len(carlos_orders))

    records = [shopify_client.build_order_record(o) for o in carlos_orders]
    order_store.append_orders(records)

    paid = [r for r in records if r["payment_type"] == "paid"]
    cod = [r for r in records if r["payment_type"] == "cod"]

    excluded_mediums = {None, "", "direct", "paid"}
    medium_counter = Counter(
        r["utm_medium"] for r in records if r["utm_medium"] not in excluded_mediums
    )

    report_data = {
        "date": day,
        "total_orders": len(records),
        "paid_count": len(paid),
        "paid_amount": sum(float(r["total_price"]) for r in paid),
        "cod_count": len(cod),
        "cod_amount": sum(float(r["total_price"]) for r in cod),
        "by_medium": dict(medium_counter),
        "cod_updates": [],
    }

    blocks = slack_client.build_daily_report(report_data)

    if config.has_zadarma():
        call_data = _fetch_and_store_calls(start, end, records)
        blocks.extend(slack_client.build_call_section(call_data))

    slack_client.send_to_slack(blocks, fallback_text=f"Reporte diario {config.CLOSER_NAME} - {start.date()}")
    logger.info("Daily report sent")


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_arg)

"""Daily report: fetch yesterday's orders, filter by UTM, report to Slack."""
import logging
from collections import Counter
from datetime import datetime, timedelta

import config
import shopify_client
import order_store
import slack_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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
    slack_client.send_to_slack(blocks, fallback_text=f"Reporte diario {config.CLOSER_NAME} - {start.date()}")
    logger.info("Daily report sent")


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_arg)

"""Weekly report: aggregate last 7 days and send performance summary."""
import logging
from collections import Counter
from datetime import datetime, timedelta

import config
import order_store
import slack_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run():
    config.validate_config()

    now = datetime.now(config.TIMEZONE)
    end_date = (now - timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)
    start_date = (end_date - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info("Weekly report: %s to %s", start_date.date(), end_date.date())

    entries = order_store.read_log()
    week_entries = order_store.filter_by_date_range(entries, start_date.isoformat(), end_date.isoformat())
    logger.info("Orders in period: %d", len(week_entries))

    paid = [e for e in week_entries if e.get("payment_type") == "paid"]
    cod = [e for e in week_entries if e.get("payment_type") == "cod"]

    cod_delivered = sum(1 for e in cod if e.get("cod_verified", False))
    cod_failed = sum(1 for e in cod if e.get("shipment_status") in ("failure", "attempted_delivery"))
    cod_pending = len(cod) - cod_delivered - cod_failed

    pending_details = [
        e for e in cod
        if not e.get("cod_verified", False) and e.get("shipment_status") not in ("failure", "attempted_delivery")
    ]

    medium_counter = Counter(e.get("utm_medium") for e in week_entries)

    report_data = {
        "start_date": start_date,
        "end_date": end_date,
        "total_orders": len(week_entries),
        "paid_count": len(paid),
        "paid_amount": sum(float(e.get("total_price", 0)) for e in paid),
        "cod_count": len(cod),
        "cod_amount": sum(float(e.get("total_price", 0)) for e in cod),
        "cod_delivered": cod_delivered,
        "cod_pending": cod_pending,
        "cod_failed": cod_failed,
        "pending_details": pending_details,
        "by_medium": dict(medium_counter),
    }

    blocks = slack_client.build_weekly_report(report_data)
    slack_client.send_to_slack(blocks, fallback_text=f"Reporte semanal {config.CLOSER_NAME}")
    logger.info("Weekly report sent")


if __name__ == "__main__":
    run()

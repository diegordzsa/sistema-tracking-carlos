"""Weekly report: aggregate last 7 days, check COD tracking, send to Slack."""
import logging
from collections import Counter
from datetime import datetime, timedelta

import config
import order_store
import slack_client
import tracking_checker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

TRACKING_STATUS_LABELS = {
    "delivered": "Entregado",
    "out_for_delivery": "En reparto",
    "at_destination": "En destino",
    "in_transit": "En transito",
    "shipped": "Enviado",
    "info_received": "Informado",
    "returned": "Devuelto",
    "incident": "Incidencia",
    "failed_attempt": "Intento fallido",
    "unknown": "Desconocido",
}


def _check_all_cod_tracking(cod_entries: list[dict]) -> list[dict]:
    """Check Correos Express tracking for all COD orders and update the log."""
    for entry in cod_entries:
        tn = entry.get("tracking_number")
        if not tn:
            continue

        result = tracking_checker.check_tracking(tn)
        if not result:
            continue

        new_status = result["status"]
        old_status = entry.get("cod_delivery_status")

        if new_status != old_status:
            updates = {
                "cod_delivery_status": new_status,
                "tracking_status_raw": result["status_raw"],
                "tracking_location": result["location"],
                "tracking_last_update": result["date"],
                "tracking_progress": result["progress"],
                "cod_verified": new_status == "delivered",
            }
            order_store.update_order(entry["order_id"], updates)
            entry.update(updates)
            logger.info("Order %s: %s -> %s", entry.get("order_number"), old_status, new_status)

    return cod_entries


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

    all_cod = [e for e in entries if e.get("payment_type") == "cod"]
    logger.info("Checking tracking for %d total COD orders", len(all_cod))
    all_cod = _check_all_cod_tracking(all_cod)

    cod_delivered = sum(1 for e in all_cod if e.get("cod_delivery_status") == "delivered")
    cod_returned = sum(1 for e in all_cod if e.get("cod_delivery_status") == "returned")
    cod_in_transit = sum(1 for e in all_cod if e.get("cod_delivery_status") in ("in_transit", "shipped", "out_for_delivery", "at_destination", "info_received"))
    cod_other = len(all_cod) - cod_delivered - cod_returned - cod_in_transit

    non_delivered = [
        e for e in all_cod
        if e.get("cod_delivery_status") != "delivered"
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
        "all_cod_total": len(all_cod),
        "cod_delivered": cod_delivered,
        "cod_in_transit": cod_in_transit,
        "cod_returned": cod_returned,
        "cod_other": cod_other,
        "non_delivered_details": non_delivered,
        "by_medium": dict(medium_counter),
    }

    blocks = slack_client.build_weekly_report(report_data)
    slack_client.send_to_slack(blocks, fallback_text=f"Reporte semanal {config.CLOSER_NAME}")
    logger.info("Weekly report sent")


if __name__ == "__main__":
    run()

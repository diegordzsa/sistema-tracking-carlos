"""COD checker: verify delivery status via Correos Express tracking + Shopify."""
import logging

import config
import shopify_client
import order_store
import slack_client
import tracking_checker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "delivered": "ENTREGADO",
    "out_for_delivery": "En reparto",
    "at_destination": "En destino",
    "in_transit": "En transito",
    "shipped": "Enviado",
    "info_received": "Informado",
    "returned": "DEVUELTO",
    "incident": "INCIDENCIA",
    "failed_attempt": "Intento fallido",
    "pending": "Pendiente",
    "unknown": "Desconocido",
}


def run():
    config.validate_config()

    pending = order_store.get_pending_cod_orders()
    logger.info("Pending COD orders to check: %d", len(pending))

    if not pending:
        logger.info("No pending COD orders")
        return

    alerts: list[list[dict]] = []

    for entry in pending:
        order_id = entry["order_id"]
        tracking_number = entry.get("tracking_number")
        old_status = entry.get("cod_delivery_status", "unknown")

        if not tracking_number:
            order = shopify_client.fetch_order_by_id(order_id)
            if order:
                fi = shopify_client.get_fulfillment_info(order)
                tracking_number = fi.get("tracking_number")

        if not tracking_number:
            logger.warning("No tracking number for order %s", entry.get("order_number"))
            continue

        tracking_result = tracking_checker.check_tracking(tracking_number)
        if not tracking_result:
            logger.warning("Could not check tracking for %s", tracking_number)
            continue

        new_status = tracking_result["status"]

        if new_status == old_status:
            continue

        logger.info(
            "Order %s: %s -> %s (%s, %s)",
            entry.get("order_number"),
            old_status,
            new_status,
            tracking_result["location"],
            tracking_result["date"],
        )

        updates = {
            "cod_delivery_status": new_status,
            "tracking_status_raw": tracking_result["status_raw"],
            "tracking_location": tracking_result["location"],
            "tracking_last_update": tracking_result["date"],
            "tracking_progress": tracking_result["progress"],
            "cod_verified": new_status == "delivered",
        }

        order_store.update_order(order_id, updates)

        label = STATUS_LABELS.get(new_status, new_status)
        alert_entry = {**entry, **updates}
        alert_entry["tracking_detail"] = (
            f"{tracking_result['location']} — {tracking_result['date']}"
        )
        alerts.append(slack_client.build_cod_alert(alert_entry, label))

    if alerts:
        all_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Actualizaciones COD — Correos Express"}},
            {"type": "divider"},
        ]
        for alert_blocks in alerts:
            all_blocks.extend(alert_blocks)
            all_blocks.append({"type": "divider"})
        slack_client.send_to_slack(all_blocks, fallback_text="Actualizaciones COD")
        logger.info("Sent %d COD alerts", len(alerts))
    else:
        logger.info("No COD status changes detected")


if __name__ == "__main__":
    run()

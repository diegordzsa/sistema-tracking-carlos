"""COD checker: re-check pending COD orders and update delivery status."""
import logging

import config
import shopify_client
import order_store
import slack_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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
        old_status = entry.get("cod_delivery_status", "unknown")

        order = shopify_client.fetch_order_by_id(order_id)
        if not order:
            logger.warning("Could not fetch order %s", order_id)
            continue

        new_status = shopify_client.get_cod_delivery_status(order)
        fulfillment = shopify_client.get_fulfillment_info(order)

        if new_status == old_status:
            continue

        logger.info("Order %s: %s -> %s", entry["order_number"], old_status, new_status)

        updates = {
            "cod_delivery_status": new_status,
            "financial_status": order.get("financial_status", ""),
            "fulfillment_status": fulfillment["fulfillment_status"],
            "tracking_company": fulfillment["tracking_company"],
            "tracking_number": fulfillment["tracking_number"],
            "tracking_url": fulfillment["tracking_url"],
            "cod_verified": new_status == "delivered",
        }

        order_store.update_order(order_id, updates)

        status_labels = {
            "delivered": "ENTREGADO",
            "returned": "DEVUELTO",
            "shipped": "Enviado",
            "pending": "Pendiente",
        }
        label = status_labels.get(new_status, new_status)

        alert_entry = {**entry, **updates}
        alerts.append(slack_client.build_cod_alert(alert_entry, label))

    if alerts:
        all_blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "Actualizaciones COD"}},
            {"type": "divider"},
        ]
        for alert_blocks in alerts:
            all_blocks.extend(alert_blocks)
            all_blocks.append({"type": "divider"})
        slack_client.send_to_slack(all_blocks, fallback_text="Actualizaciones COD")
        logger.info("Sent %d COD alerts", len(alerts))
    else:
        logger.info("No COD status changes")


if __name__ == "__main__":
    run()

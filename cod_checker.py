"""COD checker: verify delivery status via Correos Express tracking + Shopify.

Updates the JSONL log silently — COD status is reported in the weekly report.
"""
import logging

import config
import shopify_client
import order_store
import tracking_checker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run():
    config.validate_config()

    pending = order_store.get_pending_cod_orders()
    logger.info("Pending COD orders to check: %d", len(pending))

    if not pending:
        logger.info("No pending COD orders")
        return

    updated = 0

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
        updated += 1

    logger.info("Updated %d COD orders", updated)


if __name__ == "__main__":
    run()

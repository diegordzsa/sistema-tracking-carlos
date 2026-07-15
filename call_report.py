"""Detailed daily call report — reads stored calls, sends per-call breakdown to Slack."""
import logging
from datetime import datetime, timedelta

import config
import call_store
import zadarma_client
import order_store
import slack_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def run(target_date: str | None = None):
    config.validate_config()

    if not config.has_zadarma():
        logger.info("Zadarma not configured, skipping call report")
        return

    if target_date:
        day = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=config.TIMEZONE)
    else:
        day = datetime.now(config.TIMEZONE) - timedelta(days=1)

    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=0)

    start_str = start.strftime("%Y-%m-%d 00:00:00")
    end_str = end.strftime("%Y-%m-%d 23:59:59")
    calls = call_store.filter_by_date_range(
        call_store.read_log(), start_str, end_str
    )

    if not calls:
        logger.info("No stored calls for %s, fetching from Zadarma", day.date())
        start_str = start.strftime("%Y-%m-%d 00:00:00")
        end_str = end.strftime("%Y-%m-%d 23:59:59")
        try:
            raw_calls = zadarma_client.fetch_calls(start_str, end_str)
            calls = zadarma_client.build_call_records(raw_calls)
            all_orders = order_store.read_log()
            calls = zadarma_client.correlate_calls_with_orders(calls, all_orders)
            call_store.append_calls(calls)
        except Exception as e:
            logger.error("Failed to fetch calls: %s", e)
            return

    if not calls:
        logger.info("No calls found for %s", day.date())
        return

    answered = [c for c in calls if c.get("disposition") == "answered"]
    missed = [c for c in calls if c.get("disposition") in ("no_answer", "cancel")]
    busy = [c for c in calls if c.get("disposition") == "busy"]
    total_dur = sum(c.get("duration_seconds", 0) for c in answered)
    avg_dur = total_dur // len(answered) if answered else 0
    linked = sum(1 for c in calls if c.get("matched_order_id"))

    calls_sorted = sorted(calls, key=lambda c: c.get("started_at", ""))

    report_data = {
        "date": day,
        "calls": calls_sorted,
        "summary": {
            "total": len(calls),
            "answered": len(answered),
            "missed": len(missed),
            "busy": len(busy),
            "total_duration": total_dur,
            "avg_duration": avg_dur,
            "linked_orders": linked,
        },
    }

    blocks = slack_client.build_call_report(report_data)
    slack_client.send_to_slack(blocks, fallback_text=f"Detalle llamadas {config.CLOSER_NAME} - {day.date()}")
    logger.info("Call report sent for %s (%d calls)", day.date(), len(calls))


if __name__ == "__main__":
    import sys
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run(date_arg)

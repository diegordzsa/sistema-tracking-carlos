"""JSONL append-only log for tracked orders."""
import json
import os
from datetime import datetime

import config


def _ensure_data_dir():
    os.makedirs(config.DATA_DIR, exist_ok=True)


def read_log() -> list[dict]:
    """Read all entries from the orders log."""
    if not os.path.exists(config.ORDERS_LOG):
        return []
    entries = []
    with open(config.ORDERS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def get_existing_order_ids() -> set[int]:
    """Get set of order IDs already in the log."""
    return {e["order_id"] for e in read_log() if "order_id" in e}


def append_orders(records: list[dict]):
    """Append new order records, skipping duplicates by order_id."""
    if not records:
        return
    _ensure_data_dir()
    existing = get_existing_order_ids()
    new_records = [r for r in records if r["order_id"] not in existing]
    if not new_records:
        return

    ts = datetime.now(config.TIMEZONE).isoformat()
    with open(config.ORDERS_LOG, "a", encoding="utf-8") as f:
        for record in new_records:
            record["logged_at"] = ts
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def update_order(order_id: int, updates: dict):
    """Update fields on a specific order entry (rewrites the file)."""
    entries = read_log()
    updated = False
    for entry in entries:
        if entry.get("order_id") == order_id:
            entry.update(updates)
            updated = True
            break
    if updated:
        _write_all(entries)


def _write_all(entries: list[dict]):
    """Rewrite the entire log file."""
    _ensure_data_dir()
    with open(config.ORDERS_LOG, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def filter_by_date_range(entries: list[dict], start: str, end: str) -> list[dict]:
    """Filter entries by created_at date range (ISO format strings)."""
    return [
        e for e in entries
        if start <= e.get("created_at", "") <= end
    ]


def get_pending_cod_orders() -> list[dict]:
    """Get COD orders that haven't been verified as delivered yet."""
    return [
        e for e in read_log()
        if e.get("payment_type") == "cod" and not e.get("cod_verified", False)
    ]

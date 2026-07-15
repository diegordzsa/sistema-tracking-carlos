"""JSONL append-only log for tracked calls."""
import json
import os
from datetime import datetime

import config


def _ensure_data_dir():
    os.makedirs(config.DATA_DIR, exist_ok=True)


def read_log() -> list[dict]:
    if not os.path.exists(config.CALLS_LOG):
        return []
    entries = []
    with open(config.CALLS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def get_existing_call_ids() -> set[str]:
    return {e["call_id"] for e in read_log() if "call_id" in e}


def append_calls(records: list[dict]):
    if not records:
        return
    _ensure_data_dir()
    existing = get_existing_call_ids()
    new_records = [r for r in records if r["call_id"] not in existing]
    if not new_records:
        return

    ts = datetime.now(config.TIMEZONE).isoformat()
    with open(config.CALLS_LOG, "a", encoding="utf-8") as f:
        for record in new_records:
            record["logged_at"] = ts
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def filter_by_date_range(entries: list[dict], start: str, end: str) -> list[dict]:
    return [
        e for e in entries
        if start <= e.get("started_at", "") <= end
    ]

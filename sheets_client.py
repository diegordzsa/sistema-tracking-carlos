"""Google Sheets integration for COD order tracking."""
import json
import logging
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

import config

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
WORKSHEET_NAME = "COD - Seguimiento"
HEADERS = [
    "Pedido", "Fecha pedido", "Cliente", "Importe (EUR)", "Tracking",
    "URL Tracking", "Estado", "Estado Correos", "Ubicacion",
    "Ultima actualizacion", "Progreso", "Verificado", "Ultima sync",
]

STATUS_LABELS = {
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
    "pending": "Pendiente",
}


def _get_credentials() -> Credentials:
    creds_json = json.loads(config.GOOGLE_SHEETS_CREDENTIALS)
    return Credentials.from_service_account_info(creds_json, scopes=SCOPES)


def _get_or_create_worksheet(spreadsheet: gspread.Spreadsheet) -> gspread.Worksheet:
    try:
        ws = spreadsheet.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=WORKSHEET_NAME, rows=100, cols=len(HEADERS))
        ws.update([HEADERS], "A1")
        ws.format("A1:M1", {"textFormat": {"bold": True}})
        logger.info("Created worksheet '%s'", WORKSHEET_NAME)
    return ws


def _format_date(iso_date: str) -> str:
    if not iso_date:
        return ""
    try:
        dt = datetime.fromisoformat(iso_date)
        return dt.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(iso_date)


def _build_row(entry: dict) -> list:
    status = entry.get("cod_delivery_status") or "unknown"
    return [
        entry.get("order_number", ""),
        _format_date(entry.get("created_at", "")),
        entry.get("customer_name", ""),
        entry.get("total_price", ""),
        entry.get("tracking_number", ""),
        entry.get("tracking_url", ""),
        STATUS_LABELS.get(status, status),
        entry.get("tracking_status_raw", ""),
        entry.get("tracking_location", ""),
        entry.get("tracking_last_update", ""),
        entry.get("tracking_progress", ""),
        "SI" if entry.get("cod_verified") else "NO",
        datetime.now(config.TIMEZONE).strftime("%d/%m/%Y %H:%M"),
    ]


def sync_cod_orders(cod_entries: list[dict]) -> dict:
    """Sync COD orders to Google Sheets via upsert. Returns stats."""
    creds = _get_credentials()
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(config.GOOGLE_SHEETS_SPREADSHEET_ID)
    ws = _get_or_create_worksheet(spreadsheet)

    existing = ws.get_all_values()
    order_row_map = {}
    for i, row in enumerate(existing):
        if i == 0:
            continue
        if row and row[0]:
            order_row_map[row[0]] = i + 1

    added = 0
    updated = 0
    unchanged = 0
    rows_to_append = []
    cells_to_update = []

    for entry in cod_entries:
        order_number = entry.get("order_number", "")
        new_row = _build_row(entry)
        row_idx = order_row_map.get(order_number)

        if row_idx is not None:
            existing_row = existing[row_idx - 1] if row_idx - 1 < len(existing) else []
            if existing_row[:-1] != new_row[:-1]:
                cells_to_update.append({"range": f"A{row_idx}:M{row_idx}", "values": [new_row]})
                updated += 1
            else:
                unchanged += 1
        else:
            rows_to_append.append(new_row)
            added += 1

    if cells_to_update:
        ws.batch_update(cells_to_update)

    if rows_to_append:
        ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")

    logger.info("Sheets sync: %d added, %d updated, %d unchanged", added, updated, unchanged)
    return {"added": added, "updated": updated, "unchanged": unchanged}


if __name__ == "__main__":
    import order_store
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    entries = order_store.read_log()
    cod_entries = [e for e in entries if e.get("payment_type") == "cod"]
    print(f"Found {len(cod_entries)} COD orders to sync")
    result = sync_cod_orders(cod_entries)
    print(f"Done: {result['added']} added, {result['updated']} updated, {result['unchanged']} unchanged")

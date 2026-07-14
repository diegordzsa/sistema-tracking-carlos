"""Slack reporting via Incoming Webhook + Block Kit."""
import json
from datetime import datetime, timedelta

import requests

import config

MONTHS_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def send_to_slack(blocks: list[dict], fallback_text: str = "Reporte Carlos"):
    """Send a Block Kit message to Slack. Prints to stdout if DRY_RUN."""
    payload = {"text": fallback_text, "blocks": blocks}

    if config.DRY_RUN:
        print("=== DRY RUN — Slack message ===")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    resp = requests.post(config.SLACK_WEBHOOK_URL, json=payload, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Slack error: {resp.status_code} - {resp.text}")


def _fmt_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_ES[dt.month]} {dt.year}"


def _fmt_eur(amount: float) -> str:
    return f"{config.CURRENCY} {amount:,.2f}"


def build_daily_report(data: dict) -> list[dict]:
    """Build Slack blocks for the daily report.

    data keys: date, total_orders, paid_count, paid_amount, cod_count,
               cod_amount, by_medium, cod_updates
    """
    date_str = _fmt_date(data["date"])
    total = data["total_orders"]
    paid_n = data["paid_count"]
    paid_amt = data["paid_amount"]
    cod_n = data["cod_count"]
    cod_amt = data["cod_amount"]
    total_amt = paid_amt + cod_amt

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Reporte diario — {config.CLOSER_NAME} ({date_str})"}
        },
        {"type": "divider"},
    ]

    if total == 0:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No se detectaron pedidos atribuidos ayer._"}
        })
        return blocks

    summary = (
        f"*Pedidos atribuidos (UTM):* {total}\n"
        f"  - Pagados: {paid_n} ({_fmt_eur(paid_amt)})\n"
        f"  - Contrareembolso: {cod_n} ({_fmt_eur(cod_amt)})\n"
        f"*Total facturado:* {_fmt_eur(total_amt)}"
    )
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

    by_medium = data.get("by_medium", {})
    if by_medium:
        lines = [f"  - {medium or 'directo'}: {count} pedidos" for medium, count in by_medium.items()]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Canales:*\n" + "\n".join(lines)}
        })

    cod_updates = data.get("cod_updates", [])
    if cod_updates:
        blocks.append({"type": "divider"})
        lines = []
        for u in cod_updates:
            status = u.get("shipment_status", "desconocido")
            lines.append(f"  - {u['order_number']}: _{status}_")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Actualizaciones COD:*\n" + "\n".join(lines)}
        })

    return blocks


def build_weekly_report(data: dict) -> list[dict]:
    """Build Slack blocks for the weekly report.

    data keys: start_date, end_date, total_orders, paid_count, paid_amount,
               cod_count, cod_amount, cod_delivered, cod_pending, cod_failed,
               pending_details, by_medium
    """
    start_str = _fmt_date(data["start_date"])
    end_str = _fmt_date(data["end_date"])
    paid_n = data["paid_count"]
    paid_amt = data["paid_amount"]
    cod_n = data["cod_count"]
    cod_amt = data["cod_amount"]
    total_amt = paid_amt + cod_amt

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Reporte semanal — {config.CLOSER_NAME} ({start_str} - {end_str})"}
        },
        {"type": "divider"},
    ]

    ventas = (
        f"*VENTAS*\n"
        f"  Total pedidos: {data['total_orders']}\n"
        f"  - Pagados: {paid_n} ({_fmt_eur(paid_amt)})\n"
        f"  - Contrareembolso: {cod_n} ({_fmt_eur(cod_amt)})\n"
        f"  *Total facturado: {_fmt_eur(total_amt)}*"
    )
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ventas}})

    cod_delivered = data.get("cod_delivered", 0)
    cod_pending = data.get("cod_pending", 0)
    cod_failed = data.get("cod_failed", 0)
    if cod_n > 0:
        cod_section = (
            f"*CONTRAREEMBOLSO*\n"
            f"  Entregados: {cod_delivered} de {cod_n}\n"
            f"  Pendientes: {cod_pending}\n"
            f"  Fallidos/devueltos: {cod_failed}"
        )
        pending_details = data.get("pending_details", [])
        for p in pending_details:
            tracking = p.get("tracking_company", "sin tracking")
            status = p.get("shipment_status", "desconocido")
            cod_section += f"\n    - {p['order_number']}: {tracking}, _{status}_"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": cod_section}})

    by_medium = data.get("by_medium", {})
    if by_medium:
        total = sum(by_medium.values())
        lines = []
        for medium, count in sorted(by_medium.items(), key=lambda x: -x[1]):
            pct = (count / total * 100) if total > 0 else 0
            lines.append(f"  - {medium or 'directo'}: {count} ({pct:.0f}%)")
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*CANALES*\n" + "\n".join(lines)}
        })

    return blocks


def build_cod_alert(order: dict, new_status: str) -> list[dict]:
    """Build a Slack alert for a COD status change."""
    delivered = new_status in ("ENTREGADO", "delivered")
    returned = new_status in ("DEVUELTO", "returned")

    if delivered:
        emoji = ":white_check_mark:"
    elif returned:
        emoji = ":x:"
    else:
        emoji = ":package:"

    text = (
        f"{emoji} *COD {order.get('order_number', '')}* — {new_status}\n"
        f"  Cliente: {order.get('customer_name', 'N/A')}\n"
        f"  Importe: {_fmt_eur(float(order.get('total_price', 0)))}\n"
        f"  Courier: {order.get('tracking_company', 'Correos Express')}"
    )

    tracking_detail = order.get("tracking_detail")
    if tracking_detail:
        text += f"\n  Tracking: {tracking_detail}"

    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]

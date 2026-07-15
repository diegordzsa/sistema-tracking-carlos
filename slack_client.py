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

    return blocks


def build_weekly_report(data: dict) -> list[dict]:
    """Build Slack blocks for the weekly report.

    data keys: start_date, end_date, total_orders, paid_count, paid_amount,
               cod_count, cod_amount, all_cod_total, cod_delivered, cod_in_transit,
               cod_returned, cod_other, non_delivered_details, by_medium
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
        f"*VENTAS DE LA SEMANA*\n"
        f"  Total pedidos: {data['total_orders']}\n"
        f"  - Pagados: {paid_n} ({_fmt_eur(paid_amt)})\n"
        f"  - Contrareembolso: {cod_n} ({_fmt_eur(cod_amt)})\n"
        f"  *Total facturado: {_fmt_eur(total_amt)}*"
    )
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ventas}})

    all_cod = data.get("all_cod_total", 0)
    cod_delivered = data.get("cod_delivered", 0)
    cod_in_transit = data.get("cod_in_transit", 0)
    cod_returned = data.get("cod_returned", 0)
    cod_other = data.get("cod_other", 0)

    if all_cod > 0:
        blocks.append({"type": "divider"})
        summary = (
            f"*CONTRAREEMBOLSO (todos los pedidos COD)*\n"
            f"  De {all_cod} pedidos: *{cod_delivered} entregados*, "
            f"{cod_in_transit} en camino, {cod_returned} devueltos"
        )
        if cod_other > 0:
            summary += f", {cod_other} pendientes"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": summary}})

        non_delivered = data.get("non_delivered_details", [])
        if non_delivered:
            lines = []
            for o in non_delivered:
                status = o.get("cod_delivery_status", "unknown")
                status_raw = o.get("tracking_status_raw", status)
                location = o.get("tracking_location", "")
                last_update = o.get("tracking_last_update", "")
                detail = f"  - #{o.get('order_number', '?')} — _{status_raw}_"
                if location:
                    detail += f" ({location})"
                if last_update:
                    detail += f" — {last_update}"
                lines.append(detail)
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Detalle no entregados:*\n" + "\n".join(lines)}
            })

    sheets_url = data.get("sheets_url")
    if sheets_url:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":clipboard: <{sheets_url}|Ver seguimiento completo COD en Google Sheets>",
            }
        })

    by_medium = data.get("by_medium", {})
    if by_medium:
        blocks.append({"type": "divider"})
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


def _fmt_duration(seconds: int) -> str:
    if seconds >= 3600:
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"{h}h {m}min"
    if seconds >= 60:
        m = seconds // 60
        s = seconds % 60
        return f"{m}m {s:02d}s"
    return f"{seconds}s"


def build_call_section(call_data: dict) -> list[dict]:
    """Build Block Kit blocks for a call summary section (embedded in daily/weekly reports).

    call_data keys: total, answered, missed, busy, failed,
                    total_duration, avg_duration, linked_orders
    """
    total = call_data.get("total", 0)
    if total == 0:
        return [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": ":telephone_receiver: *LLAMADAS*\n_No se registraron llamadas._"}
        }]

    answered = call_data.get("answered", 0)
    missed = call_data.get("missed", 0)
    busy = call_data.get("busy", 0)
    total_dur = call_data.get("total_duration", 0)
    avg_dur = call_data.get("avg_duration", 0)
    linked = call_data.get("linked_orders", 0)

    lines = [
        f":telephone_receiver: *LLAMADAS*",
        f"  Total: {total} llamadas",
        f"  - Contestadas: {answered} ({_fmt_duration(total_dur)})",
    ]
    if missed:
        lines.append(f"  - No contestadas: {missed}")
    if busy:
        lines.append(f"  - Ocupado: {busy}")
    lines.append(f"  Duracion media: {_fmt_duration(avg_dur)}")
    if linked:
        lines.append(f"  Llamadas vinculadas a pedidos: {linked}")

    return [
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}},
    ]


def build_call_report(call_data: dict) -> list[dict]:
    """Build a full standalone call report with per-call detail.

    call_data keys: date, calls (list of call records), summary (same as build_call_section)
    """
    date_str = _fmt_date(call_data["date"])
    calls = call_data.get("calls", [])
    summary = call_data.get("summary", {})

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Detalle de llamadas — {config.CLOSER_NAME} ({date_str})"}
        },
        {"type": "divider"},
    ]

    if not calls:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "_No se registraron llamadas._"}
        })
        return blocks

    total = summary.get("total", len(calls))
    answered = summary.get("answered", 0)
    total_dur = summary.get("total_duration", 0)
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": (
            f"*Resumen:* {total} llamadas, {answered} contestadas, "
            f"{_fmt_duration(total_dur)} total"
        )}
    })

    detail_lines = []
    for c in calls:
        time_str = c.get("started_at", "")
        if "T" in time_str:
            time_str = time_str.split("T")[1][:5]
        elif " " in time_str:
            time_str = time_str.split(" ")[1][:5]

        arrow = "->" if c.get("direction") == "outbound" else "<-"
        phone = c.get("customer_phone", "?")
        if len(phone) > 6:
            phone = phone[:7] + "..."
        dur = _fmt_duration(c.get("duration_seconds", 0))
        disp = c.get("disposition", "")

        line = f"  {time_str} {arrow} {phone} ({dur})"
        if disp == "answered":
            order = c.get("matched_order_number")
            if order:
                line += f" — Pedido {order}"
        elif disp in ("no_answer", "cancel"):
            line += " _No contestada_"
        elif disp == "busy":
            line += " _Ocupado_"
        elif disp in ("call_failed", "failed"):
            line += " _Fallida_"

        detail_lines.append(line)

    chunk_size = 15
    for i in range(0, len(detail_lines), chunk_size):
        chunk = detail_lines[i:i + chunk_size]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "\n".join(chunk)}
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

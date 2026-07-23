"""Small shared helpers: badges, formatters, activity log, notifications."""
import datetime as dt

import pandas as pd

from lib.db import get_session, ActivityLog, Notification, Ticket

STATUS_COLORS = {
    "pending": "#d97706", "good": "#16a34a", "damaged": "#e11d48", "not_received": "#0284c7",
    "refund_only": "#7c3aed", "request_cancelled": "#6b7280", "lost_scrap": "#78350f",
}
STATUS_LABELS = {
    "pending": "Pending Inspection", "good": "Good Condition",
    "damaged": "Damaged", "not_received": "Not Received", "refund_only": "Refund Only",
    "request_cancelled": "Request Cancelled", "lost_scrap": "Lost & Scrap",
}
TRIGGER_COLORS = {
    "returned": "#4f46e5", "cancelled_after_shipped": "#b45309",
    "cancelled_not_shipped": "#9333ea",
    "delivery_failed": "#e11d48", "other": "#6b7280",
}


def status_badge_html(status: str) -> str:
    color = STATUS_COLORS.get(status, "#6b7280")
    label = STATUS_LABELS.get(status, status or "—")
    return (f"<span style='background:{color}22;color:{color};padding:3px 9px;"
            f"border-radius:999px;font-size:12px;font-weight:600;'>{label}</span>")


def trigger_badge_html(code: str, label: str) -> str:
    color = TRIGGER_COLORS.get(code, "#6b7280")
    return (f"<span style='background:{color}22;color:{color};padding:3px 9px;"
            f"border-radius:999px;font-size:12px;font-weight:600;'>{label or code}</span>")


def dksh_status_badge_html(status: str) -> str:
    color = "#16a34a" if status == "Closed" else ("#d97706" if status == "Open" else "#6b7280")
    return (f"<span style='background:{color}22;color:{color};padding:3px 9px;"
            f"border-radius:999px;font-size:12px;font-weight:600;'>{status or 'Unknown'}</span>")


# Warehouse must inspect a return (mark it Good / Damaged / Not Received) within
# this many hours of the return being delivered back -- return_date is the
# clock start, whether it's a real GRAAS timestamp or the estimated fallback
# (see return_date_estimated on ReturnOrder).
SLA_HOURS = 48


def sla_info(return_date, inspection_status):
    """Returns None if the inspection SLA clock doesn't apply -- either the
    return hasn't been delivered back yet (no return_date) or it's already
    been inspected (status isn't "pending" anymore). Otherwise returns a dict
    with hours remaining (negative once overdue) and a human-readable label,
    e.g. {"overdue": False, "hours": 13.2, "label": "13h left"}."""
    if inspection_status != "pending" or return_date is None or pd.isna(return_date):
        return None
    deadline = return_date + dt.timedelta(hours=SLA_HOURS)
    hours_left = (deadline - dt.datetime.utcnow()).total_seconds() / 3600
    if hours_left >= 0:
        return {"overdue": False, "hours": hours_left, "label": f"{hours_left:.0f}h left"}
    return {"overdue": True, "hours": hours_left, "label": f"Overdue by {abs(hours_left):.0f}h"}


def sla_text(return_date, inspection_status) -> str:
    """Plain-text SLA label for use in a st.dataframe column (no HTML)."""
    info = sla_info(return_date, inspection_status)
    return info["label"] if info else "—"


def sla_badge_html(return_date, inspection_status) -> str:
    """Colored badge for the order detail page: green while there's plenty of
    time, amber inside the last 12h, red once the 48h SLA has been breached."""
    info = sla_info(return_date, inspection_status)
    if info is None:
        return ""
    if info["overdue"]:
        color = "#e11d48"
    elif info["hours"] <= 12:
        color = "#d97706"
    else:
        color = "#16a34a"
    return (f"<span style='background:{color}22;color:{color};padding:3px 9px;"
            f"border-radius:999px;font-size:12px;font-weight:600;'>⏱ {info['label']} "
            f"(inspect within {SLA_HOURS}h of return delivery)</span>")


def fmt_date(v) -> str:
    if v is None:
        return "—"
    try:
        return v.strftime("%d %b %Y")
    except Exception:
        return str(v)


def fmt_dt(v) -> str:
    if v is None:
        return "—"
    try:
        return v.strftime("%d %b %Y, %H:%M")
    except Exception:
        return str(v)


def fmt_money(amt, currency="THB") -> str:
    try:
        return f"{amt:,.2f} {currency}"
    except Exception:
        return f"{amt} {currency}"


def log_activity(order_key: str, action: str, comment: str = "", ticket_id: str = None, actor: str = None):
    from lib.auth import current_user
    session = get_session()
    try:
        user = current_user()
        session.add(ActivityLog(
            order_key=order_key, ticket_id=ticket_id, action=action, comment=comment,
            actor=actor or (user["name"] if user else "System"),
            created_at=dt.datetime.utcnow(),
        ))
        session.commit()
    finally:
        session.close()


def push_notification(ntype: str, message: str, order_key: str = None):
    session = get_session()
    try:
        session.add(Notification(type=ntype, message=message, order_key=order_key, read=False))
        session.commit()
    finally:
        session.close()


def next_ticket_id() -> str:
    session = get_session()
    try:
        count = session.query(Ticket).count()
        return f"TCK-{count + 1:04d}"
    finally:
        session.close()

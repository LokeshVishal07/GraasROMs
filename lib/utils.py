"""Small shared helpers: badges, formatters, activity log, notifications."""
import datetime as dt

from lib.db import get_session, ActivityLog, Notification, Ticket

STATUS_COLORS = {
    "pending": "#d97706", "good": "#16a34a", "damaged": "#e11d48", "not_received": "#0284c7",
}
STATUS_LABELS = {
    "pending": "Pending Inspection", "good": "Good Condition",
    "damaged": "Damaged", "not_received": "Not Received",
}
TRIGGER_COLORS = {
    "returned": "#4f46e5", "cancelled_after_shipped": "#b45309",
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

import datetime as dt
import streamlit as st

from lib.data import load_orders_df, load_tickets_df, cache_nonce, bump_cache_nonce
from lib.db import get_session, Ticket, ActivityLog
from lib.auth import current_user, current_permissions
from lib.utils import log_activity, next_ticket_id, fmt_dt

STATUS_OPTIONS = ["Open", "Follow-up", "Waiting for Marketplace", "Resolved", "Rejected"]
PRIORITY_OPTIONS = ["Low", "Normal", "High", "Urgent"]


def render():
    st.subheader("Marketplace Claims")
    perms = current_permissions()
    orders = load_orders_df(cache_nonce())
    tickets = load_tickets_df(cache_nonce())

    tab1, tab2 = st.tabs(["Open a Claim", "All Claims"])

    with tab1:
        _render_new_claim(orders, perms)

    with tab2:
        _render_ticket_list(orders, tickets, perms)


def _render_new_claim(orders, perms):
    if not perms.get("raise_claim"):
        st.info("Your role can't raise new claims. Ask Operations or an Administrator.")
        return
    if orders.empty:
        st.info("No orders loaded yet.")
        return

    prefill = st.session_state.pop("prefill_claim_key", None)
    options = {row["key"]: f"{row['order_id']} · {row['brand']} · {row['marketplace']}" for _, row in orders.iterrows()}
    keys = list(options.keys())
    idx = keys.index(prefill) if prefill in keys else 0

    with st.form("new_claim_form"):
        sel_key = st.selectbox("Order", keys, index=idx, format_func=lambda k: options[k])
        subject = st.text_input("Subject", placeholder="e.g. Damaged item claim — request refund from marketplace")
        priority = st.selectbox("Priority", PRIORITY_OPTIONS, index=1)
        note = st.text_area("Initial note")
        submitted = st.form_submit_button("Open Claim", type="primary")

    if submitted:
        if not subject.strip():
            st.error("Subject is required.")
            return
        session = get_session()
        try:
            user = current_user()
            tid = next_ticket_id()
            session.add(Ticket(id=tid, order_key=sel_key, subject=subject.strip(), status="Open",
                                priority=priority, created_by=user["name"], assigned_to=user["name"]))
            session.commit()
            log_activity(order_key=sel_key, ticket_id=tid, action="Claim opened",
                          comment=note.strip() or subject.strip())
        finally:
            session.close()
        bump_cache_nonce()
        st.success(f"Claim {tid} opened.")
        st.rerun()


def _render_ticket_list(orders, tickets, perms):
    if tickets.empty:
        st.info("No claims yet.")
        return

    order_lookup = {row["key"]: row for _, row in orders.iterrows()} if not orders.empty else {}

    status_filter = st.multiselect("Filter by status", STATUS_OPTIONS, key="claims_status_filter")
    view = tickets if not status_filter else tickets[tickets["status"].isin(status_filter)]
    view = view.sort_values("updated_at", ascending=False)

    for _, t in view.iterrows():
        order = order_lookup.get(t["order_key"])
        order_label = f"{order['order_id']} · {order['brand']}" if order is not None else t["order_key"]
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(f"**{t['id']}** — {t['subject']}")
                st.caption(f"Order: {order_label} · Priority: {t['priority']} · Created by {t['created_by']}")
            with c2:
                st.markdown(
                    f"<span style='background:#4f46e522;color:#4f46e5;padding:3px 9px;border-radius:999px;"
                    f"font-size:12px;font-weight:600;'>{t['status']}</span>", unsafe_allow_html=True,
                )

            with st.expander("Timeline & update"):
                session = get_session()
                try:
                    logs = session.query(ActivityLog).filter_by(ticket_id=t["id"]).order_by(
                        ActivityLog.created_at.asc()).all()
                    for log in logs:
                        st.write(f"**{fmt_dt(log.created_at)}** — {log.actor}: {log.action}"
                                 + (f" — {log.comment}" if log.comment else ""))
                finally:
                    session.close()

                if perms.get("manage_claims"):
                    with st.form(f"update_{t['id']}"):
                        new_status = st.selectbox("Status", STATUS_OPTIONS,
                                                    index=STATUS_OPTIONS.index(t["status"]) if t["status"] in STATUS_OPTIONS else 0,
                                                    key=f"status_{t['id']}")
                        note = st.text_area("Add note", key=f"note_{t['id']}")
                        upd = st.form_submit_button("Update")
                    if upd:
                        session = get_session()
                        try:
                            ticket = session.get(Ticket, t["id"])
                            ticket.status = new_status
                            ticket.updated_at = dt.datetime.utcnow()
                            session.commit()
                        finally:
                            session.close()
                        log_activity(order_key=t["order_key"], ticket_id=t["id"],
                                     action=f"Status changed to {new_status}", comment=note.strip())
                        bump_cache_nonce()
                        st.rerun()

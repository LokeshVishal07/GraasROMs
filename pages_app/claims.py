import datetime as dt
import streamlit as st

from lib.data import load_orders_df, load_tickets_df, cache_nonce, bump_cache_nonce
from lib.db import get_session, Ticket, ActivityLog
from lib.auth import current_user, current_permissions
from lib.utils import log_activity, next_ticket_id, fmt_dt, fmt_money, status_badge_html
from lib.evidence import render_evidence_gallery

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

    sel_key = st.selectbox("Order", keys, index=idx, format_func=lambda k: options[k], key="new_claim_order")
    if sel_key:
        order = orders[orders["key"] == sel_key].iloc[0]
        _render_order_summary(order)
        with st.expander("Evidence for this order"):
            render_evidence_gallery(sel_key, key_prefix="newclaim")

    with st.form("new_claim_form"):
        subject = st.text_input("Subject", placeholder="e.g. Damaged item claim — request refund from marketplace")
        priority = st.selectbox("Priority", PRIORITY_OPTIONS, index=1)
        case_id = st.text_input("Marketplace Case ID (if already known)")
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
                                priority=priority, marketplace_case_id=case_id.strip() or None,
                                created_by=user["name"], assigned_to=user["name"]))
            session.commit()
            log_activity(order_key=sel_key, ticket_id=tid, action="Claim opened",
                          comment=note.strip() or subject.strip())
        finally:
            session.close()
        bump_cache_nonce()
        st.success(f"Claim {tid} opened.")
        st.rerun()


def _render_order_summary(order):
    """Order details + buyer return reason + warehouse inspection result & comments,
    shown so Operations has everything needed to raise/support a claim without
    digging through the Returns page separately."""
    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**Order ID:** {order['order_id']}  ")
        st.write(f"**Brand / Marketplace:** {order['brand']} · {order['marketplace']}  ")
        st.write(f"**Buyer Return Reason:** {order['return_reason'] or '—'}  ")
        st.write(f"**Order Amount:** {fmt_money(order['order_amt'], order['currency'])}  ")
    with c2:
        st.markdown(f"**Warehouse Inspection:** {status_badge_html(order['inspection_status'])}",
                    unsafe_allow_html=True)
        st.write(f"**Warehouse Comments:** {order['inspection_comment'] or '—'}  ")
        if order.get("damage_reason"):
            st.write(f"**Damage Reason:** {order['damage_reason']}  ")
        st.write(f"**Refund Amount:** {fmt_money(order['refund_amt'], order['currency'])}  ")


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
                caption = f"Order: {order_label} · Priority: {t['priority']} · Created by {t['created_by']}"
                if t.get("marketplace_case_id"):
                    caption += f" · Case ID: {t['marketplace_case_id']}"
                st.caption(caption)
            with c2:
                st.markdown(
                    f"<span style='background:#4f46e522;color:#4f46e5;padding:3px 9px;border-radius:999px;"
                    f"font-size:12px;font-weight:600;'>{t['status']}</span>", unsafe_allow_html=True,
                )

            with st.expander("Order details, evidence & timeline"):
                if order is not None:
                    st.markdown("###### Order & Inspection")
                    _render_order_summary(order)
                    st.markdown("###### Evidence")
                    render_evidence_gallery(t["order_key"], key_prefix=f"ticket_{t['id']}")

                st.markdown("###### Activity Timeline")
                session = get_session()
                try:
                    logs = session.query(ActivityLog).filter_by(ticket_id=t["id"]).order_by(
                        ActivityLog.created_at.asc()).all()
                    if not logs:
                        st.caption("No activity recorded yet.")
                    for log in logs:
                        st.write(f"**{fmt_dt(log.created_at)}** — {log.actor}: {log.action}"
                                 + (f" — {log.comment}" if log.comment else ""))
                finally:
                    session.close()

                st.markdown("###### Internal Notes")
                st.caption("Ops-only working notes — not part of the shared timeline above.")
                st.write(t.get("internal_notes") or "_No internal notes yet._")

                if perms.get("manage_claims"):
                    with st.form(f"update_{t['id']}"):
                        new_status = st.selectbox("Status", STATUS_OPTIONS,
                                                    index=STATUS_OPTIONS.index(t["status"]) if t["status"] in STATUS_OPTIONS else 0,
                                                    key=f"status_{t['id']}")
                        new_case_id = st.text_input("Marketplace Case ID", value=t.get("marketplace_case_id") or "",
                                                     key=f"case_{t['id']}")
                        new_notes = st.text_area("Internal Notes (replaces the note above)",
                                                  value=t.get("internal_notes") or "", key=f"notes_{t['id']}")
                        note = st.text_area("Add a timeline note (optional)", key=f"note_{t['id']}")
                        upd = st.form_submit_button("Update")
                    if upd:
                        session = get_session()
                        try:
                            ticket = session.get(Ticket, t["id"])
                            status_changed = ticket.status != new_status
                            ticket.status = new_status
                            ticket.marketplace_case_id = new_case_id.strip() or None
                            ticket.internal_notes = new_notes.strip() or None
                            ticket.updated_at = dt.datetime.utcnow()
                            session.commit()
                        finally:
                            session.close()
                        action = f"Status changed to {new_status}" if status_changed else "Claim updated"
                        log_activity(order_key=t["order_key"], ticket_id=t["id"],
                                     action=action, comment=note.strip())
                        bump_cache_nonce()
                        st.rerun()

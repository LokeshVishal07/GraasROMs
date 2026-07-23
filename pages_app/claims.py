import datetime as dt
import streamlit as st

from lib.data import load_orders_df, load_tickets_df, cache_nonce, bump_cache_nonce
from lib.db import get_session, Ticket, ActivityLog
from lib.auth import current_user, current_permissions
from lib.utils import log_activity, next_ticket_id, fmt_dt, fmt_money, status_badge_html
from lib.evidence import render_evidence_gallery, save_uploaded_file, save_link, is_probably_valid_link

STATUS_OPTIONS = ["Open", "Follow-up", "Waiting for Marketplace", "Resolved", "Rejected"]
PRIORITY_OPTIONS = ["Low", "Normal", "High", "Urgent"]
EVIDENCE_FILE_TYPES = ["png", "jpg", "jpeg", "webp", "gif", "pdf"]


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


def _render_claim_docs(t, perms):
    """Two dedicated drag-and-drop sections alongside the general Evidence
    gallery above: POD (proof of delivery) and Appeal Status. Appeal Status
    also carries Success/Failed buttons that record the appeal outcome and
    auto-update the claim's overall status (Success -> Resolved,
    Failed -> Rejected)."""
    order_key, tid = t["order_key"], t["id"]
    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**POD (Proof of Delivery)**")
        render_evidence_gallery(order_key, key_prefix=f"pod_{tid}", category="pod",
                                 empty_caption="No POD uploaded yet.")
        if perms.get("manage_claims"):
            pod_files = st.file_uploader("Drag & drop POD image(s)", accept_multiple_files=True,
                                          type=EVIDENCE_FILE_TYPES, key=f"pod_upl_{tid}")
            pod_link = st.text_input("Or paste a Drive/OneDrive link", key=f"pod_link_{tid}")
            if st.button("Upload POD", key=f"pod_btn_{tid}"):
                if not pod_files and not pod_link.strip():
                    st.warning("Choose a file or paste a link first.")
                elif pod_link.strip() and not is_probably_valid_link(pod_link):
                    st.warning("That link doesn't look like a valid http(s) URL.")
                else:
                    user = current_user()
                    now = dt.datetime.utcnow()
                    for f in (pod_files or []):
                        save_uploaded_file(order_key, f, user["name"], when=now, category="pod")
                    if pod_link.strip():
                        save_link(order_key, pod_link.strip(), user["name"], when=now, category="pod")
                    log_activity(order_key=order_key, ticket_id=tid, action="POD uploaded")
                    bump_cache_nonce()
                    st.rerun()

    with c2:
        st.markdown("**Appeal Status**")
        render_evidence_gallery(order_key, key_prefix=f"appeal_{tid}", category="appeal",
                                 empty_caption="No appeal evidence uploaded yet.")
        if perms.get("manage_claims"):
            appeal_files = st.file_uploader("Drag & drop appeal evidence", accept_multiple_files=True,
                                             type=EVIDENCE_FILE_TYPES, key=f"appeal_upl_{tid}")
            appeal_link = st.text_input("Or paste a Drive/OneDrive link", key=f"appeal_link_{tid}")
            if st.button("Upload Appeal Evidence", key=f"appeal_btn_{tid}"):
                if not appeal_files and not appeal_link.strip():
                    st.warning("Choose a file or paste a link first.")
                elif appeal_link.strip() and not is_probably_valid_link(appeal_link):
                    st.warning("That link doesn't look like a valid http(s) URL.")
                else:
                    user = current_user()
                    now = dt.datetime.utcnow()
                    for f in (appeal_files or []):
                        save_uploaded_file(order_key, f, user["name"], when=now, category="appeal")
                    if appeal_link.strip():
                        save_link(order_key, appeal_link.strip(), user["name"], when=now, category="appeal")
                    log_activity(order_key=order_key, ticket_id=tid, action="Appeal evidence uploaded")
                    bump_cache_nonce()
                    st.rerun()

            current = t.get("appeal_status")
            st.caption(f"Appeal outcome: **{current or 'Not set'}**")
            b1, b2 = st.columns(2)
            with b1:
                if st.button("✅ Success", key=f"appeal_success_{tid}", width="stretch"):
                    _set_appeal_outcome(tid, order_key, "Success")
            with b2:
                if st.button("❌ Failed", key=f"appeal_failed_{tid}", width="stretch"):
                    _set_appeal_outcome(tid, order_key, "Failed")


def _set_appeal_outcome(ticket_id: str, order_key: str, outcome: str):
    new_status = "Resolved" if outcome == "Success" else "Rejected"
    session = get_session()
    try:
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            return
        ticket.appeal_status = outcome
        ticket.status = new_status
        ticket.updated_at = dt.datetime.utcnow()
        session.commit()
    finally:
        session.close()
    log_activity(order_key=order_key, ticket_id=ticket_id, action=f"Appeal marked {outcome}",
                 comment=f"Claim status auto-updated to {new_status}.")
    bump_cache_nonce()
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
                caption = f"Order: {order_label} · Priority: {t['priority']} · Created by {t['created_by']}"
                if t.get("marketplace_case_id"):
                    caption += f" · Case ID: {t['marketplace_case_id']}"
                st.caption(caption)
            with c2:
                badges = (f"<span style='background:#4f46e522;color:#4f46e5;padding:3px 9px;border-radius:999px;"
                          f"font-size:12px;font-weight:600;'>{t['status']}</span>")
                appeal = t.get("appeal_status")
                if appeal:
                    a_color = "#16a34a" if appeal == "Success" else "#e11d48"
                    badges += (f" <span style='background:{a_color}22;color:{a_color};padding:3px 9px;"
                               f"border-radius:999px;font-size:12px;font-weight:600;'>Appeal: {appeal}</span>")
                st.markdown(badges, unsafe_allow_html=True)

            with st.expander("Order details, evidence & timeline"):
                if order is not None:
                    st.markdown("###### Order & Inspection")
                    _render_order_summary(order)
                    st.markdown("###### Evidence")
                    render_evidence_gallery(t["order_key"], key_prefix=f"ticket_{t['id']}")

                    st.markdown("###### Claim Documentation")
                    _render_claim_docs(t, perms)

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

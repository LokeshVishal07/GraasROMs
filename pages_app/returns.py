import datetime as dt
import streamlit as st
import pandas as pd

from lib.data import load_orders_df, load_manual_tracking_df, apply_filters, cache_nonce, bump_cache_nonce
from lib.widgets import filter_bar
from lib.utils import (status_badge_html, trigger_badge_html, dksh_status_badge_html,
                        fmt_dt, fmt_money, log_activity, push_notification)
from lib.db import get_session, ReturnOrder, Evidence
from lib.auth import current_user, current_permissions
from lib.evidence import save_link, is_probably_valid_link, render_evidence_gallery

DISPLAY_COLS = {
    "order_id": "Order ID", "brand": "Brand", "marketplace": "Marketplace", "channel": "Channel",
    "product_summary": "Product", "sku_summary": "SKU", "qty_total": "Qty",
    "order_date": "Order Date", "return_date": "Return Date", "buyer_id": "Buyer ID",
    "trigger_label": "MP Status", "return_reason": "Return Reason",
    "inspection_status": "Inspection", "warehouse": "Warehouse", "tracking_number": "Tracking #",
}

INSPECTION_OPTIONS = ["pending", "good", "damaged", "not_received"]
INSPECTION_LABELS = {"pending": "— Select —", "good": "Received in Good Condition",
                      "damaged": "Damaged", "not_received": "Not Received"}


def _order_label(row):
    return f"{row['order_id']} · {row['brand']} · {row['marketplace']} · {row['trigger_label']}"


def render():
    st.subheader("Returns")
    perms = current_permissions()
    df = load_orders_df(cache_nonce())
    f = filter_bar(df, "returns")
    fdf = apply_filters(df, f["preset"], f["custom_start"], f["custom_end"], f["marketplaces"],
                         f["channels"], f["brands"], f["warehouses"], f["statuses"], f["reasons"],
                         f["triggers"], f["search"])

    st.caption(f"{len(fdf)} return(s) match the current filters.")
    if fdf.empty:
        st.info("No returns match the current filters.")
        return

    show = fdf.copy().sort_values("order_date", ascending=False)
    display = show[list(DISPLAY_COLS.keys())].rename(columns=DISPLAY_COLS)
    st.dataframe(display, width="stretch", height=380, hide_index=True,
                 column_config={
                     "Order Date": st.column_config.DatetimeColumn(format="D MMM YYYY, h:mm a"),
                     "Return Date": st.column_config.DatetimeColumn(format="D MMM YYYY, h:mm a"),
                 })

    if perms.get("inspect"):
        mode = st.radio("Mode", ["Single order detail", "Bulk update"], horizontal=True, key="returns_mode")
    else:
        mode = "Single order detail"

    if mode == "Bulk update":
        _render_bulk_update(show)
    else:
        st.markdown("#### Order detail & warehouse inspection")
        options = {row["key"]: _order_label(row) for _, row in show.iterrows()}
        sel_key = st.selectbox("Select an order", list(options.keys()), format_func=lambda k: options[k])
        if not sel_key:
            return
        row = show[show["key"] == sel_key].iloc[0]
        _render_detail(row, perms)


def _render_bulk_update(show: pd.DataFrame):
    st.markdown("#### Bulk warehouse inspection update")
    st.caption("Select multiple returns and apply one inspection result to all of them at once.")

    editable = show[["key", "order_id", "brand", "marketplace", "trigger_label", "inspection_status"]].copy()
    editable.insert(0, "Select", False)
    editable = editable.rename(columns={
        "order_id": "Order ID", "brand": "Brand", "marketplace": "Marketplace",
        "trigger_label": "MP Status", "inspection_status": "Current Status",
    })
    edited = st.data_editor(
        editable, hide_index=True, width="stretch", height=320, key="bulk_editor",
        disabled=["Order ID", "Brand", "Marketplace", "MP Status", "Current Status"],
        column_config={"Select": st.column_config.CheckboxColumn(required=True)},
    )
    selected_keys = edited.loc[edited["Select"], "key"].tolist()
    st.write(f"**{len(selected_keys)}** order(s) selected.")

    if not selected_keys:
        return

    with st.form("bulk_update_form"):
        warehouse = st.text_input("Warehouse (applies to all selected)", placeholder="e.g. Bangkok DC 1")
        status = st.selectbox("Inspection Result", INSPECTION_OPTIONS[1:],
                               format_func=lambda s: INSPECTION_LABELS[s])
        comment = st.text_area("Comment (applies to all selected; required for Damaged / Not Received)")
        damage_reason = st.text_input("Damage Reason (if applicable)")
        st.caption("Evidence — mandatory for Damaged / Not Received. Provide a file upload, a cloud "
                   "storage link, or both (applied to every selected order).")
        evidence_files = st.file_uploader(
            "Option 1 — Direct file upload", accept_multiple_files=True,
            type=["png", "jpg", "jpeg", "webp", "gif", "mp4", "pdf"],
        )
        evidence_link = st.text_input("Option 2 — Google Drive / OneDrive / SharePoint link")
        submitted = st.form_submit_button(f"Apply to {len(selected_keys)} order(s)", type="primary")

    if not submitted:
        return

    if evidence_link.strip() and not is_probably_valid_link(evidence_link):
        st.error("The evidence link doesn't look like a valid http(s) URL.")
        return

    if status in ("damaged", "not_received"):
        if not comment.strip():
            st.error("Comment is required for Damaged / Not Received.")
            return
        if not evidence_files and not evidence_link.strip():
            st.error("Evidence is mandatory for Damaged / Not Received — upload a file or provide a link.")
            return

    session = get_session()
    try:
        user = current_user()
        now = dt.datetime.utcnow()
        for key in selected_keys:
            order = session.get(ReturnOrder, key)
            if order is None:
                continue
            if warehouse.strip():
                order.warehouse = warehouse.strip()
            order.inspection_status = status
            order.inspection_comment = comment.strip()
            if damage_reason.strip():
                order.damage_reason = damage_reason.strip()
            order.inspected_by = user["name"]
            order.inspected_at = now
            for f in (evidence_files or []):
                session.add(Evidence(order_key=key, is_link=False, filename=f.name, content_type=f.type,
                                      size=f.size, data=f.getvalue(), uploaded_by=user["name"],
                                      uploaded_at=now))
            session.commit()
            if evidence_link.strip():
                save_link(key, evidence_link.strip(), user["name"], when=now)
            log_activity(order_key=key, action="Bulk inspection update",
                          comment=f"Result: {status}" + (f" — {comment.strip()}" if comment.strip() else ""))
            if status in ("damaged", "not_received"):
                push_notification("damaged", f"Order {order.order_id} needs Operations action ({status})", key)
    finally:
        session.close()

    bump_cache_nonce()
    st.success(f"Updated {len(selected_keys)} order(s).")
    st.rerun()


def _render_detail(row, perms):
    st.markdown(f"##### {row['order_id']}")
    st.markdown(
        f"<span style='background:#4f46e522;color:#4f46e5;padding:3px 9px;border-radius:999px;"
        f"font-size:12px;font-weight:600;'>{row['brand']}</span> &nbsp; "
        f"{trigger_badge_html(row['trigger_code'], row['trigger_label'])} &nbsp; "
        f"{status_badge_html(row['inspection_status'])}",
        unsafe_allow_html=True,
    )
    if row["trigger_code"] == "cancelled_after_shipped":
        st.warning(f"This order's shipping status is \"Returned\" — it shipped, then was cancelled "
                   f"({row['cancelled_by'] or 'unknown'} — {row['cancel_reason'] or 'no reason given'}). "
                   f"Since it already left the warehouse, it's tracked here for the parcel to come back, "
                   f"even though its marketplace status still reads \"Cancelled\".")
    if row["trigger_code"] == "returned" and (row["mp_order_status"] or "").strip().upper() == "CANCELLED":
        st.info("This order was cancelled without ever shipping (shipping status isn't \"Returned\"), so "
                 "there's no parcel in transit — it's tracked here as a return only so Ops can follow up "
                 "on the refund.")
    if row["trigger_code"] == "delivery_failed":
        st.warning("Delivery failed and the parcel is being returned to the warehouse. "
                   "Marketplace status kept as \"Delivery Failed\".")

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**Brand:** {row['brand']}  ")
        st.write(f"**Marketplace:** {row['marketplace']}  ")
        st.write(f"**Channel:** {row['channel']}  ")
        st.write(f"**Marketplace Order Status:** {row['mp_order_status'] or '—'}  ")
        st.write(f"**Buyer ID:** {row['buyer_id'] or '—'}  ")
        st.write(f"**Order Date:** {fmt_dt(row['order_date'])}  ")
        st.write(f"**Shipping Status:** {row['shipping_status'] or '—'}  ")
        est = " (estimated — GRAAS return timestamp not populated)" if row["return_date_estimated"] else ""
        st.write(f"**Return Date:** {fmt_dt(row['return_date'])}{est}  ")
        st.write(f"**Buyer Return Reason:** {row['return_reason'] or '—'}  ")
    with c2:
        st.write(f"**SKU(s):** {row['sku_summary'] or '—'}  ")
        st.write(f"**Product:** {row['product_summary'] or '—'}  ")
        st.write(f"**Quantity:** {row['qty_total']}  ")
        st.write(f"**Order Amount:** {fmt_money(row['order_amt'], row['currency'])}  ")
        st.write(f"**Refunded Amount:** {fmt_money(row['refund_amt'], row['currency'])}  ")
        st.write(f"**Warehouse:** {row['warehouse'] or 'Unassigned'}  ")
        st.write(f"**Tracking Number:** {row['tracking_number'] or '—'}  ")

    _render_manual_tracking_panel(row["key"])

    st.markdown("###### Warehouse Inspection")
    if not perms.get("inspect"):
        if row["inspection_status"] == "pending":
            st.caption("Awaiting warehouse inspection.")
        else:
            st.caption(f"Inspected by {row['inspected_by'] or '—'} on {fmt_dt(row['inspected_at'])}.")
            if row["inspection_comment"]:
                st.write(row["inspection_comment"])
        return

    with st.form(f"inspect_{row['key']}"):
        warehouse = st.text_input("Warehouse", value=row["warehouse"] or "", placeholder="e.g. Bangkok DC 1")
        tracking = st.text_input("Tracking Number", value=row["tracking_number"] or "")
        status = st.selectbox(
            "Inspection Result", INSPECTION_OPTIONS,
            index=INSPECTION_OPTIONS.index(row["inspection_status"]),
            format_func=lambda s: INSPECTION_LABELS[s],
        )
        comment = st.text_area("Comments (required for Damaged / Not Received)", value=row["inspection_comment"] or "")
        damage_reason = st.text_input("Damage Reason (if applicable)", value=row.get("damage_reason") or "")
        st.caption("Evidence — mandatory for Damaged / Not Received. Provide a file upload, a cloud "
                   "storage link, or both.")
        evidence_files = st.file_uploader(
            "Option 1 — Direct file upload (images, video, PDF)",
            accept_multiple_files=True, type=["png", "jpg", "jpeg", "webp", "gif", "mp4", "pdf"],
        )
        evidence_link = st.text_input("Option 2 — Google Drive / OneDrive / SharePoint link")
        submitted = st.form_submit_button("Save Inspection", type="primary")

    if not submitted:
        st.markdown("###### Evidence on file")
        render_evidence_gallery(row["key"], key_prefix="ret_detail")
        return
    if status == "pending":
        st.error("Select an inspection result.")
        return
    if evidence_link.strip() and not is_probably_valid_link(evidence_link):
        st.error("The evidence link doesn't look like a valid http(s) URL.")
        return

    session = get_session()
    try:
        existing_evidence_count = session.query(Evidence).filter_by(order_key=row["key"]).count()
        new_files = evidence_files or []
        if status in ("damaged", "not_received"):
            if not comment.strip():
                st.error("Comments are required for Damaged / Not Received.")
                return
            if existing_evidence_count == 0 and not new_files and not evidence_link.strip():
                st.error("Evidence is mandatory for Damaged / Not Received — upload a file or provide a link.")
                return

        order = session.get(ReturnOrder, row["key"])
        user = current_user()
        now = dt.datetime.utcnow()
        order.warehouse = warehouse.strip()
        order.tracking_number = tracking.strip()
        order.inspection_status = status
        order.inspection_comment = comment.strip()
        if damage_reason.strip():
            order.damage_reason = damage_reason.strip()
        order.inspected_by = user["name"]
        order.inspected_at = now
        for f in new_files:
            session.add(Evidence(order_key=row["key"], is_link=False, filename=f.name, content_type=f.type,
                                  size=f.size, data=f.getvalue(), uploaded_by=user["name"],
                                  uploaded_at=now))
        session.commit()
        if evidence_link.strip():
            save_link(row["key"], evidence_link.strip(), user["name"], when=now)
        log_activity(order_key=row["key"], action="Inspection recorded",
                      comment=f"Result: {status}" + (f" — {comment.strip()}" if comment.strip() else ""))
        if status in ("damaged", "not_received"):
            push_notification("damaged", f"Order {row['order_id']} needs Operations action ({status})", row["key"])
    finally:
        session.close()

    bump_cache_nonce()
    st.success("Inspection saved.")
    st.rerun()


def _render_manual_tracking_panel(order_key: str):
    manual_df = load_manual_tracking_df(cache_nonce())
    if manual_df.empty:
        return
    rows = manual_df[manual_df["order_key"] == order_key]
    if rows.empty:
        return

    st.markdown("###### DKSH / Ops Return Tracking (manual)")
    for _, m in rows.iterrows():
        with st.container(border=True):
            st.markdown(dksh_status_badge_html(m["dksh_status"]), unsafe_allow_html=True)
            mc1, mc2 = st.columns(2)
            with mc1:
                st.write(f"**Request Date:** {m['request_date'] or '—'}  ")
                st.write(f"**Return ID:** {m['return_id'] or '—'}  ")
                st.write(f"**Reason to Return:** {m['reason_to_return'] or '—'}  ")
                st.write(f"**Customer Comment:** {m['customer_comment'] or '—'}  ")
            with mc2:
                st.write(f"**Courier:** {m['courier'] or '—'}  ")
                st.write(f"**Tracking No.:** {m['tracking_no'] or '—'}  ")
                st.write(f"**Return Delivered:** {m['return_delivered_date'] or '—'}  ")
                wr = m["warehouse_received_date"]
                st.write(f"**Warehouse Received (DKSH):** {wr if wr else 'Not recorded in source sheet'}  ")

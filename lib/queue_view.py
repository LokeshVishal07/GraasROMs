"""Shared renderer for the per-inspection-outcome queue pages (Damaged, Return
Not Received, Refund Only, and any future ones). Each page is a thin wrapper
that calls render_queue() with the inspection_status value(s) it owns -- this
keeps the list/filter/evidence/raise-claim UI identical across all of them
and any future bug fix only needs to happen once.
"""
import streamlit as st

from lib.data import load_orders_df, apply_filters, cache_nonce
from lib.utils import status_badge_html, fmt_dt, fmt_money
from lib.widgets import filter_bar
from lib.auth import current_permissions
from lib.evidence import render_evidence_gallery


def render_queue(statuses: list, title: str, key_prefix: str, metric_labels: dict, empty_hint: str = ""):
    """statuses: inspection_status values that belong on this page, e.g. ["damaged"].
    metric_labels: {inspection_status: display label} for the metric tiles at the top.
    empty_hint: extra sentence shown under the "nothing here" message."""
    st.subheader(title)
    perms = current_permissions()
    df = load_orders_df(cache_nonce())
    if df.empty:
        st.info("No data loaded yet.")
        return

    f = filter_bar(df, key_prefix)
    fdf = apply_filters(df, f["preset"], f["custom_start"], f["custom_end"], f["marketplaces"],
                         f["channels"], f["brands"], f["warehouses"], f["statuses"], f["reasons"],
                         f["triggers"], f["search"])

    queue = fdf[fdf["inspection_status"].isin(statuses)].sort_values("inspected_at", ascending=False)

    cols = st.columns(len(metric_labels))
    for col, (status, label) in zip(cols, metric_labels.items()):
        with col:
            st.metric(label, int((queue["inspection_status"] == status).sum()))

    if queue.empty:
        msg = f"Nothing in the {title.lower()} queue matches the current filters."
        if empty_hint:
            msg += f" {empty_hint}"
        st.info(msg)
        return

    for _, row in queue.iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown(
                    f"**{row['order_id']}** · {row['brand']} · {row['marketplace']} &nbsp; "
                    f"{status_badge_html(row['inspection_status'])}", unsafe_allow_html=True,
                )
                st.caption(f"{row['product_summary'] or '—'} · SKU: {row['sku_summary'] or '—'}")
                st.write(f"Inspected by **{row['inspected_by'] or '—'}** on {fmt_dt(row['inspected_at'])}")
                if row["inspection_comment"]:
                    st.write(f"_{row['inspection_comment']}_")
                if row.get("damage_reason"):
                    st.caption(f"Reason: {row['damage_reason']}")
                st.caption(f"Refund amount: {fmt_money(row['refund_amt'], row['currency'])}")
            with c2:
                if perms.get("raise_claim"):
                    if st.button("Raise Claim", key=f"{key_prefix}_claim_{row['key']}", width="stretch"):
                        st.session_state["prefill_claim_key"] = row["key"]
                        st.session_state["nav_target"] = "Marketplace Claims"
                        st.rerun()
            with st.expander("Evidence"):
                render_evidence_gallery(row["key"], key_prefix=f"{key_prefix}_{row['key']}")

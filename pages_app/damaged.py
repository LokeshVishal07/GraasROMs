import streamlit as st

from lib.data import load_orders_df, cache_nonce
from lib.utils import status_badge_html, fmt_dt, fmt_money
from lib.auth import current_permissions
from lib.evidence import render_evidence_gallery

DISPLAY_COLS = {
    "order_id": "Order ID", "brand": "Brand", "marketplace": "Marketplace",
    "product_summary": "Product", "sku_summary": "SKU",
    "inspected_at": "Inspected", "inspected_by": "Inspected By",
    "inspection_comment": "Comment", "refund_amt": "Refunded",
}


def render():
    st.subheader("Damaged / Not Received Queue")
    perms = current_permissions()
    df = load_orders_df(cache_nonce())
    if df.empty:
        st.info("No data loaded yet.")
        return

    queue = df[df["inspection_status"].isin(["damaged", "not_received"])].sort_values(
        "inspected_at", ascending=False)

    c1, c2 = st.columns(2)
    with c1:
        st.metric("Damaged", int((queue["inspection_status"] == "damaged").sum()))
    with c2:
        st.metric("Not Received", int((queue["inspection_status"] == "not_received").sum()))

    if queue.empty:
        st.info("Nothing in the damaged / not received queue.")
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
                    st.caption(f"Damage reason: {row['damage_reason']}")
                st.caption(f"Refund amount: {fmt_money(row['refund_amt'], row['currency'])}")
            with c2:
                if perms.get("raise_claim"):
                    if st.button("Raise Claim", key=f"claim_{row['key']}", width="stretch"):
                        st.session_state["prefill_claim_key"] = row["key"]
                        st.session_state["nav_target"] = "Marketplace Claims"
                        st.rerun()
            with st.expander("Evidence"):
                render_evidence_gallery(row["key"], key_prefix="dmgq")

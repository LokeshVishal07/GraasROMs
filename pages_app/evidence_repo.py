import datetime as dt

import streamlit as st

from lib.data import load_evidence_df, cache_nonce
from lib.evidence import render_evidence_item, zip_evidence_files
from lib.db import get_session, Evidence
from lib.auth import current_permissions

CLAIM_STATUS_OPTIONS = ["Open", "Follow-up", "Waiting for Marketplace", "Resolved", "Rejected"]


def render():
    st.subheader("Evidence Repository")
    perms = current_permissions()
    if not (perms.get("view_damaged_queue") or perms.get("manage_claims") or perms.get("inspect")):
        st.info("Your role doesn't have access to the evidence repository.")
        return

    df = load_evidence_df(cache_nonce())
    if df.empty:
        st.info("No evidence uploaded yet.")
        return

    st.caption(f"{len(df)} evidence item(s) across {df['order_key'].nunique()} order(s).")

    with st.container():
        c1, c2, c3 = st.columns(3)
        with c1:
            order_id_q = st.text_input("Order ID", key="ev_order_id")
        with c2:
            return_id_q = st.text_input("Return ID", key="ev_return_id")
        with c3:
            sku_q = st.text_input("SKU", key="ev_sku")

        c4, c5, c6 = st.columns(3)
        with c4:
            marketplaces = st.multiselect("Marketplace", sorted(df["marketplace"].dropna().unique()),
                                           key="ev_marketplace")
        with c5:
            buyer_q = st.text_input("Buyer ID", key="ev_buyer")
        with c6:
            warehouse_users = st.multiselect("Warehouse User", sorted(df["uploaded_by"].dropna().unique()),
                                              key="ev_wh_user")

        c7, c8, c9 = st.columns(3)
        with c7:
            claim_statuses = st.multiselect("Claim Status", CLAIM_STATUS_OPTIONS, key="ev_claim_status")
        with c8:
            date_from = st.date_input("Uploaded from", value=None, key="ev_date_from")
        with c9:
            date_to = st.date_input("Uploaded to", value=None, key="ev_date_to")

    view = df.copy()
    if order_id_q.strip():
        view = view[view["order_id"].fillna("").str.contains(order_id_q.strip(), case=False, regex=False)]
    if return_id_q.strip():
        view = view[view["return_id"].fillna("").str.contains(return_id_q.strip(), case=False, regex=False)]
    if sku_q.strip():
        view = view[view["sku_summary"].fillna("").str.contains(sku_q.strip(), case=False, regex=False)]
    if buyer_q.strip():
        view = view[view["buyer_id"].fillna("").str.contains(buyer_q.strip(), case=False, regex=False)]
    if marketplaces:
        view = view[view["marketplace"].isin(marketplaces)]
    if warehouse_users:
        view = view[view["uploaded_by"].isin(warehouse_users)]
    if claim_statuses:
        view = view[view["claim_status"].isin(claim_statuses)]
    if date_from:
        view = view[view["uploaded_at"].dt.date >= date_from]
    if date_to:
        view = view[view["uploaded_at"].dt.date <= date_to]

    st.markdown(f"#### {len(view)} result(s)")
    if view.empty:
        st.info("No evidence matches these filters.")
        return

    if len(view) > 1:
        session = get_session()
        try:
            ev_objs = session.query(Evidence).filter(Evidence.id.in_(view["id"].tolist())).all()
        finally:
            session.close()
        st.download_button(
            "Download all matching as ZIP", data=zip_evidence_files(ev_objs),
            file_name="evidence_repository_export.zip", mime="application/zip",
        )

    view = view.sort_values("uploaded_at", ascending=False)
    session = get_session()
    try:
        ev_by_id = {e.id: e for e in session.query(Evidence).filter(Evidence.id.in_(view["id"].tolist())).all()}
    finally:
        session.close()

    for _, row in view.iterrows():
        with st.container(border=True):
            st.markdown(f"**{row['order_id'] or 'Unknown order'}** · {row['brand'] or '—'} · "
                        f"{row['marketplace'] or '—'}"
                        + (f" · Return ID: {row['return_id']}" if row["return_id"] else ""))
            st.caption(f"SKU: {row['sku_summary'] or '—'} · Inspection: {row['inspection_status'] or '—'}"
                       + (f" · Claim: {row['claim_status']}" if row["claim_status"] else ""))
            ev = ev_by_id.get(row["id"])
            if ev is not None:
                render_evidence_item(ev, key_prefix="repo")

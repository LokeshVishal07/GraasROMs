"""Cached data loading + filtering shared by every page."""
import datetime as dt

import pandas as pd
import streamlit as st

from lib.db import get_session, ReturnOrder, Ticket, ManualTracking, Evidence


def bump_cache_nonce():
    st.session_state["cache_nonce"] = st.session_state.get("cache_nonce", 0) + 1


def cache_nonce():
    return st.session_state.get("cache_nonce", 0)


@st.cache_data(ttl=15, show_spinner=False)
def load_orders_df(_nonce) -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.query(ReturnOrder).all()
        recs = []
        for r in rows:
            recs.append({
                "key": r.key, "channel": r.channel, "marketplace": r.marketplace, "brand": r.brand,
                "order_id": r.order_id, "return_id": r.return_id, "buyer_id": r.buyer_id, "order_date": r.order_date,
                "order_status": r.order_status, "mp_order_status": r.mp_order_status,
                "shipping_status": r.shipping_status, "cancel_reason": r.cancel_reason,
                "cancelled_by": r.cancelled_by, "return_reason": r.return_reason,
                "return_date": r.return_date, "return_date_estimated": r.return_date_estimated,
                "order_amt": r.order_amt or 0, "refund_amt": r.refund_amt or 0, "currency": r.currency,
                "trigger_code": r.trigger_code, "trigger_label": r.trigger_label,
                "sku_summary": r.sku_summary, "product_summary": r.product_summary,
                "qty_total": r.qty_total or 0,
                "inspection_status": r.inspection_status, "inspection_comment": r.inspection_comment,
                "damage_reason": r.damage_reason,
                "inspected_by": r.inspected_by, "inspected_at": r.inspected_at,
                "warehouse": r.warehouse, "tracking_number": r.tracking_number,
            })
    finally:
        session.close()
    df = pd.DataFrame(recs)
    if df.empty:
        return df
    df["order_date"] = pd.to_datetime(df["order_date"])
    df["return_date"] = pd.to_datetime(df["return_date"])
    return df


@st.cache_data(ttl=15, show_spinner=False)
def load_tickets_df(_nonce) -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.query(Ticket).all()
        recs = [{
            "id": t.id, "order_key": t.order_key, "subject": t.subject, "status": t.status,
            "priority": t.priority, "marketplace_case_id": t.marketplace_case_id,
            "internal_notes": t.internal_notes,
            "assigned_to": t.assigned_to, "created_by": t.created_by,
            "created_at": t.created_at, "updated_at": t.updated_at,
        } for t in rows]
    finally:
        session.close()
    return pd.DataFrame(recs)


@st.cache_data(ttl=15, show_spinner=False)
def load_evidence_df(_nonce) -> pd.DataFrame:
    """Evidence rows joined with their order's identifying fields and the
    order's most-recently-updated claim status, for the Evidence Repository."""
    session = get_session()
    try:
        evidence_rows = session.query(Evidence).all()
        order_map = {o.key: o for o in session.query(ReturnOrder).all()}
        claim_status_by_order = {}
        for t in session.query(Ticket).order_by(Ticket.updated_at.asc()).all():
            claim_status_by_order[t.order_key] = t.status  # last write wins -> most recent

        recs = []
        for e in evidence_rows:
            o = order_map.get(e.order_key)
            recs.append({
                "id": e.id, "order_key": e.order_key,
                "order_id": o.order_id if o else None,
                "return_id": o.return_id if o else None,
                "sku_summary": o.sku_summary if o else None,
                "marketplace": o.marketplace if o else None,
                "brand": o.brand if o else None,
                "buyer_id": o.buyer_id if o else None,
                "inspection_status": o.inspection_status if o else None,
                "claim_status": claim_status_by_order.get(e.order_key),
                "is_link": e.is_link, "filename": e.filename, "link_url": e.link_url,
                "content_type": e.content_type, "size": e.size,
                "uploaded_by": e.uploaded_by, "uploaded_at": e.uploaded_at,
            })
    finally:
        session.close()
    df = pd.DataFrame(recs)
    if not df.empty:
        df["uploaded_at"] = pd.to_datetime(df["uploaded_at"])
    return df


@st.cache_data(ttl=15, show_spinner=False)
def load_manual_tracking_df(_nonce) -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.query(ManualTracking).all()
        recs = [{
            "order_key": m.order_key, "matched": m.matched, "brand": m.brand,
            "request_date": m.request_date, "marketplace": m.marketplace,
            "order_id": m.order_id, "return_id": m.return_id,
            "reason_to_return": m.reason_to_return, "customer_comment": m.customer_comment,
            "sku": m.sku, "quantity": m.quantity, "amount": m.amount,
            "courier": m.courier, "tracking_no": m.tracking_no,
            "return_delivered_date": m.return_delivered_date,
            "warehouse_received_date": m.warehouse_received_date,
            "dksh_status": m.dksh_status,
        } for m in rows]
    finally:
        session.close()
    return pd.DataFrame(recs)


def date_range_for_preset(preset: str, custom_start=None, custom_end=None):
    today = dt.date.today()
    if preset == "Last 7 days":
        return today - dt.timedelta(days=7), today
    if preset == "Last 30 days":
        return today - dt.timedelta(days=30), today
    if preset == "Last 90 days":
        return today - dt.timedelta(days=90), today
    if preset == "This year":
        return dt.date(today.year, 1, 1), today
    if preset == "Custom" and custom_start and custom_end:
        return custom_start, custom_end
    return None, None


def apply_filters(df, preset, custom_start, custom_end, marketplaces, channels, brands,
                   warehouses, statuses, reasons, triggers, search):
    if df.empty:
        return df
    out = df.copy()

    start, end = date_range_for_preset(preset, custom_start, custom_end)
    if start and end:
        mask = (out["order_date"].dt.date >= start) & (out["order_date"].dt.date <= end)
        out = out[mask]

    if marketplaces:
        out = out[out["marketplace"].isin(marketplaces)]
    if channels:
        out = out[out["channel"].isin(channels)]
    if brands:
        out = out[out["brand"].isin(brands)]
    if warehouses:
        out = out[out["warehouse"].isin(warehouses)]
    if statuses:
        out = out[out["inspection_status"].isin(statuses)]
    if reasons:
        out = out[out["return_reason"].isin(reasons)]
    if triggers:
        out = out[out["trigger_code"].isin(triggers)]

    if search:
        s = search.strip().lower()
        if s:
            hay = (
                out["order_id"].fillna("").str.lower() + " " +
                out["sku_summary"].fillna("").str.lower() + " " +
                out["tracking_number"].fillna("").str.lower() + " " +
                out["buyer_id"].fillna("").str.lower()
            )
            out = out[hay.str.contains(s, regex=False)]
    return out

"""Imports the manually-tracked DKSH/Ops return sheet (combined across the per-brand
'{Brand} - ReturnRefund' Google Sheet tabs) and maps each row onto a ReturnOrder by
order_id, so warehouse/DKSH progress shows up next to the GRAAS order data.

Expected columns (see manual_return_tracking.csv):
brand, request_date, marketplace, order_id, return_id, reason_to_return,
customer_comment, sku, quantity, amount, courier, tracking_no,
return_delivered_date, warehouse_received, product_condition, final_action, status
"""
import datetime as dt

import pandas as pd

from lib.db import get_session, ReturnOrder, ManualTracking

MARKETPLACE_NORMALIZE = {
    "shopee": "Shopee", "lazada": "Lazada", "tiktok": "TikTok", "tikok": "TikTok",
}

BROKEN_FORMULA_VALUES = {"#name?", "#n/a", "#value!", "#ref!"}


def _norm_marketplace(v):
    v = (v or "").strip().lower()
    return MARKETPLACE_NORMALIZE.get(v, v.title() if v else "")


def _norm_status(v):
    v = (v or "").strip().lower()
    if v == "close":
        return "Closed"
    if v == "open":
        return "Open"
    return "Unknown"


def _clean_text(v):
    v = (v or "").strip()
    if v.lower() in BROKEN_FORMULA_VALUES:
        return ""
    return v


def _parse_date(v):
    v = (v or "").strip()
    if not v or v.lower() in BROKEN_FORMULA_VALUES:
        return None
    try:
        return pd.to_datetime(v).date()
    except Exception:
        return None


def import_manual_tracking(file, batch_label: str = None) -> dict:
    batch_label = batch_label or dt.datetime.utcnow().strftime("manual-import-%Y%m%d-%H%M%S")
    df = pd.read_csv(file, dtype=str, keep_default_na=False)

    session = get_session()
    matched, unmatched, total = 0, 0, 0
    try:
        # index existing orders by order_id for fast lookup (order_id is effectively
        # unique per marketplace order number across our channels)
        order_index = {}
        for o in session.query(ReturnOrder.key, ReturnOrder.order_id).all():
            order_index.setdefault(o.order_id, []).append(o.key)

        for _, row in df.iterrows():
            order_id = (row.get("order_id") or "").strip()
            if not order_id:
                continue
            total += 1

            keys = order_index.get(order_id, [])
            order_key = keys[0] if keys else None
            if order_key:
                matched += 1
            else:
                unmatched += 1

            mt = ManualTracking(
                order_key=order_key,
                matched=bool(order_key),
                brand=(row.get("brand") or "").strip(),
                request_date=_parse_date(row.get("request_date")),
                marketplace=_norm_marketplace(row.get("marketplace")),
                order_id=order_id,
                return_id=(row.get("return_id") or "").strip(),
                reason_to_return=_clean_text(row.get("reason_to_return")),
                customer_comment=_clean_text(row.get("customer_comment")),
                sku=(row.get("sku") or "").strip(),
                quantity=(row.get("quantity") or "").strip(),
                amount=(row.get("amount") or "").strip(),
                courier=(row.get("courier") or "").strip(),
                tracking_no=(row.get("tracking_no") or "").strip(),
                return_delivered_date=_clean_text(row.get("return_delivered_date")),
                warehouse_received_date=_clean_text(row.get("warehouse_received")),
                dksh_status=_norm_status(row.get("status")),
                import_batch=batch_label,
            )
            session.add(mt)
        session.commit()
    finally:
        session.close()

    return {"total_rows": total, "matched": matched, "unmatched": unmatched, "batch": batch_label}

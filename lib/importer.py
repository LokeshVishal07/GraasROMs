"""CSV importer for GRAAS order/item exports (return_orders_2026.csv / return_items_2026.csv
format, or your own exports with the same columns / common aliases), plus the brand
classification and return-trigger logic ported from the original dashboard.
"""
import datetime as dt

import pandas as pd

from lib.db import get_session, ReturnOrder
from lib.seed import CHANNEL_BRAND_MAP

COLUMN_ALIASES = {
    "channel": ["channel", "CHANNEL"],
    "order_id": ["order_id", "ORDER_ID", "orderid"],
    "buyer_id": ["buyer_id", "BUYER_ID"],
    "order_created_ts": ["order_created_ts", "ORDER_CREATED_TS", "order_date"],
    "order_status": ["order_status", "ORDER_STATUS"],
    "shipping_status": ["shipping_status", "SHIPPING_STATUS"],
    "cancel_reason": ["cancel_reason", "CANCEL_REASON"],
    "cancelled_by": ["cancelled_by", "CANCELLED_BY"],
    "return_reason": ["return_reason", "RETURN_REASON"],
    "order_returned_ts": ["order_returned_ts", "ORDER_RETURNED_TS", "return_date"],
    "order_amt": ["order_amt", "ORDER_AMT"],
    "returned_refunded_revenue_amt": ["returned_refunded_revenue_amt", "RETURNED_REFUNDED_REVENUE_AMT", "refund_amt"],
    "currency": ["currency", "REPORTING_CCY", "reporting_ccy"],
}

ITEM_COLUMN_ALIASES = {
    "channel": ["channel", "CHANNEL"],
    "order_id": ["order_id", "ORDER_ID"],
    "seller_sku": ["seller_sku", "SELLER_SKU", "sku"],
    "product_name": ["product_name", "PRODUCT_NAME"],
    "item_quantity": ["item_quantity", "ITEM_QUANTITY", "quantity"],
}

DELIVERY_FAIL_PATTERNS = [
    "ไม่สำเร็จ", "failed_delivery", "package_lost", "สูญหาย", "ถูกทิ้ง",
]


def _map_columns(df: pd.DataFrame, aliases: dict) -> pd.DataFrame:
    rename = {}
    for std, options in aliases.items():
        for opt in options:
            if opt in df.columns:
                rename[opt] = std
                break
    df = df.rename(columns=rename)
    for std in aliases:
        if std not in df.columns:
            df[std] = None
    return df


def _parse_dt(val):
    if val is None or (isinstance(val, float) and pd.isna(val)) or val == "":
        return None
    try:
        return pd.to_datetime(val).to_pydatetime()
    except Exception:
        return None


def classify_trigger(order_status, shipping_status, cancel_reason, channel):
    order_status = (order_status or "").strip().upper()
    shipping_status = (shipping_status or "").strip().upper()
    cancel_reason_l = (cancel_reason or "").strip().lower()
    is_tiktok = (channel or "").lower().startswith("tiktok")

    tiktok_delivery_fail = is_tiktok and any(p in cancel_reason_l for p in DELIVERY_FAIL_PATTERNS)

    if order_status == "CANCELLED" and shipping_status == "RETURNED":
        return "cancelled_after_shipped", "Cancelled After Shipped"
    if order_status == "DELIVERY_FAILED" or tiktok_delivery_fail:
        return "delivery_failed", "Delivery Failed"
    if shipping_status == "RETURNED" or "RETURN" in order_status:
        return "returned", "Returned"
    return "other", order_status.title() if order_status else "Other"


def brand_for_channel(channel: str) -> str:
    return CHANNEL_BRAND_MAP.get((channel or "").strip().lower(), "Unmapped")


def marketplace_for_channel(channel: str) -> str:
    return (channel or "").split("-")[0].strip().capitalize()


def import_csvs(orders_file, items_file=None, batch_label: str = None) -> dict:
    """orders_file / items_file: file-like objects (e.g. from st.file_uploader). Returns a summary dict."""
    batch_label = batch_label or dt.datetime.utcnow().strftime("import-%Y%m%d-%H%M%S")

    orders_df = pd.read_csv(orders_file, dtype=str, keep_default_na=False)
    orders_df = _map_columns(orders_df, COLUMN_ALIASES)

    items_lookup = {}
    if items_file is not None:
        items_df = pd.read_csv(items_file, dtype=str, keep_default_na=False)
        items_df = _map_columns(items_df, ITEM_COLUMN_ALIASES)
        for (channel, order_id), g in items_df.groupby(["channel", "order_id"]):
            skus = [s for s in g["seller_sku"].fillna("").tolist() if s]
            names = [n for n in g["product_name"].fillna("").tolist() if n]
            qty = 0
            for q in g["item_quantity"].fillna("0").tolist():
                try:
                    qty += int(float(q))
                except Exception:
                    pass
            items_lookup[(channel, order_id)] = {
                "sku_summary": ", ".join(skus[:6]) + (f" (+{len(skus)-6} more)" if len(skus) > 6 else ""),
                "product_summary": "; ".join(n[:60] for n in names[:3]) + (f" (+{len(names)-3} more)" if len(names) > 3 else ""),
                "qty_total": qty,
            }

    session = get_session()
    inserted, updated = 0, 0
    try:
        existing_rows = session.query(ReturnOrder.key, ReturnOrder.inspection_status).all()
        existing_keys = {k: insp for k, insp in existing_rows}

        insert_mappings = []
        update_mappings = []
        seen_keys = set()

        for row in orders_df.itertuples(index=False):
            row = row._asdict()
            channel = (row.get("channel") or "").strip()
            order_id = (row.get("order_id") or "").strip()
            if not channel or not order_id:
                continue
            key = f"{channel}|{order_id}"
            if key in seen_keys:
                continue  # last-write-wins would need special handling; skip dup keys within the same file
            seen_keys.add(key)

            order_status = row.get("order_status") or ""
            shipping_status = row.get("shipping_status") or ""
            cancel_reason = row.get("cancel_reason") or ""
            trigger_code, trigger_label = classify_trigger(order_status, shipping_status, cancel_reason, channel)

            return_ts = _parse_dt(row.get("order_returned_ts"))
            order_ts = _parse_dt(row.get("order_created_ts"))
            return_estimated = return_ts is None
            if return_ts is None:
                return_ts = order_ts

            try:
                order_amt = float(row.get("order_amt") or 0)
            except Exception:
                order_amt = 0.0
            try:
                refund_amt = float(row.get("returned_refunded_revenue_amt") or 0)
            except Exception:
                refund_amt = 0.0

            item_info = items_lookup.get((channel, order_id), {})

            is_new = key not in existing_keys
            mapping = {
                "key": key,
                "channel": channel,
                "marketplace": marketplace_for_channel(channel),
                "brand": brand_for_channel(channel),
                "order_id": order_id,
                "buyer_id": row.get("buyer_id"),
                "order_date": order_ts,
                "order_status": order_status,
                "mp_order_status": order_status,
                "shipping_status": shipping_status,
                "cancel_reason": cancel_reason,
                "cancelled_by": row.get("cancelled_by"),
                "return_reason": row.get("return_reason"),
                "return_date": return_ts,
                "return_date_estimated": return_estimated,
                "order_amt": order_amt,
                "refund_amt": refund_amt,
                "currency": row.get("currency") or "THB",
                "trigger_code": trigger_code,
                "trigger_label": trigger_label,
                "sku_summary": item_info.get("sku_summary", ""),
                "product_summary": item_info.get("product_summary", ""),
                "qty_total": item_info.get("qty_total", 0),
                "import_batch": batch_label,
            }
            if is_new:
                mapping["inspection_status"] = "pending"
                insert_mappings.append(mapping)
                inserted += 1
            else:
                existing_insp = existing_keys.get(key)
                mapping["inspection_status"] = existing_insp if existing_insp else "pending"
                update_mappings.append(mapping)
                updated += 1

        if insert_mappings:
            session.bulk_insert_mappings(ReturnOrder, insert_mappings)
        if update_mappings:
            session.bulk_update_mappings(ReturnOrder, update_mappings)
        session.commit()
    finally:
        session.close()

    return {"inserted": inserted, "updated": updated, "total_rows": len(orders_df), "batch": batch_label}

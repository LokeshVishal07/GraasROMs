import io
import streamlit as st
import pandas as pd

from lib.data import load_orders_df, apply_filters, cache_nonce
from lib.widgets import filter_bar

EXPORT_COLS = {
    "order_id": "Order ID", "brand": "Brand", "channel": "Channel", "marketplace": "Marketplace",
    "sku_summary": "SKU", "product_summary": "Product", "qty_total": "Quantity",
    "order_date": "Order Date", "return_date": "Return Date", "buyer_id": "Buyer ID",
    "mp_order_status": "Marketplace Order Status", "trigger_label": "Return Trigger",
    "cancel_reason": "Cancel Reason", "return_reason": "Buyer Return Reason",
    "inspection_status": "Return Status", "warehouse": "Warehouse", "tracking_number": "Tracking Number",
    "order_amt": "Order Amount", "refund_amt": "Refunded Amount", "currency": "Currency",
}


def _build_pdf(df: pd.DataFrame) -> bytes:
    from fpdf import FPDF
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Return Orders Report", ln=1)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 6, f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} - {len(df)} records", ln=1)
    pdf.ln(2)
    cols = list(EXPORT_COLS.values())
    col_w = 277 / len(cols)
    pdf.set_font("Helvetica", "B", 6)
    for c in cols:
        pdf.cell(col_w, 6, str(c)[:20], border=1)
    pdf.ln()
    pdf.set_font("Helvetica", "", 5.5)
    for _, row in df.iterrows():
        for c in EXPORT_COLS.keys():
            val = row.get(c, "")
            val = "" if pd.isna(val) else str(val)
            pdf.cell(col_w, 5.5, val[:22], border=1)
        pdf.ln()
    return bytes(pdf.output())


def render():
    st.subheader("Reports & Export")
    df = load_orders_df(cache_nonce())
    f = filter_bar(df, "reports")
    fdf = apply_filters(df, f["preset"], f["custom_start"], f["custom_end"], f["marketplaces"],
                         f["channels"], f["brands"], f["warehouses"], f["statuses"], f["reasons"],
                         f["triggers"], f["search"])

    st.write(f"**{len(fdf)}** rows in the current filter · "
             f"**{int(fdf['inspection_status'].isin(['damaged','not_received']).sum()) if not fdf.empty else 0}** damaged/not received")

    if fdf.empty:
        st.info("No data to export for these filters.")
        return

    export_df = fdf[list(EXPORT_COLS.keys())].rename(columns=EXPORT_COLS)

    c1, c2, c3 = st.columns(3)
    with c1:
        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Export CSV", csv_bytes, file_name="returns_export.csv", mime="text/csv",
                            width="stretch")
    with c2:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Returns")
        st.download_button("⬇ Export Excel", buf.getvalue(), file_name="returns_export.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            width="stretch")
    with c3:
        try:
            pdf_bytes = _build_pdf(export_df)
            st.download_button("⬇ Export PDF", pdf_bytes, file_name="returns_export.pdf",
                                mime="application/pdf", width="stretch")
        except Exception as e:
            st.caption(f"PDF export unavailable: {e}")

    st.markdown("#### Preview")
    st.dataframe(export_df, width="stretch", height=400, hide_index=True)

import streamlit as st
import plotly.express as px

from lib.data import load_orders_df, load_tickets_df, apply_filters, cache_nonce
from lib.widgets import filter_bar, kpi_row
from lib.utils import status_badge_html, trigger_badge_html, fmt_date, fmt_money

PALETTE = ["#4f46e5", "#0d9488", "#f59e0b", "#e11d48", "#0284c7", "#8b5cf6", "#16a34a", "#f97316"]


def render():
    st.subheader("Dashboard")
    df = load_orders_df(cache_nonce())
    tickets = load_tickets_df(cache_nonce())

    f = filter_bar(df, "dash")
    fdf = apply_filters(df, f["preset"], f["custom_start"], f["custom_end"], f["marketplaces"],
                         f["channels"], f["brands"], f["warehouses"], f["statuses"], f["reasons"],
                         f["triggers"], f["search"])

    scoped_ticket_keys = set(fdf["key"]) if not fdf.empty else set()
    scoped_tickets = tickets[tickets["order_key"].isin(scoped_ticket_keys)] if not tickets.empty else tickets

    kpi_row([
        ("Total Returns", len(fdf), "#4f46e5"),
        ("Pending Inspection", int((fdf["inspection_status"] == "pending").sum()) if not fdf.empty else 0, "#d97706"),
        ("Good Condition", int((fdf["inspection_status"] == "good").sum()) if not fdf.empty else 0, "#16a34a"),
        ("Damaged", int((fdf["inspection_status"] == "damaged").sum()) if not fdf.empty else 0, "#e11d48"),
    ])
    st.write("")
    kpi_row([
        ("Not Received", int((fdf["inspection_status"] == "not_received").sum()) if not fdf.empty else 0, "#0284c7"),
        ("Cancelled After Shipped", int((fdf["trigger_code"] == "cancelled_after_shipped").sum()) if not fdf.empty else 0, "#b45309"),
        ("Delivery Failed", int((fdf["trigger_code"] == "delivery_failed").sum()) if not fdf.empty else 0, "#e11d48"),
        ("Open Marketplace Cases", int(scoped_tickets["status"].isin(["Open", "Follow-up", "Waiting for Marketplace"]).sum()) if not scoped_tickets.empty else 0, "#0284c7"),
    ])

    st.markdown("#### Trends & Breakdown")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Returns Over Time**")
        if not fdf.empty:
            trend = fdf.groupby(fdf["order_date"].dt.date).size().reset_index(name="count")
            fig = px.line(trend, x="order_date", y="count", markers=True)
            fig.update_traces(line_color="#4f46e5")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No data in range.")
    with c2:
        st.markdown("**Returns by Brand**")
        if not fdf.empty:
            bc = fdf["brand"].value_counts().reset_index()
            bc.columns = ["brand", "count"]
            fig = px.pie(bc, names="brand", values="count", hole=0.55, color_discrete_sequence=PALETTE)
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No data in range.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**Marketplace Breakdown**")
        if not fdf.empty:
            mp = fdf["marketplace"].value_counts().reset_index()
            mp.columns = ["marketplace", "count"]
            fig = px.bar(mp, x="marketplace", y="count", color_discrete_sequence=["#4f46e5"])
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No data in range.")
    with c4:
        st.markdown("**MP Status Breakdown**")
        if not fdf.empty:
            tc = fdf["trigger_label"].value_counts().reset_index()
            tc.columns = ["trigger", "count"]
            fig = px.bar(tc, x="trigger", y="count", color_discrete_sequence=["#0d9488"])
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=280)
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("No data in range.")

    st.markdown("#### Recent Return Activity")
    if fdf.empty:
        st.info("No return activity in this range.")
        return
    recent = fdf.sort_values("order_date", ascending=False).head(25)
    rows_html = []
    for _, r in recent.iterrows():
        rows_html.append(
            f"<tr><td>{r['order_id']}</td><td>{r['brand']}</td><td>{r['marketplace']}</td>"
            f"<td>{fmt_date(r['order_date'])}</td><td>{trigger_badge_html(r['trigger_code'], r['trigger_label'])}</td>"
            f"<td>{(r['return_reason'] or '')[:30]}</td><td>{status_badge_html(r['inspection_status'])}</td>"
            f"<td>{fmt_money(r['refund_amt'], r['currency'])}</td></tr>"
        )
    table_html = (
        "<div style='overflow-x:auto;'><table style='width:100%;border-collapse:collapse;font-size:13px;'>"
        "<thead><tr style='text-align:left;color:#6b7280;font-size:11.5px;text-transform:uppercase;'>"
        "<th style='padding:8px;'>Order ID</th><th style='padding:8px;'>Brand</th><th style='padding:8px;'>Marketplace</th>"
        "<th style='padding:8px;'>Order Date</th><th style='padding:8px;'>MP Status</th><th style='padding:8px;'>Reason</th>"
        "<th style='padding:8px;'>Inspection</th><th style='padding:8px;'>Amount</th></tr></thead><tbody>"
        + "".join(rows_html) + "</tbody></table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)

"""Shared filter bar and KPI row widgets used across pages."""
import datetime as dt

import streamlit as st

PRESETS = ["Last 7 days", "Last 30 days", "Last 90 days", "This year", "All time", "Custom"]


def filter_bar(df, key_prefix: str) -> dict:
    with st.container():
        c1, c2 = st.columns([1, 2])
        with c1:
            preset = st.selectbox("Date range", PRESETS, index=1, key=f"{key_prefix}_preset")
        custom_start, custom_end = None, None
        with c2:
            if preset == "Custom":
                d1, d2 = st.columns(2)
                with d1:
                    custom_start = st.date_input("From", value=dt.date.today() - dt.timedelta(days=30),
                                                  key=f"{key_prefix}_start")
                with d2:
                    custom_end = st.date_input("To", value=dt.date.today(), key=f"{key_prefix}_end")

        search = st.text_input(
            "🔍 Search — order number, tracking number, SKU, buyer ID",
            key=f"{key_prefix}_search", placeholder="Type to search…",
        )

        if df.empty:
            marketplaces = channels = brands = warehouses = statuses = reasons = triggers = []
        else:
            c3, c4, c5 = st.columns(3)
            with c3:
                marketplaces = st.multiselect("Marketplace", sorted(df["marketplace"].dropna().unique()),
                                               key=f"{key_prefix}_mp")
            with c4:
                brands = st.multiselect("Brand", sorted(df["brand"].dropna().unique()),
                                         key=f"{key_prefix}_brand")
            with c5:
                channels = st.multiselect("Channel", sorted(df["channel"].dropna().unique()),
                                           key=f"{key_prefix}_channel")

            c6, c7, c8 = st.columns(3)
            with c6:
                warehouses = st.multiselect("Warehouse", sorted([w for w in df["warehouse"].dropna().unique() if w]),
                                             key=f"{key_prefix}_wh")
            with c7:
                status_opts = ["pending", "good", "damaged", "not_received", "refund_only"]
                statuses = st.multiselect("Inspection status", status_opts, key=f"{key_prefix}_status")
            with c8:
                triggers = st.multiselect("Return trigger", sorted(df["trigger_code"].dropna().unique()),
                                           key=f"{key_prefix}_trigger")
            reasons = st.multiselect("Return reason", sorted([r for r in df["return_reason"].dropna().unique() if r]),
                                      key=f"{key_prefix}_reason")

    return {
        "preset": preset, "custom_start": custom_start, "custom_end": custom_end,
        "marketplaces": marketplaces, "channels": channels, "brands": brands,
        "warehouses": warehouses, "statuses": statuses, "reasons": reasons,
        "triggers": triggers, "search": search,
    }


def kpi_row(items):
    """items: list of (label, value, color) tuples, or (label, value, color, on_click)
    where on_click is a zero-arg callable. When on_click is given, a small
    "View orders →" link renders under the tile; clicking it runs on_click()
    (which should stash filter values + a nav_target in session_state) and
    reruns, so the tile behaves as a drill-down into the filtered data."""
    cols = st.columns(len(items))
    for i, (col, item) in enumerate(zip(cols, items)):
        label, value, color = item[0], item[1], item[2]
        on_click = item[3] if len(item) > 3 else None
        with col:
            st.markdown(
                f"<div style='border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;'>"
                f"<div style='font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;'>{label}</div>"
                f"<div style='font-size:26px;font-weight:700;color:{color};margin-top:4px;'>{value}</div>"
                f"</div>", unsafe_allow_html=True,
            )
            if on_click is not None:
                if st.button("View orders →", key=f"kpi_drill_{i}_{label}", type="tertiary"):
                    on_click()
                    st.rerun()

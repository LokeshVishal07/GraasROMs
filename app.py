import streamlit as st

from lib.seed import ensure_seed
from lib.auth import require_login, current_user, current_permissions, logout, role_label
from lib.db import get_session, Notification

st.set_page_config(page_title="Return Order Management — AAFHU", page_icon="📦", layout="wide")

ensure_seed()
require_login()  # stops execution here until the visitor is logged in

user = current_user()
perms = current_permissions()

PAGES = [
    ("Dashboard", "view_dashboard"),
    ("Returns", "view_returns"),
    ("Bulk Upload", "inspect"),
    ("Damaged Queue", "view_damaged_queue"),
    ("Marketplace Claims", "view_returns"),
    ("Evidence Repository", None),  # gated inside _page_visible below (inspect OR view_damaged_queue OR manage_claims)
    ("Reports & Export", "view_reports"),
    ("Admin Settings", None),  # gated inside _page_visible below (manage_users OR manage_data)
]

with st.sidebar:
    st.markdown("### 📦 GRAAS Returns")
    st.caption("Client · AAFHU")
    st.write(f"**{user['name']}**")
    st.caption(role_label(user["role"]))
    if st.button("Sign out", width="stretch"):
        logout()
        st.rerun()
    st.divider()

    session = get_session()
    try:
        unread = session.query(Notification).filter_by(read=False).count()
    finally:
        session.close()
    if unread:
        st.warning(f"🔔 {unread} unread notification(s) — see below.")

    def _page_visible(p, req):
        if p == "Admin Settings":
            return bool(perms.get("manage_users") or perms.get("manage_data"))
        if p == "Evidence Repository":
            return bool(perms.get("inspect") or perms.get("view_damaged_queue") or perms.get("manage_claims"))
        return req is None or bool(perms.get(req))

    available = [p for p, req in PAGES if _page_visible(p, req)]
    default_idx = 0
    if "nav_target" in st.session_state and st.session_state["nav_target"] in available:
        default_idx = available.index(st.session_state.pop("nav_target"))
    page = st.radio("Navigate", available, index=default_idx, label_visibility="collapsed", key="nav_radio")

    st.divider()
    with st.expander("🔔 Notifications"):
        session = get_session()
        try:
            notifs = session.query(Notification).order_by(Notification.created_at.desc()).limit(20).all()
            if not notifs:
                st.caption("No notifications yet.")
            for n in notifs:
                st.markdown(f"**{n.type.replace('_', ' ').title()}**")
                st.caption(n.message)
            if notifs:
                for n in notifs:
                    n.read = True
                session.commit()
        finally:
            session.close()

if page == "Dashboard":
    from pages_app import dashboard
    dashboard.render()
elif page == "Returns":
    from pages_app import returns
    returns.render()
elif page == "Bulk Upload":
    from pages_app import bulk_upload
    bulk_upload.render()
elif page == "Damaged Queue":
    from pages_app import damaged
    damaged.render()
elif page == "Marketplace Claims":
    from pages_app import claims
    claims.render()
elif page == "Evidence Repository":
    from pages_app import evidence_repo
    evidence_repo.render()
elif page == "Reports & Export":
    from pages_app import reports
    reports.render()
elif page == "Admin Settings":
    from pages_app import admin
    admin.render()

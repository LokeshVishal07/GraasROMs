"""Real, server-side authentication: bcrypt-hashed passwords + Streamlit session state.

This is meaningfully more secure than a client-side/localStorage login screen because
the password hashes and the check itself run on the server, never in the visitor's
browser -- what a user sees in their browser tools reveals nothing about credentials.
"""
import streamlit as st
import bcrypt

from lib.db import get_session, User, RolePermission
from lib.seed import ROLE_LABELS


def verify_password(pw: str, pw_hash: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode("utf-8"), pw_hash.encode("utf-8"))
    except Exception:
        return False


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def current_user():
    return st.session_state.get("auth_user")


def is_logged_in() -> bool:
    return current_user() is not None


def login(email: str, password: str) -> tuple[bool, str]:
    session = get_session()
    try:
        user = session.query(User).filter(User.email.ilike(email.strip())).first()
        if not user or not user.active:
            return False, "Invalid email or password."
        if not verify_password(password, user.password_hash):
            return False, "Invalid email or password."
        st.session_state["auth_user"] = {
            "id": user.id, "name": user.name, "email": user.email, "role": user.role,
        }
        return True, ""
    finally:
        session.close()


def logout():
    st.session_state.pop("auth_user", None)


def current_permissions() -> dict:
    user = current_user()
    if not user:
        return {}
    session = get_session()
    try:
        perm = session.query(RolePermission).filter_by(role=user["role"]).first()
        if not perm:
            return {}
        return {
            "view_dashboard": perm.view_dashboard, "view_returns": perm.view_returns,
            "inspect": perm.inspect, "view_damaged_queue": perm.view_damaged_queue,
            "raise_claim": perm.raise_claim, "manage_claims": perm.manage_claims,
            "view_reports": perm.view_reports, "manage_users": perm.manage_users,
            "manage_data": perm.manage_data,
        }
    finally:
        session.close()


def role_label(role: str) -> str:
    return ROLE_LABELS.get(role, role)


def require_login():
    """Call at the top of the app; renders the login form and stops execution until authenticated."""
    if is_logged_in():
        return
    col1, col2, col3 = st.columns([1, 1.3, 1])
    with col2:
        st.markdown("### 📦 Return Order Management")
        st.caption("GRAAS · Client AAFHU")
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", width="stretch", type="primary")
        if submitted:
            ok, err = login(email, password)
            if ok:
                st.rerun()
            else:
                st.error(err)
        with st.expander("Demo accounts (change these passwords after first login)"):
            from lib.seed import DEFAULT_USERS, DEFAULT_PASSWORD
            for name, dem_email, role in DEFAULT_USERS:
                st.write(f"**{role_label(role)}** — {dem_email}")
            st.caption(f"Default password for all seeded accounts: `{DEFAULT_PASSWORD}`")
    st.stop()

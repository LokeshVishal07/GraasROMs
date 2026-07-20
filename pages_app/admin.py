import streamlit as st

from lib.db import get_session, User, RolePermission
from lib.auth import current_permissions, current_user, hash_password, role_label
from lib.seed import ROLE_LABELS, CHANNEL_BRAND_MAP
from lib.data import bump_cache_nonce
from lib.importer import import_csvs
from lib.manual_import import import_manual_tracking

PERM_FIELDS = ["view_dashboard", "view_returns", "inspect", "view_damaged_queue",
               "raise_claim", "manage_claims", "view_reports", "manage_users", "manage_data"]
PERM_LABELS = {
    "view_dashboard": "View Dashboard", "view_returns": "View Returns", "inspect": "Warehouse Inspection",
    "view_damaged_queue": "View Damaged Queue", "raise_claim": "Raise Claims",
    "manage_claims": "Manage Claims", "view_reports": "View Reports",
    "manage_users": "Manage Users", "manage_data": "Manage Data",
}


def render():
    perms = current_permissions()
    if not (perms.get("manage_users") or perms.get("manage_data")):
        st.warning("You don't have access to Admin Settings.")
        return

    st.subheader("Admin Settings")
    tabs = st.tabs(["Users", "Permissions", "Data Import", "Brand Mapping", "About"])

    with tabs[0]:
        if perms.get("manage_users"):
            _render_users()
        else:
            st.info("Your role can't manage users.")

    with tabs[1]:
        if perms.get("manage_users"):
            _render_permissions()
        else:
            st.info("Your role can't manage permissions.")

    with tabs[2]:
        if perms.get("manage_data"):
            _render_data_import()
        else:
            st.info("Your role can't import data.")

    with tabs[3]:
        _render_brand_mapping()

    with tabs[4]:
        _render_about()


def _render_users():
    st.markdown("#### Users")
    me = current_user() or {}
    session = get_session()
    try:
        users = session.query(User).order_by(User.id).all()
        active_admin_count = sum(
            1 for u in users if u.role == "administrator" and u.active
        )
        for u in users:
            is_self = u.id == me.get("id")
            is_last_active_admin = u.role == "administrator" and u.active and active_admin_count <= 1

            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 2, 1])
                with c1:
                    st.write(f"**{u.name}**")
                    st.caption(u.email)
                    if is_self:
                        st.caption("— this is you")
                with c2:
                    st.write(role_label(u.role))
                    st.caption("Active" if u.active else "Disabled")
                with c3:
                    with st.popover("Manage"):
                        st.markdown(f"**{u.name}**")

                        # --- change role ---
                        st.markdown("Change role")
                        role_options = list(ROLE_LABELS.keys())
                        new_role = st.selectbox(
                            "Role", role_options,
                            index=role_options.index(u.role) if u.role in role_options else 0,
                            format_func=role_label, key=f"role_{u.id}", label_visibility="collapsed",
                        )
                        role_disabled = is_last_active_admin and new_role != "administrator"
                        if role_disabled:
                            st.caption("Can't change this — they're the only active administrator.")
                        if st.button("Update role", key=f"rolesave_{u.id}", disabled=role_disabled):
                            u.role = new_role
                            session.commit()
                            st.success(f"Role updated to {role_label(new_role)}.")
                            st.rerun()

                        st.divider()

                        # --- reset password ---
                        st.markdown("Reset password")
                        new_pw = st.text_input("New password", type="password", key=f"pw_{u.id}",
                                                label_visibility="collapsed", placeholder="New password")
                        if st.button("Save password", key=f"pwsave_{u.id}"):
                            if len(new_pw) < 8:
                                st.error("Use at least 8 characters.")
                            else:
                                u.password_hash = hash_password(new_pw)
                                session.commit()
                                st.success("Password updated.")

                        st.divider()

                        # --- activate / deactivate ---
                        st.markdown("Account status")
                        deactivate_disabled = is_self or is_last_active_admin
                        if u.active:
                            if deactivate_disabled:
                                reason = "your own account" if is_self else "the only active administrator"
                                st.caption(f"Can't disable — this is {reason}.")
                            if st.button("Disable account", key=f"deactivate_{u.id}", disabled=deactivate_disabled):
                                u.active = False
                                session.commit()
                                st.success("Account disabled.")
                                st.rerun()
                        else:
                            if st.button("Re-enable account", key=f"activate_{u.id}"):
                                u.active = True
                                session.commit()
                                st.success("Account re-enabled.")
                                st.rerun()

                        st.divider()

                        # --- delete ---
                        st.markdown(":red[Delete user]")
                        delete_disabled = is_self or is_last_active_admin
                        if delete_disabled:
                            reason = "your own account" if is_self else "the only active administrator"
                            st.caption(f"Can't delete — this is {reason}.")
                        confirm = st.checkbox("Yes, permanently delete this user", key=f"delconfirm_{u.id}",
                                              disabled=delete_disabled)
                        if st.button("Delete user", key=f"delete_{u.id}", type="primary",
                                     disabled=delete_disabled or not confirm):
                            session.delete(u)
                            session.commit()
                            st.success(f"Deleted {u.name}.")
                            st.rerun()
    finally:
        session.close()

    st.markdown("#### Add a user")
    with st.form("add_user_form"):
        name = st.text_input("Name")
        email = st.text_input("Email")
        role = st.selectbox("Role", list(ROLE_LABELS.keys()), format_func=role_label)
        pw = st.text_input("Temporary password", type="password", value="")
        submitted = st.form_submit_button("Add user", type="primary")
    if submitted:
        if not name.strip() or not email.strip() or len(pw) < 8:
            st.error("Name, email, and a password of at least 8 characters are required.")
        else:
            session = get_session()
            try:
                session.add(User(name=name.strip(), email=email.strip().lower(), role=role,
                                  password_hash=hash_password(pw), active=True))
                session.commit()
                st.success(f"Added {name}.")
            except Exception as e:
                st.error(f"Could not add user (maybe email already exists): {e}")
            finally:
                session.close()


def _render_permissions():
    st.markdown("#### Role Permissions")
    session = get_session()
    try:
        for role in ROLE_LABELS:
            perm = session.query(RolePermission).filter_by(role=role).first()
            if not perm:
                continue
            st.markdown(f"**{role_label(role)}**")
            cols = st.columns(3)
            changed = False
            for i, field in enumerate(PERM_FIELDS):
                with cols[i % 3]:
                    val = st.checkbox(PERM_LABELS[field], value=getattr(perm, field), key=f"{role}_{field}")
                    if val != getattr(perm, field):
                        setattr(perm, field, val)
                        changed = True
            if changed:
                session.commit()
            st.divider()
    finally:
        session.close()


def _render_data_import():
    st.markdown("#### Import Return Orders (GRAAS export)")
    st.caption("Upload the orders CSV, optionally with the matching items CSV for SKU/product detail.")
    orders_file = st.file_uploader("Orders CSV", type=["csv"], key="orders_upl")
    items_file = st.file_uploader("Items CSV (optional)", type=["csv"], key="items_upl")
    if st.button("Import orders", type="primary", disabled=orders_file is None):
        summary = import_csvs(orders_file, items_file)
        bump_cache_nonce()
        st.success(f"Imported batch {summary['batch']}: {summary['inserted']} new, "
                   f"{summary['updated']} updated, {summary['total_rows']} rows processed.")

    st.divider()
    st.markdown("#### Import Manual Return Tracking (DKSH / Ops)")
    st.caption("Upload the combined brand Return/Refund tracking CSV — mapped onto orders by Order ID.")
    manual_file = st.file_uploader("Manual tracking CSV", type=["csv"], key="manual_upl")
    if st.button("Import manual tracking", disabled=manual_file is None):
        summary = import_manual_tracking(manual_file)
        bump_cache_nonce()
        st.success(f"Imported batch {summary['batch']}: {summary['total_rows']} rows, "
                   f"{summary['matched']} matched to an order, {summary['unmatched']} unmatched.")


def _render_brand_mapping():
    st.markdown("#### Channel → Brand Mapping")
    st.caption("Used to tag every return with a brand for filtering and reporting.")
    rows = [{"Channel": k, "Brand": v} for k, v in sorted(CHANNEL_BRAND_MAP.items())]
    st.dataframe(rows, hide_index=True, width="stretch")
    st.caption("To change this mapping, edit CHANNEL_BRAND_MAP in lib/seed.py and redeploy.")


def _render_about():
    st.markdown("#### About")
    st.write("Return Order Management — GRAAS · Client AAFHU")
    st.write("Standalone Streamlit app with server-side login, shared database, "
             "bulk warehouse inspection, DKSH/Ops manual tracking import, and brand tagging.")

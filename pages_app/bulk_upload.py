import pandas as pd
import streamlit as st

from lib.auth import current_permissions, current_user
from lib.data import bump_cache_nonce
from lib.bulk_import import (
    build_template_bytes, parse_uploaded_workbook, validate_upload,
    build_error_report_bytes, apply_bulk_upload, CODE_TO_LABEL,
)


def render():
    st.subheader("WH Inspection Bulk Upload")
    perms = current_permissions()
    if not perms.get("inspect"):
        st.info("Your role doesn't have warehouse inspection access. Ask an Administrator.")
        return

    st.caption("Process return inspections in bulk: download the template, fill in one row per "
               "order, then upload it here. Every row is validated before anything is saved.")

    st.download_button(
        "⬇️ Download Template", data=build_template_bytes(),
        file_name="Warehouse_Bulk_Inspection_Template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )

    st.divider()
    uploaded = st.file_uploader("Upload completed template", type=["xlsx"], key="bulk_upload_file")
    if uploaded is None:
        return

    try:
        df = parse_uploaded_workbook(uploaded)
    except Exception as e:
        st.error(f"Couldn't read this file — make sure it's the downloaded template. ({e})")
        return

    if df.empty:
        st.warning("No data rows found in the uploaded file.")
        return

    errors, valid_rows = validate_upload(df)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Rows in file", len(df))
    with c2:
        st.metric("Valid rows", len(valid_rows))
    with c3:
        st.metric("Rows with errors", len({e["row"] for e in errors}))

    if errors:
        n_error_rows = len({e["row"] for e in errors})
        st.error(f"{n_error_rows} row(s) failed validation. Fix them and re-upload, "
                 f"or apply just the valid rows below.")
        err_df = pd.DataFrame(errors).rename(
            columns={"row": "Row", "order_id": "Order ID", "field": "Field", "message": "Error"})
        st.dataframe(err_df, width="stretch", hide_index=True, height=min(320, 40 + 35 * len(errors)))
        st.download_button(
            "⬇️ Download Error Report", data=build_error_report_bytes(errors),
            file_name="bulk_upload_errors.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    if not valid_rows:
        if not errors:
            st.warning("No usable rows found.")
        return

    st.markdown("#### Ready to apply")
    n_flagged = sum(1 for r in valid_rows if r["needs_review"])
    if n_flagged:
        st.warning(f"{n_flagged} row(s) have a status the system didn't recognize (e.g. a Thai phrase "
                   f"not in the baseline list, or a typo). They'll still be applied — the order's "
                   f"Inspection Status is left as-is and the text you entered is saved to the comment "
                   f"so someone can reclassify it from the Returns page. Marked ⚠ below.")

    def _status_display(r):
        if r["needs_review"]:
            return f"⚠ \"{r['status_raw']}\" (not recognized)"
        if r["status_code"]:
            return CODE_TO_LABEL.get(r["status_code"], r["status_code"])
        return "— (left as-is)"

    preview = pd.DataFrame([{
        "Row": r["row"], "Order ID": r["order_id"], "Status": _status_display(r),
        "Comments": r["comments"], "Warehouse User": r["warehouse_user_name"] or "(you)",
    } for r in valid_rows])
    st.dataframe(preview, width="stretch", hide_index=True, height=min(320, 40 + 35 * len(valid_rows)))

    if st.button(f"Apply {len(valid_rows)} valid row(s)", type="primary"):
        user = current_user()
        result = apply_bulk_upload(valid_rows, fallback_user_name=user["name"])
        bump_cache_nonce()
        msg = f"Applied {result['applied']} inspection update(s)."
        if result["flagged"]:
            msg += f" {result['flagged']} flagged for manual review."
        st.success(msg)
        st.rerun()

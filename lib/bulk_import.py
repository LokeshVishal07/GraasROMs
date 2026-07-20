"""Warehouse Bulk Upload: Excel template generation, validation, error
reporting, and applying validated rows to ReturnOrder + Evidence."""
import datetime as dt
import io

import openpyxl
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from lib.db import get_session, ReturnOrder
from lib.evidence import save_link, is_probably_valid_link
from lib.utils import log_activity, push_notification

FONT_NAME = "Arial"

SYSTEM_COLUMNS = [
    "order_id", "return_id", "inspection_status", "warehouse_comments",
    "damage_reason", "image_drive_link", "inspection_date", "warehouse_user_name",
]
HUMAN_LABELS = {
    "order_id": "Order ID *", "return_id": "Return ID",
    "inspection_status": "Inspection Status *", "warehouse_comments": "Warehouse Comments",
    "damage_reason": "Damage Reason", "image_drive_link": "Image / Drive Link",
    "inspection_date": "Inspection Date", "warehouse_user_name": "Warehouse User Name",
}
REQUIRED_COLUMNS = {"order_id", "inspection_status"}

STATUS_CHOICES_HUMAN = ["Good Condition", "Damaged", "Not Received"]
STATUS_MAP = {"good condition": "good", "damaged": "damaged", "not received": "not_received"}
STATUS_REQUIRES_EVIDENCE = {"damaged", "not_received"}

EXAMPLE_ROW = [
    "2201234567890", "RET-000123", "Damaged", "Box crushed, item cracked on arrival",
    "Physical damage in transit", "https://drive.google.com/file/d/example/view",
    "2026-07-19", "Wichai Warehouse",
]

MAX_TEMPLATE_ROWS = 300


# --------------------------------------------------------------------------
# Template
# --------------------------------------------------------------------------

def build_template_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Bulk Inspection Upload"

    header_fill = PatternFill("solid", fgColor="1F3864")
    header_font = Font(name=FONT_NAME, bold=True, color="FFFFFF", size=10)
    key_font = Font(name=FONT_NAME, italic=True, size=8, color="999999")
    example_font = Font(name=FONT_NAME, italic=True, color="808080", size=10)
    normal_font = Font(name=FONT_NAME, size=10)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    yellow_fill = PatternFill("solid", fgColor="FFFF00")

    ws.append(SYSTEM_COLUMNS)
    for c in range(1, len(SYSTEM_COLUMNS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = key_font
        cell.alignment = Alignment(horizontal="center")

    ws.append([HUMAN_LABELS[k] for k in SYSTEM_COLUMNS])
    for c in range(1, len(SYSTEM_COLUMNS) + 1):
        cell = ws.cell(row=2, column=c)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    ws.append(EXAMPLE_ROW)
    for c in range(1, len(SYSTEM_COLUMNS) + 1):
        cell = ws.cell(row=3, column=c)
        cell.font = example_font
        cell.border = border

    for r in range(4, 4 + MAX_TEMPLATE_ROWS):
        for c in range(1, len(SYSTEM_COLUMNS) + 1):
            cell = ws.cell(row=r, column=c)
            cell.font = normal_font
            cell.border = border
            cell.fill = yellow_fill

    widths = [18, 14, 16, 28, 22, 30, 16, 20]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 12
    ws.row_dimensions[2].height = 30
    ws.freeze_panes = "A4"

    status_col = SYSTEM_COLUMNS.index("inspection_status") + 1
    dv = DataValidation(type="list", formula1=f'"{",".join(STATUS_CHOICES_HUMAN)}"',
                         allow_blank=True, showDropDown=False)
    ws.add_data_validation(dv)
    dv.add(f"{get_column_letter(status_col)}4:{get_column_letter(status_col)}{3 + MAX_TEMPLATE_ROWS}")

    # Instructions sheet
    ins = wb.create_sheet("Instructions")
    ins.column_dimensions["A"].width = 24
    ins.column_dimensions["B"].width = 72
    title_font = Font(name=FONT_NAME, size=14, bold=True, color="1F3864")
    bold = Font(name=FONT_NAME, size=11, bold=True)
    body = Font(name=FONT_NAME, size=11)

    ins["A1"] = "Warehouse Bulk Inspection Upload — Fill-in Guide"
    ins["A1"].font = title_font
    ins.merge_cells("A1:B1")

    ins["A3"] = "How this works"
    ins["A3"].font = bold
    ins["A4"] = ("Fill in one row per return on the 'Bulk Inspection Upload' tab — one order per row. "
                 "Delete the grey EXAMPLE row (row 3) before you finish. Fields marked with * are "
                 "mandatory. The file is validated on upload; any problem rows are rejected with a "
                 "downloadable error report, and only rows that pass validation are applied.")
    ins["A4"].alignment = Alignment(wrap_text=True)
    ins.merge_cells("A4:B4")
    ins.row_dimensions[4].height = 60

    rows = [
        ("Column", "What to enter"),
        ("order_id", "REQUIRED. Must exactly match an Order ID already in the system."),
        ("return_id", "The marketplace/DKSH return case number, if available. Helps disambiguate "
                       "when an Order ID appears more than once in the system."),
        ("inspection_status", "REQUIRED. One of: Good Condition, Damaged, Not Received (dropdown provided)."),
        ("warehouse_comments", "REQUIRED when status is Damaged or Not Received."),
        ("damage_reason", "Reason for the damage, if applicable."),
        ("image_drive_link", "A Google Drive / OneDrive / SharePoint link to photo or video evidence. "
                              "REQUIRED when status is Damaged or Not Received."),
        ("inspection_date", "Date the item was inspected. Format: YYYY-MM-DD. Defaults to today if left blank."),
        ("warehouse_user_name", "Name of the warehouse staff who performed the inspection. Defaults to "
                                 "your logged-in name if left blank."),
    ]
    start_row = 6
    ins.cell(row=start_row, column=1, value=rows[0][0]).font = bold
    ins.cell(row=start_row, column=2, value=rows[0][1]).font = bold
    for i, (col, desc) in enumerate(rows[1:], start=1):
        r = start_row + i
        ins.cell(row=r, column=1, value=col).font = Font(name=FONT_NAME, size=11, bold=True)
        c2 = ins.cell(row=r, column=2, value=desc)
        c2.font = body
        c2.alignment = Alignment(wrap_text=True)
        ins.row_dimensions[r].height = 32

    note_row = start_row + len(rows) + 1
    ins.cell(row=note_row, column=1, value="Validation").font = bold
    ins.cell(row=note_row, column=2, value=(
        "Rows are rejected if: Order ID or Inspection Status is missing; the Order ID isn't found in "
        "the system; the same Order ID appears more than once in this file; the status value isn't one "
        "of the three allowed values; or comments/evidence link are missing for a Damaged or Not "
        "Received row.")).alignment = Alignment(wrap_text=True)
    ins.row_dimensions[note_row].height = 55

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Parsing + validation
# --------------------------------------------------------------------------

def _clean(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    return "" if s.lower() == "nan" else s


def parse_uploaded_workbook(file) -> pd.DataFrame:
    """Reads the Bulk Inspection Upload sheet using row 1 (system field keys)
    as the header, skipping row 2 (the human-readable label row)."""
    df = pd.read_excel(file, sheet_name=0, header=0, skiprows=[1], dtype=object)
    df.columns = [str(c).strip() for c in df.columns]
    # keep only known columns, in our canonical order, tolerating extra/missing ones
    for col in SYSTEM_COLUMNS:
        if col not in df.columns:
            df[col] = None
    df = df[SYSTEM_COLUMNS]
    # drop fully blank rows
    df = df[~df.apply(lambda r: all(_clean(v) == "" for v in r), axis=1)]
    return df.reset_index(drop=True)


def validate_upload(df: pd.DataFrame):
    """Returns (errors: list[dict], valid_rows: list[dict]).
    Each error dict: {row, order_id, field, message}.
    Each valid row dict carries the resolved ReturnOrder key plus cleaned values."""
    errors = []
    valid_rows = []

    session = get_session()
    try:
        all_orders = session.query(ReturnOrder.key, ReturnOrder.order_id, ReturnOrder.return_id).all()
    finally:
        session.close()

    by_order_id = {}
    for key, order_id, return_id in all_orders:
        by_order_id.setdefault(order_id, []).append((key, return_id))

    seen_keys = set()

    for i, row in df.iterrows():
        excel_row = i + 4  # data starts at physical row 4 (after key/header/example rows)
        order_id = _clean(row["order_id"])
        return_id = _clean(row["return_id"])
        status_raw = _clean(row["inspection_status"])
        comments = _clean(row["warehouse_comments"])
        damage_reason = _clean(row["damage_reason"])
        link = _clean(row["image_drive_link"])
        insp_date_raw = row["inspection_date"]
        wh_user = _clean(row["warehouse_user_name"])

        row_errors = []

        if not order_id:
            row_errors.append(("order_id", "Order ID is required."))
        if not status_raw:
            row_errors.append(("inspection_status", "Inspection Status is required."))

        status_code = None
        if status_raw:
            status_code = STATUS_MAP.get(status_raw.strip().lower())
            if status_code is None:
                row_errors.append(("inspection_status",
                                    f"'{status_raw}' is not a valid status — use Good Condition, "
                                    f"Damaged, or Not Received."))

        resolved_key = None
        if order_id:
            dup_key = (order_id, return_id)
            if dup_key in seen_keys:
                row_errors.append(("order_id", "Duplicate record — this Order ID"
                                    + (f" + Return ID" if return_id else "")
                                    + " combination appears more than once in this file."))
            seen_keys.add(dup_key)

            matches = by_order_id.get(order_id)
            if not matches:
                row_errors.append(("order_id", "Order ID not found in the system."))
            elif len(matches) == 1:
                resolved_key = matches[0][0]
            else:
                if return_id:
                    narrowed = [k for k, rid in matches if rid == return_id]
                    if len(narrowed) == 1:
                        resolved_key = narrowed[0]
                    else:
                        row_errors.append(("order_id", "Multiple orders match this Order ID and "
                                                         "Return ID together — needs manual resolution."))
                else:
                    row_errors.append(("order_id", "Multiple orders share this Order ID — provide "
                                                     "Return ID to disambiguate."))

        if status_code in STATUS_REQUIRES_EVIDENCE:
            if not comments:
                row_errors.append(("warehouse_comments",
                                    "Comments are required for Damaged / Not Received."))
            if not link:
                row_errors.append(("image_drive_link",
                                    "An image/drive link is required for Damaged / Not Received."))
            elif not is_probably_valid_link(link):
                row_errors.append(("image_drive_link",
                                    "This doesn't look like a valid http(s) link."))

        insp_date = None
        if insp_date_raw is not None and _clean(insp_date_raw):
            try:
                insp_date = pd.to_datetime(insp_date_raw).to_pydatetime()
            except Exception:
                row_errors.append(("inspection_date", f"'{insp_date_raw}' isn't a recognizable date."))

        if row_errors:
            for field, msg in row_errors:
                errors.append({"row": excel_row, "order_id": order_id or "(blank)",
                                "field": field, "message": msg})
        else:
            valid_rows.append({
                "row": excel_row, "key": resolved_key, "order_id": order_id, "return_id": return_id,
                "status_code": status_code, "comments": comments, "damage_reason": damage_reason,
                "link": link, "inspection_date": insp_date, "warehouse_user_name": wh_user,
            })

    return errors, valid_rows


def build_error_report_bytes(errors: list) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Errors"
    header_fill = PatternFill("solid", fgColor="B91C1C")
    header_font = Font(name=FONT_NAME, bold=True, color="FFFFFF", size=10)
    normal_font = Font(name=FONT_NAME, size=10)

    headers = ["Row", "Order ID", "Field", "Error"]
    ws.append(headers)
    for c in range(1, 5):
        cell = ws.cell(row=1, column=c)
        cell.font = header_font
        cell.fill = header_fill

    for e in errors:
        ws.append([e["row"], e["order_id"], e["field"], e["message"]])
    for r in range(2, len(errors) + 2):
        for c in range(1, 5):
            ws.cell(row=r, column=c).font = normal_font

    widths = [8, 20, 22, 60]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# Apply
# --------------------------------------------------------------------------

def apply_bulk_upload(valid_rows: list, fallback_user_name: str) -> dict:
    applied, skipped = 0, 0
    session = get_session()
    try:
        for r in valid_rows:
            order = session.get(ReturnOrder, r["key"]) if r["key"] else None
            if order is None:
                skipped += 1
                continue
            who = r["warehouse_user_name"] or fallback_user_name
            when = r["inspection_date"] or dt.datetime.utcnow()

            order.inspection_status = r["status_code"]
            if r["comments"]:
                order.inspection_comment = r["comments"]
            if r["damage_reason"]:
                order.damage_reason = r["damage_reason"]
            if r["return_id"]:
                order.return_id = r["return_id"]
            order.inspected_by = who
            order.inspected_at = when
            session.commit()

            if r["link"]:
                save_link(order.key, r["link"], who, when=when)

            log_activity(order_key=order.key, action="Bulk inspection upload",
                          comment=f"Result: {r['status_code']}" + (f" — {r['comments']}" if r["comments"] else ""))
            if r["status_code"] in STATUS_REQUIRES_EVIDENCE:
                push_notification("damaged", f"Order {order.order_id} needs Operations action "
                                              f"({r['status_code']})", order.key)
            applied += 1
    finally:
        session.close()
    return {"applied": applied, "skipped": skipped}

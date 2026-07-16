# GRAAS Return Order Management — Standalone App (Client AAFHU)

A standalone Streamlit app with real server-side login (bcrypt) and a shared
database, deployable to a public URL for people outside your organization.

## What's new in this build

- **Bulk warehouse inspection update** — Returns page → "Bulk update" mode.
  Select multiple pending returns in a table and apply one inspection result
  (with shared comment / evidence for Damaged / Not Received) to all of them
  at once.
- **DKSH / Ops manual return tracking import** — Admin Settings → Data Import
  → "Import Manual Return Tracking". Upload `manual_return_tracking.csv`
  (combined from the brand `{Brand} - ReturnRefund` Google Sheet tabs) and
  it's mapped onto each return order by Order ID. It then shows as a "DKSH /
  Ops Return Tracking" panel on the order detail page — request date, reason,
  courier/tracking, return-delivered date, warehouse-received date, and
  Open/Closed status.
- **Brand tagging** — every return is tagged with a brand (Hada Labo,
  Oatside, Lamy, Lego (Bricks), Carglo, Energizer) derived from its channel.
  Brand is now a filter on every page and shown on the order detail page and
  dashboard breakdown. The mapping lives in `lib/seed.py`
  (`CHANNEL_BRAND_MAP`) and is also viewable at Admin Settings → Brand
  Mapping.

### Known data-quality note (source sheet, not this app)

The DKSH tracking sheet's `Product Condition (Good/Damage)` column is a
broken formula (`#NAME?`) on every row, so that field isn't imported —
there's nothing usable in it. `Warehouse Received` is also `#NAME?`/blank on
~72% of rows; only rows with a real date will show a warehouse-received date
in the app. Worth fixing at the source if DKSH wants that tracked reliably.

## Project layout

```
graas-returns-app/
  app.py
  lib/
    db.py                 SQLAlchemy models (incl. ManualTracking, brand)
    seed.py                 default users/roles + CHANNEL_BRAND_MAP
    auth.py                  bcrypt login/session
    importer.py             GRAAS order/item CSV import + return classifier
    manual_import.py        DKSH/Ops manual tracking CSV import
    data.py                  cached loading + filtering (incl. brand)
    utils.py                   formatting/badges/notifications
    widgets.py                 filter bar (incl. brand) + KPI row
  pages_app/
    dashboard.py, returns.py (detail + bulk update), damaged.py,
    claims.py, reports.py, admin.py (incl. manual tracking import)
  data/                    put your CSVs here for local testing (gitignored)
  .streamlit/config.toml
  requirements.txt
```

## Run locally

```bash
cd graas-returns-app
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Default login accounts

Password `GraasReturns#2026` for all — **change these before sharing the
public URL** (Admin Settings → Users).

| Role | Email |
|---|---|
| Administrator | admin@aafhu.graas.ai |
| Warehouse Team | warehouse@aafhu.graas.ai |
| Operations Team | ops@aafhu.graas.ai |
| External User | external@aafhu.graas.ai |

### Loading data

1. Admin Settings → Data Import → upload `return_orders_2026.csv` (required)
   and `return_items_2026.csv` (optional, adds SKU/product detail).
2. Admin Settings → Data Import → upload `manual_return_tracking.csv` to
   bring in the DKSH/Ops manual tracking, mapped by Order ID.

## Deploy to Streamlit Community Cloud

Same as before — push this folder to GitHub, then deploy at
share.streamlit.io with main file `app.py`. Full click-by-click steps are in
the *Deployment Guide* document if you still have it.

**If you're replacing an existing broken deployment:** delete the old
`lib/`, `pages_app/`, and `app.py` from your GitHub repo (or just push these
files over them with the same names) so nothing from the earlier, incomplete
push lingers, then push everything in this folder. Reboot the app afterward
from Streamlit Cloud → Manage app → Reboot.

### Storage note

SQLite by default (`data/app.db`) — resets on redeploy on Streamlit Cloud.
For real use, set a `DATABASE_URL` secret pointing at Postgres (Neon,
Supabase, Railway, etc.) and add `psycopg2-binary` to `requirements.txt` —
`lib/db.py` picks it up automatically.

## Multi-tenant reuse

Change the client label in `app.py` / `lib/auth.py`, point `DATABASE_URL` at
a separate database per client, and update `CHANNEL_BRAND_MAP` in
`lib/seed.py` for the new client's channel-to-brand mapping.

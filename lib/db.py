"""SQLAlchemy models and engine/session setup.

Uses SQLite by default (data/app.db). Set the DATABASE_URL env var / Streamlit
secret to point at Postgres for real production use (Streamlit Cloud's disk
is ephemeral across redeploys).
"""
import os
import time
import datetime
import threading

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, Boolean, DateTime, Date,
    Text, LargeBinary, ForeignKey, text, inspect as sa_inspect,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True, index=True)
    role = Column(String)
    password_hash = Column(String)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class RolePermission(Base):
    __tablename__ = "role_permissions"
    id = Column(Integer, primary_key=True)
    role = Column(String, unique=True)
    view_dashboard = Column(Boolean, default=True)
    view_returns = Column(Boolean, default=True)
    inspect = Column(Boolean, default=False)
    view_damaged_queue = Column(Boolean, default=False)
    raise_claim = Column(Boolean, default=False)
    manage_claims = Column(Boolean, default=False)
    view_reports = Column(Boolean, default=False)
    manage_users = Column(Boolean, default=False)
    manage_data = Column(Boolean, default=False)


class ReturnOrder(Base):
    __tablename__ = "return_orders"
    key = Column(String, primary_key=True)
    channel = Column(String, index=True)
    marketplace = Column(String, index=True)
    brand = Column(String, index=True)
    order_id = Column(String, index=True)
    return_id = Column(String, index=True)  # external return/case ID (from manual tracking or bulk upload)
    buyer_id = Column(String)
    order_date = Column(DateTime)
    order_status = Column(String)
    mp_order_status = Column(String)
    shipping_status = Column(String)
    # When the order was dispatched from the warehouse (GRAAS ORDER_DISPATCHED_TS).
    # Used to tell a cancelled-but-already-shipped order apart from one that was
    # cancelled before it ever left the warehouse -- GRAAS doesn't expose an
    # airway bill / tracking number field on this connector, so this timestamp
    # is the closest available signal for "did it leave the warehouse".
    order_dispatched_ts = Column(DateTime)
    cancel_reason = Column(Text)
    cancelled_by = Column(String)
    return_reason = Column(Text)
    return_date = Column(DateTime)
    return_date_estimated = Column(Boolean, default=False)
    order_amt = Column(Float, default=0)
    refund_amt = Column(Float, default=0)
    currency = Column(String, default="THB")

    trigger_code = Column(String)
    trigger_label = Column(String)

    sku_summary = Column(Text)
    product_summary = Column(Text)
    qty_total = Column(Integer, default=0)

    inspection_status = Column(String, default="pending")
    inspection_comment = Column(Text)
    damage_reason = Column(Text)
    inspected_by = Column(String)
    inspected_at = Column(DateTime)
    warehouse = Column(String)
    tracking_number = Column(String)

    imported_at = Column(DateTime, default=datetime.datetime.utcnow)
    import_batch = Column(String)


class ManualTracking(Base):
    """DKSH/Ops manually-tracked return rows, imported from the brand Return/Refund
    Google Sheet tabs and mapped onto ReturnOrder by order_id (fallback return_id)."""
    __tablename__ = "manual_tracking"
    id = Column(Integer, primary_key=True)
    order_key = Column(String, ForeignKey("return_orders.key"), nullable=True, index=True)
    matched = Column(Boolean, default=False)

    brand = Column(String, index=True)
    request_date = Column(Date)
    marketplace = Column(String)
    order_id = Column(String, index=True)
    return_id = Column(String, index=True)
    reason_to_return = Column(Text)
    customer_comment = Column(Text)
    sku = Column(String)
    quantity = Column(String)
    amount = Column(String)
    courier = Column(String)
    tracking_no = Column(String)
    return_delivered_date = Column(String)
    warehouse_received_date = Column(String)
    dksh_status = Column(String)

    imported_at = Column(DateTime, default=datetime.datetime.utcnow)
    import_batch = Column(String)


class Evidence(Base):
    """A piece of inspection evidence for a return order: either an uploaded file
    (data holds the raw bytes) or a pasted cloud storage link (Google Drive /
    OneDrive / SharePoint), never both. is_link tells the UI which one it is."""
    __tablename__ = "evidence"
    id = Column(Integer, primary_key=True)
    order_key = Column(String, ForeignKey("return_orders.key"), index=True)
    is_link = Column(Boolean, default=False)
    filename = Column(String)
    content_type = Column(String)
    size = Column(Integer)
    data = Column(LargeBinary)
    link_url = Column(String)
    uploaded_by = Column(String)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)
    # None/blank = general warehouse inspection evidence (unchanged, existing
    # behavior). "pod" / "appeal" tag evidence uploaded from the Marketplace
    # Claims page's dedicated POD and Appeal Status sections, so those can be
    # shown/filtered separately from the general gallery.
    category = Column(String, nullable=True)


class Ticket(Base):
    __tablename__ = "tickets"
    id = Column(String, primary_key=True)
    order_key = Column(String, ForeignKey("return_orders.key"), index=True)
    subject = Column(String)
    status = Column(String, default="Open")
    priority = Column(String, default="Normal")
    marketplace_case_id = Column(String)  # the marketplace's own claim/case reference number
    internal_notes = Column(Text)  # ops-only running note, separate from the shared activity timeline
    # Outcome of the marketplace appeal: None (not decided yet), "Success", or
    # "Failed". Setting this via the claim's Success/Failed buttons also
    # auto-updates the claim's overall `status` (Success -> Resolved,
    # Failed -> Rejected) -- see _set_appeal_outcome in pages_app/claims.py.
    appeal_status = Column(String, nullable=True)
    assigned_to = Column(String)
    created_by = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    order_key = Column(String, index=True)
    ticket_id = Column(String, index=True, nullable=True)
    action = Column(String)
    comment = Column(Text)
    actor = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    type = Column(String)
    message = Column(String)
    order_key = Column(String, nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


_engine = None
_SessionLocal = None


_engine_lock = threading.RLock()


def _run_light_migrations(engine):
    """create_all() only creates TABLES that don't exist yet -- it never adds
    columns to a table that's already there, which is exactly the situation on
    every live deploy after a model gets a new field (e.g. adding damage_reason
    to return_orders). This adds any missing columns via a plain ALTER TABLE ...
    ADD COLUMN, which both SQLite and Postgres support for simple nullable
    columns. Safe to call on every startup: columns that already exist are
    left untouched, and any single ALTER failure (e.g. two script instances
    racing to add the same column) is swallowed so it can't crash the app."""
    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # brand-new table -- create_all() already built it in full
            existing_cols = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing_cols:
                    continue
                try:
                    col_type = col.type.compile(dialect=engine.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col_type}'))
                except Exception:
                    pass


def get_engine():
    global _engine
    if _engine is None:
        with _engine_lock:
            # re-check inside the lock: another thread may have finished
            # building the engine while we were waiting for it
            if _engine is None:
                url = os.environ.get("DATABASE_URL")
                if not url:
                    try:
                        import streamlit as st
                        url = st.secrets.get("DATABASE_URL")
                    except Exception:
                        url = None
                if not url:
                    os.makedirs("data", exist_ok=True)
                    url = "sqlite:///data/app.db"

                connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
                engine_kwargs = dict(connect_args=connect_args)
                if not url.startswith("sqlite"):
                    # Hosted Postgres (e.g. Neon's free tier) suspends its
                    # compute after a few minutes idle. A connection opened
                    # before a suspend can look fine to the pool but fail the
                    # instant it's actually used ("server closed the
                    # connection unexpectedly") -- that's what crashed
                    # ensure_seed() here. pool_pre_ping makes SQLAlchemy test
                    # every pooled connection with a cheap "is this alive?"
                    # check before handing it to our code, transparently
                    # reconnecting if it's gone stale. pool_recycle proactively
                    # retires connections before they're likely to have gone
                    # stale in the first place.
                    engine_kwargs.update(pool_pre_ping=True, pool_recycle=280)

                # A cold Neon database can take a few seconds to wake its
                # compute back up; the very first connection attempt (which
                # also runs create_all below) can land in that window and
                # fail outright rather than just being slow. Retry a few
                # times with a short backoff instead of crashing the app.
                last_err = None
                for attempt in range(4):
                    try:
                        engine = create_engine(url, **engine_kwargs)
                        try:
                            Base.metadata.create_all(engine)
                        except OperationalError as e:
                            # Benign race: Streamlit Cloud can spin up more
                            # than one script run against a brand-new (empty)
                            # database at almost the same instant. Both see
                            # "table does not exist yet" and both issue
                            # CREATE TABLE; one wins, the other hits "table
                            # already exists". The tables are there either
                            # way, so this specific error is safe to ignore
                            # rather than crash the app.
                            if "already exists" not in str(e).lower():
                                raise
                        _run_light_migrations(engine)
                        _engine = engine
                        break
                    except OperationalError as e:
                        last_err = e
                        if attempt < 3:
                            time.sleep(1.5 * (attempt + 1))
                        else:
                            raise last_err
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        with _engine_lock:
            if _SessionLocal is None:
                _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()

"""Seeds default users and role permissions on first run."""
import bcrypt

from lib.db import get_session, User, RolePermission

ROLE_LABELS = {
    "administrator": "Administrator",
    "warehouse": "Warehouse Team",
    "operations": "Operations Team",
    "external": "External User",
}

DEFAULT_PERMS = {
    "administrator": dict(view_dashboard=True, view_returns=True, inspect=True, view_damaged_queue=True,
                           raise_claim=True, manage_claims=True, view_reports=True, manage_users=True, manage_data=True),
    "warehouse":     dict(view_dashboard=True, view_returns=True, inspect=True, view_damaged_queue=True,
                           raise_claim=False, manage_claims=False, view_reports=False, manage_users=False, manage_data=False),
    "operations":    dict(view_dashboard=True, view_returns=True, inspect=False, view_damaged_queue=True,
                           raise_claim=True, manage_claims=True, view_reports=True, manage_users=False, manage_data=False),
    "external":      dict(view_dashboard=True, view_returns=True, inspect=False, view_damaged_queue=False,
                           raise_claim=False, manage_claims=False, view_reports=False, manage_users=False, manage_data=False),
}

DEFAULT_USERS = [
    ("Ananya Admin", "admin@aafhu.graas.ai", "administrator"),
    ("Wichai Warehouse", "warehouse@aafhu.graas.ai", "warehouse"),
    ("Orawan Ops", "ops@aafhu.graas.ai", "operations"),
    ("External Partner", "external@aafhu.graas.ai", "external"),
]
DEFAULT_PASSWORD = "GraasReturns#2026"

# Channel -> Brand mapping, confirmed against the account's numbered-channel tagging.
CHANNEL_BRAND_MAP = {
    "lazada-1": "Lamy",
    "lazada-2": "Hada Labo",
    "lazada-3": "Oatside",
    "lazada-4": "Carglo",
    "lazada-5": "Energizer",
    "shopee-1": "Hada Labo",
    "shopee-2": "Oatside",
    "shopee-3": "Carglo",
    "shopee-4": "Energizer",
    "shopee-5": "Lamy",
    "tiktok-1": "Hada Labo",
    "tiktok-2": "Oatside",
    "tiktok-3": "Lego (Bricks)",
}


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def ensure_seed():
    session = get_session()
    try:
        if session.query(RolePermission).count() == 0:
            for role, perms in DEFAULT_PERMS.items():
                session.add(RolePermission(role=role, **perms))
        if session.query(User).count() == 0:
            for name, email, role in DEFAULT_USERS:
                session.add(User(name=name, email=email, role=role,
                                  password_hash=hash_password(DEFAULT_PASSWORD), active=True))
        session.commit()
    finally:
        session.close()

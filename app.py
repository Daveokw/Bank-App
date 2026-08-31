"""Streamlit entry point for the DAVE Bank demonstration application."""

from __future__ import annotations

import os
from decimal import Decimal

import streamlit as st

from db import init_db
from screens import show_dashboard, show_home, show_signin, show_signup

st.set_page_config(page_title="DAVE Bank", page_icon="🏦", layout="wide")


def _admin_password() -> str | None:
    try:
        configured = st.secrets.get("BANK_ADMIN_PASSWORD")
    except (FileNotFoundError, KeyError):
        configured = None
    return configured or os.getenv("BANK_ADMIN_PASSWORD")


admin_password = _admin_password()
database_was_reset = init_db(st, admin_password=admin_password)

SESSION_DEFAULTS = {
    "page": "home",
    "customer_id": None,
    "account_id": None,
    "account_no": None,
    "email": None,
    "username": None,
    "phone": None,
    "balance": Decimal("0.00"),
    "admin_enabled": bool(admin_password),
}
for key, value in SESSION_DEFAULTS.items():
    st.session_state.setdefault(key, value)
st.session_state.admin_enabled = bool(admin_password)

if database_was_reset:
    st.session_state.flash_message = "The demonstration data was refreshed. Please sign in again."

if flash_message := st.session_state.pop("flash_message", None):
    st.info(flash_message)

ROUTES = {
    "home": show_home,
    "signup": show_signup,
    "signin": show_signin,
    "dashboard": show_dashboard,
}
ROUTES.get(st.session_state.page, show_home)()

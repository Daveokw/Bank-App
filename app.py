import streamlit as st
from decimal import Decimal
from db import init_db
from screens import show_home, show_signup, show_signin, show_dashboard

# --- Application Configuration ---
st.set_page_config(page_title="DAVE Bank", page_icon="🏦", layout="wide")

# --- Session State Initialization ---
if "page" not in st.session_state: st.session_state.page = "home"
if "customer_id" not in st.session_state: st.session_state.customer_id = None
if "account_id" not in st.session_state: st.session_state.account_id = None
if "account_no" not in st.session_state: st.session_state.account_no = None
if "email" not in st.session_state: st.session_state.email = None
if "username" not in st.session_state: st.session_state.username = None
if "phone" not in st.session_state: st.session_state.phone = None
if "balance" not in st.session_state: st.session_state.balance = Decimal('0.00')

# --- Database Initialization (and auto-reset check) ---
init_db(st)

# --- Main Routing ---
if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "signup":
    show_signup()
elif st.session_state.page == "signin":
    show_signin()
elif st.session_state.page == "dashboard":
    show_dashboard()

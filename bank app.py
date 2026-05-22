"""
DAVE Bank - Streamlit Banking Application

A prototype banking application built with Python, SQLite, and Streamlit.
Supports account creation, deposits, withdrawals, transfers,
airtime purchases, bill payments, and transaction history.
"""

import sqlite3 as sql
from datetime import datetime
import re
import os
import streamlit as st
import pandas as pd

st.set_page_config(page_title="DAVE Bank", page_icon="🏦", layout="centered")

# Database file stored alongside the script
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank_app.db")

def init_db():
    try:
        with sql.connect(DB_PATH) as mycon:
            mycursor = mycon.cursor()
            mycursor.execute('''
                CREATE TABLE IF NOT EXISTS Customer_Table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE,
                    password TEXT,
                    account_no TEXT UNIQUE,
                    balance REAL DEFAULT 0
                )
            ''')
            mycursor.execute('''
                CREATE TABLE IF NOT EXISTS transaction_table (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_no TEXT,
                    transaction_desc TEXT,
                    amount REAL,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            mycon.commit()
    except sql.Error as err:
        st.error(f"Database Error: {err}")

# Initialize Database
init_db()

# --- Session State Initialization ---
if "page" not in st.session_state:
    st.session_state.page = "home"
if "email" not in st.session_state:
    st.session_state.email = None
if "account_no" not in st.session_state:
    st.session_state.account_no = None
if "balance" not in st.session_state:
    st.session_state.balance = 0.0

# --- Helper Functions ---
def navigate_to(page):
    st.session_state.page = page

def validate_email(email):
    email = email.strip()
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def update_balance(account_no, amount_change):
    try:
        with sql.connect(DB_PATH) as mycon:
            mycursor = mycon.cursor()
            mycursor.execute('UPDATE Customer_Table SET balance = balance + ? WHERE account_no = ?', (amount_change, account_no))
            mycon.commit()
            
            # Fetch new balance
            mycursor.execute('SELECT balance FROM Customer_Table WHERE account_no = ?', (account_no,))
            new_balance = mycursor.fetchone()[0]
            st.session_state.balance = new_balance
            return True
    except sql.Error as err:
        st.error(f"Database Error: {err}")
        return False

def add_transaction(account_no, desc, amount):
    try:
        with sql.connect(DB_PATH) as mycon:
            mycursor = mycon.cursor()
            query = 'INSERT INTO transaction_table(account_no, transaction_desc, amount, date) VALUES (?, ?, ?, ?)'
            mycursor.execute(query, (account_no, desc, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            mycon.commit()
    except sql.Error as err:
        st.error(f"Database Error: {err}")

# --- UI Components ---
def show_home():
    st.markdown("<h1 style='text-align: center; color: #1E3A8A;'>🏦 Welcome to DAVE Bank</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #4B5563;'>Your trusted partner for all financial transactions.</p>", unsafe_allow_html=True)
    
    st.divider()
    
    col1, col2 = st.columns(2)
    with col1:
        st.button("Sign In", use_container_width=True, type="primary", on_click=navigate_to, args=("signin",))
    with col2:
        st.button("Sign Up", use_container_width=True, on_click=navigate_to, args=("signup",))

def show_signup():
    st.title("Sign Up")
    with st.form("signup_form"):
        email = st.text_input("Email Address")
        account_no = st.text_input("Choose Account Number (Min 5 digits)")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Create Account", type="primary")
        
        if submit:
            if not validate_email(email):
                st.error("Invalid email format.")
            elif not account_no.isdigit() or len(account_no) < 5:
                st.error("Account number must be at least 5 digits.")
            elif not password:
                st.error("Password cannot be empty.")
            else:
                try: 
                    with sql.connect(DB_PATH) as mycon: 
                        mycursor = mycon.cursor() 
                        mycursor.execute('SELECT * FROM Customer_Table WHERE email = ? OR account_no = ?', (email, account_no))
                        if mycursor.fetchone():
                            st.error("This email or account number is already registered.")
                        else:
                            mycursor.execute('INSERT INTO Customer_Table (email, password, account_no) VALUES (?, ?, ?)', (email, password, account_no))
                            mycon.commit()
                            st.success(f"Account created successfully! Welcome, {email}")
                            st.info("Please sign in to continue.")
                except sql.Error as err: 
                    st.error(f"Database Error: {err}")
    st.button("Back to Home", on_click=navigate_to, args=("home",))

def show_signin():
    st.title("Sign In")
    with st.form("signin_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login", type="primary")
        
        if submit:
            try:
                with sql.connect(DB_PATH) as mycon:
                    mycursor = mycon.cursor()
                    mycursor.execute('SELECT password, account_no, balance FROM Customer_Table WHERE email = ?', (email,))
                    result = mycursor.fetchone()

                    if result is None:
                        st.error("Account does not exist. Please sign up first.")
                    else:
                        stored_password, acct_no, balance = result
                        if password == stored_password:
                            st.session_state.email = email
                            st.session_state.account_no = acct_no
                            st.session_state.balance = balance
                            navigate_to("dashboard")
                            st.rerun()
                        else:
                            st.error("Incorrect password!")
            except sql.Error as err:
                st.error(f"Database Error: {err}")
    st.button("Back to Home", on_click=navigate_to, args=("home",))

def show_dashboard():
    # Sidebar Navigation
    st.sidebar.title(f"Welcome, {st.session_state.email.split('@')[0]}")
    st.sidebar.markdown(f"**Account No:** `{st.session_state.account_no}`")
    st.sidebar.markdown(f"**Balance:** `${st.session_state.balance:,.2f}`")
    st.sidebar.divider()
    
    # Simple navigation with session state
    if "dash_view" not in st.session_state:
        st.session_state.dash_view = "Check Balance"
        
    def set_dash_view(view):
        st.session_state.dash_view = view
        
    st.sidebar.button("💰 Check Balance", on_click=set_dash_view, args=("Check Balance",), use_container_width=True)
    st.sidebar.button("📥 Deposit", on_click=set_dash_view, args=("Deposit",), use_container_width=True)
    st.sidebar.button("📤 Withdraw", on_click=set_dash_view, args=("Withdraw",), use_container_width=True)
    st.sidebar.button("🔄 Transfer", on_click=set_dash_view, args=("Transfer",), use_container_width=True)
    st.sidebar.button("📱 Buy Airtime", on_click=set_dash_view, args=("Buy Airtime",), use_container_width=True)
    st.sidebar.button("🧾 Pay Bills", on_click=set_dash_view, args=("Pay Bills",), use_container_width=True)
    st.sidebar.button("📜 Transaction History", on_click=set_dash_view, args=("Transaction History",), use_container_width=True)
    
    st.sidebar.divider()
    
    def sign_out():
        st.session_state.clear()
        navigate_to("home")
        
    st.sidebar.button("🚪 Sign Out", on_click=sign_out, use_container_width=True)

    # Main Content Area
    st.title(st.session_state.dash_view)
    
    if st.session_state.dash_view == "Check Balance":
        st.metric(label="Current Balance", value=f"${st.session_state.balance:,.2f}")
        
    elif st.session_state.dash_view == "Deposit":
        with st.form("deposit_form", clear_on_submit=True):
            amount = st.number_input("Amount to Deposit ($)", min_value=1.0, step=10.0)
            if st.form_submit_button("Deposit Funds"):
                if update_balance(st.session_state.account_no, amount):
                    add_transaction(st.session_state.account_no, 'Deposit of funds', amount)
                    st.success(f"${amount:,.2f} deposited successfully!")
                    st.rerun()

    elif st.session_state.dash_view == "Withdraw":
        with st.form("withdraw_form", clear_on_submit=True):
            amount = st.number_input("Amount to Withdraw ($)", min_value=1.0, step=10.0)
            if st.form_submit_button("Withdraw Funds"):
                if amount > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    if update_balance(st.session_state.account_no, -amount):
                        add_transaction(st.session_state.account_no, 'Withdrawal of funds', amount)
                        st.success(f"${amount:,.2f} withdrawn successfully!")
                        st.rerun()

    elif st.session_state.dash_view == "Transfer":
        with st.form("transfer_form", clear_on_submit=True):
            bank = st.text_input("Receiver's Bank")
            receiver_acct = st.text_input("Receiver's Account Number")
            amount = st.number_input("Amount to Transfer ($)", min_value=1.0, step=10.0)
            if st.form_submit_button("Transfer Funds"):
                if not receiver_acct.isdigit():
                    st.error("Invalid account number! Must contain numbers only.")
                elif amount > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    if update_balance(st.session_state.account_no, -amount):
                        add_transaction(st.session_state.account_no, f'Transfer to {bank} ({receiver_acct})', amount)
                        st.success(f"${amount:,.2f} transferred to {bank} ({receiver_acct}).")
                        st.rerun()

    elif st.session_state.dash_view == "Buy Airtime":
        with st.form("airtime_form", clear_on_submit=True):
            network = st.selectbox("Select Network", ["MTN", "Airtel", "Glo", "9mobile"])
            phone = st.text_input("Phone Number")
            amount = st.number_input("Airtime Amount ($)", min_value=1.0, step=5.0)
            if st.form_submit_button("Buy Airtime"):
                if not phone.isdigit() or len(phone) < 10:
                    st.error("Invalid phone number! Must be at least 10 digits.")
                elif amount > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    if update_balance(st.session_state.account_no, -amount):
                        add_transaction(st.session_state.account_no, f'Airtime purchase ({network} - {phone})', amount)
                        st.success(f"${amount:,.2f} airtime recharged on {network} ({phone}).")
                        st.rerun()

    elif st.session_state.dash_view == "Pay Bills":
        with st.form("bills_form", clear_on_submit=True):
            bill_type = st.selectbox("Select Bill Type", ["Electricity", "Internet", "Water", "Cable TV"])
            amount = st.number_input("Bill Amount ($)", min_value=1.0, step=10.0)
            if st.form_submit_button("Pay Bill"):
                if amount > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    if update_balance(st.session_state.account_no, -amount):
                        add_transaction(st.session_state.account_no, f'Bill payment - {bill_type}', amount)
                        st.success(f"${amount:,.2f} paid for {bill_type}.")
                        st.rerun()

    elif st.session_state.dash_view == "Transaction History":
        try:
            with sql.connect(DB_PATH) as mycon:
                query = "SELECT transaction_desc as Description, amount as Amount, date as Date FROM transaction_table WHERE account_no = ? ORDER BY date DESC"
                df = pd.read_sql_query(query, mycon, params=(st.session_state.account_no,))
                if df.empty:
                    st.info("No transactions found.")
                else:
                    # Format amount column
                    df['Amount'] = df['Amount'].apply(lambda x: f"${x:,.2f}")
                    st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error loading transactions: {e}")

# --- Routing ---
if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "signup":
    show_signup()
elif st.session_state.page == "signin":
    show_signin()
elif st.session_state.page == "dashboard":
    show_dashboard()

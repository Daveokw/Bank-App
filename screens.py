import streamlit as st
import sqlite3 as sql
import pandas as pd
import bcrypt
import uuid
import time
from decimal import Decimal
from datetime import datetime
from db import DB_PATH
from engine import (
    validate_email, gen_account_no, validate_nuban, exec_transaction
)

def navigate_to(page):
    st.session_state.page = page

def refresh_balance():
    if st.session_state.account_id:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT balance FROM account WHERE id=?", (st.session_state.account_id,))
            res = cur.fetchone()
            if res:
                st.session_state.balance = Decimal(str(res[0]))

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
        phone = st.text_input("Phone Number (11 digits)")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Create Account", type="primary")
        
        if submit:
            if not validate_email(email):
                st.error("Invalid email format.")
            elif not phone.isdigit() or len(phone) != 11:
                st.error("Phone number must be exactly 11 digits.")
            elif phone[:3] not in ["080", "081", "090", "091", "070"]:
                st.error("Invalid phone number.")
            elif len(username) < 3:
                st.error("Username too short.")
            elif len(password) < 4:
                st.error("Password too short (min 4 chars).")
            else:
                try: 
                    with sql.connect(DB_PATH) as conn: 
                        cur = conn.cursor() 
                        cur.execute('SELECT id FROM customer WHERE email = ? OR username = ?', (email, username))
                        if cur.fetchone():
                            st.error("This email or username is already registered.")
                        else:
                            cur.execute('SELECT id FROM phone WHERE phone_number = ?', (phone,))
                            if cur.fetchone():
                                st.error("This phone number is already registered.")
                            else:
                                hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                                cur.execute("INSERT INTO customer (email, username, password) VALUES (?,?,?)", (email, username, hashed))
                                cust_id = cur.lastrowid
                                cur.execute("INSERT INTO phone (customer_id, phone_number) VALUES (?,?)", (cust_id, phone))
                                acct_no = gen_account_no(cust_id)
                                cur.execute("INSERT INTO account (customer_id, account_no) VALUES (?,?)", (cust_id, acct_no))
                                account_id = cur.lastrowid
                                cur.execute("INSERT INTO ledger (account_id, description, debit, credit, balance) VALUES (?,?,?,?,?)",
                                            (account_id, 'Opening Balance', 0.00, 0.00, 0.00))
                                cur.execute("INSERT INTO customer_ledger (ref_no, account_id, debit, credit, balance_after, description, tx_type) VALUES (?,?,?,?,?,?,?)",
                                            (f'OPEN-{uuid.uuid4().hex[:8]}', account_id, 0.00, 0.00, 0.00, 'Opening balance', 'opening'))
                                conn.commit()
                                st.success(f"Account created successfully! Your NUBAN Account #: {acct_no}")
                                time.sleep(3)
                                navigate_to("home")
                except sql.Error as err: 
                    st.error(f"Database Error: {err}")
    st.button("Back to Home", on_click=navigate_to, args=("home",))

def show_signin():
    st.title("Sign In")
    with st.form("signin_form"):
        key = st.text_input("Email, Phone or Username")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login", type="primary")
        
        if submit:
            try:
                with sql.connect(DB_PATH) as conn:
                    cur = conn.cursor()
                    cur.execute('''SELECT c.id, c.email, c.username, c.password, a.id, a.account_no, a.balance, p.phone_number
                                   FROM customer c
                                   LEFT JOIN phone p ON c.id=p.customer_id
                                   JOIN account a ON c.id=a.customer_id
                                   WHERE c.email=? OR c.username=? OR p.phone_number=? LIMIT 1''', (key, key, key))
                    row = cur.fetchone()

                    if not row:
                        st.error("Account not found.")
                    else:
                        cid, email, username, stored, aid, acc_no, bal, phone = row
                        if stored is None:
                            if username == 'admin' and email.lower() == 'admin@gmail.com':
                                st.error("Admin password not set. Please manually update DB or set default.")
                            else:
                                st.error("Account has no password. Contact admin.")
                        else:
                            if bcrypt.checkpw(password.encode('utf-8'), stored.encode('utf-8')):
                                st.session_state.customer_id = cid
                                st.session_state.email = email
                                st.session_state.username = username
                                st.session_state.account_id = aid
                                st.session_state.account_no = acc_no
                                st.session_state.balance = Decimal(str(bal))
                                st.session_state.phone = phone or ""
                                navigate_to("dashboard")
                            else:
                                st.error("Incorrect password!")
            except sql.Error as err:
                st.error(f"Database Error: {err}")
    st.button("Back to Home", on_click=navigate_to, args=("home",))

def show_dashboard():
    refresh_balance()
    is_admin = (st.session_state.username == 'admin' and st.session_state.email.lower() == 'admin@gmail.com')

    st.sidebar.title(f"Welcome, {st.session_state.username}")
    st.sidebar.markdown(f"**Account No:** `{st.session_state.account_no}`")
    st.sidebar.markdown(f"**Balance:** `₦{st.session_state.balance:,.2f}`")
    st.sidebar.divider()
    
    if "dash_view" not in st.session_state:
        st.session_state.dash_view = "Check Balance" if not is_admin else "Trial Balance"
        
    def set_dash_view(view):
        st.session_state.dash_view = view

    if is_admin:
        st.sidebar.button("📊 Trial Balance", on_click=set_dash_view, args=("Trial Balance",), use_container_width=True)
        st.sidebar.button("📚 Subledgers", on_click=set_dash_view, args=("Subledgers",), use_container_width=True)
        st.sidebar.button("📖 Customer Subledger", on_click=set_dash_view, args=("Customer Subledger",), use_container_width=True)
        st.sidebar.button("⚖️ Reconcile Customer", on_click=set_dash_view, args=("Reconcile Customer",), use_container_width=True)
    else:
        st.sidebar.button("💰 Check Balance", on_click=set_dash_view, args=("Check Balance",), use_container_width=True)
        st.sidebar.button("📥 Deposit", on_click=set_dash_view, args=("Deposit",), use_container_width=True)
        st.sidebar.button("📤 Withdraw", on_click=set_dash_view, args=("Withdraw",), use_container_width=True)
        st.sidebar.button("🔄 Transfer", on_click=set_dash_view, args=("Transfer",), use_container_width=True)
        st.sidebar.button("📱 Buy Airtime", on_click=set_dash_view, args=("Buy Airtime",), use_container_width=True)
        st.sidebar.button("🧾 Pay Bills", on_click=set_dash_view, args=("Pay Bills",), use_container_width=True)
        st.sidebar.button("📜 Transaction History", on_click=set_dash_view, args=("Transaction History",), use_container_width=True)
        st.sidebar.button("📓 View Customer Ledger", on_click=set_dash_view, args=("View Customer Ledger",), use_container_width=True)
    
    st.sidebar.divider()
    
    def sign_out():
        st.session_state.clear()
        navigate_to("home")
        
    st.sidebar.button("🚪 Sign Out", on_click=sign_out, use_container_width=True)

    st.title(st.session_state.dash_view)

    # --- Admin Views ---
    if st.session_state.dash_view == "Trial Balance" and is_admin:
        try:
            with sql.connect(DB_PATH) as conn:
                query = "SELECT account_name, SUM(debit) as Debit, SUM(credit) as Credit FROM bank_ledger GROUP BY account_name"
                df = pd.read_sql_query(query, conn)
                total_debit = df['Debit'].sum()
                total_credit = df['Credit'].sum()
                diff = total_debit - total_credit
                
                st.markdown(f"**Total Debits:** ₦{total_debit:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Total Credits:** ₦{total_credit:,.2f} &nbsp;&nbsp;|&nbsp;&nbsp; **Difference:** ₦{diff:,.2f}")
                
                df['Debit'] = df['Debit'].apply(lambda x: f"₦{x:,.2f}")
                df['Credit'] = df['Credit'].apply(lambda x: f"₦{x:,.2f}")
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error loading Trial Balance: {e}")

    elif st.session_state.dash_view == "Subledgers" and is_admin:
        try:
            with sql.connect(DB_PATH) as conn:
                query = "SELECT account_name as Name, account_type as Type, balance as Balance, description as Description FROM subledger_account ORDER BY account_type, account_name"
                df = pd.read_sql_query(query, conn)
                df['Balance'] = df['Balance'].apply(lambda x: f"₦{x:,.2f}")
                st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error loading Subledgers: {e}")

    elif st.session_state.dash_view == "Customer Subledger" and is_admin:
        st.info("Feature available directly via database queries for Admin.")
        
    elif st.session_state.dash_view == "Reconcile Customer" and is_admin:
        st.info("Feature available directly via database queries for Admin.")

    # --- Customer Views ---
    elif st.session_state.dash_view == "Check Balance":
        st.metric(label="Current Balance", value=f"₦{st.session_state.balance:,.2f}")
        
    elif st.session_state.dash_view == "Deposit":
        with st.form("deposit_form", clear_on_submit=True):
            amount = st.number_input("Amount to Deposit (₦)", min_value=1.0, step=100.0)
            if st.form_submit_button("Deposit Funds"):
                st.session_state.balance += Decimal(str(amount))
                if exec_transaction("Deposit", amount):
                    st.success(f"₦{amount:,.2f} deposited successfully!")
                    time.sleep(2)
                    st.rerun()

    elif st.session_state.dash_view == "Withdraw":
        with st.form("withdraw_form", clear_on_submit=True):
            amount = st.number_input("Amount to Withdraw (₦)", min_value=1.0, step=100.0)
            if st.form_submit_button("Withdraw Funds"):
                if Decimal(str(amount)) > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    st.session_state.balance -= Decimal(str(amount))
                    if exec_transaction("Withdrawal", amount):
                        st.success(f"₦{amount:,.2f} withdrawn successfully!")
                        time.sleep(2)
                        st.rerun()

    elif st.session_state.dash_view == "Transfer":
        with st.form("transfer_form", clear_on_submit=True):
            bank = st.text_input("Receiver's Bank")
            receiver_acct = st.text_input("Receiver's Account Number (10 digits)")
            amount = st.number_input("Amount to Transfer (₦)", min_value=1.0, step=100.0)
            if st.form_submit_button("Transfer Funds"):
                if not receiver_acct.isdigit() or len(receiver_acct) != 10:
                    st.error("Invalid account number! Must be exactly 10 digits.")
                elif not validate_nuban(receiver_acct) and bank.lower() in ["dave bank", "dave"]:
                    st.error("Invalid NUBAN account number for this bank. Please check the check digit.")
                elif Decimal(str(amount)) <= 0:
                    st.error("Transfer amount must be greater than zero.")
                elif Decimal(str(amount)) > st.session_state.balance:
                    st.error("Insufficient Balance!")
                elif receiver_acct == st.session_state.account_no:
                    st.error("You cannot transfer to your own account.")
                else:
                    try:
                        with sql.connect(DB_PATH) as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT id FROM account WHERE account_no=? LIMIT 1", (receiver_acct,))
                            r = cur.fetchone()
                            receiver_id = r[0] if r else None
                            
                            st.session_state.balance -= Decimal(str(amount))
                            
                            if receiver_id:
                                # Internal Transfer Logic
                                cur.execute("SELECT balance FROM account WHERE id=?", (receiver_id,))
                                rrow = cur.fetchone()
                                rbal = Decimal(str(rrow[0]))
                                new_rbal = rbal + Decimal(str(amount))
                                cur.execute("UPDATE account SET balance=? WHERE id=?", (float(new_rbal), receiver_id))
                                
                                cur.execute("INSERT INTO transaction_record (account_id,transaction_type,amount,date) VALUES (?,?,?,?)",
                                            (receiver_id, "Transfer", float(amount), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                                cur.execute("INSERT INTO ledger (account_id,description,debit,credit,balance,date) VALUES (?,?,?,?,?,?)",
                                            (receiver_id, "Transfer in", 0.00, float(amount), float(new_rbal), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                                conn.commit()
                                
                                extra = {'receiver_account_id': receiver_id, 'receiver_acct_no': receiver_acct, 'receiver_bank': bank}
                                exec_transaction("Transfer", amount, extra=extra)
                            else:
                                # External Transfer
                                extra = {'receiver_bank': bank, 'receiver_acct_no': receiver_acct}
                                exec_transaction("Transfer", amount, extra=extra)
                                
                        st.success(f"₦{amount:,.2f} transferred to {receiver_acct} ({bank}).")
                        time.sleep(2)
                        st.rerun()
                    except sql.Error as e:
                        st.error(f"DB Error: {e}")

    elif st.session_state.dash_view == "Buy Airtime":
        with st.form("airtime_form", clear_on_submit=True):
            network = st.selectbox("Select Network", ["MTN", "Airtel", "Glo", "9mobile"])
            phone = st.text_input("Phone Number (11 digits)")
            amount = st.number_input("Airtime Amount (₦)", min_value=1.0, step=100.0)
            if st.form_submit_button("Buy Airtime"):
                if not phone.isdigit() or len(phone) != 11:
                    st.error("Invalid phone number! Must be exactly 11 digits.")
                elif phone[:3] not in ["080", "081", "090", "091", "070"]:
                    st.error("Invalid phone number.")
                elif Decimal(str(amount)) <= 0:
                    st.error("Airtime amount must be greater than zero.")
                elif Decimal(str(amount)) > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    st.session_state.balance -= Decimal(str(amount))
                    extra = {'phone': phone}
                    if exec_transaction("Buy Airtime", amount, extra=extra):
                        st.success(f"₦{amount:,.2f} airtime recharged on {network} ({phone}).")
                        time.sleep(2)
                        st.rerun()

    elif st.session_state.dash_view == "Pay Bills":
        with st.form("bills_form", clear_on_submit=True):
            bill_type = st.selectbox("Select Bill Type", ["Electricity", "Internet", "Water", "Cable TV"])
            amount = st.number_input("Bill Amount (₦)", min_value=1.0, step=100.0)
            if st.form_submit_button("Pay Bill"):
                if Decimal(str(amount)) <= 0:
                    st.error("Bill amount must be greater than zero.")
                elif Decimal(str(amount)) > st.session_state.balance:
                    st.error("Insufficient Balance!")
                else:
                    st.session_state.balance -= Decimal(str(amount))
                    extra = {'bill': bill_type}
                    if exec_transaction("Pay Bills", amount, extra=extra):
                        st.success(f"₦{amount:,.2f} paid for {bill_type}.")
                        time.sleep(2)
                        st.rerun()

    elif st.session_state.dash_view == "Transaction History":
        try:
            with sql.connect(DB_PATH) as conn:
                query = "SELECT transaction_type AS 'Transaction', amount AS 'Amount', date AS 'Date' FROM transaction_record WHERE account_id = ? ORDER BY date DESC"
                df = pd.read_sql_query(query, conn, params=(st.session_state.account_id,))
                if df.empty:
                    st.info("No transactions found.")
                else:
                    df['Amount'] = df['Amount'].apply(lambda x: f"₦{x:,.2f}")
                    st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error loading transactions: {e}")

    elif st.session_state.dash_view == "View Customer Ledger":
        try:
            with sql.connect(DB_PATH) as conn:
                query = "SELECT date AS 'Date', description AS 'Description', debit AS 'Debit', credit AS 'Credit', balance AS 'Balance' FROM ledger WHERE account_id = ? ORDER BY date DESC"
                df = pd.read_sql_query(query, conn, params=(st.session_state.account_id,))
                if df.empty:
                    st.info("No ledger entries found.")
                else:
                    df['Debit'] = df['Debit'].apply(lambda x: f"₦{x:,.2f}")
                    df['Credit'] = df['Credit'].apply(lambda x: f"₦{x:,.2f}")
                    df['Balance'] = df['Balance'].apply(lambda x: f"₦{x:,.2f}")
                    st.dataframe(df, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Error loading ledger: {e}")

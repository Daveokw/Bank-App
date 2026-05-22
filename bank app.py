
import sqlite3 as sql
from datetime import datetime
import re
import hashlib
from decimal import Decimal
import os
import time
import uuid
import streamlit as st
import pandas as pd

st.set_page_config(page_title="DAVE Bank", page_icon="🏦", layout="wide")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank_app.db")

def check_and_reset_db():
    if os.path.exists(DB_PATH):
        try:
            with sql.connect(DB_PATH) as conn:
                cur = conn.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='system_config'")
                if cur.fetchone():
                    cur.execute("SELECT value FROM system_config WHERE key='created_at'")
                    row = cur.fetchone()
                    if row:
                        created_at = datetime.fromisoformat(row[0])
                        if (datetime.now() - created_at).total_seconds() > 24 * 3600:
                            return True
        except Exception:
            pass
    return False

def init_db():
    if check_and_reset_db():
        try:
            os.remove(DB_PATH)
            st.session_state.clear()
        except OSError:
            pass

    try:
        with sql.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customer (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    username TEXT UNIQUE NOT NULL,
                    password TEXT DEFAULT NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS phone (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    phone_number TEXT UNIQUE NOT NULL,
                    FOREIGN KEY (customer_id) REFERENCES customer(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL,
                    account_no TEXT UNIQUE NOT NULL,
                    balance REAL DEFAULT 0.00,
                    FOREIGN KEY (customer_id) REFERENCES customer(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS transaction_record (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    transaction_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    description TEXT NOT NULL,
                    debit REAL DEFAULT 0.00,
                    credit REAL DEFAULT 0.00,
                    balance REAL NOT NULL,
                    date DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS bank_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_no TEXT,
                    account_name TEXT,
                    debit REAL DEFAULT 0.00,
                    credit REAL DEFAULT 0.00,
                    related_account TEXT,
                    description TEXT,
                    tx_type TEXT,
                    account_id INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customer_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_no TEXT,
                    account_id INTEGER,
                    debit REAL DEFAULT 0.00,
                    credit REAL DEFAULT 0.00,
                    balance_after REAL,
                    description TEXT,
                    tx_type TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS subledger_account (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_name TEXT UNIQUE,
                    account_type TEXT,
                    balance REAL DEFAULT 0.00,
                    description TEXT
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS customer_subledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ref_no TEXT,
                    account_id INTEGER,
                    subledger_account_id INTEGER,
                    debit REAL DEFAULT 0.00,
                    credit REAL DEFAULT 0.00,
                    balance_after REAL,
                    description TEXT,
                    tx_type TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE,
                    FOREIGN KEY (subledger_account_id) REFERENCES subledger_account(id) ON DELETE CASCADE
                )
            ''')

            conn.commit()

            # Seed system config
            cursor.execute("SELECT value FROM system_config WHERE key='created_at'")
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO system_config (key, value) VALUES (?, ?)", ("created_at", datetime.now().isoformat()))

            # Seed subledger accounts
            seed_accounts = [
                ('Cash','asset','Cash on hand / bank balances'),
                ('Customer_Deposits','liability','Customers deposits / demand deposits (control account)'),
                ('Interbank_Payables','liability','Interbank payables / external transfer liabilities'),
                ('Airtime_Payable','liability','Airtime vendor payable'),
                ('Bills_Payable','liability','Bills vendor payable'),
                ('Equity','equity','Owners equity / shareholders equity'),
                ('Revenue','revenue','Operating revenue / sales'),
                ('Income','revenue','Other income'),
                ('Expenses','expense','Operating expenses')
            ]
            for name, acct_type, desc in seed_accounts:
                cursor.execute("SELECT id FROM subledger_account WHERE account_name=?", (name,))
                if cursor.fetchone() is None:
                    cursor.execute("INSERT INTO subledger_account (account_name, account_type, balance, description) VALUES (?,?,?,?)",
                                   (name, acct_type, 0.00, desc))
            
            # Seed Admin Account
            cursor.execute("SELECT id FROM customer WHERE username='admin' OR email='admin@gmail.com' LIMIT 1")
            if cursor.fetchone() is None:
                cursor.execute("INSERT INTO customer (email, username, password) VALUES (?,?,?)", ("admin@gmail.com","admin", None))
                admin_id = cursor.lastrowid
                cursor.execute("INSERT INTO phone (customer_id, phone_number) VALUES (?,?)", (admin_id, "100"))
                cursor.execute("INSERT INTO account (customer_id, account_no, balance) VALUES (?,?,?)", (admin_id, "ADMIN0000001", 0.00))
                admin_account_id = cursor.lastrowid
                cursor.execute("INSERT INTO ledger (account_id, description, debit, credit, balance) VALUES (?,?,?,?,?)",
                               (admin_account_id, 'Opening Balance', 0.00, 0.00, 0.00))
                cursor.execute("INSERT INTO customer_ledger (ref_no, account_id, debit, credit, balance_after, description, tx_type) VALUES (?,?,?,?,?,?,?)",
                               (f'OPEN-{uuid.uuid4().hex[:8]}', admin_account_id, 0.00, 0.00, 0.00, 'Opening balance', 'opening'))
            conn.commit()
    except sql.Error as err:
        st.error(f"Database Initialization Error: {err}")

init_db()

# --- Session State ---
if "page" not in st.session_state: st.session_state.page = "home"
if "customer_id" not in st.session_state: st.session_state.customer_id = None
if "account_id" not in st.session_state: st.session_state.account_id = None
if "account_no" not in st.session_state: st.session_state.account_no = None
if "email" not in st.session_state: st.session_state.email = None
if "username" not in st.session_state: st.session_state.username = None
if "phone" not in st.session_state: st.session_state.phone = None
if "balance" not in st.session_state: st.session_state.balance = Decimal('0.00')

def navigate_to(page):
    st.session_state.page = page
    st.rerun()

def refresh_balance():
    if st.session_state.account_id:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            cur.execute("SELECT balance FROM account WHERE id=?", (st.session_state.account_id,))
            res = cur.fetchone()
            if res:
                st.session_state.balance = Decimal(str(res[0]))

# --- Helpers ---
def validate_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email.strip())

def compute_new_subledger_balance(prev_balance: Decimal, acct_type: str, debit: Decimal, credit: Decimal) -> Decimal:
    if acct_type in ('asset', 'expense'):
        return prev_balance + (debit - credit)
    else:
        return prev_balance + (credit - debit)

def calculate_nuban_check_digit(bank_code: str, branch_code: str, serial: str) -> str:
    payload = bank_code.zfill(3) + branch_code.zfill(3) + serial.zfill(9)
    weights = [3,7,3,3,7,3,3,7,3,3,7,3,3,7,3]
    total = sum(int(d)*w for d,w in zip(payload, weights))
    remainder = total % 10
    return str((10 - remainder) if remainder else 0)

def gen_account_no(user_id: int) -> str:
    bank_code, branch_code = "011", "000"
    serial = str(user_id % 1000000000).zfill(9)
    return serial + calculate_nuban_check_digit(bank_code, branch_code, serial)

def _new_ref():
    return 'JNL-' + uuid.uuid4().hex[:12]

def record_double_entry(entries, description='', tx_type=''):
    if not isinstance(entries, list) or len(entries) < 2: return
    ref = _new_ref()
    try:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            for line in entries:
                acct = line.get('account_name')
                debit = float(line.get('debit') or 0.00)
                credit = float(line.get('credit') or 0.00)
                related = line.get('related')
                acct_id = line.get('account_id', None)
                cur.execute('''INSERT INTO bank_ledger (ref_no, account_name, debit, credit, related_account, description, tx_type, account_id, created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)''',
                            (ref, acct, debit, credit, related, description, tx_type, acct_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                if acct_id:
                    cur.execute('SELECT balance FROM account WHERE id=?', (acct_id,))
                    r = cur.fetchone()
                    bal_after = float(r[0]) if r else None
                    cur.execute('''INSERT INTO customer_ledger (ref_no, account_id, debit, credit, balance_after, description, tx_type, created_at)
                                   VALUES (?,?,?,?,?,?,?,?)''',
                                (ref, acct_id, debit, credit, bal_after, description, tx_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                cur.execute("SELECT id, account_type, balance FROM subledger_account WHERE LOWER(account_name)=LOWER(?) LIMIT 1", (acct,))
                s = cur.fetchone()
                if s:
                    sub_id, acct_type, prev_bal = s[0], s[1], Decimal(str(s[2] or 0))
                    new_bal = compute_new_subledger_balance(prev_bal, acct_type, Decimal(str(debit)), Decimal(str(credit)))
                    cur.execute("UPDATE subledger_account SET balance=? WHERE id=?", (float(new_bal), sub_id))
                    if acct_id:
                        cur.execute('''SELECT balance_after FROM customer_subledger
                                       WHERE account_id=? AND subledger_account_id=?
                                       ORDER BY created_at DESC LIMIT 1''', (acct_id, sub_id))
                        last = cur.fetchone()
                        prev_customer_bal = Decimal(str(last[0])) if last and last[0] is not None else Decimal('0.00')
                        customer_new_bal = compute_new_subledger_balance(prev_customer_bal, acct_type, Decimal(str(debit)), Decimal(str(credit)))
                        cur.execute('''INSERT INTO customer_subledger (ref_no, account_id, subledger_account_id, debit, credit, balance_after, description, tx_type, created_at)
                                       VALUES (?,?,?,?,?,?,?,?,?)''',
                                    (ref, acct_id, sub_id, debit, credit, float(customer_new_bal), description, tx_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
    except sql.Error as e:
        print("Ledger write error:", e)

def exec_transaction(t_type, amount, extra=None):
    amount_dec = Decimal(str(amount))
    try:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            new_bal = st.session_state.balance
            cur.execute("UPDATE account SET balance=? WHERE id=?", (float(new_bal), st.session_state.account_id))
            cur.execute("INSERT INTO transaction_record (account_id,transaction_type,amount,date) VALUES (?,?,?,?)", 
                        (st.session_state.account_id, t_type, float(amount_dec), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
            debit = amount_dec if t_type in ("Withdrawal", "Transfer", "Pay Bills", "Buy Airtime") else Decimal('0.00')
            credit = amount_dec if t_type == "Deposit" else Decimal('0.00')
            
            cur.execute("INSERT INTO ledger (account_id,description,debit,credit,balance,date) VALUES (?,?,?,?,?,?)",
                        (st.session_state.account_id, t_type, float(debit), float(credit), float(new_bal), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()

        entries = []
        description = t_type
        tx_type = t_type.lower().replace(' ', '_')
        acct_no = st.session_state.account_no
        acct_id = st.session_state.account_id

        if t_type == "Deposit":
            entries = [
                {'account_name': 'Cash', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'Cash deposit by {acct_no}', 'account_id': None},
                {'account_name': 'Customer_Deposits', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'Deposit to {acct_no}', 'account_id': acct_id}
            ]
        elif t_type == "Withdrawal":
            entries = [
                {'account_name': 'Customer_Deposits', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'Withdrawal by {acct_no}', 'account_id': acct_id},
                {'account_name': 'Cash', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'Cash paid to {acct_no}', 'account_id': None}
            ]
        elif t_type == "Transfer":
            receiver_id = extra.get('receiver_account_id') if extra else None
            receiver_bank = extra.get('receiver_bank') if extra else None
            receiver_acct_no = extra.get('receiver_acct_no') if extra else None
            if receiver_id:
                entries = [
                    {'account_name': 'Customer_Deposits', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'Transfer from {acct_no}', 'account_id': receiver_id},
                    {'account_name': 'Customer_Deposits', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'Transfer to {receiver_acct_no}', 'account_id': acct_id}
                ]
            else:
                entries = [
                    {'account_name': 'Customer_Deposits', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'External transfer to {receiver_bank} {receiver_acct_no} ({acct_no})', 'account_id': acct_id},
                    {'account_name': 'Interbank_Payables', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'External transfer from {acct_no} to {receiver_bank} {receiver_acct_no}', 'account_id': acct_id}
                ]
        elif t_type == "Buy Airtime":
            phone = extra.get('phone') if extra else None
            entries = [
                {'account_name': 'Customer_Deposits', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'Airtime for {phone} ({acct_no})', 'account_id': acct_id},
                {'account_name': 'Airtime_Payable', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'Airtime for {phone} ({acct_no})', 'account_id': acct_id}
            ]
        elif t_type == "Pay Bills":
            bill = extra.get('bill') if extra else None
            entries = [
                {'account_name': 'Customer_Deposits', 'debit': amount_dec, 'credit': Decimal('0.00'), 'related': f'Bill payment {bill} ({acct_no})', 'account_id': acct_id},
                {'account_name': 'Bills_Payable', 'debit': Decimal('0.00'), 'credit': amount_dec, 'related': f'Bill payment {bill} ({acct_no})', 'account_id': acct_id}
            ]
        else:
            entries = [
                {'account_name': 'Customer_Deposits', 'debit': debit, 'credit': credit, 'related': f'Generic {acct_no}', 'account_id': acct_id},
                {'account_name': 'Suspense', 'debit': Decimal('0.00'), 'credit': Decimal('0.00'), 'related': f'Generic {acct_no}', 'account_id': acct_id}
            ]

        record_double_entry(entries, description=description, tx_type=tx_type)
        return True
    except sql.Error as e:
        st.error(f"DB Error: {e}")
        return False

# --- Screens ---
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
                                hashed = hashlib.sha256(password.encode()).hexdigest()
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
                            if hashlib.sha256(password.encode()).hexdigest() == stored:
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
                elif Decimal(str(amount)) > st.session_state.balance:
                    st.error("Insufficient Balance!")
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
                    st.error("Invalid Nigerian network prefix.")
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
                if Decimal(str(amount)) > st.session_state.balance:
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
                query = "SELECT transaction_type as Transaction, amount as Amount, date as Date FROM transaction_record WHERE account_id = ? ORDER BY date DESC"
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
                query = "SELECT date as Date, description as Description, debit as Debit, credit as Credit, balance as Balance FROM ledger WHERE account_id = ? ORDER BY date DESC"
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

# --- Routing ---
if st.session_state.page == "home":
    show_home()
elif st.session_state.page == "signup":
    show_signup()
elif st.session_state.page == "signin":
    show_signin()
elif st.session_state.page == "dashboard":
    show_dashboard()

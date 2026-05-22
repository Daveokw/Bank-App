import sqlite3 as sql
from datetime import datetime
import os
import uuid

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bank_app.db")

def check_and_reset_db(st):
    """Checks if the DB is older than 24 hours. If so, deletes it and clears the user session."""
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

def init_db(st):
    """Initializes all tables and seeds the default subledgers and admin account."""
    if check_and_reset_db(st):
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
        pass # Better to silently fail in prod prototype if DB locked

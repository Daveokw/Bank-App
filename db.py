"""SQLite configuration and schema management for the banking prototype."""

from __future__ import annotations

import logging
import sqlite3 as sql
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt

DB_PATH = Path(__file__).resolve().with_name("bank_app.db")
RESET_INTERVAL = timedelta(hours=24)
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_USERNAME = "admin"

LOGGER = logging.getLogger(__name__)
_INIT_LOCK = threading.Lock()


class ClosingConnection(sql.Connection):
    """Commit or roll back a context block, then release its file handle."""

    def __exit__(self, exception_type, exception_value, traceback) -> bool:
        try:
            return super().__exit__(exception_type, exception_value, traceback)
        finally:
            self.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS phone (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    phone_number TEXT UNIQUE NOT NULL,
    FOREIGN KEY (customer_id) REFERENCES customer(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    account_no TEXT UNIQUE NOT NULL,
    balance REAL NOT NULL DEFAULT 0.00 CHECK (balance >= 0),
    FOREIGN KEY (customer_id) REFERENCES customer(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    transaction_type TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    idempotency_key TEXT UNIQUE,
    date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS transaction_header (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'COMMITTED', 'REVERSED')),
    idempotency_key TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    debit REAL NOT NULL DEFAULT 0.00 CHECK (debit >= 0),
    credit REAL NOT NULL DEFAULT 0.00 CHECK (credit >= 0),
    balance REAL NOT NULL CHECK (balance >= 0),
    date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE,
    CHECK (NOT (debit > 0 AND credit > 0))
);

CREATE TABLE IF NOT EXISTS bank_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no TEXT NOT NULL,
    account_name TEXT NOT NULL,
    debit REAL NOT NULL DEFAULT 0.00 CHECK (debit >= 0),
    credit REAL NOT NULL DEFAULT 0.00 CHECK (credit >= 0),
    related_account TEXT,
    description TEXT,
    tx_type TEXT,
    account_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ref_no) REFERENCES transaction_header(ref_no) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE SET NULL,
    CHECK ((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0))
);

CREATE TABLE IF NOT EXISTS customer_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    debit REAL NOT NULL DEFAULT 0.00 CHECK (debit >= 0),
    credit REAL NOT NULL DEFAULT 0.00 CHECK (credit >= 0),
    balance_after REAL NOT NULL CHECK (balance_after >= 0),
    description TEXT,
    tx_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS subledger_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_name TEXT UNIQUE NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    balance REAL NOT NULL DEFAULT 0.00,
    description TEXT
);

CREATE TABLE IF NOT EXISTS customer_subledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_no TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    subledger_account_id INTEGER NOT NULL,
    debit REAL NOT NULL DEFAULT 0.00 CHECK (debit >= 0),
    credit REAL NOT NULL DEFAULT 0.00 CHECK (credit >= 0),
    balance_after REAL NOT NULL,
    description TEXT,
    tx_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES account(id) ON DELETE CASCADE,
    FOREIGN KEY (subledger_account_id) REFERENCES subledger_account(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transaction_record_account_date
    ON transaction_record(account_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_ledger_account_date
    ON ledger(account_id, date DESC);
CREATE INDEX IF NOT EXISTS idx_bank_ledger_ref
    ON bank_ledger(ref_no);
CREATE INDEX IF NOT EXISTS idx_customer_subledger_account
    ON customer_subledger(account_id, subledger_account_id, id DESC);

DROP TRIGGER IF EXISTS validate_double_entry;

CREATE TRIGGER validate_double_entry
BEFORE UPDATE OF status ON transaction_header
WHEN NEW.status = 'COMMITTED'
BEGIN
    SELECT CASE
        WHEN (SELECT COUNT(*) FROM bank_ledger WHERE ref_no = NEW.ref_no) < 2
          OR ABS(COALESCE((
                SELECT ROUND(SUM(debit) - SUM(credit), 2)
                FROM bank_ledger
                WHERE ref_no = NEW.ref_no
            ), 0.00)) > 0.00
        THEN RAISE(ABORT, 'Ledger entries must contain balanced debits and credits')
    END;
END;
"""

SUBLEDGER_ACCOUNTS = (
    ("Cash", "asset", "Cash on hand and bank balances"),
    ("Customer_Deposits", "liability", "Customer demand deposits control account"),
    ("Interbank_Payables", "liability", "External transfer liabilities"),
    ("Airtime_Payable", "liability", "Airtime vendor payable"),
    ("Bills_Payable", "liability", "Bills vendor payable"),
    ("Equity", "equity", "Owners' equity"),
    ("Revenue", "revenue", "Operating revenue"),
    ("Income", "revenue", "Other income"),
    ("Expenses", "expense", "Operating expenses"),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_connection(db_path: str | Path | None = None) -> sql.Connection:
    """Return a configured SQLite connection with integrity checks enabled."""
    connection = sql.connect(
        str(db_path or DB_PATH), timeout=10, factory=ClosingConnection
    )
    connection.row_factory = sql.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def check_and_reset_db(db_path: str | Path | None = None) -> bool:
    """Return whether the demonstration database has exceeded its 24-hour lifetime."""
    path = Path(db_path or DB_PATH)
    if not path.exists():
        return False

    try:
        with get_connection(path) as connection:
            row = connection.execute(
                "SELECT value FROM system_config WHERE key = 'created_at'"
            ).fetchone()
        if not row:
            return False
        created_at = datetime.fromisoformat(row["value"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - created_at > RESET_INTERVAL
    except (sql.Error, ValueError):
        LOGGER.warning("Database age could not be determined", exc_info=True)
        return False


def _remove_database_files(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            LOGGER.exception("Could not remove expired database file %s", candidate.name)
            raise


def _seed_subledgers(connection: sql.Connection) -> None:
    connection.executemany(
        """
        INSERT INTO subledger_account (account_name, account_type, balance, description)
        VALUES (?, ?, 0.00, ?)
        ON CONFLICT(account_name) DO NOTHING
        """,
        SUBLEDGER_ACCOUNTS,
    )


def _configure_admin(connection: sql.Connection, admin_password: str | None) -> None:
    if not admin_password:
        return
    if len(admin_password) < 12 or len(admin_password.encode("utf-8")) > 72:
        raise ValueError("BANK_ADMIN_PASSWORD must contain between 12 and 72 bytes.")

    row = connection.execute(
        "SELECT id, password FROM customer WHERE username = ? OR email = ? LIMIT 1",
        (ADMIN_USERNAME, ADMIN_EMAIL),
    ).fetchone()
    if row:
        stored = row["password"] or ""
        uses_insecure_default = False
        if stored:
            try:
                uses_insecure_default = bcrypt.checkpw(
                    b"admin", stored.encode("utf-8")
                )
            except ValueError:
                LOGGER.warning("Replacing an invalid stored administrator password hash")
                uses_insecure_default = True
        if not stored or uses_insecure_default:
            password_hash = bcrypt.hashpw(
                admin_password.encode("utf-8"), bcrypt.gensalt()
            ).decode("utf-8")
            connection.execute(
                "UPDATE customer SET password = ? WHERE id = ?",
                (password_hash, row["id"]),
            )
        return

    password_hash = bcrypt.hashpw(
        admin_password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")
    cursor = connection.execute(
        "INSERT INTO customer (email, username, password) VALUES (?, ?, ?)",
        (ADMIN_EMAIL, ADMIN_USERNAME, password_hash),
    )
    admin_id = cursor.lastrowid
    account_cursor = connection.execute(
        "INSERT INTO account (customer_id, account_no, balance) VALUES (?, ?, 0.00)",
        (admin_id, "ADMIN0000001"),
    )
    connection.execute(
        """
        INSERT INTO ledger (account_id, description, debit, credit, balance, date)
        VALUES (?, 'Opening Balance', 0.00, 0.00, 0.00, ?)
        """,
        (account_cursor.lastrowid, utc_now()),
    )


def init_db(
    streamlit_module=None,
    *,
    db_path: str | Path | None = None,
    admin_password: str | None = None,
) -> bool:
    """Initialise the schema and return whether an expired demo database was reset."""
    path = Path(db_path or DB_PATH)
    reset = False

    with _INIT_LOCK:
        if check_and_reset_db(path):
            _remove_database_files(path)
            reset = True
            if streamlit_module is not None:
                streamlit_module.session_state.clear()

        with get_connection(path) as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                """
                INSERT INTO system_config (key, value)
                VALUES ('created_at', ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (utc_now(),),
            )
            _seed_subledgers(connection)
            _configure_admin(connection, admin_password)
            connection.commit()

    return reset

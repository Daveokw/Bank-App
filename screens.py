"""Streamlit views for the DAVE Bank demonstration application."""

from __future__ import annotations

import logging
import sqlite3 as sql
import time
import uuid
from decimal import Decimal

import bcrypt
import pandas as pd
import streamlit as st

from db import ADMIN_EMAIL, ADMIN_USERNAME, get_connection, utc_now
from engine import (
    exec_transaction,
    gen_account_no,
    validate_email,
    validate_nuban,
    validate_password,
    validate_phone,
    validate_username,
)

LOGGER = logging.getLogger(__name__)
NAIRA = "₦"
LOGIN_ATTEMPT_LIMIT = 5
LOGIN_LOCK_SECONDS = 30

NIGERIAN_BANKS = (
    "DAVE Bank",
    "Access Bank",
    "Citibank Nigeria",
    "Ecobank Nigeria",
    "Fidelity Bank",
    "First Bank of Nigeria",
    "First City Monument Bank (FCMB)",
    "Globus Bank",
    "Guaranty Trust Bank (GTBank)",
    "Heritage Bank",
    "Jaiz Bank",
    "Keystone Bank",
    "Kuda Bank",
    "Lotus Bank",
    "Moniepoint",
    "Mutual Trust Microfinance Bank",
    "Opay",
    "Palmpay",
    "Parallex Bank",
    "Polaris Bank",
    "PremiumTrust Bank",
    "Providus Bank",
    "Signature Bank",
    "Stanbic IBTC Bank",
    "Standard Chartered",
    "Sterling Bank",
    "SunTrust Bank",
    "TAJBank",
    "Titan Trust Bank",
    "Union Bank of Nigeria",
    "United Bank for Africa (UBA)",
    "Unity Bank",
    "Wema Bank",
    "Zenith Bank",
)


def navigate_to(page: str) -> None:
    st.session_state.page = page


def _currency(value) -> str:
    return f"{NAIRA}{Decimal(str(value or 0)):,.2f}"


def _new_idempotency_key() -> str:
    return str(uuid.uuid4())


def _is_admin() -> bool:
    return (
        st.session_state.username == ADMIN_USERNAME
        and str(st.session_state.email).casefold() == ADMIN_EMAIL
    )


def refresh_balance() -> bool:
    account_id = st.session_state.account_id
    if not account_id:
        return False
    with get_connection() as connection:
        row = connection.execute(
            "SELECT balance FROM account WHERE id = ?", (account_id,)
        ).fetchone()
    if not row:
        return False
    st.session_state.balance = Decimal(str(row["balance"]))
    return True


def show_home() -> None:
    st.title("DAVE Bank")
    st.subheader("A double-entry banking demonstration")
    st.write(
        "Explore account creation, deposits, withdrawals, transfers, airtime, "
        "bill payments, customer ledgers, and administrative reconciliation."
    )
    st.info(
        "Demonstration only: this application does not connect to real banks or process real money."
    )

    sign_in, sign_up = st.columns(2)
    with sign_in:
        st.button(
            "Sign in",
            type="primary",
            use_container_width=True,
            on_click=navigate_to,
            args=("signin",),
        )
    with sign_up:
        st.button(
            "Create an account",
            use_container_width=True,
            on_click=navigate_to,
            args=("signup",),
        )


def show_signup() -> None:
    st.title("Create an account")
    st.caption("All fields are required. Passwords must contain at least eight characters.")

    with st.form("signup_form"):
        email = st.text_input("Email address", max_chars=254)
        phone = st.text_input("Phone number", max_chars=11, help="Enter an 11-digit Nigerian mobile number.")
        username = st.text_input("Username", max_chars=30)
        password = st.text_input("Password", type="password", max_chars=72)
        submitted = st.form_submit_button("Create account", type="primary")

    if submitted:
        email = email.strip().casefold()
        phone = phone.strip()
        username = username.strip()
        if not all((email, phone, username, password)):
            st.error("Complete all fields.")
        elif not validate_email(email):
            st.error("Enter a valid email address.")
        elif not validate_phone(phone):
            st.error("Enter a valid 11-digit Nigerian mobile number.")
        elif not validate_username(username) or username.casefold() == ADMIN_USERNAME:
            st.error("Use 3–30 letters, numbers, dots, underscores, or hyphens for the username.")
        elif not validate_password(password):
            st.error("Use a password containing 8–72 bytes.")
        else:
            try:
                with get_connection() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    existing = connection.execute(
                        """
                        SELECT 1 FROM customer WHERE email = ? OR username = ?
                        UNION ALL
                        SELECT 1 FROM phone WHERE phone_number = ?
                        LIMIT 1
                        """,
                        (email, username, phone),
                    ).fetchone()
                    if existing:
                        st.error("An account already uses those details.")
                    else:
                        password_hash = bcrypt.hashpw(
                            password.encode("utf-8"), bcrypt.gensalt()
                        ).decode("utf-8")
                        cursor = connection.execute(
                            "INSERT INTO customer (email, username, password) VALUES (?, ?, ?)",
                            (email, username, password_hash),
                        )
                        customer_id = cursor.lastrowid
                        connection.execute(
                            "INSERT INTO phone (customer_id, phone_number) VALUES (?, ?)",
                            (customer_id, phone),
                        )
                        account_no = gen_account_no(customer_id)
                        account_cursor = connection.execute(
                            "INSERT INTO account (customer_id, account_no) VALUES (?, ?)",
                            (customer_id, account_no),
                        )
                        opening_reference = f"OPEN-{uuid.uuid4().hex[:8].upper()}"
                        timestamp = utc_now()
                        connection.execute(
                            """
                            INSERT INTO ledger (
                                account_id, description, debit, credit, balance, date
                            ) VALUES (?, 'Opening Balance', 0.00, 0.00, 0.00, ?)
                            """,
                            (account_cursor.lastrowid, timestamp),
                        )
                        connection.execute(
                            """
                            INSERT INTO customer_ledger (
                                ref_no, account_id, debit, credit, balance_after,
                                description, tx_type, created_at
                            ) VALUES (?, ?, 0.00, 0.00, 0.00, 'Opening balance', 'opening', ?)
                            """,
                            (opening_reference, account_cursor.lastrowid, timestamp),
                        )
                        connection.commit()
                        st.session_state.flash_message = (
                            f"Account created. Your account number is {account_no}."
                        )
                        navigate_to("signin")
                        st.rerun()
            except sql.Error:
                LOGGER.exception("Account creation failed")
                st.error("The account could not be created.")

    st.button("Back", on_click=navigate_to, args=("home",))


def _record_failed_login() -> None:
    attempts = int(st.session_state.get("login_attempts", 0)) + 1
    st.session_state.login_attempts = attempts
    if attempts >= LOGIN_ATTEMPT_LIMIT:
        st.session_state.login_locked_until = time.time() + LOGIN_LOCK_SECONDS
        st.session_state.login_attempts = 0


def show_signin() -> None:
    st.title("Sign in")
    locked_until = float(st.session_state.get("login_locked_until", 0))
    remaining = max(0, int(locked_until - time.time()))
    if remaining:
        st.warning(f"Too many attempts. Try again in {remaining} seconds.")

    with st.form("signin_form"):
        key = st.text_input("Email address or phone number")
        password = st.text_input("Password", type="password", max_chars=72)
        submitted = st.form_submit_button(
            "Sign in", type="primary", disabled=bool(remaining)
        )

    if submitted and not remaining:
        key = key.strip().casefold()
        if not key or not password:
            st.error("Enter your credentials.")
        else:
            try:
                with get_connection() as connection:
                    row = connection.execute(
                        """
                        SELECT
                            c.id AS customer_id, c.email, c.username, c.password,
                            a.id AS account_id, a.account_no, a.balance,
                            p.phone_number
                        FROM customer AS c
                        LEFT JOIN phone AS p ON p.customer_id = c.id
                        JOIN account AS a ON a.customer_id = c.id
                        WHERE LOWER(c.email) = ? OR p.phone_number = ?
                        LIMIT 1
                        """,
                        (key, key),
                    ).fetchone()

                admin_login = bool(
                    row
                    and row["username"] == ADMIN_USERNAME
                    and row["email"].casefold() == ADMIN_EMAIL
                )
                if admin_login and not st.session_state.admin_enabled:
                    st.error("Administrative access is not configured.")
                elif row and bcrypt.checkpw(
                    password.encode("utf-8"), row["password"].encode("utf-8")
                ):
                    st.session_state.update(
                        customer_id=row["customer_id"],
                        email=row["email"],
                        username=row["username"],
                        account_id=row["account_id"],
                        account_no=row["account_no"],
                        balance=Decimal(str(row["balance"])),
                        phone=row["phone_number"] or "",
                        login_attempts=0,
                        login_locked_until=0,
                    )
                    navigate_to("dashboard")
                    st.rerun()
                else:
                    _record_failed_login()
                    st.error("The credentials are incorrect.")
            except (sql.Error, ValueError):
                LOGGER.exception("Sign-in failed")
                st.error("Sign-in is temporarily unavailable.")

    st.button("Back", on_click=navigate_to, args=("home",))


def _set_dashboard_view(view: str) -> None:
    st.session_state.dash_view = view
    st.session_state.idempotency_key = _new_idempotency_key()


def _sign_out() -> None:
    st.session_state.clear()
    st.session_state.page = "home"


def _customer_options() -> dict[str, int]:
    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT a.id, a.account_no, c.username
            FROM account AS a
            JOIN customer AS c ON c.id = a.customer_id
            WHERE c.username <> ?
            ORDER BY c.username, a.account_no
            """,
            (ADMIN_USERNAME,),
        ).fetchall()
    return {f"{row['username']} — {row['account_no']}": row["id"] for row in rows}


def _show_admin_view(view: str) -> None:
    if view == "Trial Balance":
        with get_connection() as connection:
            frame = pd.read_sql_query(
                """
                SELECT account_name AS Account, SUM(debit) AS Debit, SUM(credit) AS Credit
                FROM bank_ledger
                GROUP BY account_name
                ORDER BY account_name
                """,
                connection,
            )
        total_debit = Decimal(str(frame["Debit"].sum() if not frame.empty else 0))
        total_credit = Decimal(str(frame["Credit"].sum() if not frame.empty else 0))
        debit_column, credit_column, difference_column = st.columns(3)
        debit_column.metric("Total debits", _currency(total_debit))
        credit_column.metric("Total credits", _currency(total_credit))
        difference_column.metric("Difference", _currency(total_debit - total_credit))
        if frame.empty:
            st.info("No committed transactions are available.")
        else:
            frame["Debit"] = frame["Debit"].map(_currency)
            frame["Credit"] = frame["Credit"].map(_currency)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        return

    if view == "Subledgers":
        with get_connection() as connection:
            frame = pd.read_sql_query(
                """
                SELECT account_name AS Name, account_type AS Type,
                       balance AS Balance, description AS Description
                FROM subledger_account
                ORDER BY account_type, account_name
                """,
                connection,
            )
        frame["Balance"] = frame["Balance"].map(_currency)
        st.dataframe(frame, use_container_width=True, hide_index=True)
        return

    options = _customer_options()
    if not options:
        st.info("No customer accounts are available.")
        return
    selected = st.selectbox("Customer account", tuple(options))
    account_id = options[selected]

    if view == "Customer Subledger":
        with get_connection() as connection:
            frame = pd.read_sql_query(
                """
                SELECT cs.created_at AS Date, sa.account_name AS Subledger,
                       cs.description AS Description, cs.debit AS Debit,
                       cs.credit AS Credit, cs.balance_after AS Balance
                FROM customer_subledger AS cs
                JOIN subledger_account AS sa ON sa.id = cs.subledger_account_id
                WHERE cs.account_id = ?
                ORDER BY cs.id DESC
                """,
                connection,
                params=(account_id,),
            )
        if frame.empty:
            st.info("No customer subledger entries are available.")
        else:
            for column in ("Debit", "Credit", "Balance"):
                frame[column] = frame[column].map(_currency)
            st.dataframe(frame, use_container_width=True, hide_index=True)
        return

    with get_connection() as connection:
        account = connection.execute(
            "SELECT balance FROM account WHERE id = ?", (account_id,)
        ).fetchone()
        control = connection.execute(
            """
            SELECT cs.balance_after
            FROM customer_subledger AS cs
            JOIN subledger_account AS sa ON sa.id = cs.subledger_account_id
            WHERE cs.account_id = ? AND sa.account_name = 'Customer_Deposits'
            ORDER BY cs.id DESC
            LIMIT 1
            """,
            (account_id,),
        ).fetchone()
    account_balance = Decimal(str(account["balance"] if account else 0))
    control_balance = Decimal(str(control["balance_after"] if control else 0))
    difference = account_balance - control_balance
    left, middle, right = st.columns(3)
    left.metric("Account balance", _currency(account_balance))
    middle.metric("Control balance", _currency(control_balance))
    right.metric("Difference", _currency(difference))
    if difference.quantize(Decimal("0.01")) == 0:
        st.success("The customer account reconciles with the deposits subledger.")
    else:
        st.error("The customer account does not reconcile with the deposits subledger.")


def _run_customer_transaction(
    transaction_type: str,
    amount,
    *,
    extra: dict | None = None,
) -> None:
    if exec_transaction(
        transaction_type,
        amount,
        extra=extra,
        idempotency_key=st.session_state.idempotency_key,
    ):
        st.session_state.idempotency_key = _new_idempotency_key()
        st.session_state.flash_message = f"{transaction_type} completed successfully."
        st.rerun()


def _show_customer_view(view: str) -> None:
    if view == "Check Balance":
        st.metric("Current balance", _currency(st.session_state.balance))
    elif view == "Deposit":
        with st.form("deposit_form", clear_on_submit=True):
            amount = st.number_input(f"Amount ({NAIRA})", min_value=1.0, step=100.0)
            submitted = st.form_submit_button("Deposit funds", type="primary")
        if submitted:
            _run_customer_transaction("Deposit", amount)
    elif view == "Withdraw":
        with st.form("withdraw_form", clear_on_submit=True):
            amount = st.number_input(f"Amount ({NAIRA})", min_value=1.0, step=100.0)
            submitted = st.form_submit_button("Withdraw funds", type="primary")
        if submitted:
            _run_customer_transaction("Withdrawal", amount)
    elif view == "Transfer":
        with st.form("transfer_form", clear_on_submit=True):
            bank = st.selectbox("Receiver's bank", NIGERIAN_BANKS)
            receiver_account = st.text_input("Receiver's account number", max_chars=10)
            amount = st.number_input(f"Amount ({NAIRA})", min_value=1.0, step=100.0)
            submitted = st.form_submit_button("Transfer funds", type="primary")
        if submitted:
            receiver_account = receiver_account.strip()
            if len(receiver_account) != 10 or not receiver_account.isdigit():
                st.error("Enter a valid 10-digit account number.")
            elif bank == "DAVE Bank" and not validate_nuban(receiver_account):
                st.error("Enter a valid DAVE Bank account number.")
            elif receiver_account == st.session_state.account_no:
                st.error("You cannot transfer to the same account.")
            else:
                _run_customer_transaction(
                    "Transfer",
                    amount,
                    extra={"receiver_bank": bank, "receiver_acct_no": receiver_account},
                )
    elif view == "Buy Airtime":
        with st.form("airtime_form", clear_on_submit=True):
            network = st.selectbox("Network", ("MTN", "Airtel", "Glo", "9mobile"))
            phone = st.text_input("Phone number", max_chars=11)
            amount = st.number_input(f"Amount ({NAIRA})", min_value=1.0, step=100.0)
            submitted = st.form_submit_button("Buy airtime", type="primary")
        if submitted:
            phone = phone.strip()
            if not validate_phone(phone):
                st.error("Enter a valid 11-digit Nigerian mobile number.")
            else:
                _run_customer_transaction(
                    "Buy Airtime", amount, extra={"phone": phone, "network": network}
                )
    elif view == "Pay Bills":
        with st.form("bills_form", clear_on_submit=True):
            bill = st.selectbox("Bill type", ("Electricity", "Internet", "Water", "Cable TV"))
            amount = st.number_input(f"Amount ({NAIRA})", min_value=1.0, step=100.0)
            submitted = st.form_submit_button("Pay bill", type="primary")
        if submitted:
            _run_customer_transaction("Pay Bills", amount, extra={"bill": bill})
    elif view == "Transaction History":
        with get_connection() as connection:
            frame = pd.read_sql_query(
                """
                SELECT transaction_type AS Transaction, amount AS Amount, date AS Date
                FROM transaction_record
                WHERE account_id = ?
                ORDER BY id DESC
                """,
                connection,
                params=(st.session_state.account_id,),
            )
        if frame.empty:
            st.info("No transactions are available.")
        else:
            frame["Amount"] = frame["Amount"].map(_currency)
            st.dataframe(frame, use_container_width=True, hide_index=True)
    elif view == "Customer Ledger":
        with get_connection() as connection:
            frame = pd.read_sql_query(
                """
                SELECT date AS Date, description AS Description, debit AS Debit,
                       credit AS Credit, balance AS Balance
                FROM ledger
                WHERE account_id = ?
                ORDER BY id DESC
                """,
                connection,
                params=(st.session_state.account_id,),
            )
        if frame.empty:
            st.info("No ledger entries are available.")
        else:
            for column in ("Debit", "Credit", "Balance"):
                frame[column] = frame[column].map(_currency)
            st.dataframe(frame, use_container_width=True, hide_index=True)


def show_dashboard() -> None:
    if not refresh_balance():
        st.session_state.clear()
        st.session_state.flash_message = "Your session expired. Please sign in again."
        st.session_state.page = "signin"
        st.rerun()

    is_admin = _is_admin()
    default_view = "Trial Balance" if is_admin else "Check Balance"
    st.session_state.setdefault("dash_view", default_view)
    st.session_state.setdefault("idempotency_key", _new_idempotency_key())

    st.sidebar.title(f"Welcome, {st.session_state.username}")
    if not is_admin:
        st.sidebar.caption(f"Account number: {st.session_state.account_no}")
        st.sidebar.metric("Balance", _currency(st.session_state.balance))
    st.sidebar.divider()

    views = (
        ("Trial Balance", "Subledgers", "Customer Subledger", "Reconcile Customer")
        if is_admin
        else (
            "Check Balance",
            "Deposit",
            "Withdraw",
            "Transfer",
            "Buy Airtime",
            "Pay Bills",
            "Transaction History",
            "Customer Ledger",
        )
    )
    for view in views:
        st.sidebar.button(
            view,
            key=f"nav_{view}",
            on_click=_set_dashboard_view,
            args=(view,),
            use_container_width=True,
        )

    st.sidebar.divider()
    st.sidebar.button("Sign out", on_click=_sign_out, use_container_width=True)

    view = st.session_state.dash_view
    st.title(view)
    try:
        if is_admin:
            _show_admin_view(view)
        else:
            _show_customer_view(view)
    except sql.Error:
        LOGGER.exception("Dashboard query failed for view %s", view)
        st.error("This view is temporarily unavailable.")

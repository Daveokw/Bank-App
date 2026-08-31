"""Validation and atomic transaction services for DAVE Bank."""

from __future__ import annotations

import logging
import re
import sqlite3 as sql
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

import streamlit as st

from db import DB_PATH, get_connection, utc_now

LOGGER = logging.getLogger(__name__)
MONEY_QUANTUM = Decimal("0.01")
MAX_TRANSACTION_AMOUNT = Decimal("1000000000.00")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
PHONE_PREFIXES = ("070", "080", "081", "090", "091")
SUPPORTED_TRANSACTION_TYPES = {
    "Deposit",
    "Withdrawal",
    "Transfer",
    "Buy Airtime",
    "Pay Bills",
}


class TransactionError(ValueError):
    """A safe, user-facing transaction failure."""


@dataclass(frozen=True)
class TransactionResult:
    balance: Decimal
    reference: str | None
    duplicate: bool = False


def validate_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(email.strip())) and len(email.strip()) <= 254


def validate_phone(phone: str) -> bool:
    value = phone.strip()
    return len(value) == 11 and value.isdigit() and value.startswith(PHONE_PREFIXES)


def validate_username(username: str) -> bool:
    return bool(USERNAME_PATTERN.fullmatch(username.strip()))


def validate_password(password: str) -> bool:
    encoded = password.encode("utf-8")
    return len(password) >= 8 and len(encoded) <= 72


def normalise_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise TransactionError("Enter a valid amount.") from None
    if not amount.is_finite() or amount <= 0 or amount > MAX_TRANSACTION_AMOUNT:
        raise TransactionError("Enter an amount within the permitted range.")
    return amount


def compute_new_subledger_balance(
    previous: Decimal,
    account_type: str,
    debit: Decimal,
    credit: Decimal,
) -> Decimal:
    if account_type in ("asset", "expense"):
        return previous + debit - credit
    return previous + credit - debit


def calculate_nuban_check_digit(bank_code: str, branch_code: str, serial: str) -> str:
    payload = bank_code.zfill(3) + branch_code.zfill(3) + serial.zfill(9)
    weights = (3, 7, 3, 3, 7, 3, 3, 7, 3, 3, 7, 3, 3, 7, 3)
    total = sum(int(digit) * weight for digit, weight in zip(payload, weights))
    remainder = total % 10
    return str(10 - remainder if remainder else 0)


def gen_account_no(user_id: int) -> str:
    bank_code, branch_code = "011", "000"
    serial = str(user_id % 1_000_000_000).zfill(9)
    return serial + calculate_nuban_check_digit(bank_code, branch_code, serial)


def validate_nuban(account_no: str, bank_code: str = "011", branch_code: str = "000") -> bool:
    if len(account_no) != 10 or not account_no.isdigit():
        return False
    return account_no[9] == calculate_nuban_check_digit(
        bank_code, branch_code, account_no[:9]
    )


def _new_reference() -> str:
    return "JNL-" + uuid.uuid4().hex[:12].upper()


def _money_float(value: Decimal) -> float:
    return float(value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP))


def _record_double_entry(
    cursor: sql.Cursor,
    entries: list[dict],
    *,
    description: str,
    transaction_type: str,
    idempotency_key: str | None,
) -> str:
    if len(entries) < 2:
        raise TransactionError("A transaction requires at least two ledger entries.")

    reference = _new_reference()
    timestamp = utc_now()
    cursor.execute(
        """
        INSERT INTO transaction_header (ref_no, status, idempotency_key, created_at)
        VALUES (?, 'PENDING', ?, ?)
        """,
        (reference, idempotency_key, timestamp),
    )

    for entry in entries:
        debit = normalise_amount(entry["debit"]) if entry.get("debit") else Decimal("0.00")
        credit = normalise_amount(entry["credit"]) if entry.get("credit") else Decimal("0.00")
        if (debit > 0) == (credit > 0):
            raise TransactionError("Each ledger entry must contain one debit or one credit.")

        account_id = entry.get("account_id")
        cursor.execute(
            """
            INSERT INTO bank_ledger (
                ref_no, account_name, debit, credit, related_account,
                description, tx_type, account_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference,
                entry["account_name"],
                _money_float(debit),
                _money_float(credit),
                entry.get("related"),
                description,
                transaction_type,
                account_id,
                timestamp,
            ),
        )

        if account_id is not None:
            account_row = cursor.execute(
                "SELECT balance FROM account WHERE id = ?", (account_id,)
            ).fetchone()
            if not account_row:
                raise TransactionError("A related account could not be found.")
            cursor.execute(
                """
                INSERT INTO customer_ledger (
                    ref_no, account_id, debit, credit, balance_after,
                    description, tx_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference,
                    account_id,
                    _money_float(debit),
                    _money_float(credit),
                    account_row["balance"],
                    description,
                    transaction_type,
                    timestamp,
                ),
            )

        subledger = cursor.execute(
            """
            SELECT id, account_type, balance
            FROM subledger_account
            WHERE account_name = ?
            """,
            (entry["account_name"],),
        ).fetchone()
        if not subledger:
            raise TransactionError("A required subledger account is missing.")

        new_subledger_balance = compute_new_subledger_balance(
            Decimal(str(subledger["balance"])),
            subledger["account_type"],
            debit,
            credit,
        ).quantize(MONEY_QUANTUM)
        cursor.execute(
            "UPDATE subledger_account SET balance = ? WHERE id = ?",
            (_money_float(new_subledger_balance), subledger["id"]),
        )

        if account_id is not None:
            latest = cursor.execute(
                """
                SELECT balance_after
                FROM customer_subledger
                WHERE account_id = ? AND subledger_account_id = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (account_id, subledger["id"]),
            ).fetchone()
            previous = Decimal(str(latest["balance_after"])) if latest else Decimal("0.00")
            customer_balance = compute_new_subledger_balance(
                previous, subledger["account_type"], debit, credit
            ).quantize(MONEY_QUANTUM)
            cursor.execute(
                """
                INSERT INTO customer_subledger (
                    ref_no, account_id, subledger_account_id, debit, credit,
                    balance_after, description, tx_type, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference,
                    account_id,
                    subledger["id"],
                    _money_float(debit),
                    _money_float(credit),
                    _money_float(customer_balance),
                    description,
                    transaction_type,
                    timestamp,
                ),
            )

    cursor.execute(
        "UPDATE transaction_header SET status = 'COMMITTED' WHERE ref_no = ?",
        (reference,),
    )
    return reference


def execute_transaction(
    *,
    account_id: int,
    account_no: str,
    transaction_type: str,
    amount,
    extra: dict | None = None,
    idempotency_key: str | None = None,
    db_path: str | Path | None = None,
) -> TransactionResult:
    """Execute one atomic transaction without depending on Streamlit state."""
    if transaction_type not in SUPPORTED_TRANSACTION_TYPES:
        raise TransactionError("Unsupported transaction type.")
    amount_decimal = normalise_amount(amount)
    extra = dict(extra or {})

    try:
        with get_connection(db_path or DB_PATH) as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.cursor()

            if idempotency_key:
                duplicate = cursor.execute(
                    "SELECT id FROM transaction_record WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if duplicate:
                    row = cursor.execute(
                        "SELECT balance FROM account WHERE id = ?", (account_id,)
                    ).fetchone()
                    if not row:
                        raise TransactionError("Account not found.")
                    return TransactionResult(
                        Decimal(str(row["balance"])).quantize(MONEY_QUANTUM),
                        None,
                        True,
                    )

            sender = cursor.execute(
                "SELECT balance FROM account WHERE id = ?", (account_id,)
            ).fetchone()
            if not sender:
                raise TransactionError("Account not found.")
            current_balance = Decimal(str(sender["balance"])).quantize(MONEY_QUANTUM)

            if transaction_type == "Deposit":
                new_balance = current_balance + amount_decimal
            else:
                new_balance = current_balance - amount_decimal
                if new_balance < 0:
                    raise TransactionError("Insufficient balance.")

            receiver_id = None
            receiver_account_no = str(extra.get("receiver_acct_no") or "")
            receiver_bank = str(extra.get("receiver_bank") or "")
            internal_transfer = (
                transaction_type == "Transfer"
                and receiver_bank.casefold() in {"dave bank", "dave"}
            )

            if transaction_type == "Transfer" and not receiver_account_no:
                raise TransactionError("Enter a receiver account number.")
            if internal_transfer:
                receiver = cursor.execute(
                    "SELECT id, balance FROM account WHERE account_no = ?",
                    (receiver_account_no,),
                ).fetchone()
                if not receiver:
                    raise TransactionError("Receiver account not found.")
                receiver_id = receiver["id"]
                if receiver_id == account_id:
                    raise TransactionError("You cannot transfer to the same account.")
                receiver_balance = Decimal(str(receiver["balance"])).quantize(MONEY_QUANTUM)
                cursor.execute(
                    "UPDATE account SET balance = ? WHERE id = ?",
                    (_money_float(receiver_balance + amount_decimal), receiver_id),
                )
                cursor.execute(
                    """
                    INSERT INTO transaction_record (
                        account_id, transaction_type, amount, date
                    ) VALUES (?, 'Transfer In', ?, ?)
                    """,
                    (receiver_id, _money_float(amount_decimal), utc_now()),
                )
                cursor.execute(
                    """
                    INSERT INTO ledger (
                        account_id, description, debit, credit, balance, date
                    ) VALUES (?, 'Transfer In', 0.00, ?, ?, ?)
                    """,
                    (
                        receiver_id,
                        _money_float(amount_decimal),
                        _money_float(receiver_balance + amount_decimal),
                        utc_now(),
                    ),
                )

            cursor.execute(
                "UPDATE account SET balance = ? WHERE id = ?",
                (_money_float(new_balance), account_id),
            )
            cursor.execute(
                """
                INSERT INTO transaction_record (
                    account_id, transaction_type, amount, idempotency_key, date
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    transaction_type,
                    _money_float(amount_decimal),
                    idempotency_key,
                    utc_now(),
                ),
            )

            debit = amount_decimal if transaction_type != "Deposit" else Decimal("0.00")
            credit = amount_decimal if transaction_type == "Deposit" else Decimal("0.00")
            cursor.execute(
                """
                INSERT INTO ledger (
                    account_id, description, debit, credit, balance, date
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    account_id,
                    transaction_type,
                    _money_float(debit),
                    _money_float(credit),
                    _money_float(new_balance),
                    utc_now(),
                ),
            )

            if transaction_type == "Deposit":
                entries = [
                    {"account_name": "Cash", "debit": amount_decimal, "credit": 0, "related": f"Cash deposit by {account_no}", "account_id": None},
                    {"account_name": "Customer_Deposits", "debit": 0, "credit": amount_decimal, "related": f"Deposit to {account_no}", "account_id": account_id},
                ]
            elif transaction_type == "Withdrawal":
                entries = [
                    {"account_name": "Customer_Deposits", "debit": amount_decimal, "credit": 0, "related": f"Withdrawal by {account_no}", "account_id": account_id},
                    {"account_name": "Cash", "debit": 0, "credit": amount_decimal, "related": f"Cash paid to {account_no}", "account_id": None},
                ]
            elif transaction_type == "Transfer" and receiver_id is not None:
                entries = [
                    {"account_name": "Customer_Deposits", "debit": amount_decimal, "credit": 0, "related": f"Transfer from {account_no}", "account_id": account_id},
                    {"account_name": "Customer_Deposits", "debit": 0, "credit": amount_decimal, "related": f"Transfer to {receiver_account_no}", "account_id": receiver_id},
                ]
            elif transaction_type == "Transfer":
                entries = [
                    {"account_name": "Customer_Deposits", "debit": amount_decimal, "credit": 0, "related": f"External transfer to {receiver_bank} {receiver_account_no}", "account_id": account_id},
                    {"account_name": "Interbank_Payables", "debit": 0, "credit": amount_decimal, "related": f"External transfer from {account_no}", "account_id": account_id},
                ]
            elif transaction_type == "Buy Airtime":
                phone = extra.get("phone")
                entries = [
                    {"account_name": "Customer_Deposits", "debit": amount_decimal, "credit": 0, "related": f"Airtime for {phone}", "account_id": account_id},
                    {"account_name": "Airtime_Payable", "debit": 0, "credit": amount_decimal, "related": f"Airtime for {phone}", "account_id": account_id},
                ]
            else:
                bill = extra.get("bill")
                entries = [
                    {"account_name": "Customer_Deposits", "debit": amount_decimal, "credit": 0, "related": f"Bill payment: {bill}", "account_id": account_id},
                    {"account_name": "Bills_Payable", "debit": 0, "credit": amount_decimal, "related": f"Bill payment: {bill}", "account_id": account_id},
                ]

            reference = _record_double_entry(
                cursor,
                entries,
                description=transaction_type,
                transaction_type=transaction_type.lower().replace(" ", "_"),
                idempotency_key=idempotency_key,
            )
            connection.commit()
            LOGGER.info("transaction.committed ref=%s type=%s", reference, transaction_type)
            return TransactionResult(new_balance.quantize(MONEY_QUANTUM), reference)
    except TransactionError:
        raise
    except sql.Error as error:
        LOGGER.exception("transaction.database_failure type=%s", transaction_type)
        raise TransactionError("The transaction could not be completed.") from error


def exec_transaction(transaction_type, amount, extra=None, idempotency_key=None) -> bool:
    """Streamlit compatibility wrapper around the transaction service."""
    try:
        result = execute_transaction(
            account_id=st.session_state.account_id,
            account_no=st.session_state.account_no,
            transaction_type=transaction_type,
            amount=amount,
            extra=extra,
            idempotency_key=idempotency_key,
        )
        st.session_state.balance = result.balance
        return True
    except TransactionError as error:
        st.error(str(error))
        return False

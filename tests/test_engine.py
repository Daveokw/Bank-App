from __future__ import annotations

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from db import get_connection, init_db, utc_now
from engine import TransactionError, execute_transaction


class TransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temporary_directory.name) / "test.db"
        init_db(db_path=self.db_path)
        self.sender_id, self.sender_account = self._create_account(
            "sender@example.com", "sender", "08012345678"
        )
        self.receiver_id, self.receiver_account = self._create_account(
            "receiver@example.com", "receiver", "08112345678"
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _create_account(
        self, email: str, username: str, phone_number: str
    ) -> tuple[int, str]:
        with get_connection(self.db_path) as connection:
            customer = connection.execute(
                "INSERT INTO customer (email, username, password) VALUES (?, ?, ?)",
                (email, username, "test-only-hash"),
            )
            customer_id = customer.lastrowid
            connection.execute(
                "INSERT INTO phone (customer_id, phone_number) VALUES (?, ?)",
                (customer_id, phone_number),
            )
            account_number = f"{customer_id:010d}"
            account = connection.execute(
                "INSERT INTO account (customer_id, account_no) VALUES (?, ?)",
                (customer_id, account_number),
            )
            connection.commit()
            return account.lastrowid, account_number

    def _balance(self, account_id: int) -> Decimal:
        with get_connection(self.db_path) as connection:
            row = connection.execute(
                "SELECT balance FROM account WHERE id = ?", (account_id,)
            ).fetchone()
        return Decimal(str(row["balance"])).quantize(Decimal("0.01"))

    def test_deposit_and_internal_transfer_are_atomic_and_balanced(self) -> None:
        deposit = execute_transaction(
            account_id=self.sender_id,
            account_no=self.sender_account,
            transaction_type="Deposit",
            amount="100.00",
            idempotency_key="deposit-1",
            db_path=self.db_path,
        )
        transfer = execute_transaction(
            account_id=self.sender_id,
            account_no=self.sender_account,
            transaction_type="Transfer",
            amount="25.00",
            extra={
                "receiver_bank": "DAVE Bank",
                "receiver_acct_no": self.receiver_account,
            },
            idempotency_key="transfer-1",
            db_path=self.db_path,
        )

        self.assertEqual(deposit.balance, Decimal("100.00"))
        self.assertEqual(transfer.balance, Decimal("75.00"))
        self.assertEqual(self._balance(self.sender_id), Decimal("75.00"))
        self.assertEqual(self._balance(self.receiver_id), Decimal("25.00"))

        with get_connection(self.db_path) as connection:
            totals = connection.execute(
                """
                SELECT ROUND(SUM(debit), 2) AS debit, ROUND(SUM(credit), 2) AS credit
                FROM bank_ledger
                WHERE ref_no = ?
                """,
                (transfer.reference,),
            ).fetchone()
            mappings = connection.execute(
                """
                SELECT account_id, debit, credit
                FROM bank_ledger
                WHERE ref_no = ? AND account_name = 'Customer_Deposits'
                ORDER BY account_id
                """,
                (transfer.reference,),
            ).fetchall()

        self.assertEqual(totals["debit"], totals["credit"])
        self.assertEqual(
            [(row["account_id"], row["debit"], row["credit"]) for row in mappings],
            [(self.sender_id, 25.0, 0.0), (self.receiver_id, 0.0, 25.0)],
        )

    def test_idempotency_key_prevents_duplicate_processing(self) -> None:
        details = {
            "account_id": self.sender_id,
            "account_no": self.sender_account,
            "transaction_type": "Deposit",
            "amount": "20.00",
            "idempotency_key": "same-request",
            "db_path": self.db_path,
        }
        first = execute_transaction(**details)
        second = execute_transaction(**details)

        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(self._balance(self.sender_id), Decimal("20.00"))
        with get_connection(self.db_path) as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS total FROM transaction_record"
            ).fetchone()["total"]
        self.assertEqual(count, 1)

    def test_insufficient_funds_roll_back_every_record(self) -> None:
        with self.assertRaisesRegex(TransactionError, "Insufficient balance"):
            execute_transaction(
                account_id=self.sender_id,
                account_no=self.sender_account,
                transaction_type="Withdrawal",
                amount="1.00",
                db_path=self.db_path,
            )

        self.assertEqual(self._balance(self.sender_id), Decimal("0.00"))
        with get_connection(self.db_path) as connection:
            counts = [
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("transaction_record", "bank_ledger", "customer_ledger")
            ]
        self.assertEqual(counts, [0, 0, 0])

    def test_database_rejects_an_unbalanced_journal(self) -> None:
        with get_connection(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO transaction_header (ref_no, status, created_at)
                VALUES ('BAD-JOURNAL', 'PENDING', ?)
                """,
                (utc_now(),),
            )
            connection.execute(
                """
                INSERT INTO bank_ledger (
                    ref_no, account_name, debit, credit, created_at
                ) VALUES ('BAD-JOURNAL', 'Cash', 10.00, 0.00, ?)
                """,
                (utc_now(),),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE transaction_header SET status = 'COMMITTED' WHERE ref_no = 'BAD-JOURNAL'"
                )


if __name__ == "__main__":
    unittest.main()

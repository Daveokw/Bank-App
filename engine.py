import sqlite3 as sql
from datetime import datetime
import uuid
from decimal import Decimal
import streamlit as st
import re
import logging
from db import DB_PATH

logging.basicConfig(
    filename='bank_app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

def validate_nuban(account_no: str, bank_code="011", branch_code="000") -> bool:
    """Strictly validates if a 10-digit NUBAN matches the mathematical check digit rule."""
    if len(account_no) != 10 or not account_no.isdigit():
        return False
    serial = account_no[:9]
    check_digit = account_no[9]
    expected_check_digit = calculate_nuban_check_digit(bank_code, branch_code, serial)
    return check_digit == expected_check_digit

def _new_ref():
    return 'JNL-' + uuid.uuid4().hex[:12]

def record_double_entry(entries, description='', tx_type='', idempotency_key=None):
    if not isinstance(entries, list) or len(entries) < 2: return
    ref = _new_ref()
    logger.info(f"Starting transaction {ref} (Type: {tx_type})")
    try:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            
            # 1. State Machine: PENDING
            cur.execute("INSERT INTO transaction_header (ref_no, status, idempotency_key) VALUES (?, ?, ?)",
                        (ref, 'PENDING', idempotency_key))
            for line in entries:
                acct = line.get('account_name')
                debit = float(line.get('debit') or 0.00)
                credit = float(line.get('credit') or 0.00)
                related = line.get('related')
                acct_id = line.get('account_id', None)
                cur.execute('''INSERT INTO bank_ledger (ref_no, account_name, debit, credit, related_account, description, tx_type, account_id, created_at)
                               VALUES (?,?,?,?,?,?,?,?,?)''',
                            (ref, acct, debit, credit, related, description, tx_type, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
            # 2. State Machine: COMMITTED (Fires SQLite Validation Trigger)
            cur.execute("UPDATE transaction_header SET status = 'COMMITTED' WHERE ref_no = ?", (ref,))
            conn.commit()
            logger.info(f"Transaction {ref} COMMITTED successfully.")
    except sql.IntegrityError as e:
        logger.error(f"Idempotency or Integrity Error on {ref}: {e}")
        raise e
    except sql.Error as e:
        logger.critical(f"Transaction {ref} FAILED. Error: {e}. State rolling back.")
        try:
            with sql.connect(DB_PATH) as conn2:
                cur2 = conn2.cursor()
                cur2.execute("UPDATE transaction_header SET status = 'REVERSED' WHERE ref_no = ?", (ref,))
                conn2.commit()
        except Exception:
            pass
        raise e

def exec_transaction(t_type, amount, extra=None, idempotency_key=None):
    amount_dec = Decimal(str(amount))
    if amount_dec <= 0:
        st.error("Amount must be greater than zero.")
        return False
        
    try:
        with sql.connect(DB_PATH) as conn:
            cur = conn.cursor()
            
            # Idempotency check
            if idempotency_key:
                cur.execute("SELECT id FROM transaction_record WHERE idempotency_key=?", (idempotency_key,))
                if cur.fetchone():
                    logger.warning(f"Idempotency key {idempotency_key} already processed. Ignoring duplicate.")
                    return True
            
            new_bal = st.session_state.balance
            cur.execute("UPDATE account SET balance=? WHERE id=?", (float(new_bal), st.session_state.account_id))
            cur.execute("INSERT INTO transaction_record (account_id,transaction_type,amount,idempotency_key,date) VALUES (?,?,?,?,?)", 
                        (st.session_state.account_id, t_type, float(amount_dec), idempotency_key, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
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

        record_double_entry(entries, description=description, tx_type=tx_type, idempotency_key=idempotency_key)
        return True
    except sql.Error as e:
        st.error(f"DB Error: {e}")
        return False

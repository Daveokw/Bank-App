from __future__ import annotations

import unittest
from decimal import Decimal

from engine import (
    TransactionError,
    gen_account_no,
    normalise_amount,
    validate_email,
    validate_nuban,
    validate_password,
    validate_phone,
    validate_username,
)


class ValidationTests(unittest.TestCase):
    def test_identity_fields(self) -> None:
        self.assertTrue(validate_email("person@example.com"))
        self.assertFalse(validate_email("person-at-example"))
        self.assertTrue(validate_phone("08012345678"))
        self.assertFalse(validate_phone("12345"))
        self.assertTrue(validate_username("dave.bank"))
        self.assertFalse(validate_username("no spaces allowed"))

    def test_password_uses_bcrypt_byte_limit(self) -> None:
        self.assertTrue(validate_password("reliable-password"))
        self.assertFalse(validate_password("short"))
        self.assertFalse(validate_password("é" * 40))

    def test_amount_is_rounded_to_two_decimal_places(self) -> None:
        self.assertEqual(normalise_amount("12.345"), Decimal("12.35"))
        for invalid in ("0", "-1", "not-a-number", "Infinity"):
            with self.subTest(invalid=invalid), self.assertRaises(TransactionError):
                normalise_amount(invalid)

    def test_generated_account_number_passes_check_digit_validation(self) -> None:
        for customer_id in (1, 42, 999_999_999):
            with self.subTest(customer_id=customer_id):
                self.assertTrue(validate_nuban(gen_account_no(customer_id)))


if __name__ == "__main__":
    unittest.main()

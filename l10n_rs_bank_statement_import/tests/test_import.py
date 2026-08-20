# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Odoo integration tests for the import wizard glue.

Guarded so plain pytest (without Odoo installed) skips this module instead
of failing at collection time.  Under Odoo's own test runner the tests run
normally (tagged post_install)."""

import unittest

try:
    from odoo.tests import tagged
    from odoo.tests.common import TransactionCase

    HAS_ODOO = True
except ImportError:  # plain pytest without Odoo
    HAS_ODOO = False
    TransactionCase = unittest.TestCase

    def tagged(*args, **kwargs):  # noqa: D103
        def decorator(cls):
            return cls

        return decorator

import base64
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@tagged("post_install", "-at_install")
@unittest.skipUnless(HAS_ODOO, "Odoo is not installed")
class TestSerbianStatementImport(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_rsd = cls.env.ref("base.RSD")
        cls.currency_rsd.active = True
        cls.partner_bank = cls.env["res.partner.bank"].create(
            {
                "acc_number": "205-0000000108040-45",
                "partner_id": cls.env.company.partner_id.id,
            }
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Halcom test bank",
                "type": "bank",
                "code": "HALC",
                "currency_id": cls.currency_rsd.id,
                "bank_account_id": cls.partner_bank.id,
            }
        )

    def _import(self, data, filename):
        wizard = (
            self.env["account.statement.import"]
            .with_context(journal_id=self.journal.id)
            .create(
                {
                    "statement_file": base64.b64encode(data),
                    "statement_filename": filename,
                }
            )
        )
        return wizard._import_file()

    def test_import_halcom_zip(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr(
                "HalcomIZVOD.txt",
                (FIXTURES / "halcom" / "HalcomIZVOD.txt").read_bytes(),
            )
            zf.writestr(
                "HalcomIZVOD_cov.txt",
                (FIXTURES / "halcom" / "HalcomIZVOD_cov.txt").read_bytes(),
            )
        result = self._import(buf.getvalue(), "izvod_247.zip")
        self.assertEqual(len(result["statement_ids"]), 1)
        statement = self.env["account.bank.statement"].browse(
            result["statement_ids"][0]
        )
        self.assertEqual(statement.name, "247")
        self.assertEqual(len(statement.line_ids), 6)
        self.assertAlmostEqual(statement.balance_start, 3064406.45, places=2)
        self.assertAlmostEqual(statement.balance_end_real, 3102049.00, places=2)
        self.assertAlmostEqual(
            sum(statement.line_ids.mapped("amount")), 37642.55, places=2
        )

    def test_reimport_is_deduplicated(self):
        from odoo.exceptions import UserError

        data = (FIXTURES / "halcom" / "HalcomIZVOD.txt").read_bytes()
        self._import(data, "izvod.txt")
        with self.assertRaises(UserError):
            # every transaction already imported -> wizard reports it
            self._import(data, "izvod.txt")

    def test_unknown_format_falls_through_to_oca_chain(self):
        from odoo.exceptions import UserError

        with self.assertRaises(UserError):
            self._import(b"definitely not a bank statement", "junk.txt")

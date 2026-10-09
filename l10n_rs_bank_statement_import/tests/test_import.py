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
    from odoo.tools.binary import BinaryBytes

    HAS_ODOO = True
except ImportError:  # plain pytest without Odoo
    HAS_ODOO = False
    TransactionCase = unittest.TestCase

    def tagged(*args, **kwargs):  # noqa: D103
        def decorator(cls):
            return cls

        return decorator

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
                "account_number": "205-0000000108040-45",
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
                    "statement_file": BinaryBytes(data),
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

    def test_import_alta_xls(self):
        import io

        import xlwt

        output = io.BytesIO()
        workbook = xlwt.Workbook()
        sheet = workbook.add_sheet("Sheet1")
        sheet.write(2, 7, "IZVOD BROJ 42")
        sheet.write(7, 1, "BROJ IZVODA        :\nStatement No.")
        sheet.write(7, 3, "42")
        sheet.write(7, 12, "Prethodno stanje        :\nPrevious Balance")
        sheet.write(7, 21, "100.00")
        sheet.write(9, 1, "BROJ RAČUNA    :\nAccount No.")
        sheet.write(9, 3, "205000000010804045")
        sheet.write(15, 1, "ZA PERIOD            :\nFor the period")
        sheet.write(15, 3, "07.08.2026")
        sheet.write(15, 12, "Novo stanje            :\nNew Balance")
        sheet.write(15, 21, "75.00")
        sheet.write(32, 1, "1\n07.08.2026\n07.08.2026")
        sheet.write(32, 2, "87000119900001")
        sheet.write(32, 5, "Plaćanje dobavljaču")
        sheet.write(32, 9, "DOBAVLJAČ DOO\nBeograd\n160000000000000001")
        sheet.write(32, 16, "221\n97-42")
        sheet.write(32, 22, "25.00")
        sheet.write(32, 26, "0,00")
        workbook.save(output)

        result = self._import(output.getvalue(), "alta-42.xls")
        statement = self.env["account.bank.statement"].browse(
            result["statement_ids"][0]
        )
        self.assertEqual(statement.name, "42")
        self.assertEqual(len(statement.line_ids), 1)
        self.assertEqual(statement.line_ids.amount, -25.0)
        self.assertTrue(
            statement.line_ids.unique_import_id.endswith("-87000119900001")
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

    def test_journal_registers_the_oca_import_source(self):
        """The wizard writes ``file_import_oca`` onto the journal, so that
        value must actually be part of the field's selection."""
        selection = (
            self.env["account.journal"]
            .fields_get(["bank_statements_source"])["bank_statements_source"]["selection"]
        )
        self.assertIn("file_import_oca", [key for key, _label in selection])

        data = (FIXTURES / "halcom" / "HalcomIZVOD.txt").read_bytes()
        self._import(data, "izvod.txt")
        self.assertEqual(self.journal.bank_statements_source, "file_import_oca")

    def test_import_menu_is_available_under_invoicing(self):
        menu = self.env.ref(
            "account_statement_import_file.account_statement_import_menu"
        )
        self.assertEqual(menu.parent_id, self.env.ref("account.menu_finance"))
        admin = self.env.ref("base.user_admin")
        self.assertTrue(
            self.env["account.statement.import"].with_user(admin).has_access("create")
        )
        self.assertIn(
            menu.id, self.env["ir.ui.menu"].with_user(admin)._visible_menu_ids()
        )

    def test_bank_accounts_menu_is_available_to_invoicing_admin(self):
        menu = self.env.ref(
            "l10n_rs_bank_statement_import.menu_bank_accounts"
        )
        self.assertEqual(
            menu.parent_id,
            self.env.ref("l10n_rs_bank_statement_import.menu_bank"),
        )
        self.assertEqual(
            menu.action,
            self.env.ref("base.action_res_partner_bank_account_form"),
        )
        admin = self.env.ref("base.user_admin")
        self.assertTrue(
            self.env["res.partner.bank"].with_user(admin).has_access("create")
        )
        self.assertIn(
            menu.id, self.env["ir.ui.menu"].with_user(admin)._visible_menu_ids()
        )

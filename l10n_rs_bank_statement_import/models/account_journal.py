# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

from odoo import models


class AccountJournal(models.Model):
    _inherit = "account.journal"

    def _get_bank_statements_available_import_formats(self):
        """Register our formats so ``account_statement_import_file`` adds the
        ``file_import_oca`` option to ``bank_statements_source``.

        The OCA base only inserts that selection value when this hook returns
        a non-empty list, while the import wizard writes it onto the journal
        unconditionally — without this override the journal would end up
        storing a value missing from its own selection.
        """
        res = super()._get_bank_statements_available_import_formats()
        res += ["Halcom TXT", "Asseco XML", "ROL XML"]
        return res

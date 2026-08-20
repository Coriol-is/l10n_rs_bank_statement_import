# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import logging

from odoo import models
from odoo.exceptions import UserError

from ..parsers import (
    StatementParseError,
    UnsupportedFormat,
    UnsupportedVariant,
    parse_any,
)

logger = logging.getLogger(__name__)


class AccountStatementImport(models.TransientModel):
    _inherit = "account.statement.import"

    def _parse_file(self, data_file):
        """Sniff and parse Serbian bank statement formats.

        Supported: Halcom Hal E-Bank fixed-width txt (+ optional ``_cov``
        recap, also as a ZIP pair), the Halcom extended ``#``-delimited
        variant, Asseco OfficeBanking / FX Client XML (``stmtrs`` /
        ``pmtnotification``) and ROL XML (Raiffeisen OnLine / OTP).

        Falls back to ``super()`` (the OCA chain of responsibility) when the
        file is none of these.
        """
        try:
            statements = parse_any(data_file, filename=self.statement_filename)
        except UnsupportedVariant as exc:
            raise UserError(
                self.env._(
                    "Serbian bank statement import: %(message)s", message=str(exc)
                )
            ) from exc
        except UnsupportedFormat:
            return super()._parse_file(data_file)
        except StatementParseError as exc:
            raise UserError(
                self.env._(
                    "This file looks like a Serbian bank statement but could "
                    "not be parsed: %(message)s",
                    message=str(exc),
                )
            ) from exc
        logger.info(
            "Serbian bank statement import: parsed %d statement(s) from %s",
            len(statements),
            self.statement_filename,
        )
        return self._l10n_rs_to_import_vals(statements)

    def _l10n_rs_to_import_vals(self, statements):
        """Convert parser Statement objects into the (currency,
        account_number, stmts_vals) triplets the OCA wizard expects,
        grouping statements of the same account/currency."""
        grouped = {}  # (currency, account) -> list of statement vals
        for statement in statements:
            key = (statement.currency, statement.account_number)
            grouped.setdefault(key, []).append(
                self._l10n_rs_statement_vals(statement)
            )
        return [
            (currency, account_number, stmts_vals)
            for (currency, account_number), stmts_vals in grouped.items()
        ]

    def _l10n_rs_statement_vals(self, statement):
        vals = {
            "name": statement.name,
            "date": statement.date,
            "transactions": [
                self._l10n_rs_transaction_vals(trx)
                for trx in statement.transactions
            ],
        }
        if statement.balance_start is not None:
            vals["balance_start"] = float(statement.balance_start)
        if statement.balance_end is not None:
            vals["balance_end_real"] = float(statement.balance_end)
        return vals

    def _l10n_rs_transaction_vals(self, trx):
        vals = {
            "payment_ref": trx.payment_ref,
            "date": trx.date,
            "amount": float(trx.amount),
            "unique_import_id": trx.unique_import_id,
        }
        if trx.account_number:
            vals["account_number"] = trx.account_number
        if trx.partner_name:
            vals["partner_name"] = trx.partner_name
        if trx.ref:
            vals["ref"] = trx.ref
        if trx.narration:
            vals["narration"] = trx.narration
        return vals

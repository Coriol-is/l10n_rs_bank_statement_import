# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).

import json
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError


class BankMoveResequence(models.TransientModel):
    _name = "l10n.rs.bank.move.resequence"
    _description = "Resequence Bank Entries in Statement Order"

    journal_id = fields.Many2one(
        "account.journal",
        string="Bank Journal",
        required=True,
        domain="[('type', '=', 'bank')]",
    )
    year = fields.Integer(required=True, default=lambda self: fields.Date.today().year)
    preview = fields.Text(compute="_compute_preview")
    preview_values = fields.Text(compute="_compute_preview_values")

    @api.constrains("year")
    def _check_year(self):
        for wizard in self:
            if wizard.year < 1900 or wizard.year > 9999:
                raise UserError(self.env._("Enter a valid four-digit year."))

    def _moves(self):
        self.ensure_one()
        return self.env["account.move"].search(
            [
                ("journal_id", "=", self.journal_id.id),
                ("date", ">=", date(self.year, 1, 1)),
                ("date", "<=", date(self.year, 12, 31)),
                ("state", "!=", "draft"),
                ("name", "not in", (False, "/")),
            ]
        )

    @staticmethod
    def _statement_name_key(name):
        value = (name or "").strip()
        try:
            return (0, int(value))
        except ValueError:
            return (1, value.casefold())

    def _move_order_key(self, move):
        line = move.statement_line_id
        imported = bool(line and line.unique_import_id)
        if imported:
            return (
                move.date,
                0,
                self._statement_name_key(line.statement_id.name),
                line.sequence,
                line.id,
            )
        # Non-imported entries remain in the same journal sequence.  On an
        # equal date they follow imported bank rows and keep their old order.
        return (
            move.date,
            1,
            (0, move.sequence_number),
            0,
            move.id,
        )

    def _new_names(self):
        self.ensure_one()
        moves = self._moves()
        if not moves:
            return moves, {}

        first_move = min(moves, key=lambda move: (move.sequence_number, move.id))
        first_name = first_move.name
        sequence_format, format_values = first_move._get_sequence_format_param(first_name)
        ordered_moves = moves.sorted(key=self._move_order_key)
        names = {}
        for offset, move in enumerate(ordered_moves):
            names[move.id] = sequence_format.format(
                **{
                    **format_values,
                    "year": self.year % (10 ** format_values["year_length"]),
                    "seq": format_values["seq"] + offset,
                }
            )
        return ordered_moves, names

    @api.depends("journal_id", "year")
    def _compute_preview_values(self):
        for wizard in self:
            if not wizard.journal_id or not 1900 <= wizard.year <= 9999:
                wizard.preview_values = "{}"
                continue
            moves, names = wizard._new_names()
            imported_count = len(moves.filtered(lambda m: m.statement_line_id.unique_import_id))
            changed_count = len(moves.filtered(lambda m: names.get(m.id) != m.name))
            wizard.preview_values = json.dumps(
                {
                    "total": len(moves),
                    "imported": imported_count,
                    "other": len(moves) - imported_count,
                    "changed": changed_count,
                    "first": names.get(moves[:1].id) if moves else "",
                    "last": names.get(moves[-1:].id) if moves else "",
                }
            )

    @api.depends("preview_values")
    def _compute_preview(self):
        for wizard in self:
            values = json.loads(wizard.preview_values or "{}")
            if not values or not values.get("total"):
                wizard.preview = self.env._("No numbered entries found for this journal and year.")
                continue
            wizard.preview = self.env._(
                "Entries: %(total)s\n"
                "Imported statement entries: %(imported)s\n"
                "Other entries: %(other)s\n"
                "Numbers to change: %(changed)s\n"
                "Resulting range: %(first)s — %(last)s",
                **values,
            )

    def action_resequence(self):
        self.ensure_one()
        if self.journal_id.restrict_mode_hash_table:
            raise UserError(
                self.env._(
                    "This journal uses secured entries with hash. Odoo does not allow "
                    "reordering its posted entry numbers."
                )
            )
        moves, names = self._new_names()
        if not moves:
            raise UserError(self.env._("No numbered entries found for this journal and year."))

        changed_moves = moves.filtered(lambda move: names[move.id] != move.name)
        if changed_moves:
            changed_moves.name = False
            changed_moves.flush_recordset(["name"])
            for move in moves:
                if move in changed_moves:
                    move.name = names[move.id]

        return {"type": "ir.actions.act_window_close"}

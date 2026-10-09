# Temporary CI-only ports of OCA bank-statement-import modules for Odoo 20.0

`account_statement_import_base` and `account_statement_import_file` here are
minimal, machine-made 20.0 ports of the OCA/bank-statement-import 19.0
modules (commit `d1acad803cd5e1e62a77fe12a8b5322dae2f0561`). They exist only so
the GitHub Actions job can install `l10n_rs_bank_statement_import` on Odoo
20.0 while OCA has not yet published its 20.0 branch of
https://github.com/OCA/bank-statement-import.

- They are LGPL-3, copyright their original authors (Odoo SA, Akretion,
  OCA); manifests, headers and readme files are kept as upstream wrote them.
- They are **not** part of the product and **must not be published** to the
  Odoo Apps store or shipped to customers.
- Delete this directory and point the workflow at the real OCA 20.0 branch
  as soon as OCA merges the migration.

The third dependency, `account_statement_base`, is taken straight from the
pending OCA/account-reconcile PR #1048 (`kmee/account-reconcile`, branch
`20.0-mig-account_statement_base`, pinned by sha in the workflow).

Changes made relative to 19.0 (same list as the dev-env `PORT-NOTES.md`):
manifest versions `20.0.1.0.0`; `ir.model.access.csv` -> `ir.access.csv`;
`odoo.addons.base.models.res_bank` -> `res_partner_bank`; `res.partner.bank`
`acc_number`/`sanitized_acc_number` -> `account_number`/
`sanitized_account_number`; Binary field read via `.content` instead of
`base64.b64decode`; `ir.attachment` `datas` -> `raw`;
`__get_bank_statements_available_sources` -> `_get_bank_statements_available_sources`;
tests use `BinaryBytes`.

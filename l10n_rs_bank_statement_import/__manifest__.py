# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "RS Bank Statement Import",
    "summary": "Import Serbian bank statements: Halcom Hal E-Bank txt, "
               "Asseco OfficeBanking / FX Client XML, "
               "Raiffeisen OnLine (ROL) / OTP XML",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "license": "LGPL-3",
    # First entry is the store cover: the Apps grid and product page
    # render it in a strict 2:1 box with background-size: cover, so
    # anything not 2:1 gets centre-cropped.
    "images": [
        "static/description/cover.png",
        "static/description/banner.png",
    ],
    "author": "Coriolis Lab",
    "website": "https://github.com/Coriol-is/l10n_rs_bank_statement_import",
    "support": "odoo@coriol.co",
    "depends": ["account_statement_import_file"],
    "data": [],
    "installable": True,
    "application": False,
}

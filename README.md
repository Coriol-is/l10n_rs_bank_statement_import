# Serbian Bank Statement Import for Odoo

`l10n_rs_bank_statement_import` — import electronic bank statements from
Serbian banks into Odoo bank statements (`account.bank.statement`), with
per-transaction deduplication on re-import.

One module covers the three file formats that effectively all Serbian
business banking runs on:

| # | Format | Files | Banks (examples) | Status |
|---|--------|-------|------------------|--------|
| 1 | **Halcom Hal E-Bank** | fixed-width 280-char `.txt` + optional `*_cov.txt` recap (upload together as one ZIP); extended `#`-delimited variant ("prošireni") | OTP, UniCredit, NLB Komercijalna, AIK, … (any Hal E-Bank client) | RSD ✔ / FX pseudo-XML: planned |
| 2 | **Asseco OfficeBanking / FX Client XML** | `<stmtrs>` statement and `<pmtnotification>` instant notification | Banca Intesa, Erste, Eurobank, … | RSD ✔ (statements + notifications) / devizni (`ibank.fps.*`): planned |
| 3 | **ROL XML** (Raiffeisen OnLine; OTP export-compatible) | `TransakcioniRacunPrivredaIzvod` (RSD), `RacunPrivredaIzvod` (FX) | Raiffeisen, OTP | RSD ✔ and FX (EUR, …) ✔ |

The format is detected automatically — users just upload the file(s); the
module answers for its formats and hands anything else to the next importer
in the OCA chain (so it coexists with CAMT/OFX/MT940 importers).

## What you get per transaction

Amount with correct sign (including storno lines), booking date, statement
number and opening/closing balances (when the format carries them, e.g.
from the Halcom `_cov` recap), counterparty name and account, purpose
(svrha plaćanja), payment code (šifra plaćanja), poziv na broj references,
and a stable `unique_import_id` (Asseco `fitid`, ROL `BrojZaReklamaciju`,
content hash for Halcom) so importing the same file twice never duplicates
lines.

Windows encodings are handled — real files arrive as cp1250/cp1251 as often
as UTF-8, and Halcom's trailing `0x1A` EOF marker is tolerated.

## Community and Enterprise

Odoo moved its file-import wizard to Enterprise in v14. This module instead
builds on the OCA (LGPL-3) import framework, so it works on **both**
editions:

- [`account_statement_import_base`](https://github.com/OCA/bank-statement-import) (OCA)
- [`account_statement_import_file`](https://github.com/OCA/bank-statement-import) (OCA) — the upload wizard

Enterprise users install the OCA modules alongside; nothing conflicts.

## Install

1. Install the OCA dependencies from
   [OCA/bank-statement-import](https://github.com/OCA/bank-statement-import)
   (branch matching your Odoo version): `account_statement_import_base`,
   `account_statement_import_file` (they pull `account_statement_base`
   from OCA/account-reconcile).
2. Copy `l10n_rs_bank_statement_import` into your addons path and install it.
3. Make sure the bank journal's account number contains the digits of the
   account as it appears in the statement files (e.g.
   `205-0000000108040-45` or the full IBAN — matching ignores punctuation).
4. On the journal / Accounting dashboard, use *Import Statement* and upload
   the file. For Halcom, upload the statement `.txt` together with its
   `*_cov.txt` recap in one ZIP to get the statement number and balances
   (a lone `.txt` works too — the statement number falls back to the date).

## Development

The parsers are pure Python (`l10n_rs_bank_statement_import/parsers/`) with
no Odoo imports, unit-tested against real (anonymized) bank files:

```
pytest
```

Odoo-level tests live in `l10n_rs_bank_statement_import/tests/test_import.py`
and run under Odoo's test runner (`--test-tags post_install`); plain pytest
skips them automatically when Odoo is not installed.

See `docs/NOTES.md` for observed deviations between the official format
specs and real bank files.

## Roadmap

- **FX statements, phase 2**: Halcom devizni (tag-based pseudo-XML) and
  Asseco FX Client devizni statements. (ROL FX already works.) Dinar
  statements were built first — they are the daily-volume case.
- **MT940**: Raiffeisen/UniCredit/OTP also export MT940 — planned as a thin
  profile on top of OCA `account_statement_import_mt940_base` rather than a
  parser here.
- Šifra plaćanja (NBS payment code) mapping to reconciliation models.

## License

LGPL-3. © 2026 Coriolis Lab — support: odoo@coriol.co

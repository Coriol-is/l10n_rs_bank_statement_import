# Format notes: spec vs. real files

Observed while building the parsers against the official specs
(`docs/halcom_ppz.txt`, `docs/fx_ob_spec.txt`) and real (anonymized) bank
files in `l10n_rs_bank_statement_import/tests/fixtures/`. Where a fixture
contradicts the spec, the fixture wins.

## Halcom Hal E-Bank (fixed-width, section 1.3 of the PPZ spec)

- **Šifra plaćanja is 3-digit at positions 107–109.** The spec (written for
  the pre-2003 2-digit codebook) says position 106 = `"8"`, 107 = `"8"`
  (oblik plaćanja) and 108–109 = 2-digit code. Every real fixture (2011
  Komercijalna, 2013 file) instead has a blank at 106 and the modern
  3-digit NBS code spanning 107–109 (e.g. `221`). The parser reads the
  whole 106–111 zone and strips blanks.
- **Recap (`_cov`) dates have no dots.** Spec says `DD.MM.GGGG` (which
  cannot fit the 8-char field); real files carry `DDMMGGGG` (`27122011`).
- **The bank reference (positions 241–262, "broj za reklamaciju") is NOT
  unique per line.** In the 2013 fixture two lines of the same order share
  `20130806700034//000938`. Dedup therefore uses a content hash of the
  line's identifying fields, with a deterministic suffix for genuinely
  identical repeated lines.
- **Trailing `0x1A`** — the spec mandates it, but none of the real sample
  files actually end with it. The parser tolerates both.
- **Storno**: posting codes 30 (storno of debit → amount re-credited,
  positive) and 40 (storno of credit → negative), plus the `S` flag at
  29–30. No real storno fixture was available; sign semantics follow the
  spec ("30 – storno na teret, 40 – storno u korist") and are covered by a
  synthesized test line. Verify against a real storno file when one shows up.
- **Statement number lives only in the `_cov` recap.** Without it the
  statement name falls back to the booking date (`YYYYMMDD`) and balances
  are left unset.
- The first line of the 2013 fixture is a regular debit with an *empty*
  counterparty account and empty purpose (bank-side transfer) — parsers
  must not require those fields.
- **Prošireni (`#`-delimited) variant** is not described in the PPZ spec at
  all; the parser is built from the fixtures: header row with Slovenian
  column names (`ST_RACUNA`, `ZNESEK_V_BREME`/`_V_DOBRO`, `ID_NALOGA`, …),
  Serbian display amounts (`3.000.000,00`), statement number in
  `ST_IZPISKA`. `ID_NALOGA` (when present) is used as the dedup key. No
  balances are carried in this variant.
- **FX (devizni) statements are tag-based pseudo-XML** (`<CLIENTPROFILE>…`,
  fixture `HalcomDevizniIzvod.txt`) — detected and rejected with a clear
  message; implementation is phase 2.

## Asseco OfficeBanking / FX Client XML

- `curdef` uses the legacy label **`DIN`** for dinars → mapped to `RSD`
  (same for ROL and any `CSD` occurrence).
- Per spec, `ledgerbal` is the closing balance of the *previous* statement
  (= opening balance) and `availbal` the closing balance of this one.
- The vendor demo fixture is internally inconsistent: `availbal` =
  `10001005` while the transactions sum to `10001005.90` on a `0` opening
  balance. Balances are therefore imported as declared but **not**
  hard-validated against the transaction sum.
- **No real `pmtnotification` sample was available.**
  `tests/fixtures/asseco/pmtnotification_synthetic.xml` is synthetic,
  derived 1:1 from the spec (structure mirrors `stmtrs`, `notiftype`
  instead of `rstype`). The `instantbal` element mentioned in some Intesa
  material does not appear in the spec text we have and is not parsed.
- `stmtrslist` multi-statement wrappers are supported (spec section
  `/stmtrslist`), no fixture available.

## ROL XML (Raiffeisen OnLine / OTP)

- The dinarski fixture contains a **negative `Potrazuje`** (`-2400`,
  correction/storno pair "za pomen"). Signs are passed through arithmetically
  (`amount = Potrazuje − Duguje`), so the balance equation holds even though
  the header's `DugovniPromet`/`PotrazniPromet` split counts such lines
  differently.
- Dinar `Stavke` carry only `DatumValute` (no `DatumObrade`); the line's
  booking date is taken from the header `DatumIzvoda`, the value date kept
  separately. FX `Stavke` have both.
- `account_number` returned for journal matching is the `Partija` (18-digit
  local account). For FX accounts the `Partija` digits are a substring of
  the `IBANBroj`, so journals configured with either form match.
- FX statements (`RacunPrivredaIzvod`) were cheap to parse and are in v1
  scope (currency from `OznakaValute`), even though the product plan said
  "dinar first".

## Cross-format

- Real files arrive in **cp1250/cp1251** as often as UTF-8; decoding tries
  `utf-8-sig`, `cp1250`, `cp1251` in that order (`cp1251` accepts any byte
  sequence, so it must be last — this makes Cyrillic detection best-effort).
- Halcom fixed-width account numbers are bare 18-digit strings
  (`205000000010804045`); the OCA journal matcher compares punctuation-free,
  so journals may keep the display form (`205-0000000108040-45`), but a
  *short* non-padded form (`205-108040-45`) will NOT match — document this
  in support answers.

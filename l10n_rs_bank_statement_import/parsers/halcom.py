# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Halcom Hal E-Bank statement parsers.

Three variants exist in the wild (see docs/halcom_ppz.txt, official spec
"Hal E-Bank – Formati uvozno/izvoznih datoteka", Halcom a.d. Beograd):

* fixed-width 280-char transaction lines ("Promet i izvodi", section 1.3),
  optionally accompanied by a ``*_cov.txt`` recap file ("Rekapitulacija
  izvoda", section 1.4) that carries the statement number and balances;
* an extended ``#``-delimited variant ("prošireni") with a header row;
* FX statements as tag-based pseudo-XML (``<CLIENTPROFILE>...``) — detected
  but not implemented yet (raises :class:`UnsupportedVariant`).

Field positions follow the official spec, with one deviation observed in
every real fixture: the payment code (šifra plaćanja) is a 3-digit NBS code
at positions 107-109, not "8"+"8"+2-digit code at 106-109 (see
docs/NOTES.md).
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .base import (
    Statement,
    StatementParseError,
    Transaction,
    UnsupportedVariant,
    decode_bytes,
    dedupe_import_ids,
    implied_decimal,
    line_hash,
    map_currency,
    parse_date,
    serbian_decimal,
)

TXN_LINE_LEN = 280
COV_LINE_LEN = 147
POSTING_CODES = {"10", "20", "30", "40"}
#: sign per posting code: 10 debit, 20 credit, 30 storno of debit (money
#: returns), 40 storno of credit (money leaves again)
POSTING_SIGN = {"10": -1, "20": 1, "30": 1, "40": -1}

PROSIRENI_HEADER = "ST_RACUNA#"


# --------------------------------------------------------------------------
# detection helpers
# --------------------------------------------------------------------------

def looks_like_txn_file(text: str) -> bool:
    lines = _content_lines(text)
    if not lines:
        return False
    return all(_is_txn_line(line) for line in lines)


def looks_like_cov_file(text: str) -> bool:
    lines = _content_lines(text)
    return len(lines) >= 1 and all(
        len(line) == COV_LINE_LEN and line[:2] == "01" and line[2:20].isdigit()
        for line in lines
    )


def looks_like_prosireni(text: str) -> bool:
    return text.lstrip().upper().startswith(PROSIRENI_HEADER)


def looks_like_fx(text: str) -> bool:
    return text.lstrip().startswith("<CLIENTPROFILE>")


def _content_lines(text: str):
    return [line for line in text.replace("\x1a", "").splitlines() if line.strip()]


def _is_txn_line(line: str) -> bool:
    return (
        len(line) == TXN_LINE_LEN
        and line[18:20] in POSTING_CODES
        and line[22] == "."
        and line[25] == "."
    )


# --------------------------------------------------------------------------
# recap file (rekapitulacija izvoda, *_cov.txt)
# --------------------------------------------------------------------------

@dataclass
class CovInfo:
    account_number: str
    date: datetime.date
    previous_date: datetime.date
    balance_start: Decimal
    debit_count: int
    debit_total: Decimal
    credit_count: int
    credit_total: Decimal
    balance_end: Decimal
    statement_number: str


def parse_cov(data: bytes) -> CovInfo:
    """Parse the recap file (one line per account/day)."""
    text = decode_bytes(data)
    lines = _content_lines(text)
    if not lines or not looks_like_cov_file(text):
        raise StatementParseError("Not a Halcom recap (_cov) file")
    line = lines[0]
    return CovInfo(
        account_number=line[2:20],
        date=parse_date(line[20:28], "%d%m%Y"),
        previous_date=parse_date(line[28:36], "%d%m%Y"),
        balance_start=implied_decimal(line[36:54]),
        debit_count=int(line[54:60]),
        debit_total=implied_decimal(line[60:78]),
        credit_count=int(line[78:84]),
        credit_total=implied_decimal(line[84:102]),
        balance_end=implied_decimal(line[102:120]),
        statement_number=str(int(line[144:147])),
    )


# --------------------------------------------------------------------------
# fixed-width transaction file
# --------------------------------------------------------------------------

def parse_statement(data: bytes, cov_data: Optional[bytes] = None) -> Statement:
    """Parse a Halcom fixed-width statement file.

    :param cov_data: raw bytes of the companion ``*_cov.txt`` recap, when
        available.  It provides the statement number and balances; without
        it the statement number falls back to the booking date (YYYYMMDD).
    """
    text = decode_bytes(data)
    if looks_like_fx(text):
        raise UnsupportedVariant(
            "Halcom FX (devizni) pseudo-XML statements are not supported yet"
        )
    lines = _content_lines(text)
    if not lines:
        raise StatementParseError("Empty Halcom statement file")
    bad = [i for i, line in enumerate(lines, 1) if not _is_txn_line(line)]
    if bad:
        raise StatementParseError(
            f"Line {bad[0]} is not a 280-char Halcom transaction line"
        )

    transactions = []
    own_accounts = set()
    for line in lines:
        trx = _parse_txn_line(line)
        transactions.append(trx)
        own_accounts.add(line[72:90])
    dedupe_import_ids(transactions)

    if len(own_accounts) > 1:
        raise StatementParseError(
            f"Halcom file mixes several own accounts: {sorted(own_accounts)}"
        )
    account_number = own_accounts.pop()

    statement = Statement(
        account_number=account_number,
        currency="RSD",
        date=max(t.date for t in transactions),
        transactions=transactions,
    )

    if cov_data is not None:
        cov = parse_cov(cov_data)
        if cov.account_number != account_number:
            raise StatementParseError(
                "Recap file is for account %s but statement is for %s"
                % (cov.account_number, account_number)
            )
        statement.name = cov.statement_number
        statement.date = cov.date
        statement.balance_start = cov.balance_start
        statement.balance_end = cov.balance_end
    else:
        statement.name = statement.date.strftime("%Y%m%d")
    return statement


def _parse_txn_line(line: str) -> Transaction:
    posting = line[18:20]
    storno = bool(line[28:30].strip()) or posting in ("30", "40")
    sign = POSTING_SIGN[posting]
    amount = implied_decimal(line[90:105]) * sign

    partner_account = line[0:18].strip() or line[262:280].strip() or None
    partner_name = line[205:240].strip() or None
    purpose = line[159:195].strip()
    payment_code = line[105:111].strip() or None
    debit_model = line[111:113].strip()
    debit_ref = line[113:135].strip()
    credit_model = line[135:137].strip()
    credit_ref = line[137:159].strip()
    city = line[195:205].strip()
    bank_ref = line[240:262].strip()

    ref = credit_ref or debit_ref or None
    narration_bits = []
    if payment_code:
        narration_bits.append(f"Šifra plaćanja: {payment_code}")
    if debit_ref:
        narration_bits.append(f"Poziv na broj zaduženja: ({debit_model}) {debit_ref}")
    if credit_ref:
        narration_bits.append(
            f"Poziv na broj odobrenja: ({credit_model}) {credit_ref}"
        )
    if city:
        narration_bits.append(f"Mesto: {city}")
    if bank_ref:
        narration_bits.append(f"Referenca banke: {bank_ref}")
    if storno:
        narration_bits.append("STORNO")

    payment_ref = purpose or partner_name or bank_ref or "/"
    if storno:
        payment_ref = f"STORNO {payment_ref}"

    # The bank reference is not unique per line (one order can produce
    # several lines with the same reference), so always hash.
    unique_import_id = line_hash(
        bank_ref, line[0:18], posting, line[20:28], line[90:105], purpose,
        credit_ref, debit_ref,
    )

    return Transaction(
        date=parse_date(line[20:28], "%d.%m.%y"),
        value_date=parse_date(line[66:72], "%d%m%y"),
        amount=amount,
        payment_ref=payment_ref,
        unique_import_id=unique_import_id,
        account_number=partner_account,
        partner_name=partner_name,
        ref=ref,
        narration="\n".join(narration_bits) or None,
        payment_code=payment_code,
    )


# --------------------------------------------------------------------------
# extended '#'-delimited variant (prošireni)
# --------------------------------------------------------------------------

def parse_prosireni(data: bytes) -> list:
    """Parse the extended '#'-delimited Halcom export (header row + rows).

    Returns a list of :class:`Statement` (one per account + statement
    number found in the file).
    """
    text = decode_bytes(data)
    lines = _content_lines(text)
    if not lines or not looks_like_prosireni(text):
        raise StatementParseError("Not a Halcom prošireni file")
    header = [col.strip().upper() for col in lines[0].split("#")]
    duplicates = sorted({name for name in header if name and header.count(name) > 1})
    if duplicates:
        raise StatementParseError(
            "Duplicate column(s) in Halcom prošireni header: "
            + ", ".join(duplicates)
        )
    col = {name: idx for idx, name in enumerate(header)}
    # Without these columns every row would come out as silent zeros /
    # empties, so demand them up front and fail with a clear message.
    missing = [
        name
        for name in ("ST_RACUNA", "ZNESEK_V_BREME", "ZNESEK_V_DOBRO")
        if name not in col
    ]
    if "DATUM_KNJ" not in col and "DATUM_OBD" not in col:
        missing.append("DATUM_KNJ/DATUM_OBD")
    if missing:
        raise StatementParseError(
            "Halcom prošireni header is missing required column(s): "
            + ", ".join(missing)
        )

    def get(row, name, default=""):
        idx = col.get(name)
        if idx is None or idx >= len(row):
            return default
        return row[idx].strip()

    statements = {}
    for lineno, line in enumerate(lines[1:], 2):
        row = line.split("#")
        account = get(row, "ST_RACUNA")
        number = get(row, "ST_IZPISKA")
        currency = map_currency(get(row, "VALUTA") or "RSD")
        key = (account, number, currency)
        statement = statements.get(key)
        if statement is None:
            statement = statements[key] = Statement(
                account_number=account,
                currency=currency,
                name=number or None,
            )
        debit = serbian_decimal(get(row, "ZNESEK_V_BREME"))
        credit = serbian_decimal(get(row, "ZNESEK_V_DOBRO"))
        date = parse_date(
            get(row, "DATUM_KNJ") or get(row, "DATUM_OBD"), "%d.%m.%Y"
        )
        partner = get(row, "NAZIV_NAL_PREJ").rstrip("; ").strip() or None
        purpose = get(row, "NAMEN") or get(row, "OPIS")
        order_id = get(row, "ID_NALOGA")
        payment_code = get(row, "OZN_VRSTE_POSLA") or None
        ref = get(row, "SKLIC_ODOBR") or get(row, "SKLIC_OBREM") or None
        narration_bits = []
        if payment_code:
            narration_bits.append(f"Šifra plaćanja: {payment_code}")
        if order_id:
            narration_bits.append(f"ID naloga: {order_id}")
        statement.transactions.append(
            Transaction(
                date=date,
                value_date=parse_date(get(row, "DATUM_VAL") or get(row, "DATUM_OBD"), "%d.%m.%Y"),
                amount=credit - debit,
                payment_ref=purpose or partner or "/",
                unique_import_id=order_id
                or line_hash(account, number, str(lineno), line),
                account_number=get(row, "RAC_NAL_PREJ") or None,
                partner_name=partner,
                ref=ref,
                narration="\n".join(narration_bits) or None,
                payment_code=payment_code,
            )
        )

    result = []
    for statement in statements.values():
        dedupe_import_ids(statement.transactions)
        statement.date = max(t.date for t in statement.transactions)
        result.append(statement)
    return result

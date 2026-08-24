# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Alta Banka Business e-banking daily statement parser.

Alta exports a Crystal Reports layout as a binary Excel 97-2003 workbook.
The sheet is presentation-oriented (many blank cells and rows), but its
label columns and transaction columns are stable across single- and
multi-page statements.
"""

import re
from decimal import Decimal, InvalidOperation

from .base import (
    Statement,
    StatementParseError,
    Transaction,
    UnsupportedFormat,
    UnsupportedVariant,
    dedupe_import_ids,
    parse_date,
)

try:
    import xlrd
except ImportError:  # pragma: no cover - enforced by the Odoo manifest
    xlrd = None


OLE2_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
TRANSACTION_ROW = re.compile(r"^\d+$")
ACCOUNT_NUMBER = re.compile(r"^\d{18}$")
PAYMENT_CODE = re.compile(r"^\d{3}$")


def looks_like_xls(data: bytes) -> bool:
    return data.startswith(OLE2_SIGNATURE)


def parse_statement(data: bytes) -> Statement:
    sheet = _open_sheet(data)
    if not _looks_like_alta(sheet):
        raise UnsupportedFormat("Not an Alta Banka daily statement workbook")

    statement = Statement(
        account_number=_label_value(sheet, "BROJ RAČUNA"),
        currency="RSD",
        name=_label_value(sheet, "BROJ IZVODA"),
        date=parse_date(_label_value(sheet, "ZA PERIOD"), "%d.%m.%Y"),
        balance_start=_alta_decimal(_label_value(sheet, "Prethodno stanje")),
        balance_end=_alta_decimal(_label_value(sheet, "Novo stanje")),
    )

    for row in range(sheet.nrows):
        marker = _lines(_cell_text(sheet, row, 1))
        if len(marker) != 3 or not TRANSACTION_ROW.fullmatch(marker[0]):
            continue
        statement.transactions.append(_parse_transaction(sheet, row, marker))

    if not statement.transactions:
        raise StatementParseError("Alta Banka statement contains no transactions")
    dedupe_import_ids(statement.transactions)

    expected_end = statement.balance_start + sum(
        (transaction.amount for transaction in statement.transactions), Decimal(0)
    )
    if abs(expected_end - statement.balance_end) > Decimal("0.01"):
        raise StatementParseError(
            "Alta Banka statement balance mismatch: "
            f"{statement.balance_start} + transactions = {expected_end}, "
            f"reported {statement.balance_end}"
        )
    return statement


def _open_sheet(data: bytes):
    if xlrd is None:
        raise UnsupportedVariant(
            "Alta Banka XLS statements require the Python package 'xlrd'"
        )
    try:
        workbook = xlrd.open_workbook(file_contents=data, on_demand=True)
        if not workbook.sheet_names():
            raise UnsupportedFormat("Empty XLS workbook")
        return workbook.sheet_by_index(0)
    except UnsupportedFormat:
        raise
    except Exception as exc:
        raise UnsupportedFormat(f"Unreadable XLS workbook: {exc}") from exc


def _looks_like_alta(sheet) -> bool:
    values = {
        _cell_text(sheet, row, column)
        for row in range(min(sheet.nrows, 20))
        for column in range(sheet.ncols)
    }
    return (
        any(value.startswith("IZVOD BROJ ") for value in values)
        and any("BROJ RAČUNA" in value for value in values)
        and any("ZA PERIOD" in value for value in values)
    )


def _label_value(sheet, label: str) -> str:
    for row in range(sheet.nrows):
        for column in range(sheet.ncols):
            if label.lower() not in _cell_text(sheet, row, column).lower():
                continue
            for value_column in range(column + 1, sheet.ncols):
                value = _cell_text(sheet, row, value_column)
                if value:
                    return value
            break
    raise StatementParseError(f"Missing Alta Banka field {label!r}")


def _parse_transaction(sheet, row: int, marker: list) -> Transaction:
    booking_date = parse_date(marker[1], "%d.%m.%Y")
    value_date = parse_date(marker[2], "%d.%m.%Y")
    bank_reference = _cell_text(sheet, row, 2)
    purpose = _clean_missing(_cell_text(sheet, row, 5))

    partner_lines = _lines(_cell_text(sheet, row, 9))
    partner_name = _clean_missing(partner_lines[0]) if partner_lines else None
    partner_account = (
        partner_lines[-1]
        if partner_lines and ACCOUNT_NUMBER.fullmatch(partner_lines[-1])
        else None
    )
    address_lines = partner_lines[1:-1] if partner_account else partner_lines[1:]
    address = " ".join(line for line in address_lines if _clean_missing(line))

    detail_lines = _lines(_cell_text(sheet, row, 16))
    payment_code = (
        detail_lines.pop(0)
        if detail_lines and PAYMENT_CODE.fullmatch(detail_lines[0])
        else None
    )
    payment_reference = " ".join(detail_lines) or None

    debit = _alta_decimal(_cell_text(sheet, row, 22))
    credit = _alta_decimal(_cell_text(sheet, row, 26))
    if debit and credit:
        raise StatementParseError(
            f"Alta Banka transaction {bank_reference!r} has debit and credit amounts"
        )
    if not debit and not credit:
        raise StatementParseError(
            f"Alta Banka transaction {bank_reference!r} has no amount"
        )

    narration_bits = []
    if address:
        narration_bits.append(f"Adresa: {address}")
    if payment_code:
        narration_bits.append(f"Šifra plaćanja: {payment_code}")

    return Transaction(
        date=booking_date,
        value_date=value_date,
        amount=credit - debit,
        payment_ref=purpose or partner_name or bank_reference or "/",
        unique_import_id=bank_reference or None,
        account_number=partner_account,
        partner_name=partner_name,
        ref=payment_reference,
        narration="\n".join(narration_bits) or None,
        payment_code=payment_code,
    )


def _cell_text(sheet, row: int, column: int) -> str:
    if row >= sheet.nrows or column >= sheet.ncols:
        return ""
    value = sheet.cell_value(row, column)
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _lines(value: str) -> list:
    return [
        line.strip()
        for line in value.replace("\r", "\n").splitlines()
        if line.strip()
    ]


def _clean_missing(value: str):
    value = (value or "").strip()
    tokens = value.upper().split()
    return value if value and set(tokens) != {"NOTPROVIDED"} else None


def _alta_decimal(value: str) -> Decimal:
    value = (value or "").strip().replace(" ", "")
    if not value:
        return Decimal(0)
    if "," in value and "." in value:
        if value.rfind(".") > value.rfind(","):
            value = value.replace(",", "")
        else:
            value = value.replace(".", "").replace(",", ".")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise StatementParseError(f"Bad Alta Banka amount {value!r}") from exc

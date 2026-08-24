# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Pure pytest tests for the Alta Banka binary XLS parser."""

import datetime
import io
from decimal import Decimal

import pytest

xlwt = pytest.importorskip("xlwt")
pytest.importorskip("xlrd")

from l10n_rs_bank_statement_import.parsers import (
    StatementParseError,
    alta_xls,
    parse_any,
)


def _workbook(balance_end="125.00"):
    output = io.BytesIO()
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Sheet1")
    sheet.write(2, 7, "IZVOD BROJ 42")
    sheet.write(2, 23, "Stranica 1 od 1")
    sheet.write(7, 1, "BROJ IZVODA        :\nStatement No.")
    sheet.write(7, 3, "42")
    sheet.write(7, 12, "Prethodno stanje        :\nPrevious Balance")
    sheet.write(7, 21, "100.00")
    sheet.write(9, 1, "BROJ RAČUNA    :\nAccount No.")
    sheet.write(9, 3, "190000000000000001")
    sheet.write(15, 1, "ZA PERIOD            :\nFor the period")
    sheet.write(15, 3, "07.08.2026")
    sheet.write(15, 12, "Novo stanje            :\nNew Balance")
    sheet.write(15, 21, balance_end)

    sheet.write(32, 1, "1\n07.08.2026\n08.08.2026")
    sheet.write(32, 2, "87000119900001")
    sheet.write(32, 5, "Plaćanje dobavljaču")
    sheet.write(32, 9, "DOBAVLJAČ DOO\nBeograd\n160000000000000001")
    sheet.write(32, 16, "221\n97-42")
    sheet.write(32, 22, "25,00")
    sheet.write(32, 26, "0,00")

    sheet.write(39, 1, "2\n07.08.2026\n07.08.2026")
    sheet.write(39, 2, "87000119900002")
    sheet.write(39, 5, "NOTPROVIDED")
    sheet.write(39, 9, "KUPAC DOO\nNOTPROVIDED NOTPROVIDED\n205000000000000001")
    sheet.write(39, 16, "289\r\n2026-15")
    sheet.write(39, 22, "0,00")
    sheet.write(39, 26, "50.00")
    workbook.save(output)
    return output.getvalue()


def test_parse_alta_xls_statement():
    statement = alta_xls.parse_statement(_workbook())
    assert statement.name == "42"
    assert statement.account_number == "190000000000000001"
    assert statement.currency == "RSD"
    assert statement.date == datetime.date(2026, 8, 7)
    assert statement.balance_start == Decimal("100.00")
    assert statement.balance_end == Decimal("125.00")
    assert [transaction.amount for transaction in statement.transactions] == [
        Decimal("-25.00"),
        Decimal("50.00"),
    ]

    debit, credit = statement.transactions
    assert debit.value_date == datetime.date(2026, 8, 8)
    assert debit.unique_import_id == "87000119900001"
    assert debit.partner_name == "DOBAVLJAČ DOO"
    assert debit.account_number == "160000000000000001"
    assert debit.payment_code == "221"
    assert debit.ref == "97-42"
    assert debit.narration == "Adresa: Beograd\nŠifra plaćanja: 221"
    assert credit.payment_ref == "KUPAC DOO"
    assert credit.narration == "Šifra plaćanja: 289"


def test_parse_any_dispatches_alta_xls():
    assert parse_any(_workbook())[0].name == "42"


def test_balance_mismatch_is_rejected():
    with pytest.raises(StatementParseError, match="balance mismatch"):
        alta_xls.parse_statement(_workbook(balance_end="999.00"))


def test_non_alta_xls_is_left_for_other_importers():
    output = io.BytesIO()
    workbook = xlwt.Workbook()
    workbook.add_sheet("Sheet1").write(0, 0, "Some other report")
    workbook.save(output)
    with pytest.raises(StatementParseError, match="Not an Alta Banka"):
        parse_any(output.getvalue())

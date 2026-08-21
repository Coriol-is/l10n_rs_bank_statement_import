# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Pure pytest unit tests for the Asseco OfficeBanking / FX Client parser."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from l10n_rs_bank_statement_import.parsers import (
    UnsupportedVariant,
    asseco,
    parse_any,
)

FIXTURES = Path(__file__).parent / "fixtures" / "asseco"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_parse_stmtrs():
    statements = asseco.parse_statements(_read("FXclientIzvod.xml"))
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.account_number == "160-0000000015722-52"
    assert stmt.currency == "RSD"  # mapped from legacy "DIN"
    assert stmt.name == "1"
    assert stmt.date == datetime.date(2002, 11, 26)
    # ledgerbal = closing balance of previous statement (opening balance)
    assert stmt.balance_start == Decimal("0")
    assert stmt.balance_end == Decimal("10001005")
    assert len(stmt.transactions) == 3

    first = stmt.transactions[0]
    assert first.amount == Decimal("10000000.90")
    assert first.date == datetime.date(2002, 11, 5)
    assert first.value_date == datetime.date(2002, 11, 5)
    assert first.unique_import_id == "4270038436012"
    assert first.partner_name == "Petar Petrovic"
    assert first.account_number == "160-0000000000003-67"
    # utf-8 diacritics must survive
    assert first.payment_ref == "Gotovinska plaćanja-uplate i isplate"
    assert first.payment_code == "100"
    assert first.ref == "1234"

    assert [t.amount for t in stmt.transactions] == [
        Decimal("10000000.90"),
        Decimal("1000"),
        Decimal("5"),
    ]
    assert {t.unique_import_id for t in stmt.transactions} == {
        "4270038436012",
        "8700044894992",
        "8700044895012",
    }


def test_parse_stmtrs_v2_variant():
    statements = asseco.parse_statements(_read("FXclientIzvod_v2.xml"))
    stmt = statements[0]
    assert len(stmt.transactions) == 3
    assert stmt.transactions[1].payment_ref == "Trading with goods and services"
    assert stmt.transactions[1].ref == "05"


def test_parse_pmtnotification():
    statements = asseco.parse_statements(_read("pmtnotification_synthetic.xml"))
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.currency == "RSD"
    assert stmt.name == "2"
    assert stmt.balance_start == Decimal("10001005.90")
    assert stmt.balance_end == Decimal("10000905.90")
    trx = stmt.transactions[0]
    assert trx.amount == Decimal("-100")  # benefit = debit
    assert trx.unique_import_id == "8700044895999"
    assert trx.partner_name == "Dobavljač ćirilica test"
    assert trx.payment_ref == "Plaćanje računa 55/02"


def test_parse_any_dispatches_asseco():
    statements = parse_any(_read("FXclientIzvod.xml"))
    assert len(statements) == 1
    assert statements[0].account_number == "160-0000000015722-52"


def test_fx_statement_is_rejected_instead_of_silently_emptied():
    """Devizni statements share the <stmtrs> root but use stmbal/closing.

    Parsing one with the domestic field names succeeds without error and
    produces a statement with no balances, so the variant must be refused.
    """
    data = _read("stmtrs_fx_synthetic.xml")
    with pytest.raises(UnsupportedVariant):
        asseco.parse_statements(data)
    with pytest.raises(UnsupportedVariant):
        parse_any(data)

# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Pure pytest unit tests for the ROL (Raiffeisen OnLine) XML parser."""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from l10n_rs_bank_statement_import.parsers import (
    StatementParseError,
    parse_any,
    rol,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rol"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_parse_dinarski():
    statements = rol.parse_statements(_read("DinarskiIzvodPrimerXMLsredjeno.xml"))
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.account_number == "265110031000008888"
    assert stmt.currency == "RSD"
    assert stmt.name == "181"
    assert stmt.date == datetime.date(2006, 6, 26)
    assert stmt.balance_start == Decimal("11373667.73")
    assert stmt.balance_end == Decimal("13976765.67")
    assert len(stmt.transactions) == 76

    # header cross-check: start + sum == end, and net turnover matches
    total = sum(t.amount for t in stmt.transactions)
    assert stmt.balance_start + total == stmt.balance_end
    assert total == Decimal("4483895.99") - Decimal("1880798.05")

    # the fixture contains a bank correction line with a NEGATIVE Potrazuje
    # ("za pomen" appears with +2400 and -2400) — signs must pass through
    corrections = [
        t for t in stmt.transactions
        if t.payment_ref == "za pomen" and t.amount == Decimal("-2400")
    ]
    assert len(corrections) == 1

    first = stmt.transactions[0]
    assert first.amount == Decimal("363.44")
    assert first.partner_name.startswith("LIDER TRADE COMPANY")
    assert first.account_number == "220000000005682934"
    assert first.payment_ref == "PROMET ROBE I USLUGA FINALNA POTROSNJA"
    assert first.payment_code == "221"
    assert first.ref == "9009206"
    assert first.unique_import_id == "1131062230000090000006"
    assert first.date == datetime.date(2006, 6, 26)
    assert first.value_date == datetime.date(2006, 6, 26)

    ids = [t.unique_import_id for t in stmt.transactions]
    assert all(ids)
    assert len(set(ids)) == 76


def test_parse_dinarski_unformatted_single_line():
    """The raw bank export (one huge line, no pretty-printing) must parse
    identically to the reformatted file."""
    raw = rol.parse_statements(_read("DinarskiIzvodPrimerXML.xml"))[0]
    pretty = rol.parse_statements(_read("DinarskiIzvodPrimerXMLsredjeno.xml"))[0]
    assert len(raw.transactions) == len(pretty.transactions) == 76
    assert [t.amount for t in raw.transactions] == [
        t.amount for t in pretty.transactions
    ]


def test_parse_devizni():
    statements = rol.parse_statements(_read("DevizniIzvodPrimerXMLsredjeno.xml"))
    stmt = statements[0]
    assert stmt.currency == "EUR"
    assert stmt.account_number == "265100000000066666"
    assert stmt.name == "136"
    assert stmt.balance_start == Decimal("213852.85")
    assert stmt.balance_end == Decimal("218029.1")
    assert len(stmt.transactions) == 3
    total = sum(t.amount for t in stmt.transactions)
    assert stmt.balance_start + total == stmt.balance_end
    inflow = stmt.transactions[0]
    assert inflow.amount == Decimal("4990")
    assert inflow.unique_import_id == "357732393000002"
    # diacritics survive
    assert inflow.payment_ref == "Knjiženje priliva po loro doznaci za pravna lica"


def test_parse_devizni_real_anonymized_file():
    statements = rol.parse_statements(_read("DevizniIzvodReal.xml"))
    stmt = statements[0]
    assert stmt.currency == "EUR"
    assert stmt.account_number == "265100000008731506"
    assert stmt.name == "1"
    assert stmt.date == datetime.date(2012, 1, 4)
    assert stmt.balance_start == Decimal("1839.06")
    assert stmt.balance_end == Decimal("1891.57")
    assert len(stmt.transactions) == 1
    trx = stmt.transactions[0]
    assert trx.amount == Decimal("52.51")
    assert trx.date == datetime.date(2012, 1, 4)  # DatumObrade
    assert trx.value_date == datetime.date(2012, 1, 3)  # DatumValute
    assert trx.partner_name.startswith("DVA BORA 2000")
    assert trx.unique_import_id == "4611050147000002"
    assert "Napomena: /INV/0004/11" in trx.narration


def test_dtd_payload_is_rejected_before_parsing():
    """XXE hardening: a DOCTYPE/ENTITY payload must be refused cleanly
    (ElementTree expands internal entities), not parsed or crashed on."""
    data = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<!DOCTYPE TransakcioniRacunPrivredaIzvod [<!ENTITY x "boom">]>\n'
        b"<TransakcioniRacunPrivredaIzvod>&x;</TransakcioniRacunPrivredaIzvod>"
    )
    with pytest.raises(StatementParseError, match="DOCTYPE"):
        rol.parse_statements(data)
    with pytest.raises(StatementParseError, match="DOCTYPE"):
        parse_any(data)


def test_parse_any_dispatches_rol():
    statements = parse_any(_read("DinarskiIzvodPrimerXMLsredjeno.xml"))
    assert statements[0].name == "181"
    statements = parse_any(_read("DevizniIzvodReal.xml"))
    assert statements[0].currency == "EUR"

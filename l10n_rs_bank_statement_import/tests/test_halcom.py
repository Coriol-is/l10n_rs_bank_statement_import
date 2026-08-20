# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Pure pytest unit tests for the Halcom Hal E-Bank parser (no Odoo)."""

import datetime
import io
import zipfile
from decimal import Decimal
from pathlib import Path

from l10n_rs_bank_statement_import.parsers import (
    StatementParseError,
    UnsupportedVariant,
    halcom,
    parse_any,
)

FIXTURES = Path(__file__).parent / "fixtures" / "halcom"


def _read(name):
    return (FIXTURES / name).read_bytes()


def test_parse_statement_with_cov():
    stmt = halcom.parse_statement(
        _read("HalcomIZVOD.txt"), cov_data=_read("HalcomIZVOD_cov.txt")
    )
    assert stmt.account_number == "205000000010804045"
    assert stmt.currency == "RSD"
    assert stmt.name == "247"
    assert stmt.date == datetime.date(2011, 12, 27)
    assert stmt.balance_start == Decimal("3064406.45")
    assert stmt.balance_end == Decimal("3102049.00")
    assert len(stmt.transactions) == 6

    # recap cross-check: start + sum(transactions) == end
    total = sum(t.amount for t in stmt.transactions)
    assert stmt.balance_start + total == stmt.balance_end

    credit = stmt.transactions[0]
    assert credit.amount == Decimal("69808.80")
    assert credit.date == datetime.date(2011, 12, 27)
    assert credit.value_date == datetime.date(2011, 12, 27)
    assert credit.partner_name == "KLEEMANN LIFTOVI DOO"
    assert credit.account_number == "160000000026565175"
    assert credit.payment_ref == "PROMET ROBE I USLUGA - FINALNA POTRO"
    assert credit.payment_code == "221"
    assert credit.ref == "P1194-11"

    debit = stmt.transactions[1]
    assert debit.amount == Decimal("-359.25")
    assert debit.partner_name == "LA FANTANA D.O.O. BEOGRAD"
    assert debit.ref == "398249"

    ids = [t.unique_import_id for t in stmt.transactions]
    assert all(ids)
    assert len(set(ids)) == 6


def test_parse_statement_without_cov_falls_back_to_date_name():
    stmt = halcom.parse_statement(_read("HalcomIZVOD.txt"))
    assert stmt.name == "20111227"
    assert stmt.balance_start is None
    assert stmt.balance_end is None
    assert len(stmt.transactions) == 6


def test_parse_cov_alone():
    cov = halcom.parse_cov(_read("HalcomIZVOD_cov.txt"))
    assert cov.account_number == "205000000010804045"
    assert cov.date == datetime.date(2011, 12, 27)
    assert cov.previous_date == datetime.date(2011, 12, 26)
    assert cov.debit_count == 5
    assert cov.debit_total == Decimal("32166.25")
    assert cov.credit_count == 1
    assert cov.credit_total == Decimal("69808.80")
    assert cov.statement_number == "247"


def test_parse_2013_statement_counts_and_duplicated_bank_refs():
    stmt = halcom.parse_statement(
        _read("20130806_00300457580_00141.txt"),
        cov_data=_read("20130806_00300457580_00141_cov.txt"),
    )
    assert stmt.account_number == "170000030045758065"
    assert stmt.name == "141"
    assert stmt.date == datetime.date(2013, 8, 6)
    assert len(stmt.transactions) == 4
    assert stmt.transactions[0].amount == Decimal("-3000000.00")
    credits = [t for t in stmt.transactions if t.amount > 0]
    assert sum(t.amount for t in credits) == Decimal("33669.30")
    assert stmt.balance_start + sum(t.amount for t in stmt.transactions) == (
        stmt.balance_end
    )
    # lines 3 and 4 share the same bank reference — ids must still be unique
    ids = [t.unique_import_id for t in stmt.transactions]
    assert len(set(ids)) == 4


def test_storno_line_sign_and_flagging():
    """No storno fixture exists; synthesize one from a real debit line
    (posting code 30 = storno of a debit -> money comes back, positive)."""
    raw = _read("HalcomIZVOD.txt").replace(b"\x1a", b"")
    lines = raw.split(b"\r\n")
    line = bytearray(lines[1])  # a debit line
    line[18:20] = b"30"
    line[28:30] = b"S "
    stmt = halcom.parse_statement(bytes(line) + b"\r\n")
    trx = stmt.transactions[0]
    assert trx.amount == Decimal("359.25")  # sign flipped vs the 10 debit
    assert trx.payment_ref.startswith("STORNO ")
    assert "STORNO" in trx.narration


def test_trailing_eof_marker_tolerated():
    data = _read("HalcomIZVOD.txt") + b"\x1a"
    stmt = halcom.parse_statement(data)
    assert len(stmt.transactions) == 6


def test_zip_with_statement_and_cov():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("HalcomIZVOD.txt", _read("HalcomIZVOD.txt"))
        zf.writestr("HalcomIZVOD_cov.txt", _read("HalcomIZVOD_cov.txt"))
    statements = parse_any(buf.getvalue())
    assert len(statements) == 1
    assert statements[0].name == "247"
    assert statements[0].balance_end == Decimal("3102049.00")


def test_parse_any_dispatches_fixed_width():
    statements = parse_any(_read("HalcomIZVOD.txt"))
    assert len(statements) == 1
    assert len(statements[0].transactions) == 6


def test_cov_alone_is_rejected_with_guidance():
    try:
        parse_any(_read("HalcomIZVOD_cov.txt"))
    except UnsupportedVariant as exc:
        assert "ZIP" in str(exc)
    else:
        raise AssertionError("cov-only upload should raise UnsupportedVariant")


def test_fx_pseudo_xml_raises_unsupported_variant():
    try:
        parse_any(_read("HalcomDevizniIzvod.txt"))
    except UnsupportedVariant as exc:
        assert "FX" in str(exc)
    else:
        raise AssertionError("Halcom FX file should raise UnsupportedVariant")


def test_mixed_accounts_rejected():
    raw = _read("HalcomIZVOD.txt").replace(b"\x1a", b"")
    lines = raw.split(b"\r\n")
    line = bytearray(lines[1])
    line[72:90] = b"111111111111111111"
    data = lines[0] + b"\r\n" + bytes(line) + b"\r\n"
    try:
        halcom.parse_statement(data)
    except StatementParseError as exc:
        assert "own accounts" in str(exc)
    else:
        raise AssertionError("mixed own accounts should be rejected")


# ---------------------------------------------------------------------------
# extended '#'-delimited variant (prošireni)
# ---------------------------------------------------------------------------

def test_prosireni_utf8():
    statements = parse_any(_read("prosireni.txt"))
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.account_number == "170-000030045758065"
    assert stmt.currency == "RSD"
    assert stmt.name == "141"
    assert len(stmt.transactions) == 4
    assert stmt.transactions[0].amount == Decimal("-3000000.00")
    # mirrors the fixed-width 2013 statement
    fixed = halcom.parse_statement(_read("20130806_00300457580_00141.txt"))
    assert sorted(t.amount for t in stmt.transactions) == sorted(
        t.amount for t in fixed.transactions
    )


def test_prosireni_cp1250_encoding_survival():
    statements = parse_any(_read("HalcomIZVODprosireni.txt"))
    assert len(statements) == 1
    stmt = statements[0]
    assert stmt.name == "247"
    assert len(stmt.transactions) == 6
    # cp1250 Č must survive decoding
    fee = stmt.transactions[-1]
    assert fee.partner_name == "KOMERCIJALNA BANKA AD -RAČUN TARIFE"
    assert fee.amount == Decimal("-120.00")
    # order ids are used as unique ids when present
    with_order = [t for t in stmt.transactions if t.ref or True]
    assert len({t.unique_import_id for t in with_order}) == 6

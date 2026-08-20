# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Asseco OfficeBanking / FX Client XML statement parser.

Handles the "Office Banking XML specifikacija" statement documents (see
docs/fx_ob_spec.txt):

* ``<stmtrs>`` — statement response, ``rstype`` = ``ibank.payment.stmtrs.ledger``
* ``<pmtnotification>`` — instant notification, ``notiftype`` =
  ``ibank.payment.notification.ledger``
* ``<stmtrslist>`` — wrapper aggregating several statements

Per the spec, ``ledgerbal`` is the closing balance of the *previous*
statement (= opening balance) and ``availbal`` the closing balance of this
statement.  Amounts (``trnamt``) are absolute; ``benefit`` gives the
direction (credit/debit).  ``fitid`` is the bank-unique transaction id and
is used as the dedup key.
"""

import xml.etree.ElementTree as ET

from .base import (
    Statement,
    StatementParseError,
    Transaction,
    decode_bytes,
    dedupe_import_ids,
    line_hash,
    map_currency,
    parse_date,
    plain_decimal,
)

ROOT_TAGS = ("stmtrs", "pmtnotification", "stmtrslist")


def looks_like_asseco(root: ET.Element) -> bool:
    return _local(root.tag) in ROOT_TAGS


def parse_statements(data: bytes) -> list:
    """Parse an Asseco XML document into a list of :class:`Statement`."""
    text = decode_bytes(data)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise StatementParseError(f"Invalid XML: {exc}") from exc
    return parse_tree(root)


def parse_tree(root: ET.Element) -> list:
    tag = _local(root.tag)
    if tag == "stmtrslist":
        statements = []
        for child in root:
            if _local(child.tag) in ("stmtrs", "pmtnotification"):
                statements.append(_parse_stmtrs(child))
        if not statements:
            raise StatementParseError("stmtrslist contains no statements")
        return statements
    if tag in ("stmtrs", "pmtnotification"):
        return [_parse_stmtrs(root)]
    raise StatementParseError(f"Unexpected root element <{tag}>")


def _parse_stmtrs(node: ET.Element) -> Statement:
    status_code = _text(node, "status/code")
    if status_code not in ("", "0"):
        raise StatementParseError(
            "Bank response status is %s (%s)"
            % (status_code, _text(node, "status/severity"))
        )
    account = _text(node, "acctid")
    if not account:
        raise StatementParseError("Missing <acctid> in statement")
    currency = map_currency(_text(node, "curdef") or "RSD")
    statement = Statement(
        account_number=account,
        currency=currency,
        name=_text(node, "stmtnumber") or None,
    )
    # ledgerbal = closing balance of the previous statement (i.e. opening),
    # availbal = closing balance of this statement.
    start = _text(node, "ledgerbal/balamt")
    end = _text(node, "availbal/balamt")
    if start:
        statement.balance_start = plain_decimal(start)
    if end:
        statement.balance_end = plain_decimal(end)
    date_text = _text(node, "availbal/dtasof") or _text(node, "ledgerbal/dtasof")
    if date_text:
        statement.date = _parse_dt(date_text)

    trnlist = node.find("trnlist")
    if trnlist is None:
        raise StatementParseError("Missing <trnlist> in statement")
    for trn in trnlist.findall("stmttrn"):
        statement.transactions.append(_parse_stmttrn(trn))
    dedupe_import_ids(statement.transactions)

    if statement.date is None and statement.transactions:
        statement.date = max(t.date for t in statement.transactions)
    if not statement.name and statement.date:
        statement.name = statement.date.strftime("%Y%m%d")
    return statement


def _parse_stmttrn(trn: ET.Element) -> Transaction:
    benefit = _text(trn, "benefit").lower()
    if benefit not in ("credit", "debit"):
        raise StatementParseError(f"Unexpected <benefit> value {benefit!r}")
    sign = 1 if benefit == "credit" else -1
    amount = plain_decimal(_text(trn, "trnamt")).copy_abs() * sign

    fitid = _text(trn, "fitid")
    date = _parse_dt(_text(trn, "dtposted"))
    value_date_text = _text(trn, "dtavail")
    purpose = _text(trn, "purpose")
    purpose_code = _text(trn, "purposecode") or None
    partner_name = _text(trn, "payeeinfo/name") or None
    partner_city = _text(trn, "payeeinfo/city")
    account = _text(trn, "payeeaccountinfo/acctid") or None
    ref_model = _text(trn, "refmodel")
    ref_number = _text(trn, "refnumber")
    payee_ref_model = _text(trn, "payeerefmodel")
    payee_ref_number = _text(trn, "payeerefnumber")

    narration_bits = []
    if purpose_code:
        narration_bits.append(f"Šifra plaćanja: {purpose_code}")
    if ref_number:
        narration_bits.append(f"Poziv na broj (naš): ({ref_model}) {ref_number}")
    if payee_ref_number:
        narration_bits.append(
            f"Poziv na broj (partner): ({payee_ref_model}) {payee_ref_number}"
        )
    if partner_city:
        narration_bits.append(f"Mesto: {partner_city}")
    bank_name = _text(trn, "payeeaccountinfo/bankname")
    if bank_name:
        narration_bits.append(f"Banka: {bank_name}")

    return Transaction(
        date=date,
        value_date=_parse_dt(value_date_text) if value_date_text else None,
        amount=amount,
        payment_ref=purpose or partner_name or fitid or "/",
        unique_import_id=fitid
        or line_hash(_text(trn, "dtposted"), benefit, _text(trn, "trnamt"), purpose),
        account_number=account,
        partner_name=partner_name,
        ref=payee_ref_number or ref_number or None,
        narration="\n".join(narration_bits) or None,
        payment_code=purpose_code,
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _text(node: ET.Element, path: str) -> str:
    child = node.find(path)
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _parse_dt(text: str):
    # UTC format per spec, e.g. 2002-11-05T00:00:00
    return parse_date(text[:10], "%Y-%m-%d")

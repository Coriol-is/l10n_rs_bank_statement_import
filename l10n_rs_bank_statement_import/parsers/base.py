# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Common data structures and helpers for Serbian bank statement parsers.

This package is pure Python (no Odoo imports) so the parsers can be
unit-tested with plain pytest against real fixture files.
"""

import datetime
import hashlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

#: Encodings seen in the wild for Serbian bank exports, tried in order.
#: Real files come out of Windows software (cp1250 latin / cp1251 cyrillic);
#: newer exports are UTF-8, sometimes with a BOM.  cp1251 accepts any byte
#: sequence, so it must be last.
ENCODINGS = ("utf-8-sig", "cp1250", "cp1251")

#: Serbian statements label dinars either "RSD" or the legacy "DIN".
CURRENCY_MAP = {"DIN": "RSD", "CSD": "RSD"}


class StatementParseError(Exception):
    """A recognized statement file could not be parsed."""


class UnsupportedFormat(StatementParseError):
    """The file is not one of the formats this package understands.

    The Odoo glue converts this into a ``super()`` call so other importer
    modules in the OCA chain get a chance to handle the file.
    """


class UnsupportedVariant(StatementParseError):
    """The file *is* recognized but the variant is not implemented yet
    (e.g. Halcom FX pseudo-XML statements)."""


@dataclass
class Transaction:
    """One statement line, format-agnostic."""

    date: datetime.date
    amount: Decimal  # signed: credit > 0, debit < 0
    payment_ref: str  # label / purpose of the payment (never empty)
    unique_import_id: Optional[str] = None
    account_number: Optional[str] = None  # counterparty account
    partner_name: Optional[str] = None  # counterparty name
    ref: Optional[str] = None  # poziv na broj / bank reference
    narration: Optional[str] = None  # extra details, free text
    payment_code: Optional[str] = None  # šifra plaćanja (NBS codebook)
    value_date: Optional[datetime.date] = None


@dataclass
class Statement:
    """One bank statement (izvod)."""

    account_number: str
    currency: str
    name: Optional[str] = None  # statement number, e.g. "247"
    date: Optional[datetime.date] = None
    balance_start: Optional[Decimal] = None
    balance_end: Optional[Decimal] = None
    transactions: list = field(default_factory=list)


def decode_bytes(data: bytes) -> str:
    """Decode raw file bytes, trying the known Serbian bank encodings.

    Strips an eventual trailing 0x1A (DOS end-of-file marker used by
    Halcom exports).  Only EOF/EOL bytes are stripped — trailing spaces are
    significant in fixed-width lines.
    """
    data = data.rstrip(b"\x1a\r\n")
    last_exc = None
    for enc in ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError as exc:  # pragma: no cover - cp1251 rarely fails
            last_exc = exc
    raise StatementParseError(f"Could not decode file: {last_exc}")


def reject_dtd(text: str) -> None:
    """Refuse XML that carries a DTD, before it reaches the parser.

    Serbian bank exports never use DTDs, and :mod:`xml.etree.ElementTree`
    expands internal entities, so an uploaded file with a ``<!DOCTYPE`` or
    ``<!ENTITY`` declaration is at best broken and at worst an XXE /
    entity-expansion attack.
    """
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise StatementParseError(
            "XML with a document type declaration (<!DOCTYPE/<!ENTITY) "
            "is not accepted"
        )


def implied_decimal(digits: str) -> Decimal:
    """Fixed-width amount with two implied decimals: '000000006980880' -> 69808.80."""
    digits = digits.strip() or "0"
    try:
        return Decimal(digits) / Decimal(100)
    except InvalidOperation as exc:
        raise StatementParseError(f"Bad fixed-width amount {digits!r}") from exc


def serbian_decimal(text: str) -> Decimal:
    """Amount in Serbian display format: '3.000.000,00' -> 3000000.00."""
    text = (text or "").strip()
    if not text:
        return Decimal(0)
    try:
        return Decimal(text.replace(".", "").replace(",", "."))
    except InvalidOperation as exc:
        raise StatementParseError(f"Bad amount {text!r}") from exc


def plain_decimal(text: str) -> Decimal:
    """Amount with a dot decimal separator (XML formats)."""
    text = (text or "").strip()
    if not text:
        return Decimal(0)
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise StatementParseError(f"Bad amount {text!r}") from exc


def parse_date(text: str, fmt: str) -> datetime.date:
    try:
        return datetime.datetime.strptime(text.strip(), fmt).date()
    except ValueError as exc:
        raise StatementParseError(f"Bad date {text!r} (expected {fmt})") from exc


def map_currency(code: str) -> str:
    code = (code or "").strip().upper()
    return CURRENCY_MAP.get(code, code)


def line_hash(*parts: str) -> str:
    """Deterministic fallback unique id for lines without a bank reference."""
    payload = "|".join(p or "" for p in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def dedupe_import_ids(transactions) -> None:
    """Make unique_import_id values unique within one parse result.

    Some banks reuse the complaint reference for several lines of the same
    order (seen in real Halcom files) and two genuinely identical payments
    can appear on the same day.  Deterministically suffix repeats so
    re-importing the same file still dedupes correctly.
    """
    seen = {}
    for trx in transactions:
        uid = trx.unique_import_id
        if not uid:
            continue
        count = seen.get(uid, 0)
        seen[uid] = count + 1
        if count:
            trx.unique_import_id = f"{uid}-{count + 1}"

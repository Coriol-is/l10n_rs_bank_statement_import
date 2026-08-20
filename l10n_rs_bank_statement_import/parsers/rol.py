# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""ROL (Raiffeisen OnLine) XML statement parser.

Attribute-based XML with two roots (OTP exports are compatible):

* ``<TransakcioniRacunPrivredaIzvod>`` — dinar (RSD) current account
* ``<RacunPrivredaIzvod>`` — FX account (``OznakaValute`` gives the currency)

``<Zaglavlje>`` carries the header (IzvodID, BrojIzvoda, DatumIzvoda,
Partija, PrethodnoStanje, NovoStanje, ...), each ``<Stavke>`` is one
transaction with ``Duguje``/``Potrazuje`` absolute amounts.
``BrojZaReklamaciju`` is the bank complaint reference, used as dedup key.
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

ROOT_TAGS = ("transakcioniracunprivredaizvod", "racunprivredaizvod")


def looks_like_rol(root: ET.Element) -> bool:
    return root.tag.rsplit("}", 1)[-1].lower() in ROOT_TAGS


def parse_statements(data: bytes) -> list:
    text = decode_bytes(data)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise StatementParseError(f"Invalid XML: {exc}") from exc
    return parse_tree(root)


def parse_tree(root: ET.Element) -> list:
    tag = root.tag.rsplit("}", 1)[-1].lower()
    if tag not in ROOT_TAGS:
        raise StatementParseError(f"Unexpected root element <{root.tag}>")
    is_fx = tag == "racunprivredaizvod"

    header = root.find("Zaglavlje")
    if header is None:
        raise StatementParseError("Missing <Zaglavlje> in ROL statement")
    account = (header.get("Partija") or "").strip()
    if not account:
        raise StatementParseError("Missing Partija (account number) in <Zaglavlje>")
    currency = map_currency(header.get("OznakaValute") or "RSD")
    date = parse_date(header.get("DatumIzvoda") or "", "%d.%m.%Y")

    statement = Statement(
        account_number=account,
        currency=currency,
        name=(header.get("BrojIzvoda") or "").strip() or None,
        date=date,
        balance_start=_attr_decimal(header, "PrethodnoStanje"),
        balance_end=_attr_decimal(header, "NovoStanje"),
    )

    for idx, stavka in enumerate(root.findall("Stavke"), 1):
        statement.transactions.append(_parse_stavka(stavka, date, is_fx, idx))
    dedupe_import_ids(statement.transactions)
    return [statement]


def _parse_stavka(node, statement_date, is_fx, idx) -> Transaction:
    get = lambda name: (node.get(name) or "").strip()  # noqa: E731

    debit = plain_decimal(get("Duguje"))
    credit = plain_decimal(get("Potrazuje"))
    amount = credit - debit

    # dinar Stavke only carry DatumValute; FX ones also have DatumObrade
    booking_text = get("DatumObrade")
    date = parse_date(booking_text, "%d.%m.%Y") if booking_text else statement_date
    value_text = get("DatumValute")
    value_date = parse_date(value_text, "%d.%m.%Y") if value_text else None

    partner_name = get("NalogKorisnik") or None
    partner_account = (
        get("BrojRacunaPrimaocaPosiljaoca") or get("RacunNalogodavacKorisnik") or None
    )
    description = get("Opis")
    payment_code = get("SifraPlacanja") or None
    complaint_ref = get("BrojZaReklamaciju")
    poziv = get("PozivNaBrojKorisnika")
    poziv_model = get("ModelKorisnika")
    poziv_zad_odo = get("PozivNaBrojZaduzenjaOdobrenja")
    poziv_zad_odo_model = get("ModelZaduzenjaOdobrenja")
    reference = get("Referenca")

    narration_bits = []
    if payment_code:
        label = get("SifraPlacanjaOpis")
        narration_bits.append(
            f"Šifra plaćanja: {payment_code}" + (f" ({label})" if label else "")
        )
    if poziv:
        narration_bits.append(f"Poziv na broj korisnika: ({poziv_model}) {poziv}")
    if poziv_zad_odo:
        narration_bits.append(
            "Poziv na broj zaduženja/odobrenja: "
            f"({poziv_zad_odo_model}) {poziv_zad_odo}"
        )
    if get("VasBrojNaloga"):
        narration_bits.append(f"Vaš broj naloga: {get('VasBrojNaloga')}")
    if reference:
        narration_bits.append(f"Referenca: {reference}")
    if complaint_ref:
        narration_bits.append(f"Broj za reklamaciju: {complaint_ref}")
    if is_fx:
        for attr, label in (
            ("Napomena", "Napomena"),
            ("TekstOsnova", "Osnov plaćanja"),
            ("DinarskaProtivvrednost", "Dinarska protivvrednost"),
        ):
            if get(attr):
                narration_bits.append(f"{label}: {get(attr)}")
        payment_code = payment_code or get("OsnovPlacanja") or None

    return Transaction(
        date=date,
        value_date=value_date,
        amount=amount,
        payment_ref=description or partner_name or complaint_ref or "/",
        unique_import_id=complaint_ref
        or line_hash(
            str(idx), get("Duguje"), get("Potrazuje"), description, reference
        ),
        account_number=partner_account,
        partner_name=partner_name,
        ref=poziv or poziv_zad_odo or reference or None,
        narration="\n".join(narration_bits) or None,
        payment_code=payment_code,
    )


def _attr_decimal(node, name):
    value = (node.get(name) or "").strip()
    return plain_decimal(value) if value else None

# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Format sniffer and dispatcher for Serbian bank statement files.

Pure Python — no Odoo imports.  :func:`parse_any` accepts the raw uploaded
bytes (a single statement file or a ZIP archive bundling Halcom statement +
``_cov`` recap pairs) and returns a list of
:class:`~.base.Statement` objects, or raises:

* :class:`~.base.UnsupportedFormat` — not a format we know (the Odoo glue
  then hands the file over to the next importer in the OCA chain);
* :class:`~.base.UnsupportedVariant` — recognized but not implemented
  (e.g. Halcom FX pseudo-XML);
* :class:`~.base.StatementParseError` — recognized but broken.
"""

import io
import xml.etree.ElementTree as ET
import zipfile

from . import asseco, halcom, rol
from .base import (  # noqa: F401 - re-exported for the Odoo glue and tests
    Statement,
    StatementParseError,
    Transaction,
    UnsupportedFormat,
    UnsupportedVariant,
    decode_bytes,
)


def parse_any(data: bytes, filename: str = None) -> list:
    """Sniff and parse a statement file (or ZIP of statement files)."""
    if not data:
        raise UnsupportedFormat("Empty file")
    if data[:4] == b"PK\x03\x04":
        return _parse_zip(data)
    return _parse_single(data, filename=filename)


def _parse_single(data: bytes, cov_data: bytes = None, filename: str = None) -> list:
    try:
        text = decode_bytes(data)
    except StatementParseError as exc:
        raise UnsupportedFormat(str(exc)) from exc

    stripped = text.lstrip()
    if stripped.startswith("<"):
        if halcom.looks_like_fx(text):
            raise UnsupportedVariant(
                "Halcom FX (devizni) pseudo-XML statements are not supported yet "
                "— planned for a future release."
            )
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise UnsupportedFormat(f"Unparseable XML: {exc}") from exc
        if asseco.looks_like_asseco(root):
            return asseco.parse_tree(root)
        if rol.looks_like_rol(root):
            return rol.parse_tree(root)
        raise UnsupportedFormat(
            f"Unknown XML root element <{root.tag}>"
        )

    if halcom.looks_like_prosireni(text):
        return halcom.parse_prosireni(data)
    if halcom.looks_like_txn_file(text):
        return [halcom.parse_statement(data, cov_data=cov_data)]
    if halcom.looks_like_cov_file(text):
        raise UnsupportedVariant(
            "This is a Halcom recap (_cov) file. Upload it together with the "
            "statement file in one ZIP archive, or upload the statement file "
            "alone."
        )
    raise UnsupportedFormat("Not a recognized Serbian bank statement format")


def _parse_zip(data: bytes) -> list:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsupportedFormat(f"Broken ZIP archive: {exc}") from exc

    members = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        name = info.filename.rsplit("/", 1)[-1]
        if name.startswith(".") or name.startswith("__MACOSX"):
            continue
        members[info.filename] = archive.read(info.filename)
    if not members:
        raise UnsupportedFormat("Empty ZIP archive")

    # Pair Halcom *_cov recap files with their statement files by name.
    covs = {}
    for path in list(members):
        stem = _stem(path)
        if stem.lower().endswith("_cov"):
            covs[stem[: -len("_cov")].lower()] = members.pop(path)

    statements = []
    errors = []
    for path, blob in members.items():
        cov_data = covs.get(_stem(path).lower())
        try:
            statements.extend(_parse_single(blob, cov_data=cov_data, filename=path))
        except UnsupportedFormat as exc:
            errors.append(f"{path}: {exc}")
    if not statements:
        if errors:
            raise UnsupportedFormat(
                "No importable statement found in the ZIP archive:\n"
                + "\n".join(errors)
            )
        raise UnsupportedFormat("No importable statement found in the ZIP archive")
    return statements


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name

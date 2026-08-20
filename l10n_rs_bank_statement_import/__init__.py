# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import importlib.util

from . import parsers  # noqa: F401 - pure Python, importable without Odoo

# The models subpackage needs Odoo; skip it when the package is imported for
# pure-python parser tests (plain pytest, no Odoo installed).
if importlib.util.find_spec("odoo"):
    from . import models  # noqa: F401

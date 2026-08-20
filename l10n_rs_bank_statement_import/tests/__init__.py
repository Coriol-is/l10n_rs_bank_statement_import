# Copyright 2026 Coriolis Lab
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
#
# test_halcom / test_asseco / test_rol are pure pytest suites for the parser
# core and are intentionally NOT imported here (Odoo's test runner only
# executes what this package imports).  test_import is the Odoo-level test.
import importlib.util

if importlib.util.find_spec("odoo"):
    from . import test_import  # noqa: F401

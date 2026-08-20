"""Make the addon package importable when running plain pytest from the
repository root (the parsers subpackage is pure Python)."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

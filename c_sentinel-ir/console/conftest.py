"""
conftest.py - make `console` and `common` importable when pytest collects
console/.

The console, like the SOC layer, relies on `c_sentinel-ir/` (this file's
parent's parent) being importable so that `import console...`, `import soc...`
and `import common...` all resolve. Adding it here keeps the test invocation a
bare `python -m pytest console`.

Author: Colile
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIBS = _PROJECT_ROOT / "libs"

for path in (_PROJECT_ROOT, _LIBS):
    entry = str(path)
    if entry not in sys.path:
        sys.path.insert(0, entry)

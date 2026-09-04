"""
conftest.py - make `soc` and `common` importable when pytest collects soc/.

The services put `libs/` on `sys.path` themselves; the SOC layer instead relies
on `c_sentinel-ir/` (this file's parent's parent) being importable so that both
`import soc...` and `import common...` resolve. Adding it here keeps the test
invocation a bare `python -m pytest soc`.

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

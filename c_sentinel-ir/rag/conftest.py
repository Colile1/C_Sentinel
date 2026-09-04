"""
conftest.py - make `rag`, `kg`, `soc` and `common` importable when pytest
collects rag/.

Mirrors `soc/conftest.py` and `kg/conftest.py`: `c_sentinel-ir/` (this file's
parent) and `c_sentinel-ir/libs/` go on `sys.path`, so `import rag...`,
`import kg...` and `import common...` all resolve and the test invocation stays
a bare `python -m pytest rag`.

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

"""
conftest.py - make `kg`, `soc` and `common` importable when pytest collects kg/.

Mirrors `soc/conftest.py`: the SOC and KG layers rely on `c_sentinel-ir/` (this
file's parent) and `c_sentinel-ir/libs/` being on `sys.path` so `import kg...`,
`import soc...` and `import common...` all resolve, keeping the test invocation
a bare `python -m pytest kg`.

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

"""
__init__.py - the alert service package.

Holds the alert schema fixed by the Phase 2 specification, and (from step 16)
its store and API. The model lives here rather than in `soc/rules` because an
alert is a contract shared by the rules that raise it, the API that serves it
and the knowledge-graph loader that projects it - the same reason the security
event schema lives in `libs/common`.

Author: Colile
"""

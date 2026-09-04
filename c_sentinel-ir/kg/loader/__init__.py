"""
__init__.py - the graph loader package.

One loader per required source - `load_topology`, `load_events`,
`load_security_knowledge` - plus `main`, the thin orchestrator that applies the
schema then runs the three in order. `connection.py` is the only place Neo4j
connection details live. Every loader is idempotent: `MERGE`, never blind
`CREATE`.

Author: Colile
"""

"""
main.py - the graph loader orchestrator: schema, then the three sources in order.

  python -m kg.loader.main --file docs/evidence/step15-attack-events.jsonl
  python -m kg.loader.main                    # the running stack's logs

Steps, in order, because each MATCHes what the previous one MERGEd:
  1. apply kg/model/schema.cypher (constraints and indexes)
  2. load_topology  - services, endpoints, the dependency, users, assets
  3. load_events    - every collected event and raised alert, with their edges
  4. load_security_knowledge - MITRE T1110 and the rest, plus INDICATES

Events and alerts come from the same place `soc.rules.main` gets them: the
collector builds the event store from the chosen source, the rule catalogue is
evaluated against it, and the alerts land in the shared `AlertStore` - so the
graph holds exactly the alerts the rules would raise on that stream.

`--dry-run` prints the write counts per source without touching Neo4j, for a
check that does not need a database.

Author: Colile
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from soc.alert_service.store import AlertStore
from soc.collector.main import build_store, select_source
from soc.collector.store import EventStore, parse_timestamp
from soc.rules.catalogue import evaluate_all
from kg.loader.connection import close_driver, database_name, get_driver
from kg.loader.load_events import events as events_writes
from kg.loader.load_events import with_stable_ids
from kg.loader.load_security_knowledge import knowledge as knowledge_writes
from kg.loader.load_topology import topology as topology_writes
from kg.loader.writes import Write, apply

_SCHEMA_FILE = Path(__file__).resolve().parents[1] / "model" / "schema.cypher"


def schema_statements() -> list[str]:
    """
    Purpose: the constraint and index statements from `schema.cypher`, split on
             `;` and stripped of comments and blank lines.
    Inputs:  none.
    Output:  a list of executable Cypher statements.
    """
    text = _SCHEMA_FILE.read_text(encoding="utf-8")
    lines = [
        line for line in text.splitlines() if not line.strip().startswith("//")
    ]
    body = "\n".join(lines)
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


def _latest_moment(store: EventStore) -> datetime:
    """
    Purpose: the evaluation moment for the rules - the newest event's timestamp
             for a captured file, the clock for a live run.
    Inputs:  store - the populated event store.
    Output:  a timezone-aware UTC datetime.
    """
    events = store.all_events()
    if events:
        return parse_timestamp(events[-1].timestamp)
    return datetime.now(timezone.utc)


def collect_writes(store: EventStore) -> list[tuple[str, list[Write]]]:
    """
    Purpose: build every loader's write list from one event store, running the
             detection rules to populate the alert store first.
    Inputs:  store - the collector's populated `EventStore`.
    Output:  a list of (source name, writes) pairs, in apply order.
    """
    alerts = with_stable_ids(evaluate_all(store, _latest_moment(store)))
    alert_store = AlertStore()
    alert_store.extend(alerts)
    return [
        ("topology", topology_writes()),
        ("events", events_writes(store, alert_store)),
        ("security-knowledge", knowledge_writes()),
    ]


def _apply_schema(session) -> int:
    """Purpose: run every schema statement. Inputs: an open session.
    Output: the count applied."""
    statements = schema_statements()
    for statement in statements:
        session.run(statement)
    return len(statements)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Purpose: define and parse the command line. Inputs: argv or None.
    Output: the parsed namespace."""
    parser = argparse.ArgumentParser(
        prog="kg.loader.main",
        description="Load the Sentinel-IR knowledge graph from its three sources.",
    )
    parser.add_argument("--file", type=Path, default=None,
                        help="read newline-JSON events from this file")
    parser.add_argument("--stdin", action="store_true",
                        help="read events from standard input")
    parser.add_argument("--dry-run", action="store_true",
                        help="print write counts per source without touching Neo4j")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Purpose: wire the loader together - collect, build writes, apply schema and
             the three sources, report.
    Inputs:  argv - the argument list, or None for `sys.argv`.
    Output:  a process exit code: 0 on success, 1 on a collection or connection
             failure.
    """
    args = _parse_args(argv)
    try:
        store = build_store(select_source(args))
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1

    sources = collect_writes(store)
    print(f"Events collected: {len(store)}")
    for name, writes in sources:
        print(f"Writes for {name}: {len(writes)}")

    if args.dry_run:
        print("Dry run: Neo4j not contacted.")
        return 0

    try:
        driver = get_driver()
        with driver.session(database=database_name()) as session:
            applied = _apply_schema(session)
            print(f"Schema statements applied: {applied}")
            for name, writes in sources:
                count = apply(session, writes)
                print(f"Applied {name}: {count}")
    except Exception as exc:  # noqa: BLE001 - report any driver failure plainly
        print(f"Load failed: {exc}", file=sys.stderr)
        return 1
    finally:
        close_driver()

    print("Graph load complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

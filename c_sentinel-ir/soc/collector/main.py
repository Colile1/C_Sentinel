"""
main.py - the collector entry point: stream, validate, store, summarise.

Reads the Phase 1 event stream, builds an `EventStore` from it, and prints a
`Description: value` summary. No detection logic lives here - that is step 15.

Sources, in order of precedence:
  --file PATH        read newline-JSON from a file (used by the offline
                     evidence capture and by tests)
  (default)          run `docker compose -f deploy/docker-compose.yml logs
                     --no-color --no-log-prefix` and read its output
  --stdin            read `sys.stdin` (for `... logs -f | python -m
                     soc.collector.main --stdin`)

Author: Colile
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Iterator

from soc.collector.reader import stream_events
from soc.collector.store import EventStore

# The compose file, relative to the repository's c_sentinel-ir/ folder.
_COMPOSE_FILE = Path("deploy") / "docker-compose.yml"
_DOCKER_LOGS_COMMAND = [
    "docker",
    "compose",
    "-f",
    str(_COMPOSE_FILE),
    "logs",
    "--no-color",
    "--no-log-prefix",
]


def _lines_from_file(path: Path) -> Iterator[str]:
    """
    Purpose: yield each line of a log file.
    Inputs:  path - the file to read.
    Output:  an iterator of strings.
    """
    with path.open(encoding="utf-8") as handle:
        yield from handle


def _lines_from_docker() -> Iterator[str]:
    """
    Purpose: yield each line of `docker compose logs` for the running stack.
    Inputs:  none; runs the compose command in a subprocess.
    Output:  an iterator of strings.
    Raises:  `RuntimeError` if the command is missing or exits non-zero.
    """
    try:
        completed = subprocess.run(
            _DOCKER_LOGS_COMMAND,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "docker not found on PATH; use --file or --stdin instead"
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"`docker compose logs` failed ({exc.returncode}): {exc.stderr.strip()}"
        ) from exc
    yield from completed.stdout.splitlines()


def _select_source(args: argparse.Namespace) -> Iterator[str]:
    """
    Purpose: pick the line source from the parsed arguments.
    Inputs:  args - the parsed command line.
    Output:  an iterator of raw log lines.
    """
    if args.file is not None:
        return _lines_from_file(args.file)
    if args.stdin:
        return iter(sys.stdin)
    return _lines_from_docker()


def _print_summary(store: EventStore) -> None:
    """
    Purpose: report what was collected, in the project's `Description: value`
             output style.
    Inputs:  store - the populated event store.
    Output:  None; writes to stdout.
    """
    events = store.all_events()
    services = sorted({event.service_name for event in events})
    correlations = sorted({event.correlation_id for event in events})
    event_types = sorted({event.event_type.value for event in events})
    print(f"Events collected: {len(events)}")
    print(f"Distinct services: {len(services)} ({', '.join(services) or 'none'})")
    print(f"Distinct correlation IDs: {len(correlations)}")
    print(f"Event types seen: {', '.join(event_types) or 'none'}")


def build_store(lines: Iterator[str]) -> EventStore:
    """
    Purpose: the collector proper - stream the lines through the reader and
             append every event to a fresh store.
    Inputs:  lines - an iterator of raw log lines.
    Output:  a populated `EventStore`.
    Raises:  `MalformedEventError` from the reader on a bad event line.
    """
    store = EventStore()
    store.extend(stream_events(lines))
    return store


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """
    Purpose: define and parse the command line.
    Inputs:  argv - the argument list, or None for `sys.argv`.
    Output:  the parsed namespace.
    """
    parser = argparse.ArgumentParser(
        prog="soc.collector.main",
        description="Collect Phase 1 security events into a queryable store.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="read newline-JSON events from this file instead of docker",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="read events from standard input instead of docker",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Purpose: wire the entry point together.
    Inputs:  argv - the argument list, or None for `sys.argv`.
    Output:  a process exit code: 0 on success, 1 on a collection failure.
    """
    args = _parse_args(argv)
    try:
        store = build_store(_select_source(args))
    except (RuntimeError, OSError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        return 1
    _print_summary(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

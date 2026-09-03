"""
correlation.py - the request-scoped correlation identifier.

The central invariant of Sentinel-IR is that every request crossing the system
carries one `X-Correlation-ID`, so a single workflow can be traced through the
gateway and all three services. This module owns that value and nothing else,
kept apart from `logging.py` so business logic can read the current correlation
id without importing the logging stack.

The value lives in a `ContextVar`, so it is per-task and safe under FastAPI's
concurrency: two requests handled at once never see each other's id.

Author: Colile
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

# The canonical header name. Every service and the gateway use this spelling.
CORRELATION_ID_HEADER = "X-Correlation-ID"

_UNSET = "-"

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default=_UNSET)


def new_correlation_id() -> str:
    """
    Purpose: mint a correlation id for a request that arrived without one.
    Inputs:  none.
    Output:  a string `corr-` followed by 12 hexadecimal characters.
    """
    return f"corr-{uuid.uuid4().hex[:12]}"


def get_correlation_id() -> str:
    """
    Purpose: read the correlation id of the request being handled.
    Inputs:  none.
    Output:  the current id, or `-` when called outside a request, which is
             what background startup logging produces.
    """
    return _correlation_id.get()


def set_correlation_id(correlation_id: str) -> Token[str]:
    """
    Purpose: bind a correlation id to the current context for the life of one
             request.
    Inputs:  correlation_id - the id taken from the request header, or a newly
             minted one when the header was absent.
    Output:  the reset token, which the caller passes to `reset_correlation_id`
             so the previous value is restored and contexts do not leak.
    """
    return _correlation_id.set(correlation_id)


def reset_correlation_id(token: Token[str]) -> None:
    """
    Purpose: restore the correlation id that was current before `set`.
    Inputs:  token - the token returned by `set_correlation_id`.
    Output:  None.
    """
    _correlation_id.reset(token)

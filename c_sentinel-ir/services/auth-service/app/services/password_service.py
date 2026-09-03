"""
password_service.py - the only place auth-service hashes or checks a password.

Bcrypt is used directly rather than through passlib: passlib 1.7.4 probes
`bcrypt.__about__`, which bcrypt 4.1+ removed, and every hash call then fails.
See DECISIONS.md D-05. Keeping both operations behind this one module means the
algorithm is swappable in one file and nothing else in the service ever sees a
plaintext password after this point.

Pure: no database, no HTTP, no FastAPI.

Author: Colile
"""

from __future__ import annotations

import bcrypt

from common.errors import ValidationError

# Bcrypt hashes at most 72 bytes of input and silently ignores the rest, so a
# 200-character password would share a hash with its own first 72 bytes. We
# reject rather than truncate: silent truncation is a real authentication
# weakness that no test would ever notice.
MAX_PASSWORD_BYTES = 72

MIN_PASSWORD_LENGTH = 8


def hash_password(plain: str) -> str:
    """
    Purpose: turn a plaintext password into a storable bcrypt hash.
    Inputs:  plain - the password as typed by the user.
    Output:  the bcrypt hash as a UTF-8 string, salt included.
    Raises:  `ValidationError` when the password is too short, or longer than
             bcrypt can hash without truncating it.
    """
    encoded = _validated_bytes(plain)
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Purpose: check a supplied password against a stored hash.
    Inputs:  plain - the password as typed.
             hashed - the stored bcrypt hash.
    Output:  True when they match, False otherwise. A malformed or empty stored
             hash returns False rather than raising: a corrupt row must fail the
             login, not the service.
    """
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # bcrypt raises this on a hash that is not in its format at all.
        return False


def _validated_bytes(plain: str) -> bytes:
    """
    Purpose: enforce the password rules once, where hashing happens.
    Inputs:  plain - the candidate password.
    Output:  the password encoded as UTF-8 bytes.
    Raises:  `ValidationError` naming the field and the rule it broke.
    """
    if len(plain) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            {"field": "password", "rule": f"min_length={MIN_PASSWORD_LENGTH}"},
        )
    encoded = plain.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValidationError(
            f"Password must be at most {MAX_PASSWORD_BYTES} bytes; bcrypt "
            "ignores anything beyond that.",
            {"field": "password", "rule": f"max_bytes={MAX_PASSWORD_BYTES}"},
        )
    return encoded

"""Connection settings are REQUIRED, not defaulted.

Every place that opened a PostgreSQL connection read its settings with a
fallback — `config.get('username', 'vitalgraph_user')`, and the same for host,
port, database and password. A caller whose key was missing or misspelled did not
get an error. It got a connection attempt against
`vitalgraph_user@localhost:5432/vitalgraph`, credentials nobody configured.

The benign outcome is an authentication failure naming a user that appears
nowhere in the config — confusing, but loud. The dangerous outcome is an
environment where that database DOES exist: the wrong target answers, the caller
reports success, and every query is correct about the wrong data. That is
`issues/055`, where fixtures were written to one cluster and read from another
and both ends reported success because same-named spaces existed.

This is not hypothetical for this config dict. `config_loader` carries a comment
recording that SQLAlchemy-style `pool_size`/`max_overflow` keys were silently
ignored by asyncpg, leaving `max_size` at a hardcoded 15 — the same shape, in the
same dictionary, already hit once.

SPELLING. The key is `username`, but asyncpg's parameter is `user`, so the
mismatch is easy to make. With a default it was silent; now the error names the
key that was not found and lists the keys that were, which makes a typo obvious.
"""

from __future__ import annotations

from typing import Any, Dict

# Everything needed to name a database. A default for ANY of these can silently
# redirect a connection, so none of them has one.
REQUIRED_KEYS = ("host", "port", "database", "username", "password")


def require(config: Dict[str, Any], key: str) -> Any:
    """Read a connection setting, or raise naming what is missing.

    `password` may legitimately be an empty string (trust authentication), so
    this tests for the KEY's presence rather than the value's truthiness.
    """
    if key not in config:
        present = ", ".join(sorted(str(k) for k in config)) or "nothing"
        raise ValueError(
            f"database config is missing {key!r}; it has: {present}. "
            f"All of {', '.join(REQUIRED_KEYS)} are required — a default here "
            f"would connect somewhere nobody configured."
        )
    return config[key]

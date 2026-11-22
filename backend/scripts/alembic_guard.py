"""Fail-closed target validation for online Alembic commands."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

from sqlalchemy.engine import URL, make_url


def resolve_database_url(settings_url: str, environ: Mapping[str, str] | None = None) -> str:
    """Prefer an explicit Alembic URL, falling back to the application setting."""
    env = os.environ if environ is None else environ
    if "ALEMBIC_DATABASE_URL" in env:
        return env["ALEMBIC_DATABASE_URL"]
    return settings_url


def database_target(database_url: str) -> tuple[str, str]:
    """Return only the host and database name; never include URL credentials."""
    parsed: URL = make_url(database_url)
    host = parsed.host or "localhost"
    database = parsed.database or ""
    # SQLite URLs store paths in `database`; report only the final path component.
    database = database.rstrip("/").rsplit("/", 1)[-1]
    return host, database


def enforce_database_target(
    database_url: str,
    *,
    target: str | None = None,
    confirmation: str | None = None,
    offline: bool = False,
    stream=None,
) -> None:
    """Reject unsafe online targets before Alembic opens a connection.

    Offline SQL generation is deliberately exempt because it makes no database
    connection. Any online operation against a non-test database requires an
    exact database-name confirmation.
    """
    if offline:
        return
    if stream is None:
        stream = sys.stderr
    try:
        host, database = database_target(database_url)
    except Exception:
        print("Alembic safety guard: invalid database URL; refusing online operation.", file=stream)
        raise SystemExit(2) from None

    is_test_database = "test" in database.casefold()
    safe_target = f"host={host} database={database or '<empty>'}"
    if target == "test" and not is_test_database:
        print(
            f"Alembic safety guard: ALEMBIC_TARGET=test requires a database name containing 'test'; {safe_target}.",
            file=stream,
        )
        raise SystemExit(2)
    if not is_test_database and confirmation != database:
        print(
            f"Alembic safety guard: online Alembic access refused without ALEMBIC_CONFIRM_DB={database!r}; {safe_target}.",
            file=stream,
        )
        raise SystemExit(2)

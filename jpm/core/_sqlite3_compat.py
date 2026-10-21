"""PG-only connection shim — no SQLite fallback.
import typing

Replaces ``sqlite3.connect(...)`` with ``sync_conn()`` when PG is enabled.
When PG is not enabled, raises RuntimeError — no SQLite fallback to
prevent ghost database files (sessions.db, etc.).

This is a compatibility shim for SessionDB and CLI tools that still
use the sqlite3.Connection API. New code should use sync_conn() directly.
"""

from __future__ import annotations

from typing import Any

from jpm.core._pg import sync_conn, is_pg_enabled

# Re-export common exception types

OperationalError = RuntimeError
DatabaseError = RuntimeError

# ── Shim ──

class _CompatRow:
    """sqlite3.Row-compatible wrapper that supports both dict and integer access."""
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._keys = list(data.keys())
        self._col_names = self._keys  # sqlite3.Row compatibility

    def keys(self) -> list[str]:
        return self._keys

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, str):
            return self._data[key]
        return self._data[self._keys[key]]

    def __getattr__(self, name: str) -> Any:
        if name in self._data:
            return self._data[name]
        raise AttributeError(name)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __iter__(self):
        return iter(self._data.values())

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return repr(self._data)


class _CompatCursor:
    """Bare-minimum sqlite3.Cursor-compatible wrapper around PGConnection."""
    def __init__(self, conn: Any) -> None:
        self._conn = conn
        self.rowcount = -1

    def execute(self, sql: str, params: tuple = ()) -> _CompatCursor:
        self._conn.execute(sql, params)
        self.rowcount = self._conn.rowcount
        return self

    def executemany(self, sql: str, seq_of_params: list[tuple]) -> None:
        self._conn.executemany(sql, seq_of_params)

    def fetchone(self) -> typing.Optional[dict[str, Any]]:
        row = self._conn.fetchone_from_last()
        return _CompatRow(row) if row else None

    def fetchall(self) -> list[dict[str, Any]]:
        rows = self._conn.fetchall_from_last()
        return [_CompatRow(r) for r in rows]

    def fetchmany(self, size: int = 1) -> list[dict[str, Any]]:
        rows = self._conn.fetchmany(size)
        return [_CompatRow(r) for r in rows]

    @property
    def lastrowid(self) -> typing.Optional[int]:
        return self._conn.lastrowid

    @property
    def description(self) -> Any:
        return None

    def close(self) -> None:
        pass


class _PGCompatConnection:
    """Wraps PGConnection to look like sqlite3.Connection for SessionDB.

    Holds the sync_conn() context manager open so the pooled connection
    isn't released back to the pool prematurely.
    """

    def __init__(self, pg_conn: Any, ctx: Any) -> None:
        self._c = pg_conn
        self._ctx = ctx  # Keep context manager alive
        self._transactions = 0

    def execute(self, sql: str, params: tuple = ()) -> _CompatCursor:
        self._c.execute(sql, params)
        return _CompatCursor(self._c)

    def executemany(self, sql: str, seq_of_params: list[tuple]) -> None:
        self._c.executemany(sql, seq_of_params)

    def executescript(self, script: str) -> None:
        self._c.executescript(script)

    def cursor(self) -> _CompatCursor:
        return _CompatCursor(self._c)

    def commit(self) -> None:
        pass  # PG autocommits

    def rollback(self) -> None:
        pass  # Not needed for PG

    def close(self) -> None:
        """Release the PG connection back to the pool."""
        self._ctx.__exit__(None, None, None)
        self._c = None
        self._ctx = None

    def __enter__(self) -> _PGCompatConnection:
        self._transactions += 1
        return self

    def __exit__(self, *args: Any) -> None:
        self._transactions -= 1


# ── Shims for module-level functions ──

def connect(database: str, **kwargs: Any) -> _PGCompatConnection:
    """Route to PG when enabled, raise if not.

    ``database`` and ``**kwargs`` are accepted for signature compatibility
    but ignored — the actual target database is controlled by PG env vars
    (JPM_PG_*). Raises RuntimeError if PG is not configured — no SQLite
    fallback to prevent ghost database files.
    """
    if not is_pg_enabled():
        raise RuntimeError(
            "PG is not enabled — cannot connect. Set JPM_PG_HOST or use sync_conn() directly. "
            "SQLite fallback has been removed to prevent ghost database files."
        )
    # PG active — use sync_conn() and wrap it
    ctx = sync_conn()
    raw = ctx.__enter__()
    return _PGCompatConnection(raw, ctx)


# ── Convenience: one-call init helper ──

def maybe_pg_connect(
    database: str,
    label: str = "SessionDB",
    **kwargs: Any,
) -> _PGCompatConnection:
    """Connect to PG; apply schema. Raises if PG not enabled.

    This is the intended replacement for ``sqlite3.connect(path)``
    at the top of SessionDB.__init__.
    """
    from jpm.core._pg import apply_schema
    apply_schema()
    return connect(database, **kwargs)
# Re-export Row for type hints in kanban_db, heartbeat, etc.
Row = _CompatRow

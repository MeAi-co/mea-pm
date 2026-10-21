"""PostgreSQL wrapper for JPM — asyncpg singleton with sync_conn().
import typing

Architecture:
  - Single background event loop thread (daemon) started on first use
  - asyncpg connection pool (min=2, max=10)
  - sync_conn() context manager bridges async → sync via run_coroutine_threadsafe()
  - PGConnection wraps asyncpg Record → dict-compatible results
  - ? placeholders auto-converted to $1, $2, ... for PG compatibility
  - Raises RuntimeError when PG is unreachable (no SQLite fallback)

Env vars (per-agent):
  JPM_PG_HOST     — required; raises RuntimeError if not set
  JPM_PG_PORT     — default: 5432
  JPM_PG_DB       — default: jpm
  JPM_PG_USER     — default: postgres
  JPM_PG_PASSWORD — default: (from .pgpass or empty)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import re
import threading
from contextlib import contextmanager
from typing import Any, Iterator

LOG = logging.getLogger(__name__)

# ── Singleton state ──────────────────────────────────────────────────────
_background_loop: asyncio.AbstractEventLoop | None = None
_pool: Any = None  # asyncpg.Pool
_pg_enabled: typing.Optional[bool] = None  # None = not checked yet

# ── Config ────────────────────────────────────────────────────────────────

def _get_pg_config() -> typing.Optional[dict[str, Any]]:
    """Read PG connection config from env vars. Returns None if not configured."""
    host = os.environ.get("JPM_PG_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("JPM_PG_PORT", "5432")),
        "database": os.environ.get("JPM_PG_DB", "jpm"),
        "user": os.environ.get("JPM_PG_USER", "postgres"),
        "password": os.environ.get("JPM_PG_PASSWORD", ""),
    }


def is_pg_enabled() -> bool:
    """Check if PG is configured and reachable.

    Only caches the *True* result — if PG was unreachable at module
    import time (e.g. .env not yet loaded), the next call re-checks
    so the service can pick up env vars loaded after imports.

    Raises RuntimeError when JPM_PG_HOST is set but PG is unreachable
    — no silent fallback to SQLite when PG is configured.
    """
    global _pg_enabled
    if _pg_enabled is True:
        return True
    cfg = _get_pg_config()
    if cfg is None:
        LOG.debug("jpm-pg: not configured (JPM_PG_HOST not set), using SQLite")
        _pg_enabled = False
        return False
    # Quick connectivity check
    try:
        import psycopg2
        conn = psycopg2.connect(**cfg, connect_timeout=3)
        conn.close()
        _pg_enabled = True
        LOG.info("jpm-pg: connected to %s:%s/%s", cfg["host"], cfg["port"], cfg["database"])
    except ImportError:
        raise RuntimeError(
            "jpm-pg: JPM_PG_HOST is set but psycopg2 is not installed. "
            "Run from the joshaico venv or install psycopg2-binary."
        )
    except Exception as exc:
        _pg_enabled = False
        raise RuntimeError(
            f"jpm-pg: JPM_PG_HOST={cfg['host']} is set but PG is unreachable: {exc}"
        )
    return _pg_enabled


# ── Event loop + pool ────────────────────────────────────────────────────

def _get_loop() -> asyncio.AbstractEventLoop:
    """Start background event loop thread on first call."""
    global _background_loop
    if _background_loop is None:
        _background_loop = asyncio.new_event_loop()
        t = threading.Thread(target=_background_loop.run_forever, daemon=True)
        t.start()
        LOG.debug("jpm-pg: background event loop started")
    return _background_loop


def _local_tz_name() -> str:
    """Resolve the host's IANA timezone name for the PG session.

    The bench DB runs with TimeZone=Etc/UTC, so every column DEFAULT
    (CURRENT_TIMESTAMP) writes UTC while the application writes
    ``datetime.fromtimestamp()`` — i.e. LOCAL time. On this host that is a
    flat 4-hour skew between ``messages.timestamp`` and
    ``knowledge.created_at`` for rows written in the same second. Pinning the
    session timezone to the host zone makes CURRENT_TIMESTAMP agree with the
    app, so all timestamp columns are local system time.

    Resolution order: /etc/localtime symlink -> TZ env -> numeric offset.
    """
    import os
    try:
        link = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in link:
            return link.split(marker, 1)[1]
    except Exception:
        pass
    tz = os.environ.get("TZ")
    if tz:
        return tz
    # Last resort: fixed numeric offset PG accepts (e.g. "+04").
    from datetime import datetime
    off = datetime.now().astimezone().utcoffset()
    if off is not None:
        total = int(off.total_seconds())
        sign = "+" if total >= 0 else "-"
        total = abs(total)
        return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
    return "UTC"


async def _create_pool() -> Any:
    """Create asyncpg connection pool."""
    import asyncpg
    cfg = _get_pg_config()
    if cfg is None:
        raise RuntimeError("PG not configured")
    return await asyncpg.create_pool(
        **cfg,
        min_size=2,
        max_size=10,
        timeout=5,
        # Server-side safety net: abort any single statement that runs
        # longer than 60s. The per-call _run_with_timeout cancellation is
        # the primary guard; this ensures the server itself kills runaway
        # queries so a connection can never be held busy indefinitely.
        #
        # timezone: pin the session to the HOST zone so column DEFAULTs
        # (CURRENT_TIMESTAMP) match the app's local-time writes. Without
        # this the DB default is UTC and every *_at column is 4h behind
        # messages.timestamp on the same instant.
        server_settings={
            "statement_timeout": "60000",
            "timezone": _local_tz_name(),
        },
    )


def _ensure_pool() -> Any:
    """Ensure pool exists, return it."""
    global _pool
    if _pool is None:
        loop = _get_loop()
        future = asyncio.run_coroutine_threadsafe(_create_pool(), loop)
        try:
            _pool = future.result(timeout=10)
        except (asyncio.TimeoutError, TimeoutError) as e:
            msg = str(e) or f"{type(e).__name__} (no message)"
            raise RuntimeError(
                f"jpm-pg: pool creation timed out after 10s — "
                f"event loop may be busy streaming. {msg}"
            ) from e
        except Exception as e:
            msg = str(e) or f"{type(e).__name__} (no message)"
            raise RuntimeError(f"jpm-pg: pool creation failed: {msg}") from e
        LOG.info("jpm-pg: pool created (min=2, max=10)")
    return _pool


# ── Placeholder converter ───────────────────────────────────────────────

def _convert_placeholders(sql: str) -> str:
    """Convert ? placeholders to $1, $2, ... for PG compatibility.

    String-aware: a ``?`` inside a single-quoted string literal, a
    double-quoted identifier, a dollar-quoted string, or a comment is left
    untouched, so ``SELECT 'what?'`` is NOT mangled into ``SELECT 'what'$1``.

    NOTE: the jsonb ``?`` operator (``data ? 'key'``) is genuinely ambiguous
    with a placeholder and is still rewritten. For jsonb existence checks
    prefer ``data @> '{\"key\": true}'`` or ``jsonb_exists(data, 'key')``, or
    pass the key as a bound param (``data ? ?``) so the operator is written
    literally and the value is a placeholder.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    counter = 0
    while i < n:
        c = sql[i]
        # single-quoted string literal ('' escapes a quote)
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
            continue
        # double-quoted identifier ("" escapes a quote)
        if c == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(sql[i:j])
            i = j
            continue
        # dollar-quoted string ($$...$$ or $tag$...$tag$)
        if c == "$":
            m = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[i:])
            if m:
                tag = m.group(0)
                end = sql.find(tag, i + len(tag))
                if end != -1:
                    out.append(sql[i:end + len(tag)])
                    i = end + len(tag)
                    continue
        # line comment
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                j = n
            out.append(sql[i:j])
            i = j
            continue
        # block comment
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                j = n
            else:
                j += 2
            out.append(sql[i:j])
            i = j
            continue
        # placeholder
        if c == "?":
            counter += 1
            out.append(f"${counter}")
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ── PGConnection wrapper ────────────────────────────────────────────────

_STATUS_RE = re.compile(r"^(?:UPDATE|INSERT|DELETE|SELECT|MERGE|MOVE|FETCH|COPY)\s+(\d+)", re.IGNORECASE)
# asyncpg INSERT status is "INSERT <oid> <count>" — the row count is the
# SECOND number (the first is the table OID). e.g. "INSERT 0 3" = 3 rows.
_INSERT_STATUS_RE = re.compile(r"^INSERT\s+\d+\s+(\d+)", re.IGNORECASE)


def _parse_status_rowcount(status: str) -> int:
    """Parse asyncpg's status string ('UPDATE 3') into an int row count."""
    if not status:
        return 0
    m = _STATUS_RE.match(status)
    return int(m.group(1)) if m else 0


def _parse_insert_rowcount(status: str) -> int:
    """Parse asyncpg's INSERT status ('INSERT 0 3') into an int row count.

    asyncpg reports INSERT as ``INSERT <oid> <count>`` where the first
    number is the table OID and the second is the number of rows inserted.
    The generic ``_parse_status_rowcount`` would grab the OID (0), so this
    dedicated parser targets the second field.
    """
    if not status:
        return 0
    m = _INSERT_STATUS_RE.match(status)
    return int(m.group(1)) if m else 0


def _run_with_timeout(coro, timeout: float, what: str = "query"):
    """Run a coroutine on the background loop with a hard timeout.

    On timeout, the underlying task is CANCELLED (not just abandoned).
    This is critical: if we only let ``future.result(timeout=...)`` raise
    and walk away, the coroutine keeps running on the connection. The
    caller's ``sync_conn`` finally-block then tries to ROLLBACK + release
    a connection that is still busy, which asyncpg forbids — the next
    acquirer inherits a poisoned connection ("another operation is in
    progress"). Cancelling the task aborts the in-flight query so the
    connection returns to a clean state before release.

    Returns the coroutine's result, or raises asyncio.TimeoutError on
    timeout (after cancelling), or the original exception on failure.
    """
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        # Cancel the in-flight task so the connection frees up.
        future.cancel()
        # Give the loop a moment to actually process the cancellation so
        # the connection isn't released mid-query by sync_conn's finally.
        try:
            future.result(timeout=2)
        except (concurrent.futures.CancelledError, concurrent.futures.TimeoutError):
            pass
        except Exception:
            pass
        raise asyncio.TimeoutError(
            f"jpm-pg: {what} timed out after {timeout}s (task cancelled)"
        ) from None


class PGConnection:
    """Wraps an asyncpg connection for synchronous use.

    Compatible with the sqlite3.Connection interface used by JPM:
      - execute(sql, *params) → cursor-like
      - fetchone() / fetchall()
      - row_factory (no-op)
      - commit() (no-op — autocommit in PG)
      - close() (returns connection to pool)
    """

    def __init__(self, conn: Any, loop: asyncio.AbstractEventLoop):
        self._conn = conn
        self._loop = loop
        self._last_result: typing.Optional[list[dict[str, Any]]] = None
        self._lastrowid: typing.Optional[int] = None
        self._was_insert: bool = False
        self._rowcount: typing.Optional[int] = None
        self.row_factory = None  # compatibility shim

    @property
    def lastrowid(self) -> typing.Optional[int]:
        """Return the last inserted row ID (uses LASTVAL for PG)."""
        return self._lastrowid

    @property
    def rowcount(self) -> int:
        """Rows affected by the last statement (sqlite3-compatible shim).

        asyncpg execute() returns a status string like "UPDATE 3" or
        "SELECT 0"; we parse it on the write path. For SELECT the row
        count is the fetched result length when available, else 0.
        """
        if self._rowcount is not None:
            return self._rowcount
        if self._last_result is not None:
            return len(self._last_result)
        return 0

    def execute(self, sql: str, *args) -> PGConnection:
        """Execute SQL with ? → $N conversion. Returns self for chaining."""
        pg_sql = _convert_placeholders(sql)
        params = args[0] if args else ()
        _run_with_timeout(self._execute(pg_sql, params), 30, "execute")
        return self

    async def _execute(self, sql: str, params: tuple) -> None:
        stripped = sql.strip().upper()
        if stripped.startswith("SELECT") or stripped.startswith("WITH"):
            rows = await self._conn.fetch(sql, *params)
            self._last_result = [dict(r) for r in rows]
            self._was_insert = False
            self._rowcount = len(rows)
        elif stripped.startswith("INSERT") and "RETURNING" not in stripped:
            # Try with RETURNING id first; fall back to no RETURNING for
            # tables without an id column (compression_locks, state_meta, etc.)
            return_sql = sql.rstrip(";") + " RETURNING id"
            try:
                rows = await self._conn.fetch(return_sql, *params)
                self._last_result = None
                self._was_insert = True
                # fetch (not fetchrow) returns one row per inserted row, so
                # rowcount is the TRUE count: multi-row INSERTs report N,
                # and ON CONFLICT DO NOTHING on an existing row reports 0
                # (accurate — nothing was inserted, nothing rolled back).
                self._lastrowid = rows[0]["id"] if rows else None
                self._rowcount = len(rows)
            except Exception as ex:
                err_str = str(ex)
                if "column \"id\" does not exist" in err_str:
                    # Table has no id column — execute without RETURNING.
                    # The failed RETURNING id aborted the asyncpg transaction;
                    # ROLLBACK clears the aborted state so the fallback
                    # execute doesn't fail with InFailedSQLTransactionError.
                    await self._conn.execute("ROLLBACK")
                    status = await self._conn.execute(sql, *params)
                    self._last_result = None
                    self._was_insert = True
                    self._lastrowid = None
                    self._rowcount = _parse_insert_rowcount(status)
                else:
                    raise
        else:
            status = await self._conn.execute(sql, *params)
            self._last_result = None
            self._was_insert = False
            self._rowcount = _parse_status_rowcount(status)

    def executemany(self, sql: str, seq_of_params: list[tuple]) -> None:
        """Execute same SQL with multiple parameter sets."""
        pg_sql = _convert_placeholders(sql)
        _run_with_timeout(self._executemany(pg_sql, seq_of_params), 60, "executemany")

    async def _executemany(self, sql: str, seq_of_params: list[tuple]) -> None:
        await self._conn.executemany(sql, seq_of_params)

    def executescript(self, script: str) -> None:
        """Execute multi-statement SQL script, splitting on semicolons.

        asyncpg's ``execute()`` rejects multi-statement strings and
        ``pg_dump`` comment lines (``-- Type: TABLE; Schema: ...``).
        Split the dump into individual statements, strip comment lines,
        and execute each one separately.
        """
        statements: list[str] = []
        for line in script.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("--"):
                continue
            statements.append(line)
        full = "\n".join(statements)
        for stmt in full.split(";"):
            stmt = stmt.strip()
            if not stmt:
                continue
            _run_with_timeout(self._conn.execute(stmt), 60, "executescript")

    @contextmanager
    def transaction(self) -> Iterator["PGConnection"]:
        """Run a block of statements atomically in a single transaction.

        Wraps the body in BEGIN / COMMIT (or ROLLBACK on exception). This
        makes multi-statement writes crash-safe and serializes concurrent
        writers at the DB level. Use for delete-then-insert sequences where
        a crash between the two would otherwise lose data.

        Usage:
            with sync_conn() as conn:
                with conn.transaction():
                    conn.execute("DELETE FROM ... WHERE ...")
                    conn.execute("INSERT INTO ... VALUES (?, ?)", a, b)
        """
        loop = _get_loop()
        asyncio.run_coroutine_threadsafe(
            self._conn.execute("BEGIN"), loop
        ).result(timeout=10)
        try:
            yield self
        except BaseException:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._conn.execute("ROLLBACK"), loop
                ).result(timeout=10)
            except Exception:
                pass
            raise
        else:
            asyncio.run_coroutine_threadsafe(
                self._conn.execute("COMMIT"), loop
            ).result(timeout=10)

    def fetchone(self, sql: typing.Optional[str] = None, *args) -> typing.Optional[dict[str, Any]]:
        """Execute and return first row as dict, or None.

        Supports two calling patterns:
          fetchone(sql, *params) — direct fetch
          cur.fetchone() — from last execute() results (cursor-style)
        """
        if sql is None:
            return self.fetchone_from_last()
        pg_sql = _convert_placeholders(sql)
        params = args[0] if args else ()
        return _run_with_timeout(self._fetchone(pg_sql, params), 30, "fetchone")

    async def _fetchone(self, sql: str, params: tuple) -> typing.Optional[dict[str, Any]]:
        row = await self._conn.fetchrow(sql, *params)
        self._last_result = [dict(row)] if row else []
        return dict(row) if row else None

    def fetchall(self, sql: typing.Optional[str] = None, *args) -> list[dict[str, Any]]:
        """Execute and return all rows as list of dicts.

        Supports two calling patterns:
          fetchall(sql, *params) — direct fetch
          cur.fetchall() — from last execute() results (cursor-style)
        """
        if sql is None:
            return self.fetchall_from_last()
        pg_sql = _convert_placeholders(sql)
        params = args[0] if args else ()
        return _run_with_timeout(self._fetchall(pg_sql, params), 30, "fetchall")

    async def _fetchall(self, sql: str, params: tuple) -> list[dict[str, Any]]:
        rows = await self._conn.fetch(sql, *params)
        return [dict(r) for r in rows]

    def fetchmany(self, size: int = 1) -> list[dict[str, Any]]:
        """Return up to `size` rows from last result."""
        if self._last_result is None:
            return []
        result = self._last_result[:size]
        self._last_result = self._last_result[size:]
        return result

    def fetchall_from_last(self) -> list[dict[str, Any]]:
        """Return all rows from last execute()."""
        result = self._last_result or []
        self._last_result = None
        return result

    def fetchone_from_last(self) -> typing.Optional[dict[str, Any]]:
        """Return first row from last execute()."""
        if not self._last_result:
            return None
        return self._last_result[0]

    def commit(self) -> None:
        """No-op — PG is autocommit by default."""

    def close(self) -> None:
        """Return connection to pool."""
        self._last_result = None
        # Connection is managed by pool — no explicit close needed

    def cursor(self) -> PGConnection:
        """Return self as cursor-compatible object."""
        return self

    @property
    def description(self) -> typing.Optional[list[tuple[str]]]:
        """Compatibility shim for sqlite3 cursor.description."""
        return None


async def _reset_connection_transaction(raw_conn: Any) -> None:
    """Reset the connection's transaction state before returning to pool.

    If a previous operation left the connection in an aborted transaction,
    all subsequent statements on this connection fail silently with
    "current transaction is aborted, commands ignored until end of
    transaction block".  ROLLBACK clears the aborted state so the next
    user of this pooled connection sees a clean slate.
    """
    try:
        await raw_conn.execute("ROLLBACK")
    except Exception:
        pass  # No active transaction — expected on clean connections


# ── Context manager ──────────────────────────────────────────────────────

@contextmanager
def sync_conn() -> Iterator[PGConnection]:
    """Synchronous connection context manager via background event loop.

    Usage:
        with sync_conn() as conn:
            row = conn.fetchone("SELECT * FROM knowledge WHERE id = $1", fact_id)

    Requires JPM_PG_HOST to be set. Raises RuntimeError if PG is configured
    but unreachable. No SQLite fallback — PG is the only backend.
    """
    if not is_pg_enabled():
        raise RuntimeError(
            "sync_conn: JPM_PG_HOST is not set or PG is unreachable. "
            "JPM requires PostgreSQL — no SQLite fallback available."
        )

    pool = _ensure_pool()
    loop = _get_loop()
    # pool.acquire() returns an async context manager; __aenter__ gives us the coroutine
    future = asyncio.run_coroutine_threadsafe(
        pool.acquire(timeout=5).__aenter__(), loop
    )
    try:
        raw_conn = future.result(timeout=10)
    except (asyncio.TimeoutError, TimeoutError) as e:
        msg = str(e) or f"{type(e).__name__} (no message)"
        raise RuntimeError(
            f"sync_conn: PG pool acquire timed out after 10s — "
            f"event loop may be busy streaming. {msg}"
        ) from e
    except Exception as e:
        msg = str(e) or f"{type(e).__name__} (no message)"
        raise RuntimeError(f"sync_conn: PG pool acquire failed: {msg}") from e
    wrapper = PGConnection(raw_conn, loop)
    exc_in_finally: BaseException | None = None
    try:
        yield wrapper
    except BaseException as sync_conn_exc:
        exc_in_finally = sync_conn_exc
        raise
    finally:
        # ── Return the connection to a clean transaction state ───────
        # If the user code inside the context manager raised (or caught
        # and swallowed) a PG-sourced exception, the transaction may be
        # aborted.  Returning a poisoned connection to the pool means
        # the next acquirer inherits the aborted state and all its
        # statements fail silently — the "empty persisted transcript"
        # bug.
        try:
            asyncio.run_coroutine_threadsafe(
                _reset_connection_transaction(raw_conn), loop
            ).result(timeout=5)
        except Exception:
            pass  # Best effort — the pool may already reject this conn
        finally:
            # ── Release connection back to pool ────────────────────────
            # IMPORTANT: must call .result() here, NOT fire-and-forget.
            # If the event loop is busy (e.g. processing the 30s schema
            # apply), a fire-and-forget release sits in the queue
            # indefinitely — the pool still counts the connection as
            # acquired, so all N pool connections leak, and the next
            # caller gets "too many clients" or a pool-acquire timeout.
            try:
                asyncio.run_coroutine_threadsafe(
                    pool.release(raw_conn), loop
                ).result(timeout=5)
            except Exception:
                pass  # Best effort — the pool may already reject this conn


# ── Schema application ───────────────────────────────────────────────────

def apply_schema() -> None:
    """Apply PG schema to the configured database."""
    if not is_pg_enabled():
        LOG.info("jpm-pg: schema apply skipped (PG not enabled)")
        return

    schema_path = os.path.join(os.path.dirname(__file__), "_schema_pg.sql")
    if not os.path.isfile(schema_path):
        LOG.warning("jpm-pg: schema file not found at %s", schema_path)
        return

    with open(schema_path) as f:
        schema_sql = f.read()

    pool = _ensure_pool()
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(
        _apply_schema_async(pool, schema_sql), loop
    )
    future.result(timeout=60)
    LOG.info("jpm-pg: schema applied")


async def _apply_schema_async(pool: Any, schema_sql: str) -> None:
    async with pool.acquire() as conn:
        # ── Safety: clear any leftover poisoned transaction state ───────
        # If a previous migration run left the connection in an aborted
        # transaction state, ROLLBACK clears it so subsequent statements
        # don't all fail with "current transaction is aborted".
        try:
            await conn.execute("ROLLBACK")
        except Exception:
            pass  # No active transaction to roll back — expected on fresh connections

        # ── Pre-migration: dedup messages table ────────────────────────
        # Before creating the UNIQUE index on (session_id, role, timestamp),
        # remove any duplicate rows that accumulated from the old compaction
        # path (bare INSERT with no ON CONFLICT).  This lets fleet nodes
        # pull + restart without a manual dedup step.
        # NOTE: the NOT IN anti-join is O(n²) on 200K+ rows — always check
        # for actual duplicates first to avoid a 60s+ no-op on every restart.
        try:
            dup_row = await conn.fetchrow(
                "SELECT count(*) - count(DISTINCT (session_id, role, timestamp)) AS dupes FROM messages"
            )
            dup_count = dup_row["dupes"] if dup_row else 0
            if dup_count:
                dedup_sql = """\
                    DELETE FROM messages
                    WHERE id NOT IN (
                        SELECT MIN(id) FROM messages
                        GROUP BY session_id, role, timestamp
                    )
                """
                tag = await conn.execute(dedup_sql)
                deleted = 0
                if tag and tag.startswith("DELETE "):
                    try:
                        deleted = int(tag.split(" ")[1])
                    except (IndexError, ValueError):
                        pass
                LOG.info("jpm-pg: deduped %s duplicate message rows", deleted)
            else:
                LOG.debug("jpm-pg: no duplicate messages to dedup")
        except Exception as exc:
            LOG.warning("jpm-pg: message dedup failed (continuing): %s", exc)

        # ── Pre-step: ensure pgvector extension ────────────────────────
        # The base schema declares `vector(768)` columns (skills.embedding,
        # and the 5 retrieval tables via migration 0029). If the extension
        # isn't present BEFORE the base-schema loop runs, the skills table
        # fails to create (`type "vector" does not exist`) and every
        # vector/timestamp migration cascades. The CREATE EXTENSION line in
        # _schema_pg.sql is NOT reliable on its own — a single failed
        # statement in the 481-statement loop is swallowed and the loop
        # continues, leaving the DB half-applied. So we create + VERIFY the
        # extension here, deterministically, and fail fast if it's missing.
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            ext_row = await conn.fetchrow(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            )
            if ext_row is None:
                raise RuntimeError(
                    "pgvector extension 'vector' is not available. Install "
                    "pgvector (e.g. use the pgvector/pg17 image) or the "
                    "schema cannot create vector(768) columns."
                )
            LOG.info("jpm-pg: pgvector extension ensured")
        except Exception as exc:
            LOG.error(
                "jpm-pg: FATAL — cannot ensure pgvector extension: %s. "
                "Aborting schema apply to avoid a half-applied DB.",
                exc,
            )
            raise

        # ── Apply schema ───────────────────────────────────────────────
        # Split into individual statements, respecting $$-quoted blocks
        # (DO $$ ... END $$;) that contain semicolons internally.
        # Skip the entire base schema if the sentinel table already exists
        # — the 481-statement loop takes ~30s and is pure no-op on re-runs.
        try:
            row = await conn.fetchrow(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name='_schema_migrations'"
            )
            schema_already_applied = row is not None
        except Exception:
            schema_already_applied = False

        if not schema_already_applied:
            statements = _split_sql_statements(schema_sql)
            for stmt in statements:
                try:
                    async with conn.transaction():
                        await conn.execute(stmt)
                except Exception as exc:
                    exc_str = str(exc)
                    # "already exists" and "multiple primary keys" are expected
                    # on re-runs — skip the warning
                    if "already exists" in exc_str or "multiple primary keys" in exc_str:
                        continue
                    LOG.warning(
                        "jpm-pg: schema statement failed (continuing): %s\n%s",
                        exc, stmt[:200],
                    )
        else:
            LOG.info("jpm-pg: base schema already applied (sentinel found), skipping 481-statement loop")

        # ── Apply migrations ───────────────────────────────────────────
        # Run numbered migration files in order after the base schema.
        # Each migration is tracked in _schema_migrations so it runs
        # exactly once — preventing "tuple concurrently updated" races
        # when two gateways restart simultaneously.
        _migrations_dir = os.path.join(os.path.dirname(__file__), "_migrations")
        if os.path.isdir(_migrations_dir):
            migration_files = sorted(
                f for f in os.listdir(_migrations_dir) if f.endswith(".sql")
            )
            for mf in migration_files:
                # Check if this migration was already applied
                try:
                    row = await conn.fetchrow(
                        "SELECT 1 FROM public._schema_migrations WHERE name = $1",
                        mf,
                    )
                    if row is not None:
                        LOG.debug("jpm-pg: migration %s already applied, skipping", mf)
                        continue
                except Exception:
                    pass  # _schema_migrations table may not exist yet — run the migration

                mpath = os.path.join(_migrations_dir, mf)
                try:
                    with open(mpath) as f:
                        migration_sql = f.read()
                    mstatements = _split_sql_statements(migration_sql)
                    migration_failed = False
                    failed_stmt_count = 0
                    for mstmt in mstatements:
                        try:
                            # Nested conn.transaction() auto-creates savepoints
                            async with conn.transaction():
                                await conn.execute(mstmt)
                        except Exception as exc:
                            exc_str = str(exc)
                            if "already exists" in exc_str or "multiple primary keys" in exc_str:
                                continue
                            # Real failure — flag it so we DON'T mark this
                            # migration applied. Re-running on next start is
                            # safe for idempotent migrations (retried
                            # statements hit the benign "already exists" path
                            # above). Marking a half-failed migration applied
                            # was the root cause of the 0034 incident.
                            migration_failed = True
                            failed_stmt_count += 1
                            LOG.warning(
                                "jpm-pg: migration %s statement failed (continuing): %s\n%s",
                                mf, exc, mstmt[:200],
                            )
                    if not migration_failed:
                        # Only record the migration as applied if EVERY
                        # statement succeeded. A partial failure must leave the
                        # migration unrecorded so it retries on next startup.
                        try:
                            await conn.execute(
                                "INSERT INTO public._schema_migrations (name) VALUES ($1) "
                                "ON CONFLICT (name) DO NOTHING",
                                mf,
                            )
                        except Exception:
                            pass
                        LOG.info("jpm-pg: migration %s applied", mf)
                    else:
                        LOG.error(
                            "jpm-pg: migration %s had %d failed statement(s) — "
                            "NOT marked applied, will retry on next start",
                            mf, failed_stmt_count,
                        )
                except Exception as exc:
                    LOG.warning("jpm-pg: migration %s failed (continuing): %s", mf, exc)

        # ── Schema drift guard ─────────────────────────────────────────
        # The base schema only runs once, on a fresh DB (guarded by the
        # _schema_migrations sentinel). On existing nodes, only numbered
        # migrations in _migrations/ run. If a commit adds a column to the
        # base schema but forgets the matching numbered migration, the live
        # DB silently drifts — every write to that column fails with
        # 'column does not exist'. This guard parses the base schema for
        # CREATE TABLE column definitions and compares against
        # information_schema.columns, logging a loud warning for any missing
        # column so drift fails loudly at deploy time instead of silently
        # breaking message persistence.
        try:
            await _check_schema_drift_async(conn, schema_sql)
        except Exception as exc:
            LOG.warning("jpm-pg: schema drift check failed (continuing): %s", exc)


async def _check_schema_drift_async(conn: Any, schema_sql: str) -> None:
    """Detect base-schema columns missing from a live DB.

    Parses ``CREATE TABLE IF NOT EXISTS public.<name> ( ... )`` blocks from
    the base schema, extracts the column names, and compares them against
    ``information_schema.columns`` for the live database. Any base-schema
    column absent from the live table is reported as a loud warning naming
    the table, the missing column, and the likely cause (a base-schema edit
    without a matching numbered migration in ``_migrations/``).
    """
    table_re = re.compile(
        r"CREATE TABLE IF NOT EXISTS public\.(\w+)\s*\((.*?)\);",
        re.DOTALL,
    )
    col_re = re.compile(r"^\s+(\w+)\s+\S", re.MULTILINE)
    # Table-level constraint keywords that aren't column definitions.
    skip = {
        "PRIMARY", "UNIQUE", "FOREIGN", "CHECK", "EXCLUDE",
        "CONSTRAINT", "REFERENCES", "KEY",
    }

    expected: dict[str, set[str]] = {}
    for m in table_re.finditer(schema_sql):
        table = m.group(1)
        cols: set[str] = set()
        for cm in col_re.finditer(m.group(2)):
            name = cm.group(1)
            if name in skip:
                continue
            cols.add(name)
        if cols:
            expected[table] = cols

    if not expected:
        return

    for table, cols in expected.items():
        try:
            rows = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name=$1",
                table,
            )
        except Exception:
            continue  # table may not exist yet — not drift, just not created
        live = {r["column_name"] for r in rows}
        missing = cols - live
        if missing:
            LOG.warning(
                "jpm-pg: SCHEMA DRIFT — table %s is missing base-schema "
                "column(s) %s. A commit added these to _schema_pg.sql but no "
                "numbered migration in _migrations/ applied them to this live "
                "DB. Add a migration (e.g. ALTER TABLE %s ADD COLUMN IF NOT "
                "EXISTS ...) or writes to these columns will fail.",
                table, sorted(missing), table,
            )


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL into individual statements, respecting $$-quoting.

    A naive ``split(";")`` breaks DO $$ ... END $$; blocks because
    they contain semicolons inside the dollar-quoted body. This
    splitter uses a **stack** to track nested dollar-quote tags
    (``$$``, ``$_$``, ``$tag$``) and only splits on ``;`` when
    outside all dollar-quoted regions.
    """
    statements: list[str] = []
    current: list[str] = []
    dollar_stack: list[str] = []  # stack of open dollar-quote tags
    for line in sql.split("\n"):
        stripped = line.strip()
        # Skip comment lines and pg_dump meta-commands
        if stripped.startswith("--") or stripped.startswith("\\"):
            continue
        # Track dollar-quote boundaries using a stack.
        # Check $_$ first (3 chars) since it contains $$ (2 chars).
        pos = 0
        while pos < len(line):
            if line[pos : pos + 3] == "$_$":
                tag = "$_$"
            elif line[pos : pos + 2] == "$$":
                tag = "$$"
            else:
                pos += 1
                continue
            if dollar_stack and dollar_stack[-1] == tag:
                dollar_stack.pop()  # closing tag
            else:
                dollar_stack.append(tag)  # opening tag
            pos += len(tag)
        current.append(line)
        if not dollar_stack and stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
    # Catch any trailing statement without a semicolon
    remaining = "\n".join(current).strip()
    if remaining:
        statements.append(remaining)
    return statements


# ── Shutdown ─────────────────────────────────────────────────────────────

def record_gateway_event() -> None:
    """Record a gateway boot event in the gateway_events table.

    Called from start_gateway() after the boot fingerprint is recorded.
    Self-healing — creates the table if it doesn't exist yet (schema
    apply runs later via JPM init).
    Best-effort — never raises.
    """
    import socket
    try:
        commit_sha = ""
        try:
            from gateway.code_skew import _fingerprint
            fp = _fingerprint()
            if fp:
                commit_sha = fp.rsplit(":", 1)[-1][:10] if ":" in fp else fp[:10]
        except Exception:
            pass
        with sync_conn() as conn:
            # Self-healing: ensure table exists (schema apply runs later)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS gateway_events ("
                "  id BIGSERIAL PRIMARY KEY,"
                "  event_type TEXT NOT NULL DEFAULT 'boot',"
                "  commit_sha TEXT DEFAULT '',"
                "  pid INTEGER DEFAULT 0,"
                "  hostname TEXT DEFAULT '',"
                "  started_at REAL DEFAULT EXTRACT(EPOCH FROM NOW()),"
                "  created_at REAL DEFAULT EXTRACT(EPOCH FROM NOW())"
                ")"
            )
            conn.execute(
                "INSERT INTO gateway_events (event_type, commit_sha, pid, hostname) "
                "VALUES (?, ?, ?, ?)",
                ("boot", commit_sha, os.getpid(), socket.gethostname()[:64]),
            )
    except Exception as exc:
        LOG.debug("jpm-pg: record_gateway_event failed (non-fatal): %s", exc)


def get_last_gateway_event() -> dict[str, Any] | None:
    """Return the most recent gateway boot event, or None.

    Returns dict with keys: event_type, commit_sha, pid, hostname, started_at, created_at
    """
    try:
        with sync_conn() as conn:
            return conn.fetchone(
                "SELECT event_type, commit_sha, pid, hostname, started_at, created_at "
                "FROM gateway_events "
                "WHERE event_type = 'boot' "
                "ORDER BY started_at DESC LIMIT 1"
            )
    except Exception:
        return None


def shutdown() -> None:
    """Close pool and stop event loop."""
    global _pool, _background_loop, _pg_enabled
    if _pool is not None:
        loop = _get_loop()
        future = asyncio.run_coroutine_threadsafe(_pool.close(), loop)
        try:
            future.result(timeout=10)
        except Exception:
            pass
        _pool = None
    if _background_loop is not None:
        _background_loop.call_soon_threadsafe(_background_loop.stop)
        _background_loop = None
    _pg_enabled = None
    LOG.info("jpm-pg: shutdown complete")

"""anchor_store — DB persistence for the volatile session anchor (P6.5).

The fork keeps the anchor on the live agent (``agent._session_anchor``) and
injects it at API-call time. Stock hooks/middleware never receive the agent, so
the anchor is split across two seams:

  * GENERATION (DB-only) -> a detached subprocess writes the anchor here.
  * INJECTION (in-process) -> the ``llm_request`` middleware reads it here and
    inserts it at position 1 of the request messages.

Storage is a tiny dedicated table so the middleware read is a single indexed
lookup. Created lazily; best-effort (any failure returns None / no-ops).
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)

_TABLE = "mea_session_anchor"
# Per-loop turn counters live in their OWN table, keyed (session_id, loop).
# Sharing one counter across loops double-bumps it: two loops each calling
# bump_and_check on the same row advance it by 2 per turn, so the boundary is
# reached at half the interval and whichever loop bumps second "wins" the fire
# (resetting to 0) — the other loop then NEVER fires. One counter per loop.
_COUNTER_TABLE = "mea_loop_turns"


def _conn():
    from jpm.core._pg import sync_conn
    return sync_conn()


def _ensure(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_TABLE} ("
        "session_id text PRIMARY KEY, "
        "anchor text NOT NULL DEFAULT '', "
        "turns_since integer NOT NULL DEFAULT 0, "
        "updated_at timestamptz NOT NULL DEFAULT now())"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_COUNTER_TABLE} ("
        "session_id text NOT NULL, "
        "loop text NOT NULL, "
        "turns_since integer NOT NULL DEFAULT 0, "
        "updated_at timestamptz NOT NULL DEFAULT now(), "
        "PRIMARY KEY (session_id, loop))"
    )


def bump_and_check(session_id: str, interval: int, loop: str = "anchor") -> bool:
    """Increment *loop*'s per-session turn counter; True when it reaches *interval*.

    The fork regenerates the anchor on the NUDGE boundary only (never every
    turn) so the tail cache stays warm between nudges. The subprocess is
    stateless, so the counter lives in the DB. On fire the counter resets to 0.

    The counter is keyed ``(session_id, loop)`` — each loop owns its own row.
    A single shared counter is WRONG: two loops bumping it advance it by 2 per
    turn, so the boundary is hit at half the interval and the loop that bumps
    second resets it to 0, starving the other loop forever.
    """
    if not session_id or interval <= 0:
        return False
    try:
        with _conn() as conn:
            _ensure(conn)
            row = conn.execute(
                f"SELECT turns_since FROM {_COUNTER_TABLE} "
                "WHERE session_id = ? AND loop = ?",
                (session_id, loop),
            ).fetchone()
            cur = (row["turns_since"] if hasattr(row, "keys") else row[0]) if row else 0
            cur = int(cur or 0) + 1
            fire = cur >= interval
            new = 0 if fire else cur
            conn.execute(
                f"INSERT INTO {_COUNTER_TABLE} (session_id, loop, turns_since, updated_at) "
                "VALUES (?, ?, ?, now()) "
                "ON CONFLICT (session_id, loop) DO UPDATE "
                "SET turns_since = EXCLUDED.turns_since, updated_at = now()",
                (session_id, loop, new),
            )
        return fire
    except Exception as exc:
        LOG.debug("anchor_store: bump failed (%s)", exc)
        return False


def get_anchor(session_id: str) -> str:
    """Return the stored anchor for *session_id*, or '' when none exists."""
    if not session_id:
        return ""
    try:
        with _conn() as conn:
            _ensure(conn)
            row = conn.execute(
                f"SELECT anchor FROM {_TABLE} WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if not row:
            return ""
        return (row["anchor"] if hasattr(row, "keys") else row[0]) or ""
    except Exception as exc:
        LOG.debug("anchor_store: get failed (%s)", exc)
        return ""


def set_anchor(session_id: str, anchor: str) -> bool:
    """Upsert the anchor for *session_id*. Returns True on success."""
    if not session_id or not anchor:
        return False
    try:
        with _conn() as conn:
            _ensure(conn)
            conn.execute(
                f"INSERT INTO {_TABLE} (session_id, anchor, updated_at) "
                "VALUES (?, ?, now()) "
                "ON CONFLICT (session_id) DO UPDATE "
                "SET anchor = EXCLUDED.anchor, updated_at = now()",
                (session_id, anchor),
            )
        return True
    except Exception as exc:
        LOG.debug("anchor_store: set failed (%s)", exc)
        return False

"""_mirror — mirror every persisted turn from SQLite state.db into PG.

WHY: stock Hermes persists turns to SQLite (``state.db``) and PRUNES it
(``maybe_auto_prune_and_vacuum``, 90-day retention). The MEAI recall tools
(``mea_sessions`` / ``mea_messages``) read PostgreSQL. Without a mirror, the
recall tools see only seed data and never the agent's own live conversation.

WHAT: a ``post_llm_call`` hook that copies each turn's persisted rows from
SQLite into the PG ``messages`` table, and upserts the ``sessions`` row so the
lineage CTE in ``mea_sessions`` has a root.

TRUTH RULES (Josh, 2026-10-14):
  * NO truncation  — every role is mirrored (user/assistant/tool/session_meta).
  * NO dupes       — idempotency is ``msg_key = md5(session_id:sqlite_row_id)``,
                     a deterministic hash of the SOURCE row id. Re-running a
                     turn re-computes the same key and ON CONFLICT swallows it.
  * NO oversights  — ``content_hash`` is deliberately left NULL. The fork's
                     ``(session_id, content_hash)`` unique index would collapse
                     two legitimately identical messages (e.g. the user says
                     "ok" twice). msg_key is per-row, so identical content in
                     distinct rows both survive.
  * TRUE timestamps — the SQLite row's REAL epoch is written verbatim as
                     ``datetime.fromtimestamp(ts)``; never a batch clock.

ORDERING (verified): ``post_llm_call`` fires at turn_finalizer.py:659, AFTER
``_persist_step`` (the SQLite flush) at :637. So the rows are already in
SQLite when this hook runs — we mirror the ACTUAL persisted rows, not a
reconstruction.

Fail-open: any error returns immediately; the turn is never blocked.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path

LOG = logging.getLogger(__name__)

# Profile home holds state.db. Do NOT derive it from ``Path(__file__).resolve()``
# alone: the plugin directory is a symlink into the source repo in the installed
# layout, so resolving it points inside plugins/mea_pm and the store is missed
# (symptom: mirror reports "no state.db" and silently stops advancing).
def _profile_home() -> Path:
    candidates: list[Path] = []
    env = os.environ.get("HERMES_HOME")
    if env:
        candidates.append(Path(env).expanduser())
    try:
        from hermes_constants import get_hermes_home  # type: ignore

        candidates.append(Path(get_hermes_home()))
    except Exception:
        pass
    # Unresolved __file__ keeps the symlinked path, so the ancestor walk still
    # lands on the profile home in both layouts.
    candidates.append(Path(__file__).parent.parent.parent)
    candidates.append(Path(__file__).resolve().parent.parent.parent)
    for cand in candidates:
        if (cand / "state.db").exists():
            return cand
    return candidates[0] if candidates else Path.home() / ".hermes"


PROFILE_HOME = _profile_home()
STATE_DB = PROFILE_HOME / "state.db"

# SQLite columns we copy, in the order we bind them to PG.
# ``active`` and ``compacted`` MUST be mirrored: they are the compaction state
# axis. Without them PG rows land on the column defaults (active=1,
# compacted=0) and PG can never reflect a compaction that already happened in
# state.db — the two stores then disagree on every archived row.
_COLS = (
    "id", "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason",
    "reasoning_content", "reasoning_details", "codex_reasoning_items",
    "codex_message_items", "platform_message_id", "observed",
    "active", "compacted",
)

_INSERT_SQL = """INSERT INTO messages (session_id, role, content, tool_call_id,
       tool_calls, tool_name, timestamp, token_count, finish_reason,
       reasoning_content, reasoning_details, codex_reasoning_items,
       codex_message_items, platform_message_id, observed,
       active, compacted,
       message_id, msg_key, content_hash)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
   ON CONFLICT DO NOTHING"""


def _insert_rows(conn, session_id: str, rows) -> int:
    """Insert SQLite message rows; return the count that ACTUALLY landed.

    The return value must come from the driver's rowcount, never from the
    number of loop iterations: ``ON CONFLICT DO NOTHING`` makes a swallowed
    insert indistinguishable from a successful one, which is how a real data
    loss stayed invisible in the logs for days (attempts were logged as
    inserts while the real row count stayed flat).
    """
    landed = 0
    for r in rows:
        d = dict(r)
        mid = int(d["id"])
        msg_key = hashlib.md5(f"{session_id}:{mid}".encode("utf-8")).hexdigest()
        ts = d.get("timestamp")
        cur = conn.execute(
            _INSERT_SQL,
            (
                session_id, d.get("role"), d.get("content"), d.get("tool_call_id"),
                d.get("tool_calls"), d.get("tool_name"),
                datetime.fromtimestamp(ts) if ts is not None else None,
                d.get("token_count"), d.get("finish_reason"),
                d.get("reasoning_content"), d.get("reasoning_details"),
                d.get("codex_reasoning_items"), d.get("codex_message_items"),
                d.get("platform_message_id"), d.get("observed") or 0,
                int(d.get("active") if d.get("active") is not None else 1),
                int(d.get("compacted") if d.get("compacted") is not None else 0),
                mid, msg_key,
            ),
        )
        landed += int(cur.rowcount or 0)
    return landed


def _conn():
    from jpm.core._pg import sync_conn
    return sync_conn()


def _origin_field(raw, key: str) -> str | None:
    """Read one string field out of a state.db ``origin_json`` blob.

    state.db has no ``chat_topic``/``chat_name``/``user_name`` columns: the
    gateway puts them inside ``origin_json`` only. Parsing here is the whole
    source of truth for those fields; anything unparseable yields None rather
    than a guess.
    """
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw.get(key) or None
    try:
        origin = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(origin, dict):
        return origin.get(key) or None
    return None


def _topic_from_origin(raw) -> str | None:
    return _origin_field(raw, "chat_topic")


def _owning_profile() -> str | None:
    """Name of the profile whose state.db this module is mirroring.

    Same resolution order core uses (``hermes_cli.profiles.current_profile_name``):
    a launcher-pinned ``HERMES_PROFILE_NAME``/``HERMES_PROFILE`` wins, else the
    name is derived from the home directory. A named profile lives at
    ``<home>/profiles/<name>``, so the directory basename IS the identity; the
    default profile IS ``<home>`` itself and is named "default". Nothing here
    guesses: an unrecognisable layout yields None rather than a wrong label.
    """
    for env_name in ("HERMES_PROFILE_NAME", "HERMES_PROFILE"):
        value = (os.environ.get(env_name) or "").strip()
        if value:
            return value
    home = PROFILE_HOME
    if home.parent.name == "profiles":
        return home.name or None
    if (home / "config.yaml").exists() or (home / "profile.yaml").exists():
        return "default"
    return None


def _profile_for(row: dict) -> str | None:
    """Profile recorded on the SQLite row, else the one that owns this store.

    state.db carries ``profile_name`` on newer rows and leaves it NULL on rows
    written before that column existed, so the fallback is not cosmetic: without
    it those rows land unlabelled and a multi-profile store cannot tell which
    profile produced them.
    """
    value = row.get("profile_name")
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    return _owning_profile()


def _upsert_session(conn, row: dict) -> None:
    """Insert the session row if absent. mea_sessions needs id/source/started_at.

    KEY CLAIM: ``idx_sessions_active_key`` is UNIQUE on ``session_key`` for OPEN
    rows only (``end_reason IS NULL OR end_reason = ''``). When a new session
    takes over a key that a stale-but-still-open row holds, a bare INSERT
    raises UniqueViolationError and the whole mirror turn is lost. The gateway's
    own ``SessionStore._save`` (core/gateway/session.py) solves this by clearing
    the key from the previous session_id first; we do the same here so the
    mirror matches gateway semantics instead of fighting the index.

    RACE: the clear-then-insert is TWO statements. Side loops fork in parallel
    (``_mea_loops_core`` launches several per turn), so two mirrors can both
    clear, then both insert, and the second hits the index. A transaction-scoped
    advisory lock keyed on the session_key makes the pair single-flight; PG
    releases it automatically at COMMIT/ROLLBACK. The caller MUST hold a
    transaction (see ``mirror``) or the lock is a no-op.
    """
    session_key = row.get("session_key")
    if session_key:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtext(?))", (session_key,)
        )
        conn.execute(
            "UPDATE sessions SET session_key = NULL "
            "WHERE session_key = ? AND id != ?",
            (session_key, row.get("id")),
        )

    # Topic name has no column of its own in state.db; it only ever appears
    # inside origin_json. Resolve it there first, then from the label table, so
    # a name learned once survives later turns that arrive without origin_json.
    chat_id = row.get("chat_id") or None
    thread_id = row.get("thread_id") or None
    chat_topic = _topic_from_origin(row.get("origin_json"))
    if chat_topic is None and chat_id and thread_id is not None:
        try:
            t = conn.fetchone(
                "SELECT topic_name FROM session_topics WHERE chat_id = ? AND thread_id = ?",
                (str(chat_id), str(thread_id)),
            )
            chat_topic = (t["topic_name"] if t else None) or None
        except Exception:  # fail-open: a missing table must not drop the turn
            chat_topic = None

    conn.execute(
        """INSERT INTO sessions (id, source, model, title, message_count,
               parent_session_id, started_at, chat_type, session_key,
               chat_id, thread_id, chat_topic, display_name, chat_name,
               user_name, profile)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (id) DO UPDATE SET
               message_count = EXCLUDED.message_count,
               title = COALESCE(EXCLUDED.title, sessions.title),
               session_key = COALESCE(EXCLUDED.session_key, sessions.session_key),
               chat_id = COALESCE(EXCLUDED.chat_id, sessions.chat_id),
               thread_id = COALESCE(EXCLUDED.thread_id, sessions.thread_id),
               chat_topic = COALESCE(EXCLUDED.chat_topic, sessions.chat_topic),
               display_name = COALESCE(EXCLUDED.display_name, sessions.display_name),
               chat_name = COALESCE(EXCLUDED.chat_name, sessions.chat_name),
               user_name = COALESCE(EXCLUDED.user_name, sessions.user_name),
               profile = COALESCE(EXCLUDED.profile, sessions.profile)""",
        (
            row.get("id"),
            row.get("source") or "unknown",
            row.get("model"),
            row.get("title"),
            row.get("message_count") or 0,
            row.get("parent_session_id"),
            datetime.fromtimestamp(row["started_at"]) if row.get("started_at") else None,
            row.get("chat_type") or "dm",
            row.get("session_key"),
            str(chat_id) if chat_id else None,
            str(thread_id) if thread_id else None,
            chat_topic,
            row.get("display_name"),
            _origin_field(row.get("origin_json"), "chat_name"),
            _origin_field(row.get("origin_json"), "user_name"),
            _profile_for(row),
        ),
    )

    # Persist a learned topic name so later sessions in the same thread inherit
    # it and recall can filter by name.
    if chat_id and thread_id is not None and chat_topic:
        try:
            conn.execute(
                """INSERT INTO session_topics
                       (chat_id, thread_id, platform, topic_name, updated_at)
                   VALUES (?, ?, ?, ?, now())
                   ON CONFLICT (chat_id, thread_id) DO UPDATE
                       SET topic_name = EXCLUDED.topic_name,
                           updated_at = now()""",
                (str(chat_id), str(thread_id),
                 row.get("source") or "telegram", chat_topic),
            )
        except Exception:  # fail-open
            pass


def mirror(session_id: str) -> dict:
    """Copy new SQLite rows for *session_id* into PG. Returns a small report."""
    if not STATE_DB.exists():
        return {"ok": False, "reason": "no state.db"}

    # 1. Highest message_id already mirrored for this session (idempotency floor).
    with _conn() as conn:
        row = conn.fetchone(
            "SELECT COALESCE(MAX(message_id), 0) AS hi FROM messages WHERE session_id = ?",
            (session_id,),
        )
        hi = int(row["hi"]) if row else 0

        # 2. Read the session row + any messages newer than the floor.
        src = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        src.row_factory = sqlite3.Row
        try:
            srow = src.execute(
                "SELECT id, source, model, title, message_count, parent_session_id, "
                "started_at, chat_type, session_key, chat_id, thread_id, "
                "display_name, origin_json, profile_name FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if srow is None:
                return {"ok": False, "reason": "session not in state.db"}

            rows = src.execute(
                f"SELECT {', '.join(_COLS)} FROM messages "
                "WHERE session_id = ? AND id > ? ORDER BY id ASC",
                (session_id, hi),
            ).fetchall()
        finally:
            src.close()

        # 3. Write everything in ONE transaction. This is what makes the
        #    advisory lock in _upsert_session transaction-scoped: PG holds it
        #    from the clear through the insert and releases it at COMMIT, so
        #    two concurrent mirrors on the same session_key serialize instead
        #    of interleaving between the UPDATE and the INSERT.
        inserted = 0
        reconciled = 0
        with conn.transaction():
            _upsert_session(conn, dict(srow))

            inserted = _insert_rows(conn, session_id, rows)

            # ── Gap reconciliation ────────────────────────────────────────
            # The `id > floor` watermark is append-only, so a row missing
            # BELOW the floor is never retried and the gap becomes permanent.
            # That is what turned the PG-side dedupe into silent data loss.
            # Compare against the source and backfill by id set; idempotent
            # because the same msg_key makes ON CONFLICT a no-op for rows we
            # already hold.
            src = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
            src.row_factory = sqlite3.Row
            try:
                all_rows = src.execute(
                    f"SELECT {', '.join(_COLS)} FROM messages "
                    "WHERE session_id = ? ORDER BY id ASC",
                    (session_id,),
                ).fetchall()
            finally:
                src.close()

            have = {
                int(r["message_id"])
                for r in (conn.fetchall(
                    "SELECT message_id FROM messages "
                    "WHERE session_id = ? AND message_id IS NOT NULL",
                    (session_id,),
                ) or [])
            }
            missing = [r for r in all_rows if int(r["id"]) not in have]
            if missing:
                reconciled = _insert_rows(conn, session_id, missing)

            # message_count must describe the rows PG actually holds. Core's
            # sessions.message_count goes stale (it stops bumping for sessions
            # that keep receiving messages), and copying it verbatim published
            # that staleness into recall. Count what we really have.
            conn.execute(
                "UPDATE sessions SET message_count = ("
                "  SELECT count(*) FROM messages m WHERE m.session_id = sessions.id"
                ") WHERE id = ?",
                (session_id,),
            )

    return {"ok": True, "session_id": session_id, "floor": hi,
            "seen": len(rows), "inserted": inserted, "reconciled": reconciled}


def on_post_llm_call(**ctx) -> None:
    """post_llm_call hook: mirror this turn's persisted rows into PG."""
    try:
        session_id = str(ctx.get("session_id") or "")
        if not session_id:
            return
        report = mirror(session_id)
        LOG.info("mea_sessions.mirror: %s", report)
    except Exception as exc:
        LOG.warning("mea_sessions.mirror: hook failed (fail-open): %s", exc)

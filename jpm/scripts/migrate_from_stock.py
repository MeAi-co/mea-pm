#!/usr/bin/env python3
"""migrate_from_stock — import a stock Hermes SQLite history into the PG vault.

WHY
    Stock Hermes persists conversation to SQLite (``state.db``). The MEAI
    plugins read PostgreSQL. A user who installs the plugins on an existing
    stock install gets an EMPTY vault: their entire history stays invisible to
    every recall tool. The ``mea_sessions`` mirror only copies turns from the
    moment it is installed forward — it never backfills.

WHAT
    One-shot, idempotent, resumable import of ``sessions`` and ``messages``
    from a stock ``state.db`` into the PG tables the plugins read.

DESIGN RULES
    * NO hardcoded paths. The SQLite file comes from ``--state-db``, else
      ``$HERMES_HOME/state.db``, else ``~/.hermes/state.db``. PG comes from the
      standard ``JPM_PG_*`` env vars via ``jpm.core._pg``.
    * DRY RUN BY DEFAULT. Nothing is written without ``--apply``.
    * EXPLICIT COLUMN PROJECTION. Stock SQLite and the PG schema have drifted
      apart in both directions (messages 30 vs 22 cols, sessions 62 vs 52).
      A naive ``INSERT ... SELECT *`` fails. Only columns present on BOTH
      sides are copied; PG defaults fill the rest.
    * IDEMPOTENT. ``msg_key = md5(session_id || ':' || sqlite_row_id)`` is the
      same formula the live mirror uses, so re-running is a no-op and a
      partially-completed run resumes cleanly.
    * RESUMABLE. Per-session floor = MAX(message_id) already in PG. Only rows
      above the floor are read.
    * READ-ONLY on the source. SQLite is opened ``mode=ro``; the stock install
      is never modified.

USAGE
    # 1. Inspect what would move (writes nothing)
    python3 -m jpm.scripts.migrate_from_stock

    # 2. Apply
    python3 -m jpm.scripts.migrate_from_stock --apply

    # 3. Verify
    python3 -m jpm.scripts.migrate_from_stock --verify

    # Point at a non-default SQLite file
    python3 -m jpm.scripts.migrate_from_stock --state-db /path/to/state.db --apply

EXIT CODES
    0  success (or dry-run completed)
    1  PG not configured / unreachable
    2  source state.db missing or unreadable
    3  one or more sessions failed (see report)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Column projection ───────────────────────────────────────────────────────
# Columns copied from SQLite -> PG. Every name here MUST exist on BOTH sides.
# Anything absent from the PG schema is deliberately dropped (see the drift
# table in MIGRATION.md); anything PG-only is left to its column default.
MESSAGE_COLS = (
    "id", "session_id", "role", "content", "tool_call_id", "tool_calls",
    "tool_name", "timestamp", "token_count", "finish_reason",
    "reasoning_content", "reasoning_details", "codex_reasoning_items",
    "codex_message_items", "platform_message_id", "observed",
    "active", "compacted",
)

SESSION_COLS = (
    "id", "source", "user_id", "model", "model_config", "system_prompt",
    "parent_session_id", "started_at", "ended_at", "end_reason",
    "message_count", "tool_call_count", "input_tokens", "output_tokens",
    "cache_read_tokens", "cache_write_tokens", "reasoning_tokens", "cwd",
    "billing_provider", "billing_base_url", "billing_mode",
    "estimated_cost_usd", "actual_cost_usd", "cost_status", "cost_source",
    "pricing_version", "title", "api_call_count", "handoff_state",
    "handoff_platform", "handoff_error", "rewind_count", "archived",
    "git_branch", "git_repo_root", "session_key", "display_name",
    "chat_type", "chat_id", "thread_id", "origin_json", "expiry_finalized",
)

# Epoch-second columns that must become timestamptz on the PG side.
_TS_COLS = {"started_at", "ended_at"}


def _resolve_state_db(explicit: str | None) -> Path:
    """Locate the stock SQLite file. No hardcoded absolute paths."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    home = os.environ.get("HERMES_HOME")
    if home:
        return (Path(home).expanduser() / "state.db").resolve()
    return (Path.home() / ".hermes" / "state.db").resolve()


def _sqlite_cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _project(wanted: tuple[str, ...], available: list[str]) -> list[str]:
    """Intersection, preserving the declared order."""
    have = set(available)
    return [c for c in wanted if c in have]


def _to_ts(value):
    """Epoch seconds -> NAIVE UTC datetime. Pass through None.

    The PG columns are ``timestamp without time zone`` (verified against
    information_schema), so asyncpg rejects a tz-aware datetime with
    "can't subtract offset-naive and offset-aware datetimes". Convert to UTC
    and drop the tzinfo.
    """
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _pg_conn():
    from jpm.core._pg import sync_conn
    return sync_conn()


def _pg_ready() -> tuple[bool, str]:
    """Confirm PG is configured AND the schema exists. Never guesses."""
    try:
        from jpm.core._pg import is_pg_enabled
    except Exception as exc:  # pragma: no cover - import guard
        return False, f"cannot import jpm.core._pg: {exc}"
    try:
        if not is_pg_enabled():
            return False, (
                "PG not configured — set JPM_PG_HOST (and JPM_PG_PORT/DB/USER/"
                "PASSWORD as needed). Without it the plugins silently fall "
                "back to SQLite and this migration has no target."
            )
    except Exception as exc:
        return False, f"PG unreachable: {exc}"
    try:
        with _pg_conn() as conn:
            row = conn.fetchone(
                "SELECT to_regclass('public.messages') AS m, "
                "       to_regclass('public.sessions') AS s"
            )
        if not row or not row["m"] or not row["s"]:
            return False, (
                "PG reachable but the schema is missing. Start the agent once "
                "with the plugin enabled so apply_schema() creates the tables, "
                "then re-run this migration."
            )
    except Exception as exc:
        return False, f"schema probe failed: {exc}"
    return True, "ok"


def _survey(src: sqlite3.Connection) -> dict:
    """Count what is in the source. Read-only."""
    out = {}
    for t in ("sessions", "messages"):
        try:
            out[t] = src.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            out[t] = None
    return out


def _pg_survey() -> dict:
    with _pg_conn() as conn:
        s = conn.fetchone("SELECT COUNT(*) AS n FROM sessions")
        m = conn.fetchone("SELECT COUNT(*) AS n FROM messages")
    return {"sessions": s["n"] if s else 0, "messages": m["n"] if m else 0}


def _migrate_sessions(src: sqlite3.Connection, apply: bool) -> dict:
    cols = _project(SESSION_COLS, _sqlite_cols(src, "sessions"))
    src.row_factory = sqlite3.Row
    rows = src.execute(f"SELECT {', '.join(cols)} FROM sessions ORDER BY id").fetchall()

    placeholders = ", ".join("?" for _ in cols)
    updates = ", ".join(
        f"{c} = COALESCE(EXCLUDED.{c}, sessions.{c})"
        for c in cols if c != "id"
    )
    sql = (
        f"INSERT INTO sessions ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO UPDATE SET {updates}"
    )

    inserted = 0
    failed = []
    if apply:
        with _pg_conn() as conn:
            for r in rows:
                d = dict(r)
                vals = []
                for c in cols:
                    v = d.get(c)
                    if c in _TS_COLS:
                        v = _to_ts(v)
                    vals.append(v)
                try:
                    conn.execute(sql, tuple(vals))
                    # Upsert: rowcount is 1 whether inserted or updated.
                    inserted += 1
                except Exception as exc:
                    failed.append({"id": d.get("id"), "error": str(exc)[:200]})
    return {"seen": len(rows), "written": inserted, "failed": failed, "cols": cols}


def _migrate_messages(src: sqlite3.Connection, apply: bool, batch: int) -> dict:
    cols = _project(MESSAGE_COLS, _sqlite_cols(src, "messages"))
    if "id" not in cols or "session_id" not in cols:
        return {"seen": 0, "written": 0, "failed": [],
                "error": "source messages table lacks id/session_id"}

    # Per-session floor so a re-run resumes instead of rescanning.
    floors: dict[str, int] = {}
    if apply:
        with _pg_conn() as conn:
            for r in conn.fetchall(
                "SELECT session_id, COALESCE(MAX(message_id), 0) AS hi "
                "FROM messages GROUP BY session_id"
            ):
                floors[r["session_id"]] = int(r["hi"])

    src.row_factory = sqlite3.Row
    session_ids = [r[0] for r in src.execute(
        "SELECT DISTINCT session_id FROM messages ORDER BY session_id"
    )]

    # PG insert column list: source cols + the two derived keys.
    pg_cols = list(cols) + ["msg_key"]
    placeholders = ", ".join("?" for _ in pg_cols)
    sql = (
        f"INSERT INTO messages ({', '.join(pg_cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT DO NOTHING"
    )

    seen = written = 0
    failed: list[dict] = []

    for sid in session_ids:
        floor = floors.get(sid, 0)
        rows = src.execute(
            f"SELECT {', '.join(cols)} FROM messages "
            "WHERE session_id = ? AND id > ? ORDER BY id ASC",
            (sid, floor),
        ).fetchall()
        if not rows:
            continue
        seen += len(rows)
        if not apply:
            continue

        with _pg_conn() as conn:
            for i in range(0, len(rows), batch):
                chunk = rows[i:i + batch]
                with conn.transaction():
                    for r in chunk:
                        d = dict(r)
                        mid = int(d["id"])
                        msg_key = hashlib.md5(
                            f"{sid}:{mid}".encode("utf-8")
                        ).hexdigest()
                        vals = []
                        for c in cols:
                            v = d.get(c)
                            if c == "timestamp":
                                v = _to_ts(v)
                            vals.append(v)
                        vals.append(msg_key)
                        try:
                            conn.execute(sql, tuple(vals))
                            # ON CONFLICT DO NOTHING: rowcount is the TRUE
                            # insert count — 0 when the msg_key already exists.
                            written += conn.rowcount
                        except Exception as exc:
                            failed.append({"id": mid, "session_id": sid,
                                           "error": str(exc)[:200]})

    return {"seen": seen, "written": written, "failed": failed, "cols": cols}


def _verify(src: sqlite3.Connection) -> dict:
    """Compare source row counts against PG. Reports, never repairs."""
    src_counts = _survey(src)
    pg_counts = _pg_survey()
    return {
        "source": src_counts,
        "pg": pg_counts,
        "delta": {
            k: (pg_counts.get(k, 0) - (src_counts.get(k) or 0))
            for k in ("sessions", "messages")
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="migrate_from_stock",
        description="Import a stock Hermes SQLite history into the PG vault.",
    )
    ap.add_argument("--state-db", default=None,
                    help="Path to stock state.db (default: $HERMES_HOME/state.db "
                         "or ~/.hermes/state.db)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to PG. Without this the run is a dry run.")
    ap.add_argument("--verify", action="store_true",
                    help="Only compare source vs PG row counts, then exit.")
    ap.add_argument("--sessions-only", action="store_true",
                    help="Migrate sessions, skip messages.")
    ap.add_argument("--messages-only", action="store_true",
                    help="Migrate messages, skip sessions.")
    ap.add_argument("--batch-size", type=int, default=500,
                    help="Messages per transaction (default 500).")
    args = ap.parse_args(argv)

    state_db = _resolve_state_db(args.state_db)
    print(f"source : {state_db}")
    if not state_db.exists():
        print(f"ERROR  : state.db not found at {state_db}", file=sys.stderr)
        print("         Pass --state-db /path/to/state.db", file=sys.stderr)
        return 2

    ok, why = _pg_ready()
    print(f"target : {'PG ready' if ok else 'PG NOT READY'}")
    if not ok:
        print(f"ERROR  : {why}", file=sys.stderr)
        return 1

    try:
        src = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        print(f"ERROR  : cannot open state.db read-only: {exc}", file=sys.stderr)
        return 2

    try:
        if args.verify:
            import json
            print(json.dumps(_verify(src), indent=2))
            return 0

        mode = "APPLY" if args.apply else "DRY RUN (nothing will be written)"
        print(f"mode   : {mode}")
        print(f"source counts: {_survey(src)}")
        print(f"pg counts    : {_pg_survey()}")
        print()

        rc = 0
        if not args.messages_only:
            rep = _migrate_sessions(src, args.apply)
            print(f"sessions: seen={rep['seen']} upserted={rep['written']} "
                  f"failed={len(rep['failed'])}")
            print(f"  cols copied ({len(rep['cols'])}): {', '.join(rep['cols'])}")
            for f in rep["failed"][:5]:
                print(f"  ! {f['id']}: {f['error']}")
            if rep["failed"]:
                rc = 3

        if not args.sessions_only:
            rep = _migrate_messages(src, args.apply, args.batch_size)
            print(f"messages: seen={rep['seen']} written={rep['written']} "
                  f"failed={len(rep['failed'])}")
            print(f"  cols copied ({len(rep['cols'])}): {', '.join(rep['cols'])}")
            for f in rep["failed"][:5]:
                print(f"  ! {f['session_id']}/{f['id']}: {f['error']}")
            if rep["failed"]:
                rc = 3

        if args.apply:
            print()
            print("post-migration counts:")
            print(f"  {_pg_survey()}")
        else:
            print()
            print("Dry run complete. Re-run with --apply to write.")
        return rc
    finally:
        src.close()


if __name__ == "__main__":
    sys.exit(main())

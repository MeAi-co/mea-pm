"""_backfill_topic_scope — repair session scope columns in PG from SQLite.

WHY: ``_mirror._upsert_session`` upserted 9 columns, so ``chat_id``,
``thread_id``, ``chat_topic`` and ``display_name`` arrived NULL on every PG
``sessions`` row even though core Hermes had already written them to
``state.db``. No PG session row carried a thread id, and a thread-scoped live
session existed only in SQLite.

WHAT: reads the surviving SQLite sessions (source of truth, including
``origin_json``, which is the ONLY place a topic name ever appears — SQLite has
no ``chat_topic`` column) and writes the scope onto the matching PG rows, then
seeds ``public.session_topics`` with any resolvable
``(chat_id, thread_id) -> topic_name`` pair.

HONEST LIMITS:
  * Only sessions still present in ``state.db`` can be repaired. Core prunes
    that store, so older PG rows are gone at the source and stay NULL. They are
    not recoverable and must not be invented.
  * ``origin_json.chat_topic`` is currently null for every Telegram DM row, so
    ``sessions.chat_topic`` remains NULL for those sessions. The column and the
    label table exist so that a real topic name is stored the moment one shows
    up, not so that a placeholder can be fabricated now.

IDEMPOTENT: pure UPDATE/INSERT with COALESCE-style guards; re-running changes
nothing. Safe to call from install.sh and from the mirror hook.

Usage:
    python3 _backfill_topic_scope.py [--dry-run]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

def _resolve_state_db() -> Path:
    """state.db lives in the profile home, not next to the plugin.

    ``Path(__file__).resolve()`` points into the source repo when the plugin
    directory is a symlink, so check the declared home first and fall back to the
    ancestor walk only when it actually holds a store.
    """
    import os

    candidates = []
    if os.environ.get("HERMES_HOME"):
        candidates.append(Path(os.environ["HERMES_HOME"]).expanduser())
    candidates += [
        Path(__file__).parent.parent.parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    for cand in candidates:
        if (cand / "state.db").exists():
            return cand
    return candidates[0]


PROFILE_HOME = _resolve_state_db()
STATE_DB = PROFILE_HOME / "state.db"


def _conn():
    from jpm.core._pg import sync_conn
    return sync_conn()


def _read_sqlite() -> list[dict]:
    """Every SQLite session row that carries any scope information."""
    if not STATE_DB.exists():
        return []
    src = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        rows = src.execute(
            "SELECT id, source, chat_id, thread_id, display_name, chat_type, origin_json "
            "FROM sessions WHERE coalesce(chat_id, '') <> '' "
            "   OR coalesce(thread_id, '') <> ''"
        ).fetchall()
    finally:
        src.close()

    out = []
    for r in rows:
        d = dict(r)
        topic = None
        raw = d.get("origin_json")
        if raw:
            try:
                origin = json.loads(raw)
            except (TypeError, ValueError):
                origin = {}
            if isinstance(origin, dict):
                topic = origin.get("chat_topic") or None
                # origin_json is authoritative when the flat columns are empty.
                d["chat_id"] = d.get("chat_id") or origin.get("chat_id")
                d["thread_id"] = d.get("thread_id") or origin.get("thread_id")
                d["display_name"] = d.get("display_name") or origin.get("chat_name")
        d["chat_topic"] = topic
        out.append(d)
    return out


def backfill(dry_run: bool = False) -> dict:
    rows = _read_sqlite()
    if not rows:
        return {"ok": True, "candidates": 0, "updated": 0, "topics": 0,
                "reason": "no scoped rows in state.db"}

    report = {"ok": True, "candidates": len(rows), "updated": 0,
              "missing_in_pg": 0, "topics": 0, "dry_run": dry_run}

    with _conn() as conn:
        with conn.transaction():
            for d in rows:
                sid = d.get("id")
                cur = conn.execute(
                    """UPDATE sessions SET
                           chat_id      = COALESCE(?, chat_id),
                           thread_id    = COALESCE(?, thread_id),
                           chat_topic   = COALESCE(?, chat_topic),
                           display_name = COALESCE(?, display_name)
                       WHERE id = ?""",
                    (d.get("chat_id") or None,
                     d.get("thread_id") or None,
                     d.get("chat_topic") or None,
                     d.get("display_name") or None,
                     sid),
                )
                changed = getattr(cur, "rowcount", None)
                if changed == 0:
                    report["missing_in_pg"] += 1
                else:
                    report["updated"] += changed

                # Seed the label table only with real names, never blanks.
                if d.get("chat_id") and d.get("chat_topic"):
                    conn.execute(
                        """INSERT INTO session_topics
                               (chat_id, thread_id, platform, topic_name, updated_at)
                           VALUES (?, ?, ?, ?, now())
                           ON CONFLICT (chat_id, thread_id) DO UPDATE
                               SET topic_name = EXCLUDED.topic_name,
                                   platform   = EXCLUDED.platform,
                                   updated_at = now()""",
                        (d["chat_id"], d.get("thread_id") or "",
                         d.get("source") or "telegram", d["chat_topic"]),
                    )
                    report["topics"] += 1

            if dry_run:
                raise RuntimeError("dry-run rollback")

    return report


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    try:
        print(backfill(dry_run=dry))
    except RuntimeError as exc:
        if "dry-run rollback" in str(exc):
            print({"ok": True, "dry_run": True})
        else:
            raise

"""mea_sessions — the ``sessions`` tool (PG-backed session recall).

A fork of the Joshaico fork's ``session_search`` tool, retargeted at the
MEAI PG memory interface. It keeps the fork's single-shape calling contract
(mode inferred from args) but reads the PostgreSQL ``messages`` / ``sessions``
tables directly through the vendored ``jpm`` engine's ``sync_conn`` — no
``joshaico_state.SessionDB`` dependency, no SQLite.

Four calling shapes (inferred, no explicit mode arg):

  1. DISCOVERY — pass ``query``. FTS over ``messages.search_vector`` with a
     pgvector recall fallback (``jpm.core._hybrid_search.hybrid_message_ids``),
     deduped by session lineage, ranked newest-first with rank as tiebreaker.
  2. SCROLL — pass ``session_id`` + ``around_message_id``. ±window slice.
  3. READ — pass ``session_id`` only. Whole-session dump (first 20 + last 10).
  4. BROWSE — no args. Recent sessions chronologically.

No LLM calls anywhere — every shape returns actual rows from PG.

DB API note: the vendored ``PGConnection`` wrapper takes params as a SINGLE
tuple — ``conn.fetchall(sql, (a, b))`` — and converts ``?`` placeholders to
``$1, $2, ...``. Passing multiple positional args makes it unpack ``args[0]``
(a string/list) into the parameter list, which corrupts the query.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Sources excluded from browsing/searching by default (mirrors the fork).
_HIDDEN_SESSION_SOURCES = ("subagent", "tool")
# Automation sources kept searchable but demoted below interactive sessions.
_DEMOTED_SESSION_SOURCES = ("cron",)

_DISCOVER_SCAN_LIMIT = 300

# Compaction/summary rows are synthetic context, not conversation — stock
# filters them out of bookends (session_search_tool.py:103). Ported here.
_COMPACTION_PREFIXES = ("[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:")


def _is_compaction_summary(content: str) -> bool:
    return bool(content) and content.lstrip().startswith(_COMPACTION_PREFIXES)


def _fmt_ts(ts: Any) -> str:
    """Human-readable timestamp from a PG timestamp / ISO string."""
    if ts is None:
        return "unknown"
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%B %d, %Y at %I:%M %p")
        return str(ts)
    except Exception:
        return str(ts)


def _conn():
    from jpm.core._pg import sync_conn
    return sync_conn()


def _session_meta(conn, session_id: str) -> dict:
    row = conn.fetchone(
        "SELECT id, title, source, model, message_count, started_at, ended_at, "
        "parent_session_id, summary FROM sessions WHERE id = ?",
        (session_id,),
    )
    return dict(row) if row else {}


def _lineage_root(conn, session_id: str) -> str:
    """Walk parent_session_id to the lineage root (recursive CTE)."""
    try:
        rows = conn.fetchall(
            """
            WITH RECURSIVE chain AS (
                SELECT id, parent_session_id FROM sessions WHERE id = ?
                UNION ALL
                SELECT s.id, s.parent_session_id
                FROM sessions s JOIN chain c ON s.id = c.parent_session_id
            )
            SELECT id FROM chain WHERE parent_session_id IS NULL LIMIT 1
            """,
            (session_id,),
        )
        if rows:
            return rows[0]["id"]
    except Exception as e:
        logger.debug("lineage walk failed for %s: %s", session_id, e)
    return session_id


def _window(conn, session_id: str, anchor_id: int, window: int) -> List[dict]:
    """±window messages around anchor_id, ordered by id."""
    rows = conn.fetchall(
        "SELECT id, role, content, tool_name, timestamp FROM messages "
        "WHERE session_id = ? AND id BETWEEN ? AND ? "
        "ORDER BY id ASC",
        (session_id, anchor_id - window, anchor_id + window),
    )
    out = []
    for r in rows:
        out.append({
            "id": r["id"],
            "role": r["role"],
            "content": (r["content"] or "")[:2000],
            "tool_name": r["tool_name"],
            "timestamp": _fmt_ts(r["timestamp"]),
            "anchor": r["id"] == anchor_id,
        })
    return out


def _anchor_counts(conn, session_id: str, anchor_id: int) -> tuple[int, int]:
    """Count messages before/after the anchor in the session (stock parity)."""
    row = conn.fetchone(
        "SELECT "
        "count(*) FILTER (WHERE id < ?) AS before, "
        "count(*) FILTER (WHERE id > ?) AS after "
        "FROM messages WHERE session_id = ?",
        (anchor_id, anchor_id, session_id),
    )
    if not row:
        return 0, 0
    return int(row["before"] or 0), int(row["after"] or 0)


def _bookend(conn, session_id: str, n: int = 3) -> tuple[List[dict], List[dict]]:
    """First n and last n user/assistant messages of a session.

    Compaction/summary rows are filtered out (stock parity) — they are
    synthetic context, not conversation.
    """
    head = conn.fetchall(
        "SELECT id, role, content, timestamp FROM messages "
        "WHERE session_id = ? AND role IN ('user','assistant') "
        "ORDER BY id ASC LIMIT ?",
        (session_id, n),
    )
    tail = conn.fetchall(
        "SELECT id, role, content, timestamp FROM messages "
        "WHERE session_id = ? AND role IN ('user','assistant') "
        "ORDER BY id DESC LIMIT ?",
        (session_id, n),
    )
    def _shape(rows):
        return [{"id": r["id"], "role": r["role"],
                 "content": (r["content"] or "")[:600],
                 "timestamp": _fmt_ts(r["timestamp"])} for r in rows
                if not _is_compaction_summary(r["content"] or "")]
    return _shape(head), _shape(list(reversed(tail)))


def _scroll(session_id: str, around_message_id: int, window: int) -> str:
    try:
        with _conn() as conn:
            meta = _session_meta(conn, session_id)
            if not meta:
                return json.dumps({"success": False,
                                   "error": f"session '{session_id}' not found"})
            msgs = _window(conn, session_id, int(around_message_id), int(window))
            return json.dumps({
                "success": True, "mode": "scroll", "session_id": session_id,
                "title": meta.get("title"), "window": window,
                "messages": msgs,
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"scroll failed: {e}"})


def _read_session(session_id: str) -> str:
    try:
        with _conn() as conn:
            meta = _session_meta(conn, session_id)
            if not meta:
                return json.dumps({"success": False,
                                   "error": f"session '{session_id}' not found"})
            total = conn.fetchone(
                "SELECT count(*) AS c FROM messages WHERE session_id = ?",
                (session_id,),
            )
            total = total["c"] if total else 0
            head = conn.fetchall(
                "SELECT id, role, content, timestamp FROM messages "
                "WHERE session_id = ? ORDER BY id ASC LIMIT 20", (session_id,))
            tail = conn.fetchall(
                "SELECT id, role, content, timestamp FROM messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT 10", (session_id,))
            def _shape(rows):
                return [{"id": r["id"], "role": r["role"],
                         "content": (r["content"] or "")[:2000],
                         "timestamp": _fmt_ts(r["timestamp"])} for r in rows]
            return json.dumps({
                "success": True, "mode": "read", "session_id": session_id,
                "title": meta.get("title"), "source": meta.get("source"),
                "message_count": total,
                "messages": _shape(head) + _shape(list(reversed(tail))),
                "truncated": total > 30,
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"read failed: {e}"})


def _list_recent_sessions(limit: int) -> str:
    try:
        with _conn() as conn:
            rows = conn.fetchall(
                "SELECT id, title, source, message_count, started_at, ended_at "
                "FROM sessions WHERE source <> ALL(?) "
                "ORDER BY started_at DESC NULLS LAST LIMIT ?",
                (list(_HIDDEN_SESSION_SOURCES), limit),
            )
            sessions = [{
                "session_id": r["id"], "title": r["title"], "source": r["source"],
                "message_count": r["message_count"],
                "when": _fmt_ts(r["started_at"]),
            } for r in rows]
            return json.dumps({"success": True, "mode": "browse",
                                "total": len(sessions), "sessions": sessions},
                               ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"browse failed: {e}"})


def _fts_message_ids(conn, query: str, limit: int) -> List[dict]:
    """FTS over messages.search_vector, newest-first with rank tiebreak."""
    words = [w.strip() for w in query.split() if w.strip()]
    if not words:
        return []
    or_query = " OR ".join(words)
    rows = conn.fetchall(
        """
        SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
               ts_rank(m.search_vector, websearch_to_tsquery('english', ?)) AS rank
        FROM messages m
        WHERE m.search_vector @@ websearch_to_tsquery('english', ?)
        ORDER BY m.timestamp DESC NULLS LAST, rank DESC
        LIMIT ?
        """,
        (or_query, or_query, limit),
    )
    return [dict(r) for r in rows]


def _discover(query: str, limit: int, sort: str, detail: str = "adaptive") -> str:
    try:
        with _conn() as conn:
            hits = _fts_message_ids(conn, query, _DISCOVER_SCAN_LIMIT)
            vector_used = False
            if len(hits) < 3:
                # Thin FTS → pgvector recall fallback (graceful: [] on no embed).
                try:
                    from jpm.core._hybrid_search import hybrid_message_ids
                    ids, _ = hybrid_message_ids(query, limit=_DISCOVER_SCAN_LIMIT)
                    if ids:
                        vector_used = True
                        rows = conn.fetchall(
                            "SELECT id, session_id, role, content, timestamp "
                            "FROM messages WHERE id = ANY(?)", (ids,))
                        by_id = {r["id"]: dict(r) for r in rows}
                        hits = [by_id[i] for i in ids if i in by_id]
                except Exception as e:
                    logger.debug("vector fallback skipped: %s", e)

            # Dedupe by session lineage root, keep first (best) hit per session.
            seen: Dict[str, dict] = {}
            for h in hits:
                sid = h["session_id"]
                root = _lineage_root(conn, sid)
                if root in seen:
                    continue
                meta = _session_meta(conn, sid)
                if meta.get("source") in _HIDDEN_SESSION_SOURCES:
                    continue
                seen[root] = {"hit": h, "meta": meta, "sid": sid}

            # Adaptive hydration (stock parity): only the TOP-ranked result is
            # fully hydrated (bookends + ±5 window); lower-ranked results return
            # just the anchor message. detail="full" hydrates every result.
            full = detail == "full"
            results = []
            for rank, (root, entry) in enumerate(list(seen.items())[:limit]):
                h, meta, sid = entry["hit"], entry["meta"], entry["sid"]
                hydrate = full or rank == 0
                if hydrate:
                    bstart, bend = _bookend(conn, sid, 3)
                    window = _window(conn, sid, h["id"], 5)
                else:
                    bstart, bend, window = [], [], [
                        m for m in _window(conn, sid, h["id"], 0)
                        if m.get("id") == h["id"]
                    ]
                before, after = _anchor_counts(conn, sid, h["id"])
                results.append({
                    "session_id": sid,
                    "title": meta.get("title"),
                    "when": _fmt_ts(meta.get("started_at")),
                    "source": meta.get("source"),
                    "snippet": (h.get("content") or "")[:400],
                    "match_message_id": h["id"],
                    "bookend_start": bstart,
                    "messages": window,
                    "bookend_end": bend,
                    "messages_before": before,
                    "messages_after": after,
                    "message_count": meta.get("message_count"),
                    "detail": "full" if hydrate else "anchor",
                })
            return json.dumps({
                "success": True, "mode": "discover", "query": query,
                "total": len(results), "vector_used": vector_used,
                "sort": sort, "detail": detail, "results": results,
            }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": f"discover failed: {e}"})


def sessions(
    query: str = "",
    role_filter: Optional[str] = None,
    limit: int = 3,
    session_id: Optional[str] = None,
    around_message_id: Optional[int] = None,
    window: int = 5,
    sort: Optional[str] = None,
    profile: Optional[str] = None,
    detail: str = "adaptive",
    current_session_id: Optional[str] = None,
) -> str:
    """Single-shape session recall. Mode inferred from which args are set."""
    # Normalise a raw `@session:<profile>/<id>` link passed as session_id.
    if isinstance(session_id, str) and "/" in session_id:
        _emb_profile, _, emb_id = session_id.partition("/")
        if emb_id:
            session_id = emb_id

    # Scroll wins over read/discovery when an anchor is set.
    if isinstance(session_id, str) and session_id.strip() and around_message_id is not None:
        return _scroll(session_id.strip(), int(around_message_id), int(window))

    # Read shape: session_id with no anchor.
    if isinstance(session_id, str) and session_id.strip():
        return _read_session(session_id.strip())

    # Limit clamp [1, 10].
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 3
    limit = max(1, min(limit, 10))

    # Browse shape: no query.
    if not query or not isinstance(query, str) or not query.strip():
        return _list_recent_sessions(limit)

    sort_norm = "newest"
    if isinstance(sort, str) and sort.strip().lower() in ("newest", "oldest", "recency"):
        sort_norm = sort.strip().lower()

    detail_norm = "adaptive"
    if isinstance(detail, str) and detail.strip().lower() in ("adaptive", "full"):
        detail_norm = detail.strip().lower()

    return _discover(query.strip(), limit, sort_norm, detail_norm)


def check_sessions_requirements() -> bool:
    """Requires the MEAI PG store."""
    try:
        with _conn() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.warning("sessions tool DISABLED — MEAI PG unreachable: %s", e)
        return False


SESSIONS_SCHEMA = {
    "name": "sessions",
    "description": (
        "sessions — recall what was actually said across past sessions, backed by "
        "the MEAI PostgreSQL memory store. Pass a query= to discover sessions, "
        "session_id+around_message_id to scroll inside one, session_id alone to read "
        "one, or no args to browse recent sessions. HYBRID recall over the "
        "message store — full-text first, then pgvector semantic recall merged in "
        "when full-text returns thin results, so paraphrased and non-exact queries "
        "still surface hits; a keyword miss is NOT evidence of absence. Results are "
        "deduped by session lineage and "
        "ranked newest-first. No LLM calls — every shape returns actual messages.\n\n"
        "SHAPES\n\n"
        "  1) DISCOVERY — sessions(query=\\\"auth refactor\\\", limit=3): hybrid "
        "recall (full-text + semantic merge), deduped by lineage. Each result carries session_id, title, when, "
        "source, snippet, match_message_id, bookend_start, a ±5 message window, "
        "bookend_end, and message_count.\n"
        "  2) SCROLL — sessions(session_id=\"...\", around_message_id=12345, window=10): "
        "±window slice around the anchor. Re-anchor on the first/last id to page.\n"
        "  3) READ — sessions(session_id=\"...\"): whole-session dump (first 20 + last 10).\n"
        "  4) BROWSE — sessions(): recent sessions chronologically.\n\n"
        "SOURCE-FIRST LIMIT\n\n"
        "  This tool searches conversation history only. It is not evidence about the "
        "current contents of external sources. If the user provided a direct source "
        "(URL, contact, file path, account, live system), inspect that source first. "
        "Do not conclude 'not found' from sessions alone when a direct source was given."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "Discovery: keywords/phrase to search past sessions."},
            "role_filter": {"type": "string",
                            "description": "Optional comma-separated roles (user,assistant,tool)."},
            "limit": {"type": "integer", "default": 3,
                      "description": "Max sessions to return (1-10)."},
            "session_id": {"type": "string",
                           "description": "Scroll/read: the session to open."},
            "around_message_id": {"type": "integer",
                                  "description": "Scroll: anchor message id."},
            "window": {"type": "integer", "default": 5,
                       "description": "Scroll: messages on each side of the anchor."},
            "sort": {"type": "string", "enum": ["newest", "oldest", "recency"],
                     "description": "Discovery ordering (default newest)."},
            "detail": {"type": "string", "enum": ["adaptive", "full"],
                       "default": "adaptive",
                       "description": ("Discovery only. 'adaptive' (default) fully "
                                       "hydrates the top-ranked result and returns only "
                                       "the anchor message for lower-ranked results. "
                                       "'full' returns bookends and the complete "
                                       "anchored window for every result.")},
            "profile": {"type": "string",
                        "description": "Optional: read another profile's sessions."},
        },
        "required": [],
    },
}

#!/usr/bin/env python3
"""messages — Surgical message-level recall across all sessions.

TWO MODES:
  1. Browse (no query) — candle-style time buckets + recent messages.
     Agent gets instant situational awareness: "23 hits in last 1h, 89 in 4h..."
  2. Search (with query) — VECTOR-FIRST semantic search across all messages
     (pgvector embeddings, RRF-merged with full-text). Paraphrased and
     non-exact queries work; a keyword miss is NOT evidence of absence.

Returns individual messages sorted by timestamp DESC (newest first).
Each result includes a Google-style snippet (via ts_headline), session title,
and timestamp. No session-level dedup — every matching message is its own result.

This complements session_search (which finds sessions) by finding the exact
message within those sessions.

Role filter: array param (role=["user","assistant"]), not comma-separated.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Pattern to strip JPM context injection blocks from snippets
_JPM_CTX_RE = re.compile(
    r"\[Context:\s*JPM found\s+[^\]]*\]",
    re.IGNORECASE,
)
# Broader: strip any [Context: ...] injection block (session context, JPM, etc.)
_CTX_BLOCK_RE = re.compile(
    r"\[Context:\s*[^\]]*\]\s*",
    re.IGNORECASE,
)
# Pattern for system-injected timestamps like [Sun 2026-07-12 13:53:04 +04]
_TS_PREFIX_RE = re.compile(
    r"\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s*[+-]\d{2,4}\]\s*",
    re.IGNORECASE,
)


def _clean_snippet(text: str, strip_context: bool = True) -> str:
    """Strip JPM context blocks and system injection prefixes from a snippet.

    When strip_context=True (default), removes:
      - [Context: JPM found "..." (0.85)] lines
      - [Context: Session "..." (date)] lines
      - System timestamp prefixes like [Sun 2026-07-12 ...]

    This dramatically improves signal-to-noise when FTS5 matches hit
    injected context blocks rather than actual conversation.
    """
    if not text:
        return text
    if strip_context:
        text = _CTX_BLOCK_RE.sub("", text)
        text = _TS_PREFIX_RE.sub("", text)
    return text.strip()


def _format_timestamp(ts) -> str:
    """Format a timestamp to a human-readable string.

    Handles both float epochs (legacy) and datetime objects (post-migration).
    """
    if ts is None:
        return "unknown"
    try:
        from datetime import datetime
        if isinstance(ts, datetime):
            return ts.strftime("%B %d, %Y at %I:%M %p")
        dt = datetime.fromtimestamp(float(ts))
        return dt.strftime("%B %d, %Y at %I:%M %p")
    except (ValueError, OSError, OverflowError, TypeError):
        return str(ts)


def _now_ts() -> float:
    """Current unix timestamp."""
    from datetime import datetime, timezone
    return datetime.now().timestamp()


def _dt_default(obj):
    """Serialize datetime/date values to ISO strings for JSON output.

    After the timestamp migration, message rows carry real datetime objects
    (previously floats). json.dumps can't serialize them natively, so any
    tool returning raw rows uses this as the default= handler.
    """
    import datetime as _dt
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _cutoff_ts(seconds_ago: float):
    """Datetime N seconds ago, matching the datetime timestamp column.

    The column is `timestamp without time zone`, so we return a naive UTC
    datetime — asyncpg/psycopg2 need a datetime object here, not an ISO string.
    """
    from datetime import datetime, timezone, timedelta
    return datetime.now().replace(tzinfo=None) - timedelta(seconds=seconds_ago)


def _build_browse_buckets(conn, role_list) -> List[dict]:
    """Build candle-style time buckets: hits in 1h, 4h, 12h, 24h, 7d, 30d, older."""
    buckets = [
        ("1h", 3600),
        ("4h", 14400),
        ("12h", 43200),
        ("24h", 86400),
        ("7d", 604800),
        ("30d", 2592000),
    ]
    role_placeholders = ",".join("?" for _ in role_list)
    results = []
    for label, seconds in buckets:
        cutoff = _cutoff_ts(seconds)
        row = conn.execute(
            f"""
            SELECT COUNT(*) as cnt
            FROM messages m
            WHERE m.timestamp >= ?
              AND (m.active = 1 OR m.compacted = 1)
              AND m.role IN ({role_placeholders})
            """,
            tuple([cutoff] + role_list),
        ).fetchone()
        results.append({"window": label, "count": row["cnt"]})
    # Older bucket
    oldest_cutoff = _cutoff_ts(2592000)
    row = conn.execute(
        f"""
        SELECT COUNT(*) as cnt
        FROM messages m
        WHERE (m.timestamp < ? OR m.timestamp IS NULL)
          AND (m.active = 1 OR m.compacted = 1)
          AND m.role IN ({role_placeholders})
        """,
        tuple([oldest_cutoff] + role_list),
    ).fetchone()
    results.append({"window": "older", "count": row["cnt"]})
    return results


def _build_browse_recent(conn, role_list, limit, offset) -> tuple:
    """Fetch recent messages for browse mode (last 24h only)."""
    cutoff_24h = _cutoff_ts(86400)
    role_placeholders = ",".join("?" for _ in role_list)
    rows = conn.execute(
        f"""
        SELECT
            m.id,
            m.session_id,
            m.role,
            substr(m.content, 1, 200) AS snippet,
            m.timestamp,
            s.source,
            s.model,
            s.title AS session_title
        FROM messages m
        LEFT JOIN sessions s ON s.id = m.session_id
        WHERE (m.active = 1 OR m.compacted = 1)
          AND m.role IN ({role_placeholders})
          AND m.timestamp >= ?
        ORDER BY m.timestamp DESC
        LIMIT ? OFFSET ?
        """,
        tuple(role_list + [cutoff_24h, limit, offset]),
    ).fetchall()

    # Total count (last 24h only)
    total_row = conn.execute(
        f"""
        SELECT COUNT(*) as total
        FROM messages m
        WHERE (m.active = 1 OR m.compacted = 1)
          AND m.role IN ({role_placeholders})
          AND m.timestamp >= ?
        """,
        tuple(role_list + [cutoff_24h]),
    ).fetchone()
    total = total_row["total"] if total_row else 0

    results = []
    for r in rows:
        ts_fmt = _format_timestamp(r["timestamp"])
        results.append({
            "id": r["id"],
            "session_id": r["session_id"],
            "role": r["role"],
            "snippet": (r.get("snippet") or "")[:200],
            "timestamp": r["timestamp"],
            "timestamp_formatted": ts_fmt,
            "session_title": r.get("session_title") or "",
            "source": r.get("source") or "",
            "model": r.get("model") or "",
        })
    return results, total


def messages(
    query: str = "",
    role: Optional[List[str]] = None,
    filter: str = "messages",
    limit: int = 20,
    offset: int = 0,
    smart: bool = False,
    current_session_id: str = None,
) -> str:
    """Search individual messages across all sessions using PG full-text search.

    TWO MODES:
      - No query = browse mode: candle-style time buckets + recent messages.
      - With query = FTS5 search mode: find messages matching the query.

    Use this when you need to find a specific message — not a session.
    Use session_search() when you need session-level context.
    """

    # Validate PG availability
    try:
        from jpm.core._pg import sync_conn, is_pg_enabled
        if not is_pg_enabled():
            return json.dumps({
                "success": False,
                "error": "PostgreSQL session store is not enabled",
            })
    except ImportError:
        return json.dumps({
            "success": False,
            "error": "JPM PG module not available",
        })

    # Normalise role filter — default to user + assistant (exclude tool)
    role_list = role if role else ["user", "assistant"]
    if not isinstance(role_list, list):
        role_list = [role_list]

    # Normalise content filter
    #   "messages"  — actual conversation (no JPM context blocks, no tool output)
    #   "tool_calls" — only tool invocations
    #   "context"   — JPM/system context injection blocks only
    #   "all"       — everything (raw content, no filtering)
    content_filter = (filter or "messages").strip().lower()
    if content_filter not in ("messages", "tool_calls", "context", "all"):
        content_filter = "messages"

    # Clamp limit
    try:
        limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        limit = 20
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0

    # --- BROWSE MODE (no query) ---
    if not query or not query.strip():
        try:
            with sync_conn() as conn:
                buckets = _build_browse_buckets(conn, role_list)
                recent, total = _build_browse_recent(conn, role_list, limit, offset)
        except Exception as e:
            logger.error("messages browse failed: %s", e, exc_info=True)
            return json.dumps({
                "success": False,
                "error": f"Browse failed: {e}",
            })

        # Build XML summary
        xml_parts = [f"<messages_browse total=\"{total}\" as_of=\"{_format_timestamp(_now_ts())}\">"]
        xml_parts.append("  <buckets>")
        for b in buckets:
            xml_parts.append(f"    <bucket window=\"{b['window']}\" count=\"{b['count']}\"/>")
        xml_parts.append("  </buckets>")
        xml_parts.append(f"  <recent limit=\"{limit}\" offset=\"{offset}\">")
        for r in recent:
            ts = r["timestamp_formatted"]
            title = r["session_title"] or r["session_id"][:12]
            sid = r["session_id"]
            xml_parts.append(
                f"    <hit id=\"{r['id']}\" ts=\"{ts}\" session=\"{sid}\" title=\"{title}\" role=\"{r['role']}\"/>"
            )
        xml_parts.append("  </recent>")
        xml_parts.append("</messages_browse>")

        response = {
            "success": True,
            "mode": "browse",
            "buckets": buckets,
            "results": recent,
            "count": len(recent),
            "total": total,
            "limit": limit,
            "offset": offset,
            "summary": "\n".join(xml_parts),
            "message": f"📊 {total} total messages (last 24h). "
                       + ", ".join(f"{b['window']}: {b['count']}" for b in buckets),
        }
        return json.dumps(response, ensure_ascii=False, default=_dt_default)

    # --- SEARCH MODE (with query) ---
    # Build the query — use websearch_to_tsquery for user-friendly syntax
    # (supports quoted phrases, OR, NOT, etc.)
    # Content filter clauses:
    #   "messages"   → exclude JPM context blocks AND tool calls
    #   "tool_calls" → only tool invocations
    #   "context"    → only JPM/system context injection blocks
    #   "all"        → no additional filter
    if content_filter == "tool_calls":
        content_clause = "AND m.tool_name IS NOT NULL AND m.tool_name != ''"
    elif content_filter == "context":
        content_clause = "AND m.content LIKE '[Context:%'"
    elif content_filter == "all":
        content_clause = ""
    else:  # "messages" — default: exclude context blocks AND tool calls
        content_clause = (
            "AND (m.tool_name IS NULL OR m.tool_name = '') "
            "AND m.content NOT LIKE '[Context:%'"
        )

    role_placeholders = ",".join("?" for _ in role_list)

    # Dedup by session: one best hit per session, ordered by relevance (timestamp desc).
    # This prevents 15 results from the same session drowning out other sessions.
    # DISTINCT ON (session_id) keeps the first row per session after ORDER BY,
    # which is the most recent matching message in that session.
    sql = f"""
        WITH q AS (
            SELECT websearch_to_tsquery('english', ?) AS tsq
        )
        SELECT
            m.id,
            m.session_id,
            m.role,
            ts_headline('english', m.content, (SELECT tsq FROM q),
                'StartSel=[hl],StopSel=[/hl],MaxWords=60,MinWords=25') AS snippet,
            m.timestamp,
            m.tool_name,
            s.source,
            s.model,
            s.title AS session_title,
            s.started_at AS session_started,
            COUNT(*) OVER () AS total
        FROM (
            SELECT DISTINCT ON (m.session_id)
                m.id,
                m.session_id,
                m.role,
                m.content,
                m.timestamp,
                m.tool_name
            FROM messages m
            WHERE m.search_vector @@ (SELECT tsq FROM q)
              AND (m.active = 1 OR m.compacted = 1)
              AND m.role IN ({role_placeholders})
              {content_clause}
            ORDER BY m.session_id, m.timestamp DESC
        ) m
        LEFT JOIN sessions s ON s.id = m.session_id
        ORDER BY m.timestamp DESC
        LIMIT ? OFFSET ?
    """

    params: list = [query]
    params.extend(role_list)
    params.extend([limit, offset])

    try:
        with sync_conn() as conn:
            cursor = conn.execute(sql, tuple(params))
            rows = [dict(r) for r in cursor.fetchall()]
            # Total from the window function (matches all deduped sessions, not just the page)
            total = rows[0]["total"] if rows else 0
    except Exception as e:
        logger.error("messages_search query failed: %s", e, exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Search failed: {e}",
        })

    # ── Hybrid vector recall (on by default; JPM_HYBRID_SEARCH=0 opt-out) ─
    # FTS fast-path first; if vector recall finds semantic hits that FTS
    # missed (including the case where FTS returned nothing), RRF-merge
    # them in. Same filter scope (role + content) applied to both paths.
    # Graceful: Ollama/embedding down → FTS stands.
    import os as _os

    if _os.environ.get("JPM_HYBRID_SEARCH", "1") != "0":
        try:
            from jpm.core._hybrid_search import hybrid_message_ids

            # Vector scope mirrors the FTS content_clause + role filter.
            # FTS clauses carry a leading "AND " prefix; strip it so the
            # joined vector WHERE reads cleanly.
            vec_filters = []
            if content_clause:
                vec_filters.append(content_clause.strip().lstrip("AND ").strip())
            if role_list:
                rp = ",".join("?" for _ in role_list)
                vec_filters.append(f"m.role IN ({rp})")
            vec_filters.append("(m.active = 1 OR m.compacted = 1)")
            vec_where = " AND ".join(vec_filters)

            vec_ids, _ = hybrid_message_ids(
                query,
                limit=limit + offset + 5,
                offset=0,
                where_sql=vec_where,
                params=tuple(role_list) if role_list else (),
            )
            if vec_ids:
                # RRF merge at message level (before session dedup).
                rrf_k = 60
                scores: dict[int, float] = {}
                for rank, r in enumerate(rows):
                    scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 / (rrf_k + rank + 1)
                for rank, mid in enumerate(vec_ids):
                    scores[mid] = scores.get(mid, 0.0) + 1.0 / (rrf_k + rank + 1)
                merged_ids = [mid for mid, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]

                # Fetch vector-only rows (missed by FTS).
                existing = {r["id"] for r in rows}
                vec_only = [mid for mid in merged_ids if mid not in existing]
                if vec_only:
                    ph = ",".join("?" for _ in vec_only)
                    try:
                        with sync_conn() as conn2:
                            vrows = conn2.fetchall(
                                f"""
                                SELECT
                                    m.id, m.session_id, m.role,
                                    substr(m.content, 1, 400) AS snippet,
                                    m.timestamp, m.tool_name,
                                    s.source, s.model,
                                    s.title AS session_title
                                FROM messages m
                                LEFT JOIN sessions s ON s.id = m.session_id
                                WHERE m.id IN ({ph})
                                """,
                                tuple(vec_only),
                            )
                            vdict = {r["id"]: dict(r) for r in vrows}
                    except Exception:
                        vdict = {}
                else:
                    vdict = {}

                by_id = {r["id"]: r for r in rows}
                by_id.update(vdict)
                # Rebuild rows in merged order; keep the tool's count semantics.
                merged_rows = [by_id[mid] for mid in merged_ids if mid in by_id]
                rows = merged_rows
                total = len(rows) if rows else total
        except Exception as exc:
            logger.warning("messages hybrid recall failed, using FTS-only: %s", exc)

    # Shape results — XML format for agent readability
    results = []
    for r in rows:
        snippet = _clean_snippet(r.get("snippet") or "")[:500]
        ts_fmt = _format_timestamp(r["timestamp"])
        sid = r["session_id"]
        results.append({
            "id": r["id"],
            "session_id": sid,
            "role": r["role"],
            "snippet": snippet,
            "timestamp": r["timestamp"],
            "timestamp_formatted": ts_fmt,
            "session_title": r.get("session_title") or "",
            "source": r.get("source") or "",
            "model": r.get("model") or "",
        })

    # Build XML summary — compact, navigable, agent-friendly
    xml_parts = [f"<messages query=\"{query}\" total=\"{total}\" shown=\"{len(results)}\" offset=\"{offset}\">"]
    for r in results:
        ts = r["timestamp_formatted"]
        title = r["session_title"] or r["session_id"][:12]
        sid = r["session_id"]
        xml_parts.append(
            f"  <hit id=\"{r['id']}\" ts=\"{ts}\" session=\"{sid}\" title=\"{title}\"/>"
        )
    xml_parts.append("</messages>")

    response = {
        "success": True,
        "query": query,
        "results": results,
        "count": len(results),
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": "\n".join(xml_parts),
        "message": f"💬 {total} sessions for \"{query}\". Showing {len(results)} (offset {offset}).",
    }

    # ── Smart refinement loop ──────────────────────────────────────────
    # RETIRED (2026-08-12): pgvector now does a decent job on single-topic
    # queries, so the FTS5 smart_refine loop is a dead leg for basic searches.
    # The LLM plumbing it used was repurposed into jpm.core._recall_planner,
    # which plans scope-aware vector queries for multi-topic context recall.
    # We keep the flag in the signature for backwards compat but no longer
    # invoke the FTS5 refinement loop.
    # if smart and current_session_id:
    #     from tools._smart_refine import smart_refine
    #     ... (removed)

    # Query relaxation on 0 results (only when smart=False — smart handles this)
    if not results and total == 0:
        relaxed = []
        words = query.strip().split()
        for n in range(len(words) - 1, 0, -1):
            shorter = " ".join(words[:n])
            try:
                with sync_conn() as conn:
                    rel_count = conn.execute(
                        """
                        SELECT COUNT(DISTINCT m.session_id) as total
                        FROM messages m
                        JOIN sessions s ON s.id = m.session_id
                        WHERE m.search_vector @@ websearch_to_tsquery('english', ?)
                          AND (m.active = 1 OR m.compacted = 1)
                          AND m.role IN ({rp})
                        """.format(rp=role_placeholders),
                        tuple([shorter] + role_list),
                    ).fetchone()
                    cnt = rel_count["total"] if rel_count else 0
                    if cnt > 0:
                        relaxed.append({"query": shorter, "count": cnt})
            except Exception:
                pass
        if relaxed:
            response["relaxed"] = relaxed
            response["message"] = (
                f"💬 0 sessions for \"{query}\". Try: "
                + ", ".join(f"'{r['query']}' ({r['count']} sessions)" for r in relaxed)
            )

    return json.dumps(response, ensure_ascii=False, default=_dt_default)


MESSAGES_SCHEMA = {
    "name": "messages",
    "description": (
        "messages — targeted recall of individual messages, session-independent. "
        "Use this to find a specific message or get situational awareness: pass a query= to search, "
        "or no query for browse mode (candle-style time buckets + recent messages). "
        "Search individual messages across ALL past sessions using HYBRID search — "
        "full-text first, then pgvector semantic recall RRF-merged in, so paraphrased and "
        "non-exact queries work. A keyword miss is NOT evidence of absence — vector "
        "recall returns top-k by meaning. "
        "Returns one result per session (the most recent matching message), sorted by "
        "timestamp DESC (newest first). Each result includes "
        "a Google-style snippet with the matched terms highlighted, the session title, "
        "and a timestamp.\\\\n\\\\n"
        "TWO MODES\\\\n\\\\n"
        "  BROWSE MODE (no query) — candle-style time buckets + recent messages.\\\\n"
        "  Returns XML like:\\\\n"
        "  <messages_browse total=\\\"52847\\\">\\\\n"
        "    <buckets>\\\\n"
        "      <bucket window=\\\"1h\\\" count=\\\"23\\\"/>\\\\n"
        "      <bucket window=\\\"4h\\\" count=\\\"89\\\"/>\\\\n"
        "      <bucket window=\\\"12h\\\" count=\\\"215\\\"/>\\\\n"
        "      <bucket window=\\\"24h\\\" count=\\\"347\\\"/>\\\\n"
        "      <bucket window=\\\"7d\\\" count=\\\"2103\\\"/>\\\\n"
        "      <bucket window=\\\"30d\\\" count=\\\"8920\\\"/>\\\\n"
        "      <bucket window=\\\"older\\\" count=\\\"43927\\\"/>\\\\n"
        "    </buckets>\\\\n"
        "    <recent limit=\\\"20\\\" offset=\\\"0\\\">\\\\n"
        "      <hit id=\\\"123\\\" ts=\\\"July 13, 2026 at 09:15 AM\\\" session=\\\"abc\\\" title=\\\"Title\\\" role=\\\"user\\\"/>\\\\n"
        "    </recent>\\\\n"
        "  </messages_browse>\\\\n\\\\n"
        "  SEARCH MODE (with query) — HYBRID search (full-text + semantic RRF merge).\\\\n"
        "  Returns XML like:\\\\n"
        "  <messages query=\\\"term\\\" total=\\\"42\\\" shown=\\\"20\\\" offset=\\\"0\\\">\\\\n"
        "    <hit id=\\\"123\\\" ts=\\\"...\\\" session=\\\"abc\\\" title=\\\"Title\\\"/>\\\\n"
        "  </messages>\\\\n\\\\n"
        "SEARCH SYNTAX\\\\n\\\\n"
        "  OR is the default — plain multi-word queries match any of the words. "
        "Use AND explicitly for stricter recall (`alpha AND beta`), quoted phrases "
        "for exact match (`\\\\\\\"docker networking\\\\\\\"`), boolean (`python NOT java`), "
        "or prefix wildcards (`deploy*`).\\\\n\\\\n"
        "ROLE FILTER\\\\n\\\\n"
        "  Pass an array of roles to include: `role=[\\\\\\\"user\\\\\\\",\\\\\\\"assistant\\\\\\\"]`. "
        "Default: user and assistant (tool output excluded). To include tool output, "
        "pass `role=[\\\\\\\"user\\\\\\\",\\\\\\\"assistant\\\\\\\",\\\\\\\"tool\\\\\\\"]`.\\\\n\\\\n"
        "CONTENT FILTER\\\\n\\\\n"
        "  `filter` controls what message content is searched:\\\\n"
        "  - `\\\\\\\"messages\\\\\\\"` (default) — actual conversation only. Excludes JPM context "
        "injection blocks and tool call output. Best for finding what was actually said.\\\\n"
        "  - `\\\\\\\"tool_calls\\\\\\\"` — only tool invocations (terminal, read_file, etc.). "
        "Use when you need to find a specific tool call.\\\\n"
        "  - `\\\\\\\"context\\\\\\\"` — only JPM/system context injection blocks "
        "(`[Context: JPM found ...]`). Use to audit what context was injected.\\\\n"
        "  - `\\\\\\\"all\\\\\\\"` — everything, no filtering. Raw content as stored.\\\\n"
        "  Combine with `role` for precision: "
        "`role=[\\\\\\\"assistant\\\\\\\"], filter=\\\\\\\"messages\\\\\\\"` finds only what the assistant said.\\\\n\\\\n"
        "PAGINATION\\\\n\\\\n"
        "  Use `limit` and `offset` for pagination. Default limit: 20, max: 100.\\\\n\\\\n"
        "QUERY RELAXATION\\\\n\\\\n"
        "  When 0 results are returned in search mode, the tool automatically tries "
        "progressively shorter versions of your query and includes them in the response "
        "so you can re-search without guessing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Search query. Omit for browse mode (candle-style time buckets + recent messages). "
                    "Keywords, phrases, or boolean expressions. "
                    "OR is default — plain multi-word queries match any word. "
                    "Use AND for stricter recall. Quoted phrases for exact match. "
                    "Boolean: python NOT java."
                ),
            },
            "role": {
                "type": "array",
                "items": {"type": "string", "enum": ["user", "assistant", "tool"]},
                "description": (
                    "Roles to include. Default: [\\\"user\\\", \\\"assistant\\\"]. "
                    "Pass [\\\"user\\\",\\\"assistant\\\",\\\"tool\\\"] to include tool output."
                ),
            },
            "filter": {
                "type": "string",
                "enum": ["messages", "tool_calls", "context", "all"],
                "description": (
                    "Content type to search. 'messages' (default) = actual conversation, "
                    "no JPM context blocks or tool output. 'tool_calls' = only tool invocations. "
                    "'context' = only JPM/system context injection blocks. "
                    "'all' = everything, no filtering."
                ),
                "default": "messages",
            },
            "limit": {
                "type": "integer",
                "description": "Max messages to return (default 20, max 100).",
                "default": 20,
            },
            "offset": {
                "type": "integer",
                "description": "Result offset for pagination (default 0).",
                "default": 0,
            },
            "smart": {
                "type": "boolean",
                "description": (
                    "When True, uses multi-pass LLM refinement to find better results "
                    "if the initial query returns poor results. The LLM sees the current "
                    "conversation context and suggests improved queries. Default: False."
                ),
                "default": False,
            },
        },
        "required": [],
    },
}


def check_messages_search_requirements() -> bool:
    """Requires PostgreSQL session store."""
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as e:
        logger.warning(
            "messages tool DISABLED — JPM PG unreachable: %s", e
        )
        return False



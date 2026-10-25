import os
import typing
import re
import logging
from datetime import datetime, timezone
from typing import Any

from ._pg import sync_conn
from ._ensure import _ensure_db
from ._paths import _get_yaml_path
from ._yaml import _build_yaml, _write_yaml
from ._read import _get_latest_pulse
from ._write import _write_pulse, _track_tool_use
from ._search import _search_knowledge
from ._hybrid_search import hybrid_enabled
from ._briefing import on_session_start_callback, get_briefing

LOG = logging.getLogger(__name__)

# ── Module-level state ──────────────────────────────────────────────────
_INJECTED_SESSIONS: set[str] = set()

# Default recall scope for the plugin's per-turn adaptive recall. Matches the
# run.py memory_enrichment default (curated high-signal stores only) so the two
# recall paths stay consistent and raw message/session history + skills (already
# in the system prompt) don't bloat the block or double the embed/vector cost.
_ENRICHMENT_DEFAULT_TABLES = ["knowledge", "reflections", "patterns"]

# ── retrieval filter chain (ported from the Mnemosyne prefetch chain) ──
# Single source of truth: the defaults dict lives in _hybrid_search (which does
# NOT import this module — the reverse would be circular, as _hooks imports
# _hybrid_search at module level). Every tunable still fails OPEN to its
# default when the key is absent from the memory_enrichment block, so a node
# with an older config.yaml keeps working unchanged. Read via
# _enrichment_config() — never hardcoded at the call site.
def _enrichment_tuning_defaults() -> dict:
    """The recall tuning defaults, sourced from _hybrid_search (one dict, no drift)."""
    from ._hybrid_search import _RECALL_TUNING_DEFAULTS

    return _RECALL_TUNING_DEFAULTS


def _parse_tuning(block: dict) -> dict:
    """Extract the recall tuning keys from the memory_enrichment block (fail-open).

    Missing/invalid value -> the default from _RECALL_TUNING_DEFAULTS.
    Never raises: a malformed value degrades to the default, not a crash.
    """
    out = {}
    for key, default in _enrichment_tuning_defaults().items():
        val = block.get(key, default)
        if isinstance(default, dict):
            # P3: weight map — accept a dict override, else the default map.
            out[key] = val if isinstance(val, dict) else default
            continue
        try:
            out[key] = type(default)(val) if val is not None else default
        except (TypeError, ValueError):
            out[key] = default
    return out


# Mtime-keyed cache so _enrichment_config doesn't re-read+parse config.yaml on
# every single turn. (mirrors run.py's _load_gateway_config caching).
_ENRICHMENT_CFG_CACHE: dict | None = None
_ENRICHMENT_CFG_MTIME: float | None = None


def _enrichment_config() -> dict:
    """Read the memory_enrichment block from $HERMES_HOME/config.yaml (fail-open).

    Returns {"enabled": bool, "tables": [str, ...]} with the same defaults as
    the run.py memory_enrichment gate, so the plugin's per-turn adaptive recall
    and the gateway's auto-enrichment honor ONE config and never disagree about
    scope. Any read error degrades to the defaults (enabled, curated scope).

    Result is cached and invalidated on config mtime change, so this costs a
    stat() per turn, not a read+parse.
    """
    try:
        import yaml as _yaml
        from ._paths import _get_agent_home
        from pathlib import Path

        cfg_path = Path(_get_agent_home()) / "config.yaml"
        if cfg_path.exists():
            mtime = cfg_path.stat().st_mtime
            global _ENRICHMENT_CFG_CACHE, _ENRICHMENT_CFG_MTIME
            if _ENRICHMENT_CFG_CACHE is not None and mtime == _ENRICHMENT_CFG_MTIME:
                return _ENRICHMENT_CFG_CACHE
            cfg = _yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            block = cfg.get("memory_enrichment", {}) or {}
            raw_tables = block.get("tables")
            # Guard the empty-list footgun: an explicit [] means "sweep
            # nothing", NOT "full sweep". Distinguish missing key (None) from
            # explicit empty list.
            tables = (
                _ENRICHMENT_DEFAULT_TABLES
                if raw_tables is None
                else ([t for t in raw_tables if isinstance(t, str)] if isinstance(raw_tables, (list, tuple)) else _ENRICHMENT_DEFAULT_TABLES)
            )
            # If an explicit [] was set, keep it empty (sweep nothing).
            if isinstance(raw_tables, (list, tuple)) and len(raw_tables) == 0:
                tables = []
            _ENRICHMENT_CFG_CACHE = {
                "enabled": bool(block.get("enabled", True)),
                "tables": tables,
                # Independent kill-switch for the plugin (pre_llm_call) path,
                # so it can be disabled without turning off the gateway hook.
                "plugin_enabled": bool(block.get("plugin", True)),
                # retrieval filter-chain tunables (fail-open defaults per key).
                **_parse_tuning(block),
            }
            _ENRICHMENT_CFG_MTIME = mtime
            return _ENRICHMENT_CFG_CACHE
    except Exception as e:
        LOG.debug("memory_enrichment config read failed, using defaults: %s", e)
    return {"enabled": True, "tables": list(_ENRICHMENT_DEFAULT_TABLES), "plugin_enabled": True}


def _fetch_recent_session_context(user_message: str) -> str:
    """Find the most semantically relevant session via pgvector, then bookend it.

    Vector-primary: embed the user's message and pull the nearest-neighbor
    session from the sessions HNSW index (fast, semantic — not a keyword
    lottery). Falls back to the old FTS path if pgvector/Ollama is down.
    """
    if not user_message:
        return ""

    # ── Vector-primary path ────────────────────────────────────────
    try:
        from ._hybrid_search import _embed_query, _vector_search_ids

        query_vec = _embed_query(user_message)
        if query_vec:
            session_hits = _vector_search_ids("sessions", query_vec, 1)
            if session_hits:
                return _bookend_session(session_hits[0][0])
    except Exception:
        pass

    # ── FTS fallback (crutch — only when vector path unavailable) ──
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT m.session_id, s.title, s.started_at, "
                "       MIN(m.id) as first_id, MAX(m.id) as last_id "
                "FROM messages m "
                "JOIN sessions s ON s.id = m.session_id "
                "WHERE m.search_vector @@ plainto_tsquery('english', ?) "
                "  AND m.role = 'user' "
                "GROUP BY m.session_id, s.title, s.started_at "
                "ORDER BY s.started_at DESC "
                "LIMIT 1",
                (user_message,)
            )
            if not row:
                return ""
            return _bookend_session(row["session_id"])
    except Exception:
        return ""


def _bookend_session(session_id: str) -> str:
    """Build the [Recent Session] block for a given session id (first + last messages)."""
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT s.title, s.started_at, "
                "       (SELECT MIN(m.id) FROM messages m WHERE m.session_id = s.id) as first_id, "
                "       (SELECT MAX(m.id) FROM messages m WHERE m.session_id = s.id) as last_id "
                "FROM sessions s WHERE s.id = ?",
                (session_id,)
            )
            if not row:
                return ""
            title = row["title"]
            started_at = row["started_at"]
            first_id = row["first_id"]
            last_id = row["last_id"]

            start_messages = conn.fetchall(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND id >= ? "
                "ORDER BY id ASC LIMIT 3",
                (session_id, first_id)
            )
            end_rows = conn.fetchall(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND id <= ? "
                "ORDER BY id DESC LIMIT 3",
                (session_id, last_id)
            )
            end_messages = list(reversed(end_rows))
    except Exception:
        return ""

    lines = []
    ts = datetime.fromtimestamp(started_at).strftime("%Y-%m-%d %H:%M") if started_at else "?"
    lines.append(f"[Recent Session] {title or 'untitled'} ({ts})")

    for msg in start_messages[:2]:
        snippet = (msg["content"] or "")[:100].replace("\n", " ")
        if snippet:
            lines.append(f"  [Start] {msg['role']}: {snippet}")

    lines.append(f"  ... ({'?' if last_id and first_id else '0'} messages total)")

    for msg in end_messages[:2]:
        snippet = (msg["content"] or "")[:100].replace("\n", " ")
        if snippet:
            lines.append(f"  [End] {msg['role']}: {snippet}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# Hooks
# ═══════════════════════════════════════════════════════════════════════

def pre_llm_call_callback(
    user_message: str = "",
    conversation_history: list | None = None,
    **kwargs,
) -> typing.Optional[str]:
    """Inject compact YAML context on first turn of a new session.
    Also does lightweight JPM lookup on every turn for lookup-style queries.
    """
    if not user_message:
        return None

    session_id: str = kwargs.get("session_id", "") or ""
    _ensure_db()

    # ── Per-turn adaptive JPM recall (vector-primary, on by default) ──
    # Every turn, embed the user's message and pull the nearest-neighbor
    # matches across the configured memory tables — so the agent is born
    # knowing the most relevant context to the *current* query, not a keyword
    # lottery. Scope + kill-switch come from memory_enrichment config (shared
    # with the run.py auto-enrichment gate) so the two paths stay consistent.
    _enr = _enrichment_config()
    # Gate on BOTH the global enabled flag AND the plugin-specific switch, so
    # the plugin recall path can be turned off independently of the gateway's
    # run.py auto-enrichment (avoids double embed + double sweep per turn when
    # both are on).
    if _enr["enabled"] and _enr.get("plugin_enabled", True) and hybrid_enabled():
        from ._hybrid_search import recall_context

        try:
            recalled = recall_context(
                user_message,
                limit=5,
                session_id=session_id,
                tables=_enr["tables"],
                tuning=_enr,
            )
            if recalled:
                lines = ["[JPM Adaptive Recall]"]
                for r in recalled:
                    snippet = (r["snippet"] or "").replace("\n", " ")[:140]
                    title = r["title"] or ""
                    if title:
                        lines.append(f"  [{r['tag']}] {title}: {snippet}")
                    else:
                        lines.append(f"  [{r['tag']}] {snippet}")
                recall_block = "\n".join(lines)
                LOG.info("jpm: injected adaptive recall (%d) for session %s",
                         len(recalled), session_id)
                # Merge with briefing on first turn, else return recall block
                briefing = get_briefing(session_id) if (session_id and session_id not in _INJECTED_SESSIONS) else ""
                if briefing:
                    combined = briefing + "\n\n" + recall_block
                    _INJECTED_SESSIONS.add(session_id) if session_id else None
                    return combined
                return recall_block
        except Exception as e:
            LOG.warning("jpm: adaptive recall failed, falling through: %s", e)

    # ── Fallback: per-turn lookup for credential/system queries ──
    lookup_patterns = [
        r'\b(credential|password|ssh|login|auth|token|key|secret|host|ip|port)\b',
        r'\b(jim|melissa|kate|tina|node|server|agent)\b.*\b(cred|ssh|host|ip|port|pass)\b',
        r'\b(where|what|how|who)\b.*\b(is|are|does|runs|host|connect)\b',
        r'\b(find|lookup|search|get|fetch|recall|remember)\b',
        r'\b(credential|config|setup|access|details|info)\b',
    ]
    is_lookup = any(re.search(p, user_message.lower()) for p in lookup_patterns)

    if is_lookup:
        try:
            lookup_results, _ = _search_knowledge(user_message, 5)
            if lookup_results:
                lines = ["[JPM Quick Lookup]"]
                for r in lookup_results:
                    lines.append(f"  [{r['entity_type']}] {r['name']}: {r['description'][:120]}")
                lookup_block = "\n".join(lines)
                LOG.info("jpm: injected lookup (%d results) for session %s", len(lookup_results), session_id)
                return lookup_block
        except Exception:
            pass

    # ── First-turn full context injection ─────────────────────────
    if not session_id or session_id in _INJECTED_SESSIONS:
        return None

    # Inject session briefing (cached by on_session_start)
    briefing = get_briefing(session_id)
    if briefing:
        LOG.info("jpm: injected briefing (%d chars) for session %s", len(briefing), session_id)
        return briefing

    yaml_content = _build_yaml()
    if not yaml_content:
        return None

    # Append recent session context
    session_context = _fetch_recent_session_context(user_message)
    if session_context:
        yaml_content += "\n\n" + session_context

    _write_yaml(_get_yaml_path(), yaml_content)
    _INJECTED_SESSIONS.add(session_id)
    LOG.info("jpm: injected %d chars for session %s", len(yaml_content), session_id)

    return yaml_content


def post_llm_call_callback(**kwargs) -> None:
    """Auto-write pulse on session end."""
    user_msg = kwargs.get("user_message", "")
    response_text = kwargs.get("response_text", "")
    session_id = kwargs.get("session_id", "")

    end_patterns = [
        re.compile(r"\b(?:/new|/reset|/quit|/exit|goodbye|signing off)\b", re.IGNORECASE),
    ]
    is_ending = any(p.search(user_msg) for p in end_patterns) if user_msg else False

    if is_ending:
        _ensure_db()
        summary = ""
        if response_text:
            first_sent = response_text.split(".")[0].strip()
            if first_sent and len(first_sent) > 10:
                summary = first_sent[:200]
        _write_pulse("idle", summary, session_id)
        LOG.info("jpm: wrote session end pulse")


def post_tool_call_callback(tool_name: str = "", result: Any = None, **kwargs) -> None:
    """Track tool usage."""
    if not tool_name:
        return
    _ensure_db()
    _track_tool_use(tool_name)


def on_session_end_callback(**kwargs) -> None:
    """Write session breadcrumb + pulse_history snapshot."""
    _ensure_db()
    session_id = kwargs.get("session_id", "")

    # ── Pulse (existing behavior) ──
    pulse = _get_latest_pulse()
    if not pulse:
        _write_pulse("idle", "", session_id)

    # ── pulse_history snapshot ──
    try:
        with sync_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pulse_history (
                    id         BIGSERIAL PRIMARY KEY,
                    mood       TEXT DEFAULT 'neutral',
                    energy     TEXT DEFAULT 'okay',
                    health     TEXT DEFAULT '',
                    headspace  TEXT DEFAULT '',
                    session_id TEXT DEFAULT '',
                    created_at REAL DEFAULT EXTRACT(EPOCH FROM NOW())
                )
            """)
            conn.execute("""
                INSERT INTO pulse_history (mood, energy, health, headspace, session_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                "neutral",
                "okay",
                "nominal" if pulse else "unknown",
                f"session ended: {session_id}",
                session_id,
            ))
    except Exception:
        LOG.debug("pulse_history write failed", exc_info=True)

    LOG.info("jpm: memory extraction on session: %s", session_id)
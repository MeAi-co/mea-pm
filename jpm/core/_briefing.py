"""Session briefing — auto-gathered context at session start.

Fires on the ``on_session_start`` hook. Queries the session DB and JPM
tables directly (no LLM call) to build a compact briefing of recent
activity, open loops, and current focus. The briefing is cached per
session and injected into the first ``pre_llm_call``.

No delegate_task needed — this is pure SQL, runs in <50ms.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ._pg import sync_conn

LOG = logging.getLogger(__name__)

# Session-scoped cache: session_id -> briefing text
_BRIEFING_CACHE: dict[str, str] = {}


def _safe(val: Any, default: str = "") -> str:
    if val is None:
        return default
    s = str(val)
    return s[:200] if len(s) > 200 else s


_LOCAL_TZ = timezone(timedelta(hours=4))  # Asia/Dubai (UTC+4), no DST


def _local(ts: float) -> str:
    """Format a Unix epoch as local Dubai wall-clock time."""
    try:
        return datetime.fromtimestamp(ts, tz=_LOCAL_TZ).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def build_briefing(session_id: str) -> str:
    """Build a compact session briefing from DB queries.

    Returns a plain-text block that the main agent can consume on first turn.
    """
    parts: list[str] = []

    try:
        with sync_conn() as conn:
            # ── 1. Recent sessions (by timestamp, not FTS5) ────────────
            recent = conn.fetchall(
                "SELECT id, title, started_at, message_count "
                "FROM sessions "
                "WHERE id != ? "
                "ORDER BY started_at DESC "
                "LIMIT 3",
                (session_id,)
            )

            if recent:
                parts.append("── Recent Sessions ──")
                for s in recent:
                    ts = ""
                    if s["started_at"]:
                        ts = _local(s["started_at"])
                    title = _safe(s["title"], "untitled")
                    msg_count = s["message_count"] or 0
                    parts.append(f"  [{ts}] {title} ({msg_count} msgs)")

                    # Get last 2 user/assistant messages from this session for context
                    last_msgs = conn.fetchall(
                        "SELECT role, content FROM messages "
                        "WHERE session_id = ? AND role IN ('user', 'assistant') "
                        "ORDER BY id DESC LIMIT 2",
                        (s["id"],)
                    )
                    last_msgs.reverse()
                    for msg in last_msgs:
                        role = msg["role"] or "?"
                        content = _safe(msg["content"], "")[:120]
                        if content:
                            if role == "user":
                                parts.append(f"    👤 {content}")
                            elif role == "assistant" and not content.startswith("{"):
                                parts.append(f"    🤖 {content}")
                parts.append("")

            # ── 2. JPM Pulse ──────────────────────────────────────────
            try:
                pulse = conn.fetchone(
                    "SELECT status, summary FROM pulse ORDER BY created_at DESC LIMIT 1"
                )
                if pulse and pulse["status"]:
                    status = pulse["status"]
                    summary = _safe(pulse["summary"])
                    if summary:
                        parts.append(f"Status: {status} — {summary}")
                    else:
                        parts.append(f"Status: {status}")
            except Exception:
                pass

            # ── 2b. Gateway restart awareness ─────────────────────────
            try:
                gw = conn.fetchone(
                    "SELECT event_type, commit_sha, pid, hostname, started_at "
                    "FROM gateway_events "
                    "WHERE event_type = 'boot' "
                    "ORDER BY started_at DESC LIMIT 1"
                )
                if gw and gw["started_at"]:
                    _boot_dt = datetime.fromtimestamp(gw["started_at"], tz=_LOCAL_TZ)
                    _ago = (datetime.now(_LOCAL_TZ) - _boot_dt).total_seconds()
                    _ago_str = f"{int(_ago)}s"
                    if _ago > 3600:
                        _ago_str = f"{_ago/3600:.1f}h"
                    elif _ago > 60:
                        _ago_str = f"{int(_ago/60)}m"
                    _sha = _safe(gw.get("commit_sha", ""))
                    _sha_str = f" @ {_sha}" if _sha else ""
                    _host = _safe(gw.get("hostname", ""))
                    _host_str = f" on {_host}" if _host else ""
                    parts.append(f"Gateway boot: {_ago_str} ago{_sha_str}{_host_str}")
            except Exception:
                pass

            # ── 3. Active focus ────────────────────────────────────────
            try:
                active = conn.fetchone(
                    "SELECT focus, project, status FROM active ORDER BY updated_at DESC LIMIT 1"
                )
                if active and active["focus"]:
                    focus = active["focus"]
                    proj = _safe(active.get("project", ""))
                    st = _safe(active.get("status", ""))
                    line = f"Focus: {focus}"
                    if proj:
                        line += f" [{proj}]"
                    if st:
                        line += f" ({st})"
                    parts.append(line)
            except Exception:
                pass

            # ── 4. Open loops (top 3) ──────────────────────────────────
            try:
                loops = conn.fetchall(
                    "SELECT content, priority, project FROM loops WHERE resolved = 0 ORDER BY priority DESC, created_at DESC LIMIT 3"
                )
                if loops:
                    parts.append("Open Loops:")
                    for l in loops:
                        content = _safe(l["content"], "")[:100]
                        priority = l["priority"] or "medium"
                        proj = _safe(l.get("project", ""))
                        tag = f"[{priority.upper()}]" if priority != "medium" else ""
                        proj_tag = f" ({proj})" if proj else ""
                        if content:
                            parts.append(f"  {tag} {content}{proj_tag}")
            except Exception:
                pass
    except Exception as e:
        LOG.debug("jpm briefing: query failed: %s", e)
        return ""

    if not parts:
        return ""

    return "\n".join(parts)


def on_session_start_callback(**kwargs: Any) -> None:
    """Hook: build and cache a session briefing on session start.

    Fires from the ``on_session_start`` plugin hook. The briefing is
    stored in a module-level dict keyed by session_id. On the first
    ``pre_llm_call``, the briefing is injected into the context.
    """
    session_id: str = kwargs.get("session_id", "") or ""
    if not session_id:
        return

    briefing = build_briefing(session_id)
    if briefing:
        _BRIEFING_CACHE[session_id] = briefing
        LOG.info("jpm: session briefing cached (%d chars) for %s", len(briefing), session_id)


def get_briefing(session_id: str) -> str:
    """Retrieve and consume the cached briefing for a session."""
    return _BRIEFING_CACHE.pop(session_id, "")


def clear_briefing(session_id: str) -> None:
    """Explicitly clear a cached briefing."""
    _BRIEFING_CACHE.pop(session_id, None)

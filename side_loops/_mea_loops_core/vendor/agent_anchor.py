"""agent_anchor (vendored) — DB-only anchor GENERATION for the MEAI loop.

The fork's ``core/agent/agent_anchor.py`` stores the anchor on the live agent
and injects it in ``conversation_loop``. Stock has no agent in the hook, so the
loop is split:

  * GENERATION (this module, DB-only) -> reads the lean trajectory, condenses it
    to 1-3 first-person sentences via the aux LLM, returns the text. The caller
    persists it (``_mea_loops_core.anchor_store``).
  * INJECTION -> the ``llm_request`` middleware reads the store and inserts the
    anchor at position 1.

Vendored (not imported from the upstream tree) so the plugin has no external
dependency. Imports ONLY stock modules + the vendored engine.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ANCHOR_CAP_CHARS = 300
DEFAULT_MAX_SOURCE_CHARS = 6000


def _cfg(agent: Any, name: str, default: Any) -> Any:
    val = getattr(agent, name, None)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def build_anchor(agent: Any, session_id: str) -> Optional[str]:
    """Generate the volatile first-person anchor for *session_id*.

    Reads the lean surviving trajectory from the DB, condenses it, caps it, and
    returns the text (or None). Best-effort — never raises.
    """
    if not session_id:
        return None
    try:
        from jpm.core._pg import sync_conn

        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND role IN ('user','assistant') "
                "AND content IS NOT NULL AND TRIM(content) <> '' "
                "AND is_digest IS NOT TRUE "
                "ORDER BY id ASC "
                "LIMIT 40",
                [session_id],
            )
        if not rows:
            return None

        parts: List[str] = []
        for r in rows[-16:]:
            role = r.get("role")
            txt = (r.get("content") or "").strip()
            if not txt:
                continue
            parts.append(f"{'USER' if role == 'user' else 'ASST'}: {txt[:400]}")
        source = "\n".join(parts)[-_cfg(agent, "anchor_max_source_chars", DEFAULT_MAX_SOURCE_CHARS):]
        if not source.strip():
            return None

        anchor = _condense(agent, source)
        if not anchor:
            return None

        cap = _cfg(agent, "session_anchor_cap_chars", DEFAULT_ANCHOR_CAP_CHARS)
        if len(anchor) > cap:
            anchor = anchor[:cap].rstrip() + "…"
        return anchor
    except Exception as exc:
        logger.debug("anchor: build failed (%s)", exc)
        return None


def _condense(agent: Any, source: str) -> Optional[str]:
    """Condense the trajectory into a tight first-person anchor via the aux LLM."""
    try:
        from agent.auxiliary_client import call_llm

        prompt = (
            "You condense a session trajectory into ONE tiny first-person anchor "
            "that lets the assistant immediately remember where it is. Write it "
            "STRICTLY FIRST-PERSON from the assistant's own view (\"We're working "
            "on X. Established: Y. Open: Z.\") in the assistant's own warm, natural "
            "voice. Cover: state, decisions made, established facts, open loops. "
            "Keep it to 1-3 short sentences — a pointer, not a replay. Do NOT add "
            "anything not implied by the source. Do NOT write third-person "
            "(\"The assistant is...\"). Do NOT use a user's voice.\n\n"
            "TRAJECTORY:\n"
            f"{source}"
        )
        resp = call_llm(
            task="compression",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_cfg(agent, "session_anchor_max_tokens", 220),
        )
        out = ""
        try:
            out = resp.choices[0].message.content or ""
        except Exception:
            out = str(resp) if not isinstance(resp, (dict, list)) else ""
        if not out and isinstance(resp, dict):
            out = resp.get("content") or resp.get("text") or ""
        return (out or "").strip() or None
    except Exception as exc:
        logger.debug("anchor: aux condense failed (%s)", exc)
        return None


def recompact_session_summary(agent: Any, anchor: Optional[str] = None) -> Optional[str]:
    """Tier-2 recompact: condense uncompacted session_summary_log rows (+ the
    volatile anchor) into ONE first-person ``sessions.summary`` brief, then flip
    the absorbed rows to ``compacted = true``.

    DB-only — the whole read→condense→write→flip is one transaction. The anchor
    is passed IN (the subprocess has no live agent to read ``_session_anchor``
    from); the caller reads it from the anchor store. Returns the new brief, or
    None if there was nothing to condense. Best-effort — never raises.
    """
    session_id = getattr(agent, "session_id", None)
    if not session_id:
        return None
    try:
        from jpm.core._pg import sync_conn

        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT id, content FROM session_summary_log "
                "WHERE session_id = ? AND compacted IS NOT TRUE "
                "ORDER BY id ASC",
                [session_id],
            )
            if not rows:
                return None
            row_ids = [r.get("id") for r in rows]
            chunks = "\n\n".join(
                (r.get("content") or "").strip() for r in rows if (r.get("content") or "").strip()
            )
        if not chunks.strip():
            return None

        if anchor:
            chunks = f"VOLATILE ANCHOR (first-person, current state):\n{anchor}\n\nCHAPTER LOG:\n{chunks}"

        brief = _condense_summary(agent, chunks)
        if not brief:
            return None

        cap = _cfg(agent, "session_anchor_cap_chars", DEFAULT_ANCHOR_CAP_CHARS)
        if len(brief) > cap:
            brief = brief[:cap].rstrip() + "…"

        with sync_conn() as conn:
            with conn.transaction():
                conn.execute(
                    "UPDATE sessions SET summary = ? WHERE id = ?",
                    (brief, session_id),
                )
                for _rid in row_ids:
                    conn.execute(
                        "UPDATE session_summary_log SET compacted = true WHERE id = ?",
                        (_rid,),
                    )
        logger.info(
            "🧭 summary: recompacted %d chapter rows → sessions.summary (%d chars) for %s",
            len(row_ids), len(brief), session_id,
        )
        return brief
    except Exception as _e:
        logger.debug("🧭 summary: recompact failed (%s) — keeping last brief", _e)
        return None


def _condense_summary(agent: Any, source: str) -> Optional[str]:
    """Condense the chapter log (+ anchor) into ONE first-person session brief."""
    try:
        from agent.auxiliary_client import call_llm

        prompt = (
            "You condense a session's chapter log into ONE first-person brief that "
            "lets the assistant know exactly where the session stands. Write it "
            "STRICTLY FIRST-PERSON from the assistant's own view (\"We built X. "
            "Decided Y. Open: Z.\") in the assistant's own warm, natural voice. "
            "Cover: what's been done, decisions made, established facts, open loops. "
            "Keep it to 2-4 sentences — a pointer, not a replay. Do NOT add anything "
            "not implied by the source. Do NOT write third-person. Do NOT use a "
            "user's voice.\n\n"
            "SOURCE:\n"
            f"{source}"
        )
        resp = call_llm(
            task="compression",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=_cfg(agent, "session_anchor_max_tokens", 220),
        )
        out = ""
        try:
            out = resp.choices[0].message.content or ""
        except Exception:
            out = str(resp) if not isinstance(resp, (dict, list)) else ""
        if not out and isinstance(resp, dict):
            out = resp.get("content") or resp.get("text") or ""
        return (out or "").strip() or None
    except Exception as _e:
        logger.debug("🧭 summary: aux condense failed (%s) — keeping raw", _e)
        return None

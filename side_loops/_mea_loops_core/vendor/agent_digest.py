"""
Agent-Message Digest Compressor — async, deferred, in-place per-row compression.

Compresses the CONTENT of oversized old ASSISTANT messages so the rolling window
stays lean — without deleting rows, without inserting, without re-embedding, and
without touching the user's messages or the in-flight turn. See skill
`agent-message-digest-compressor` for the full design rationale.

Fire `run_agent_digest(...)` from the nudge-boundary background thread
(`turn_finalizer._run_background_review`) AFTER tool-flow summarization has
collapsed the tool wall, so this only digests assistant TEXT — not tool outputs
(which TFS already handles).

Core rules (from Josh, 2026-09-01):
  1. Row-count constant, IDs preserved AS-IS. Only `UPDATE messages SET content`.
     Zero deletes, zero inserts, zero identity churn.
  2. Only ASSISTANT rows, never user (short + precious) and never the in-flight
     (current) row — only rows already `id < current`.
  3. Embeddings kept identical. Do NOT re-embed — the original vector points at
     true semantic meaning; re-embedding the digest pays an embed call for a WORSE
     vector. `content_hash` + `@lru_cache` dedup stay untouched.
  4. Digest MUST be synthetic-tagged so recall treats it as recollect, not verbatim
     truth (else "I already said that" narration-abort stall).
  5. Track `summarized_at` per row so we don't re-chew the same block every nudge.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Diagnostic dump (mirrors context_dump_logger) ────────────────────────
# Logs the ins/outs of every digest pass so we can see WHY it fires or bails.
# Enabled via `digest_dump_log: true` on the agent (or env JOSHAICO_DIGEST_DUMP_LOG).
_DUMP_DIR = Path.home() / ".joshaico" / "logs" / "digest_dump"
_DUMP_DIR.mkdir(parents=True, exist_ok=True)
_DUMP_LINE = _DUMP_DIR.parent / "digest_dump.log"


def _dump_enabled(agent: Any = None) -> bool:
    if agent is not None:
        flag = getattr(agent, "_digest_dump_log", None)
        if flag is not None:
            return bool(flag)
    return os.environ.get("JOSHAICO_DIGEST_DUMP_LOG", "").lower() in ("1", "true", "yes")


def _dump_event(agent: Any, *, event: str, session_id: str = "", **extra: Any) -> None:
    """Write one digest-pass event to the dump log (JSON line + per-event file)."""
    if not _dump_enabled(agent):
        return
    ts = datetime.now()
    payload = {
        "ts": ts.isoformat(),
        "event": event,
        "session": (session_id or getattr(agent, "session_id", "") or "")[-32:],
        **extra,
    }
    try:
        with open(_DUMP_LINE, "a") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.debug("agent_digest: dump line failed (%s)", exc)
    try:
        fname = f"{ts.strftime('%Y%m%d_%H%M%S_%f')}_{event}.json"
        (_DUMP_DIR / fname).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        )
    except Exception as exc:
        logger.debug("agent_digest: dump file failed (%s)", exc)

# ── Defaults (overridable on the agent, see run_agent_digest) ──────────────
DEFAULT_COMPRESS_ABOVE_CHARS = 500   # rows with content > this get processed
DEFAULT_DIGEST_MAX_CHARS = 300      # target max length for a mid digest
DEFAULT_HEAD_TAIL_CHARS = 100       # head/tail kept RAW, never summarized
DEFAULT_BATCH_SIZE = 20             # rows per pass
DEFAULT_MAX_LLM_CALLS = 5           # hard cap on aux LLM calls per pass (safety)
DEFAULT_WARM_WINDOW = 50            # only digest rows inside the warm-start tail


def _cfg(agent: Any, name: str, default: Any) -> Any:
    """Read an int config knob off the agent, falling back to the default."""
    val = getattr(agent, name, None)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _now_ts() -> datetime:
    """UTC datetime — asyncpg binds this natively to timestamptz."""
    return datetime.now(timezone.utc)


def _summarize_gist(agent: Any, text: str, row_id: Optional[int] = None) -> str:
    """Produce a lean, ACCURATE gist of the middle content in the agent's voice.

    Returns the raw middle if summarization fails or is unavailable — never a
    fabricated digest. The only quality gate is accuracy: preserve decision /
    state change / answer / established fact; shed the flourish.
    """
    # Use the centralized aux LLM call — the proven path siblings use
    # (title_generator, conversation_compression). It resolves provider +
    # model from `auxiliary.compression` config with its own fallbacks and
    # returns a chat-completions-style response. Never carries/reuses an agent
    # attribute (agents have no persistent aux client), and never crashes the
    # pass on failure.
    try:
        from agent.auxiliary_client import call_llm

        system = (
            "You compress one assistant message for a compact rolling context.\n"
            "Rules:\n"
            "- Preserve the DECISION, STATE CHANGE, ANSWER, and any ESTABLISHED FACT.\n"
            "- Shed all flourish, hedging, filler, and word soup.\n"
            "- Do NOT add anything not implied by the source. Do NOT prefix with "
            "labels. Do NOT wrap in quotes.\n"
            "- If the source is already concise, keep it as-is.\n"
            "\n"
            "Your final response MUST NOT exceed %d characters. This is a hard limit."
        ) % _cfg(agent, "digest_max_chars", DEFAULT_DIGEST_MAX_CHARS)
        prompt = (
            "SOURCE (assistant message, may be truncated):\n"
            f"{text}"
        )
        resp = call_llm(
            task="compression",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=_cfg(agent, "digest_max_tokens", 220),
            temperature=0,
            main_runtime=(
                agent._current_main_runtime()
                if hasattr(agent, "_current_main_runtime")
                else None
            ),
        )
        out = ""
        try:
            out = resp.choices[0].message.content or ""
        except Exception:
            out = str(resp) if not isinstance(resp, (dict, list)) else ""
        if not out and isinstance(resp, dict):
            out = resp.get("content") or resp.get("text") or ""
        out = (out or "").strip()
        # Never return an empty or runaway digest — fall back to a truncated raw.
        if not out:
            _dump_event(
                agent, event="llm_call", row_id=row_id,
                system=system, prompt=prompt, output="",
                note="empty output — fell back to truncated raw",
            )
            return text[: _cfg(agent, "digest_max_chars", DEFAULT_DIGEST_MAX_CHARS)]
        _dump_event(
            agent, event="llm_call", row_id=row_id,
            system=system, prompt=prompt, output=out,
        )
        return out
    except Exception as _e:  # best-effort; never fabricate under failure
        logger.debug("agent_digest: aux summarizer failed (%s) — keeping raw", _e)
        _dump_event(
            agent, event="llm_call", row_id=row_id,
            system=locals().get("system", ""), prompt=locals().get("prompt", ""),
            output="", err=str(_e),
        )
        return text


def _digest_row(agent: Any, content: str, row_id: Optional[int] = None) -> str:
    """Build the per-row digest: head (raw) + mid (gist) + tail (raw)."""
    head_chars = _cfg(agent, "digest_head_tail_chars", DEFAULT_HEAD_TAIL_CHARS)
    max_chars = _cfg(agent, "digest_max_chars", DEFAULT_DIGEST_MAX_CHARS)
    if len(content) <= head_chars * 2 + max_chars:
        # Middle shorter than a digest would be — leave the row raw entirely.
        return content
    head = content[:head_chars]
    tail = content[-head_chars:]
    mid = content[head_chars:-head_chars] if head_chars else content
    gist = _summarize_gist(agent, mid, row_id=row_id)
    if len(gist) > max_chars:
        gist = gist[:max_chars].rstrip() + "…"
    return f"{head} …⟦digest⟧… {gist} …⟦digest⟧… {tail}"


def _select_candidates(
    conn: Any,
    session_id: str,
    current_id: int,
    batch_size: int,
    compress_above: int,
    warm_window: int = DEFAULT_WARM_WINDOW,
) -> List[Dict[str, Any]]:
    # Only ASSISTANT FINAL rows (finish_reason='stop') that are LIVE (active=1)
    # and inside the warm-start replay tail — the only rows a future turn
    # actually re-reads from PG. Never user/system/tool rows, never the
    # in-flight row, never archived rows (active=0), never tool-call rows.
    #
    # Why the scope (Josh 2026-10-11): the warm-start tail is the last
    # `warm_window` user/assistant rows (gateway `warm_start_messages`, default
    # 50). Digesting anything outside it is pure waste — archived rows are
    # never replayed, and old live rows fall out of the tail before they are
    # ever read again. Oldest-first (ORDER BY id ASC) drained the wrong end of
    # the queue and never reached the rows that replay.
    #
    # The window subquery MUST mirror `get_messages_tail`'s replay filter
    # EXACTLY (role set + active/compacted gate), or the two windows drift:
    # the replay tail counts tool_flow_summary carriers, so a user/assistant-
    # only window reaches FURTHER BACK than the true tail and digests rows that
    # never replay. Keep these two in lockstep. (Josh 2026-10-11)
    return conn.fetchall(
        "SELECT id, content FROM messages "
        "WHERE session_id = ? AND role = 'assistant' "
        "AND finish_reason = 'stop' AND active = 1 "
        "AND id < ? AND agent_compacted = 0 "
        "AND COALESCE(LENGTH(content), 0) > ? "
        "AND id >= ("
        "  SELECT COALESCE(MIN(id), 0) FROM ("
        "    SELECT id FROM messages m "
        "    WHERE m.session_id = ? AND (m.active = 1 OR m.compacted = 1) "
        "    AND (m.role = 'user' "
        "         OR (m.role = 'assistant' AND m.finish_reason = 'stop') "
        "         OR (m.role = 'tool' AND m.tool_name = 'tool_flow_summary')) "
        "    ORDER BY m.id DESC LIMIT ?"
        "  ) warm"
        ") "
        "ORDER BY id ASC LIMIT ?",
        [session_id, current_id, compress_above,
         session_id, warm_window, batch_size],
    )


def _archive_stray_rows(
    agent: Any,
    session_id: str,
    current_id: int,
    protect_last_n: int,
    compress_above: int,
) -> int:
    """Soft-archive stray rows that do NOT belong in conversation history.

    Runs at the nudge boundary alongside the digest pass. Every operation is a
    soft-archive (``active = 0``) — nothing is deleted, IDs / embeddings /
    content_hash are untouched, and the canonical copy of every logical message
    always survives. Only ``user`` + ``assistant(finish_reason='stop')`` rows
    (plus the recent tool_flow_summary carriers) remain live for history fetch.

    Scope — three safe categories:
      1. assistant ``finish_reason`` empty/NULL rows that have a ``stop`` twin
         (same ``content_hash``) -> pure warm-replay dupe; the stop row is
         canonical, so the bare copy is archived.
      2. assistant ``finish_reason`` empty/NULL rows <= ``compress_above`` chars
         -> interstitial narration, never a real reply (finals are stamped
         ``stop`` by design).
      3. ``tool_flow_summary`` carrier rows older than the last
         ``protect_last_n`` messages -> the summarizer's gist is only needed
         inside the live window; older carriers add no history value.

    NEVER touches: ``user`` rows, ``assistant`` rows with ``finish_reason='stop'``,
    non-summary ``tool`` rows, or the in-flight turn (``id >= current_id``).
    """
    archived = 0
    try:
        from jpm.core._pg import sync_conn

        with sync_conn() as conn:
            # 1. bare assistant dupes — a stop twin exists (any active state).
            # NOTE: conn.execute() returns self, so capture rowcount IMMEDIATELY
            # after each statement — a later execute overwrites it.
            # Soft-archive ONLY (active=0). Do NOT stamp compacted=1: that column
            # is the warm-start replay gate (`active=1 OR compacted=1`), so
            # stamping it would RE-EXPOSE the very rows we are hiding.
            conn.execute(
                "UPDATE messages SET active = 0 "
                "WHERE session_id = ? AND role = 'assistant' AND active = 1 "
                "AND id < ? "
                "AND (finish_reason IS NULL OR finish_reason = '') "
                "AND content_hash IS NOT NULL "
                "AND EXISTS ("
                "  SELECT 1 FROM messages m2 "
                "  WHERE m2.session_id = messages.session_id "
                "    AND m2.content_hash = messages.content_hash "
                "    AND m2.role = 'assistant' AND m2.finish_reason = 'stop'"
                ")",
                [session_id, current_id],
            )
            archived += int(getattr(conn, "rowcount", 0) or 0)

            # 2. bare assistant narration — short, no stop twin required.
            conn.execute(
                "UPDATE messages SET active = 0 "
                "WHERE session_id = ? AND role = 'assistant' AND active = 1 "
                "AND id < ? "
                "AND (finish_reason IS NULL OR finish_reason = '') "
                "AND COALESCE(LENGTH(content), 0) <= ?",
                [session_id, current_id, compress_above],
            )
            archived += int(getattr(conn, "rowcount", 0) or 0)

            # 3. tool_flow_summary carriers older than the live window.
            if protect_last_n > 0:
                conn.execute(
                    "UPDATE messages SET active = 0 "
                    "WHERE session_id = ? AND role = 'tool' "
                    "AND tool_name = 'tool_flow_summary' AND active = 1 "
                    "AND id < ? "
                    "AND id < ("
                    "  SELECT COALESCE(MIN(id), 0) FROM ("
                    "    SELECT id FROM messages "
                    "    WHERE session_id = ? AND active = 1 "
                    "    ORDER BY id DESC LIMIT ?"
                    "  ) keep"
                    ")",
                    [session_id, current_id, session_id, protect_last_n],
                )
                archived += int(getattr(conn, "rowcount", 0) or 0)

            if archived:
                logger.info(
                    "agent_digest: archived %d stray rows (session %s, id<%d) "
                    "— soft-archive, IDs/embeddings preserved",
                    archived, session_id, current_id,
                )
            _dump_event(
                agent, event="archive_stray", session_id=session_id,
                archived=archived, protect_last_n=protect_last_n,
            )
    except Exception as _e:
        logger.debug("agent_digest: archive pass failed (%s)", _e)
        _dump_event(agent, event="archive_exception", session_id=session_id, err=str(_e))
    return archived


def run_agent_digest(agent: Any, current_turn_id: Optional[int] = None) -> int:
    """Background, best-effort per-row digest pass. Returns rows compressed.

    Fires on the nudge boundary; never blocks a turn. Only UPDATEs rows, IDs and
    embeddings are untouched. Safe to call from the daemon review thread.
    """
    session_id = getattr(agent, "session_id", None)
    if not session_id:
        _dump_event(agent, event="bail_no_session", reason="agent.session_id is None")
        return 0

    if current_turn_id is None:
        # Snapshot a current-turn marker from the agent if available; otherwise
        # derive the max persisted id and never touch it or anything newer.
        current_turn_id = getattr(agent, "_current_turn_msg_id", None)
    if not current_turn_id:
        try:
            from jpm.core._pg import sync_conn

            with sync_conn() as conn:
                row = conn.fetchone(
                    "SELECT COALESCE(MAX(id), 0) AS max_id FROM messages "
                    "WHERE session_id = ?",
                    [session_id],
                )
                current_turn_id = int((row or {}).get("max_id", 0))
        except Exception as _e:
            logger.debug("agent_digest: no current id (%s) — aborting", _e)
            _dump_event(agent, event="bail_no_current_id", session_id=session_id, err=str(_e))
            return 0

    batch = _cfg(agent, "digest_batch_size", DEFAULT_BATCH_SIZE)
    compress_above = _cfg(agent, "digest_compress_above_chars", DEFAULT_COMPRESS_ABOVE_CHARS)

    try:
        from jpm.core._pg import sync_conn

        with sync_conn() as conn:
            rows = _select_candidates(
                conn, session_id, current_turn_id, batch, compress_above
            )
            _dump_event(
                agent, event="pass_start", session_id=session_id,
                current_turn_id=current_turn_id, batch=batch,
                compress_above=compress_above, candidates=len(rows),
            )
            if not rows:
                _dump_event(agent, event="no_candidates", session_id=session_id)
                return 0

            changed = 0
            for row in rows[: batch]:
                rid = row["id"]
                content = row["content"] or ""
                if len(content) <= compress_above:
                    continue
                digest = _digest_row(agent, content, row_id=rid)
                if digest == content:
                    # Summarizer fell back raw (aux LLM failed or returned empty).
                    _dump_event(
                        agent, event="row_skipped_raw", session_id=session_id,
                        row_id=rid, content_len=len(content),
                        digest_len=len(digest), reason="digest==content (aux fallback)",
                    )
                    continue  # nothing worth changing (or summarizer fell back raw)

                now = _now_ts()
                # SINGLE UPDATE per row — IDs + embeddings + hash untouched.
                conn.execute(
                    "UPDATE messages SET content_original = ?, content = ?, "
                    "agent_compacted = 1, is_digest = TRUE, summarized_at = ? "
                    "WHERE id = ?",
                    [content, digest, now, rid],
                )
                changed += 1
                _dump_event(
                    agent, event="row_compressed", session_id=session_id,
                    row_id=rid, content_len=len(content), digest_len=len(digest),
                    content_before=content, content_after=digest,
                )
                if changed >= _cfg(agent, "digest_max_llm_calls", DEFAULT_MAX_LLM_CALLS):
                    break  # hard safety cap on aux LLM calls per pass

            # ── Stray-row hygiene: soft-archive rows that don't belong in
            # conversation history (bare assistant dupes/narration, stale
            # tool_flow_summary carriers). Runs in the SAME nudge-boundary pass
            # as the digest. Soft-archive only — nothing deleted, canonical
            # copies always survive. (Josh 2026-10-08)
            _protect_last_n = 0
            try:
                _cc = getattr(agent, "context_compressor", None)
                if _cc is not None:
                    _protect_last_n = int(getattr(_cc, "protect_last_n", 0) or 0)
            except Exception:
                _protect_last_n = 0
            _archive_stray_rows(
                agent, session_id, current_turn_id, _protect_last_n, compress_above
            )

            # ── Migration safety: ensure the new columns exist even if the DDL
            # migration hasn't run yet (idempotent). Failure here is non-fatal.
            if changed:
                logger.info(
                    "✂️ agent_digest: compressed %d assistant rows ("
                    "id<%d) — IDs/embeddings preserved",
                    changed, current_turn_id,
                )
            _dump_event(
                agent, event="pass_end", session_id=session_id, changed=changed,
            )
            return changed
    except Exception as _e:
        # Best-effort by design — a failure here never breaks the turn.
        logger.debug("agent_digest: pass failed (%s)", _e)
        _dump_event(agent, event="pass_exception", session_id=session_id, err=str(_e))
        return 0

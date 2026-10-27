"""Post-turn tool-flow summarization.

Collapses intermediate tool results and assistant reasoning between the last
two un-summarized stop boundaries into a single DETERMINISTIC summary (one-line
"ran X -> concluded Y" records, no LLM call), while preserving the user's
message and the assistant's final response intact. Updates the DB in-place.
The next turn's ``build_turn_context()`` naturally picks up the lean version -
no special injection, no new message types.

The per-turn collapse is deterministic observation masking (the research's #1
context lever): tool results are reduced to short records via ``_mask_tool_result``
with NO LLM call - cheap, lossless (full content stays in the DB, re-fetchable),
reversible, and free of the narration-abort stall risk that the old per-turn LLM
path carried. The rich fumbles/skills extraction the old LLM path produced is
deliberately NOT attempted here - that belongs at the nudge-period LLM vacuum,
not the per-turn hot path.

Boundary detection
------------------
Queries the last 2 un-summarized stop messages that are NOT coaching or
tool-flow summaries, then collapses everything between them.  The user
message and final assistant response are kept verbatim; only the tool
calls and intermediate reasoning in between are deleted.

Safety
------
- The DELETE uses an explicit, verified ID list - never a bare ``WHERE
  session_id = ...``.
- If there is only 1 un-summarized stop message (first turn), the summarizer
  skips.
- If there are no messages in the range, the summarizer skips.
- Kept messages are stamped ``flow_summarized_at`` after collapse, making the
  summarizer idempotent - already-processed turns are never re-visited. This
  marker is deliberately SEPARATE from ``compacted`` (owned by
  archive_and_compact / the context compressor): sharing that column let the
  compressor's blind UPDATE starve this summarizer.
- Wrapped in try/except - best-effort, never blocks the turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import sys 

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("🧰 tool_flow")

def _mask_tool_result(tool_name: str, tool_args: str, tool_content: str) -> str:
    """Create an informative 1-line summary of a tool call + result.

    Self-contained copy of the context compressor's ``_summarize_tool_result``
    (kept local to avoid dragging the whole ``auxiliary_client`` import chain
    into this per-turn hot path). Produces the deterministic "ran X -> concluded
    Y" records that replace verbose tool output without any LLM call.

    Returns strings like::

        [terminal] ran `npm test` -> exit 0, 47 lines output
        [read_file] read config.py from line 1 (1,200 chars)
        [search_files] content search for 'compress' in agent/ -> 12 matches
    """
    try:
        args = json.loads(tool_args) if tool_args else {}
    except (json.JSONDecodeError, TypeError):
        args = {}

    content = tool_content or ""
    content_len = len(content)
    line_count = content.count("\n") + 1 if content.strip() else 0

    if tool_name == "terminal":
        cmd = args.get("command", "")
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        exit_match = re.search(r'"exit_code"\s*:\s*(-?\d+)', content)
        exit_code = exit_match.group(1) if exit_match else "?"
        return f"[terminal] ran `{cmd}` -> exit {exit_code}, {line_count} lines output"

    if tool_name == "read_file":
        path = args.get("path", "?")
        offset = args.get("offset", 1)
        return f"[read_file] read {path} from line {offset} ({content_len:,} chars)"

    if tool_name == "write_file":
        path = args.get("path", "?")
        written_lines = args.get("content", "").count("\n") + 1 if args.get("content") else "?"
        return f"[write_file] wrote to {path} ({written_lines} lines)"

    if tool_name == "search_files":
        pattern = args.get("pattern", "?")
        path = args.get("path", ".")
        target = args.get("target", "content")
        match_count = re.search(r'"total_count"\s*:\s*(\d+)', content)
        count = match_count.group(1) if match_count else "?"
        return f"[search_files] {target} search for '{pattern}' in {path} -> {count} matches"

    if tool_name == "patch":
        path = args.get("path", "?")
        mode = args.get("mode", "replace")
        return f"[patch] {mode} in {path} ({content_len:,} chars result)"

    if tool_name in {"browser_navigate", "browser_click", "browser_snapshot",
                     "browser_type", "browser_scroll", "browser_vision"}:
        url = args.get("url", "")
        ref = args.get("ref", "")
        detail = f" {url}" if url else (f" ref={ref}" if ref else "")
        return f"[{tool_name}]{detail} ({content_len:,} chars)"

    if tool_name == "web_search":
        query = args.get("query", "?")
        return f"[web_search] query='{query}' ({content_len:,} chars result)"

    if tool_name == "web_extract":
        urls = args.get("urls", [])
        url_desc = urls[0] if isinstance(urls, list) and urls else "?"
        if isinstance(urls, list) and len(urls) > 1:
            url_desc += f" (+{len(urls) - 1} more)"
        return f"[web_extract] {url_desc} ({content_len:,} chars)"

    if tool_name == "delegate_task":
        goal = args.get("goal", "")
        if len(goal) > 60:
            goal = goal[:57] + "..."
        return f"[delegate_task] '{goal}' ({content_len:,} chars result)"

    if tool_name == "execute_code":
        code_preview = (args.get("code") or "")[:60].replace("\n", " ")
        if len(args.get("code", "")) > 60:
            code_preview += "..."
        return f"[execute_code] `{code_preview}` ({line_count} lines output)"

    if tool_name in {"skill_view", "skills_list", "skill_manage"}:
        name = args.get("name", "?")
        return f"[{tool_name}] name={name} ({content_len:,} chars)"

    if tool_name == "vision_analyze":
        question = args.get("question", "")[:50]
        return f"[vision_analyze] '{question}' ({content_len:,} chars)"

    if tool_name == "jpm":
        action = args.get("action", "?")
        table = args.get("table", "")
        section = args.get("section", "")
        detail = f" table={table}" if table else (f" section={section}" if section else "")
        return f"[jpm] {action}{detail} ({content_len:,} chars)"

    if tool_name == "memory":
        target = args.get("target", "?")
        return f"[memory] target={target} ({content_len:,} chars)"

    if tool_name == "todo":
        return f"[todo] ({content_len:,} chars)"

    if tool_name == "clarify":
        question = args.get("question", "")[:50]
        return f"[clarify] '{question}'"

    # Generic fallback: name + content length
    return f"[{tool_name}] ({content_len:,} chars)"

# ── Synthetic context-note tool_names exempt from collapse ────────────────
# Rows that ride as role='tool' with a synthetic tool_name + tool_call_id
# (no real assistant tool_call matches them). They are legitimate context
# notes - coach self-improvement lines, tool-flow summaries themselves, JPM
# breadcrumb enrichment (jpm_context), and the skill-manager directive
# (skill_directive). If any landed inside a collapse window they'd be
# deleted as "tool noise". Guard BOTH the range query and the DELETE with
# this set (defense in depth - the DELETE's bare role filter is the trap).
#
# skill_view / skill_choose are NOT exempt (removed 2026-10-08). A loaded
# skill body is a real tool result, but it is the single largest row in a
# turn (measured 76KB = 36% of a 211KB dump) and it re-sends on EVERY
# api_call. Josh's directive: "tool summary beyond protect_last_n isn't
# required to persist on long runs." Collapsing it to a 1-line gist at turn
# end keeps the turn's signal (which skill loaded) without carrying the full
# body across turns. The model can re-load via skill_view if it needs the
# body again — the gist tells it what was loaded.
_SUMMARY_EXEMPT_TOOL_NAMES = ("coach", "tool_flow_summary", "jpm_context", "skill_directive")
# NOTE: this MUST be a NOT IN exclusion, not a `!= ... OR != ...` chain. The
# naive `tool_name IS NULL OR tool_name != 'x' OR tool_name != 'y'` form is
# TRUE for EVERY row (any row's tool_name is != most names), so it never
# actually excludes anything - the exempt rows would be swept by the DELETE
# anyway. NOT IN is TRUE only for rows whose tool_name is NULL or not in the
# set, which is the real "not exempt" predicate.
_SUMMARY_EXEMPT_SQL = "(tool_name IS NULL OR tool_name NOT IN (" + ",".join(
    f"'{n}'" for n in _SUMMARY_EXEMPT_TOOL_NAMES
) + "))"

# ── Public API ──────────────────────────────────────────────────────────────

def summarize_tool_flow(agent, messages: List[Dict[str, Any]], turn_freeze_ts: Optional[datetime] = None):
    """Collapse intermediate tool calls and reasoning into a summary.

    Collapses tool results and assistant reasoning between the last two
    uncompacted stop boundaries into a single LLM-generated summary, while
    preserving the user's message and the assistant's final response intact
    so the next turn has conversational context.

    ``turn_freeze_ts`` is a wall-clock timestamp frozen at the START of this
    summarization pass (after this turn's messages are written, before any
    later turn appends). Both the boundary and range queries gate on
    ``timestamp < turn_freeze_ts`` so a delayed pass can never sweep in a
    NEW turn's messages - the late-run race where ORDER BY id DESC LIMIT 2
    re-grabs the next turn's stop and collapses its content. When omitted,
    no timestamp gate is applied (callers that are guaranteed to run inline
    at the turn boundary).

    Args:
        agent: The AIAgent instance (must have ``session_id`` and a live
               ``_session_db``).
        messages: The in-memory message list for this turn (mutated in-place).
        turn_freeze_ts: Optional timestamp boundary; only messages with
                        ``timestamp`` BEFORE this are considered.

    Returns:
        Tuple ``(collapsed_count, gap_ids)``. ``collapsed_count`` is the
        number of messages collapsed (0 if nothing was done). ``gap_ids`` is
        the sorted list of PG ``id`` slots freed by the collapse - the deleted
        middle-row ids strictly between the carrier row (the surviving tool
        result whose content now holds the summary) and the final response.
        Downstream writers (self_improvement's coach / prose inserts) may claim
        these ids to place their rows INSIDE the turn gap instead of appending
        at the tail, which keeps transcript order chronological and avoids the
        out-of-order rows that trip the repair/alteration passes.
    """
    session_id = getattr(agent, "session_id", None)
    if not session_id:
        logger.info("tool_flow_summarizer: no-op (agent has no session_id)")
        return (0, [])

    session_db = getattr(agent, "_session_db", None)
    if not session_db:
        logger.info("tool_flow_summarizer: no-op (agent has no _session_db)")
        return (0, [])

    # ── Step 1: Find turn boundaries ────────────────────────────────────
    # Find the last un-summarized stop, then the stop immediately before it
    # (regardless of its own marker).  This guarantees we only collapse
    # one turn at a time - on a warm start there could be many un-summarized
    # stops, and the range between the 2nd-to-last and the last would span
    # multiple turns.
    try:
        from jpm.core._pg import sync_conn

        with sync_conn() as conn:
            # First: get the last un-summarized stop (the current turn's final
            # response). Timestamp gate: if turn_freeze_ts was passed, only
            # consider stops written BEFORE this turn's finalization began - so
            # a delayed pass can't re-grab a NEW turn's stop (ORDER BY id DESC
            # at execution time would otherwise sweep in the next turn once its
            # messages got flushed).
            #
            # NOTE: only role='assistant' rows ever carry finish_reason='stop'
            # (verified: 2267 assistant stops, zero non-assistant). The
            # synthetic summary/coach rows are role='tool' and never have
            # finish_reason='stop', so no content filter is needed to exclude
            # them - and content filters are HARMFUL here because a legitimate
            # assistant response that merely MENTIONS "Tool Flow Summary" or
            # "coaching" in its body would be wrongly excluded as a boundary,
            # ballooning the collapse range across multiple turns.
            #
            # The gate is `flow_summarized_at IS NULL` - NOT `compacted`, and
            # NOT `active`. `compacted` belongs to archive_and_compact (the
            # context compressor); gating on it here meant that once the
            # compressor fired, this query matched nothing and the summarizer
            # silently collapsed 0 rows (the missing 🧰 icon). The `active = 1`
            # clause was the SAME starvation via a different column: the
            # compressor soft-archives pre-compaction turns (active=0) DURING
            # the turn, before this summarizer runs at turn END, so the
            # boundary/range queries matched nothing and 788 rows sat archived
            # un-summarized (2026-10-08). Archived rows are exactly the ones
            # that need a gist - drop the gate.
            _curr_sql = (
                "SELECT id FROM messages "
                "WHERE session_id = ? AND finish_reason = 'stop' AND role = 'assistant' "
                "AND flow_summarized_at IS NULL "
            )
            _curr_params: list = [session_id]
            if turn_freeze_ts is not None:
                _curr_sql += "AND timestamp < ? "
                _curr_params.append(turn_freeze_ts)
            _curr_sql += "ORDER BY id DESC LIMIT 1"
            _curr_row = conn.fetchone(_curr_sql, _curr_params)
            if not _curr_row:
                logger.info(
                    "tool_flow_summarizer: no-op (no un-summarized assistant stop "
                    "boundary for session %s)", session_id,
                )
                return (0, [])
            curr_stop_id = _curr_row["id"]   # recent row

            # Second: get the stop immediately BEFORE the current one,
            # REGARDLESS of its marker. This is the documented intent
            # (see comment above) - the previous turn's final response may
            # already be summarized/archived from an earlier pass, and skipping
            # it would balloon the collapse range across multiple turns (the
            # 79-message wipe). Only the CURRENT stop must be un-summarized.
            _prev_sql = (
                "SELECT id FROM messages "
                "WHERE session_id = ? AND finish_reason = 'stop' AND role = 'assistant' "
                "AND id < ? "
            )
            _prev_params: list = [session_id, curr_stop_id]
            if turn_freeze_ts is not None:
                _prev_sql += "AND timestamp < ? "
                _prev_params.append(turn_freeze_ts)
            _prev_sql += "ORDER BY id DESC LIMIT 1"
            _prev_row = conn.fetchone(_prev_sql, _prev_params)
            if not _prev_row:
                logger.info(
                    "tool_flow_summarizer: no-op (no previous stop boundary before "
                    "id=%s - first turn)", curr_stop_id,
                )
                return (0, [])
            prev_stop_id = _prev_row["id"]   # previous row
 
    except Exception as exc:
        logger.debug("tool_flow_summarizer: boundary query failed: %s", exc)
        return (0, [])

    # ── Step 2: Collect ALL messages in range ──────────────────────────
    try:
        with sync_conn() as conn:
            # Timestamp gate (same turn-boundary freeze): never collapse a NEW
            # turn's tool calls that landed after this turn's finalization began.
            # Scope: ONLY assistant tool-call narrations (finish_reason =
            # 'tool_calls') and tool RESULT rows. This protects user rows AND
            # the final assistant response (finish_reason='stop') by
            # construction - neither can ever enter the collapse set. The
            # `active = 1` gate is dropped for the same reason as the boundary
            # query above: the compressor archives rows before this runs, and
            # archived-but-unsummarized rows are the ones that need collapsing.
            _range_sql = (
                "SELECT id, session_id, role, content, tool_name, tool_call_id, message_id, finish_reason, token_count, tool_calls "
                "FROM messages "
                "WHERE id > ? AND id < ? AND flow_summarized_at IS NULL "
                "AND (role = 'tool' OR (role = 'assistant' AND finish_reason = 'tool_calls')) "
                "AND content NOT LIKE '%[coach]%' "
                "AND content NOT LIKE '%**CONTEXT:**%' "
                f"AND {_SUMMARY_EXEMPT_SQL} "
            )
            _range_params: list = [prev_stop_id, curr_stop_id]
            if turn_freeze_ts is not None:
                _range_sql += "AND timestamp < ? "
                _range_params.append(turn_freeze_ts)
            _range_sql += "ORDER BY id ASC"
            range_rows = conn.fetchall(_range_sql, _range_params)
    except Exception as exc:
        logger.debug("tool_flow_summarizer: range query failed: %s", exc)
        return (0, [])

    if not range_rows:
        logger.info(
            "tool_flow_summarizer: no-op (no collapsible tool/tool_calls rows "
            "between stop %d and stop %d)", prev_stop_id, curr_stop_id,
        )
        return (0, [])

    # ── Fetch the triggering user message + any mid-turn steers ────────
    # The range query above excludes role='user' (line 194), so the user's
    # actual ask is never in range_rows - the summarizer would otherwise have
    # to GUESS the goal from tool calls alone.  Fetch ALL user messages in the
    # collapse range (the triggering ask + any mid-turn steers that landed
    # between msg_ids) and prepend them to the prompt as grounding context.
    # They are NOT added to the range/delete set, so they can never be
    # collapsed or deleted - they stay as live conversational anchors.
    #
    # Mid-turn steers matter: a user can interject ("no, use X instead",
    # "that's wrong, do Y") between tool calls.  The summarizer MUST see them
    # to judge intent correctly - e.g. whether a skill was loaded because the
    # USER asked for it, or whether a "false_tail" was actually a steer the
    # agent was responding to.  Without them the summarizer misattributes
    # intent (the exact bug Josh caught: it claimed "user never asked" when
    # the user HAD steered mid-turn).
    user_prompt = ""
    user_steers = []
    try:
        with sync_conn() as conn:
            _user_sql = (
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'user' AND id > ? AND id < ? "
            )
            _user_params: list = [session_id, prev_stop_id, curr_stop_id]
            if turn_freeze_ts is not None:
                _user_sql += "AND timestamp < ? "
                _user_params.append(turn_freeze_ts)
            _user_sql += "ORDER BY id ASC"
            _steer_rows = conn.fetchall(_user_sql, _user_params)
            for _sr in _steer_rows:
                if _sr["content"]:
                    user_steers.append(_sr["content"])
            # The triggering user message is the LAST user message before the
            # current stop (may be the same as the last steer if the turn was
            # a single ask).  Fetch it separately as the primary grounding.
            _trigger_sql = (
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'user' AND id < ? "
            )
            _trigger_params: list = [session_id, curr_stop_id]
            if turn_freeze_ts is not None:
                _trigger_sql += "AND timestamp < ? "
                _trigger_params.append(turn_freeze_ts)
            _trigger_sql += "ORDER BY id DESC LIMIT 1"
            _trigger_row = conn.fetchone(_trigger_sql, _trigger_params)
            if _trigger_row and _trigger_row["content"]:
                user_prompt = _trigger_row["content"]
    except Exception as exc:
        logger.debug("tool_flow_summarizer: user-message fetch failed: %s", exc)

    all_ids = [r["id"] for r in range_rows]
    all_msg_ids = [r["message_id"] for r in range_rows]

    # ── Identify the rows to keep vs collapse ───────────────────────────
    # The range is `id > prev_stop AND id < curr_stop` - EXCLUSIVE of
    # curr_stop. So the current turn's final response (curr_stop, the
    # assistant row with finish_reason='stop') is NEVER in range_rows; it is
    # the upper boundary and is always kept (never deleted). Likewise the
    # triggering user message is excluded by the range query's
    # `role NOT IN ('user','system')` filter, so it is never in range_rows
    # and always kept. Both are preserved as live conversational anchors.
    #
    # Therefore the ONLY row in range_rows that must be kept is the FIRST
    # assistant response (the agent's opening intent anchor). Everything else
    # in range is middle noise (tool calls, intermediate reasoning) to
    # collapse. The old code tried to find the final response IN range_rows
    # and, failing (it's the excluded curr_stop boundary), fell back to
    # `len(range_rows) - 1` - which is the LAST TOOL RESULT before the final
    # response. That stray tool row got KEPT instead of collapsed, leaking a
    # tool result into the transcript on every turn.
    first_assistant_idx = None
    for i, r in enumerate(range_rows):
        if r["role"] == "assistant" and first_assistant_idx is None:
            first_assistant_idx = i
    if first_assistant_idx is None:
        first_assistant_idx = 0

    # IDs to keep: the first assistant response anchor. The user message and
    # final response are outside the range and always kept by construction.
    keep_ids = {all_ids[first_assistant_idx]}
    keep_msg_ids = {all_msg_ids[first_assistant_idx]}
    # IDs to delete: everything else in range (tool calls, intermediate
    # reasoning, and the stray trailing tool result that the old fallback
    # wrongly preserved).
    delete_ids = [all_ids[i] for i in range(len(all_ids)) if all_ids[i] not in keep_ids]
    delete_msg_ids = [all_msg_ids[i] for i in range(len(all_msg_ids)) if all_msg_ids[i] not in keep_msg_ids]

    logger.info(
        "found %d messages (ids %d..%d) between "
        "stop %d and stop %d - keeping first assistant id=%d, "
        "collapsing %d middle messages (final response id=%d kept as boundary)",
        len(all_ids), all_ids[0], all_ids[-1],
        prev_stop_id, curr_stop_id,
        all_ids[first_assistant_idx],
        len(delete_ids),
        curr_stop_id,
    )

    if not delete_ids:
        # Nothing to collapse - only user message and final response exist
        logger.info(
            "tool_flow_summarizer: no-op (range has only the kept anchor - "
            "nothing to collapse between stop %d and stop %d)",
            prev_stop_id, curr_stop_id,
        )
        return (0, [])

    # ── Token accounting for the collapsed rows ─────────────────────────
    # Additive loop: sum token_count across every message being collapsed.
    # Tool RESULT rows carry 0/NULL (they're not LLM calls), but the
    # assistant messages that emitted the tool_calls carry their completion
    # tokens via _last_output_tokens (chat_completion_helpers.py:928), so
    # this total reflects the real LLM cost of the tool round-trips being
    # summarized. Stamped onto the summary row so the cost isn't lost when
    # the individual rows are deleted.
    collapsed_token_count = 0
    tc_by_id = {r["id"]: r.get("token_count") for r in range_rows}
    for rid in delete_ids:
        tc = tc_by_id.get(rid)
        if tc:
            collapsed_token_count += int(tc)

    # ── Step 3+4: Build deterministic summary (NO LLM call) ─────────────
    # The per-turn collapse is now deterministic observation masking - tool
    # results are reduced to one-line "ran X -> concluded Y" records using the
    # proven _mask_tool_result pattern. No LLM, no latency, no stall risk, and
    # lossless (the full tool content stays in the DB, re-fetchable). The rich
    # fumbles/skills extraction that the old LLM path produced is deliberately
    # NOT attempted here - that belongs at the nudge-period LLM vacuum, not the
    # per-turn hot path.
    middle_rows = [r for i, r in enumerate(range_rows) if all_ids[i] in delete_ids]
    summary = _build_deterministic_summary(middle_rows, user_prompt, user_steers, all_rows=range_rows)
    if not summary:
        logger.info("tool_flow_summarizer: deterministic summary empty - skipping collapse")
        return (0, [])

    # ── Step 5: Collapse in DB ──────────────────────────────────────────
    try:
        with sync_conn() as conn:
            conn.execute("BEGIN")
            try:
                # ── Collapse IN PLACE (spec: keep the OG row, replace ONLY
                # its content).  We do NOT delete+insert a new summary row.
                #
                # CARRIER selection: the summary must ride on a row that keeps
                # the transcript's alternation legal (user -> assistant(anchor)
                # -> tool -> assistant(final)) AND that a strict provider will
                # accept.  Both constraints point at the SAME row: the first
                # real tool-result row whose ``tool_call_id`` matches a
                # tool_call emitted by the kept FIRST assistant anchor.  Reusing
                # it means:
                #   * role stays 'tool'  -> compresses normally (no bloat);
                #   * tool_call_id stays REAL and matches a surviving assistant
                #     call -> strict providers accept it (no synthetic id, so
                #     sanitize_api_messages never rewrites it to 'user');
                #   * it already sits in the gap between the two assistant rows
                #     -> valid alternation, turn tail stays on the final
                #     response (no fake "interrupted turn" note).
                #
                # If no such carrier exists (a turn with no tool calls, or an
                # anchor whose results fell outside the window) we SKIP the
                # collapse - safest, and such turns carry negligible noise.
                anchor_id = all_ids[first_assistant_idx]
                anchor_row = next((r for r in range_rows if r["id"] == anchor_id), None)
                anchor_calls: set = set()
                if anchor_row:
                    try:
                        _calls = json.loads(anchor_row.get("tool_calls") or "[]")
                    except (json.JSONDecodeError, TypeError):
                        _calls = []
                    for c in _calls:
                        if isinstance(c, dict):
                            _cid = c.get("id") or c.get("call_id")
                            if _cid:
                                anchor_calls.add(_cid)
                carrier_id = None
                for rid in delete_ids:
                    r = next((x for x in range_rows if x["id"] == rid), None)
                    if (
                        r
                        and r.get("role") == "tool"
                        and (r.get("tool_call_id") or "") in anchor_calls
                    ):
                        carrier_id = rid
                        break
                if carrier_id is None:
                    logger.info(
                        "tool_flow_summarizer: no legal in-place carrier "
                        "(no tool result matching the anchor's calls) - skipping collapse"
                    )
                    return (0, [])
                # Delete every OTHER middle row; the carrier survives untouched
                # except for its content (overwritten below).
                purge_ids = [rid for rid in delete_ids if rid != carrier_id]
                purge_msg_ids = [
                    r["message_id"] for r in range_rows
                    if r["id"] in set(purge_ids)
                ]
                if purge_ids:
                    placeholders = ", ".join("?" for _ in purge_ids)
                    conn.execute(
                        f"DELETE FROM messages WHERE role NOT IN ('user','system') AND id IN ({placeholders}) AND {_SUMMARY_EXEMPT_SQL}",
                        purge_ids,
                    )
                # Overwrite the carrier's content with the summary AND stamp
                # tool_name='tool_flow_summary'.  The row is no longer a
                # terminal/read_file result - its content is now a summary, so
                # the name must say so.  role, tool_call_id, message_id, msg_key
                # and timestamp are preserved - it is the SAME row, merely
                # masked.  Keeping the REAL tool_call_id (matching a surviving
                # assistant call) keeps it a legal tool result for strict
                # providers; the tool_flow_summary name makes the warm-replay
                # filter (role='tool' AND tool_name='tool_flow_summary') match
                # it again, and marks it exempt from future collapses.  No new
                # row is minted, so the agent's message_id counter needs no sync
                # and there is no ON CONFLICT idempotency hazard.
                _carrier_hash = hashlib.md5(summary.encode("utf-8")).hexdigest()
                conn.execute(
                    "UPDATE messages SET content = ?, content_hash = ?, "
                    "tool_name = ?, token_count = ?, flow_summarized_at = ? WHERE id = ?",
                    (summary, _carrier_hash, "tool_flow_summary",
                     collapsed_token_count or None,
                     datetime.now(), carrier_id),
                )
                carrier_msg_id = next(
                    (r["message_id"] for r in range_rows if r["id"] == carrier_id),
                    None,
                )
                # Mark the kept messages with the summarizer's OWN marker so we
                # never re-process them. This is deliberately NOT `compacted`:
                # that column is owned by archive_and_compact (the context
                # compressor) and means "archived out of live context". Sharing
                # it made the compressor's blind UPDATE starve this summarizer
                # (its boundary/range queries gated on `compacted NOT IN (1)`,
                # so once compression fired they matched nothing and it
                # silently collapsed 0 rows — the missing 🧰 icon).
                _flow_ts = datetime.now()
                for kid in keep_ids:
                    conn.execute(
                        "UPDATE messages SET flow_summarized_at = ? WHERE id = ?",
                        (_flow_ts, kid),
                    )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except Exception as exc:
        logger.warning(
            "tool_flow_summarizer: DB collapse failed: %s", exc, exc_info=True,
        )
        return (0, [])

    # ── Step 6: Update in-memory messages list ──────────────────────────
    # Mirror the DB: overwrite the CARRIER row's content in place (same row,
    # same role, same tool_call_id) and drop every other collapsed middle row.
    _carrier_tcid = next(
        (r.get("tool_call_id") or "" for r in range_rows if r["id"] == carrier_id),
        "",
    )
    _collapse_in_memory(
        messages, keep_msg_ids, purge_msg_ids, summary,
        carrier_msg_id, _carrier_tcid,
    )

    # ── Step 7: Log ─────────────────────────────────────────────────────
    roles = list(dict.fromkeys(r["role"] or "?" for r in middle_rows))
    # The carrier row keeps its original PK (in the gap, between the kept user
    # message and the final response). Every other freed middle-row id is a
    # slot strictly AFTER the carrier and BEFORE the final response -
    # downstream writers (self_impr coach/prose inserts) may claim these ids to
    # stay inside the turn gap rather than appending at the tail. ``sorted()``
    # keeps them in ascending id order so consumers pop from the front (oldest
    # slot first). If a downstream insert is added, we could also shrink this
    # list; it is returned read-only.
    gap_ids = sorted(purge_ids)

    logger.info(
        "%dx Tool & Assistant calls summarized in place (msg_ids %d..%d, roles: %s) - "
        "carrier id=%d kept, user msg and final response kept",
        len(delete_ids), all_ids[0], all_ids[-1], ", ".join(roles), carrier_id,
    )

    return (len(delete_ids), gap_ids)

# ── Internal helpers ────────────────────────────────────────────────────────

def _build_deterministic_summary(
    middle_rows: List[Dict[str, Any]],
    user_prompt: str = "",
    user_steers: Optional[List[str]] = None,
    all_rows: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build a compact one-line-per-tool summary WITHOUT any LLM call.

    This is the deterministic replacement for the per-turn LLM summarization
    (the research's #1 lever: observation masking). Tool results are masked to
    short "ran X -> concluded Y" records using the proven
    ``_summarize_tool_result`` pattern from context_compressor.py. It is:
      - deterministic (no LLM, no latency, no stall risk)
      - lossless (the full tool content is still in the DB, re-fetchable)
      - reversible (nothing is destroyed, only the transcript copy is compacted)

    The summary preserves the ORDER OF OPERATIONS (what was done, in what
    order) and the outcome of each tool, which is all the next turn needs to
    continue. It deliberately does NOT attempt fumbles/skills classification -
    that rich extraction belongs at the nudge-period LLM vacuum, not the
    per-turn path.

    Args:
        middle_rows: The rows being collapsed (tool results + assistant
            reasoning), each with ``id``, ``role``, ``content``, ``tool_name``,
            ``tool_call_id``, and ``tool_calls`` (assistant rows carry the
            tool_call_id -> (name, args) map).
        user_prompt: The triggering user message (grounding, not summarized).
        user_steers: Any mid-turn user interjections (grounding, not summarized).

    Returns:
        A compact multi-line summary string.
    """
    # Build tool_call_id -> (name, args) map from assistant rows' tool_calls JSON.
    # The tool RESULT rows carry tool_call_id matching the assistant's call id,
    # so we can attach real args (command/path/pattern) to each result.
    #
    # CRITICAL: build the map from ALL rows in the collapse window (all_rows),
    # NOT just middle_rows. The FIRST assistant row is kept as the turn's
    # "opening intent anchor" (never collapsed), so its tool_calls are absent
    # from middle_rows. When the agent fires parallel tool calls in that first
    # message, every tool result referencing those call ids would get an empty
    # args lookup -> _mask_tool_result falls back to '?' (e.g. "[jpm] ? (155
    # chars)", "[search_files] content search for '?' in ."). Including the
    # kept first-assistant row in the map fixes the args for those results.
    call_map: Dict[str, Dict[str, Any]] = {}
    for r in (all_rows if all_rows else middle_rows):
        tc_json = r.get("tool_calls")
        if not tc_json:
            continue
        try:
            calls = json.loads(tc_json) if isinstance(tc_json, str) else tc_json
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(calls, list):
            continue
        for c in calls:
            if not isinstance(c, dict):
                continue
            cid = c.get("id") or c.get("call_id")
            fn = c.get("function") or {}
            if cid:
                call_map[cid] = {
                    "name": fn.get("name", ""),
                    "arguments": fn.get("arguments", ""),
                }

    lines: List[str] = []
    for r in middle_rows:
        role = r.get("role") or "?"
        tool_name = r.get("tool_name") or ""
        content = r.get("content") or ""
        tcid = r.get("tool_call_id") or ""

        # Tool RESULT rows: mask to a one-line record using the proven pattern.
        if role == "tool" and tool_name:
            args = call_map.get(tcid, {})
            arg_str = args.get("arguments", "") if args else ""
            lines.append(_mask_tool_result(tool_name, arg_str, content))
            continue

        # Assistant rows that emitted tool_calls: record the calls (short).
        if role == "assistant" and tool_name:
            args = call_map.get(tcid, {})
            arg_str = args.get("arguments", "") if args else ""
            lines.append(_mask_tool_result(tool_name, arg_str, content))
            continue

        # Assistant reasoning rows (no tool): DROPPED (2026-10-10, Josh).
        # The [reasoning] gist was a debug aid; replayed back every turn it
        # was ~28% of summary bytes and pure bloat - the model does not need
        # its own prior thinking to continue, only tool results + user asks.
        if role == "assistant":
            continue

        # Fallback: any other row type.
        if content.strip():
            gist = content.strip()
            if len(gist) > 200:
                gist = gist[:200]
            lines.append(f"[{role}] {gist}")

    if not lines:
        return ""

    # NOTE (2026-08-30): the summary does NOT prepend a "User:" / "Steer N:"
    # header echoing the triggering message and mid-turn steers. Those rows
    # are role='user' and are ALREADY preserved intact after collapse - the
    # range query (role NOT IN user/system) and the DELETE (same guard) never
    # touch them, so they remain live in the transcript. Echoing them here
    # produced three defects Josh caught: (1) the real user message appeared
    # TWICE (live row + "User:" header), (2) stale warm-start recovery lines
    # got captured as "Steer N" and leaked into the per-turn summary, and
    # (3) the same ask was repeated as both User: and Steer N. The summary's
    # only job is to compress the COLLAPSED middle rows (tools + reasoning);
    # the user ask and steers are preserved as real context rows and never
    # belong in the summary body.
    return "\n".join(lines)

def _collapse_in_memory(
    messages: List[Dict[str, Any]],
    keep_msg_ids: set,
    delete_msg_ids: List[int],
    summary: str = "",
    carrier_msg_id: Optional[int] = None,
    carrier_tcid: str = "",
) -> None:
    """Mirror the DB in-place collapse in the in-memory ``messages`` list.

    In-memory messages have ``_msg_id`` (stamped by
    ``_flush_messages_to_session_db``), not ``id`` (PG serial PK).
    We match on ``_msg_id`` which corresponds to the session-scoped
    ``message_id`` column in PG.

    The collapse is IN PLACE: the CARRIER row (``carrier_msg_id``) is the
    first real tool-result row whose ``tool_call_id`` matches a surviving
    assistant call.  We overwrite ONLY its content with the summary - role,
    tool_name and tool_call_id are preserved, so the row stays a legal tool
    result that strict providers accept (no synthetic id, no role rewrite).
    Every OTHER collapsed middle row (``delete_msg_ids``) is dropped.  The
    user message and final assistant response are never touched.

    Mutates ``messages`` in-place so the result dict returned by
    ``finalize_turn()`` is consistent with what was written to PG.
    """
    delete_set = set(delete_msg_ids)
    new_messages = []
    for msg in messages:
        if not isinstance(msg, dict):
            new_messages.append(msg)
            continue
        msg_id = msg.get("_msg_id")
        if msg_id in delete_set:
            continue  # drop this collapsed middle row
        if summary and carrier_msg_id is not None and msg_id == carrier_msg_id:
            # Overwrite the carrier's content IN PLACE - same row, same role,
            # same tool_call_id, but renamed to tool_flow_summary (its content
            # is a summary now, not a tool result).  This is the in-memory
            # mirror of the DB UPDATE.
            msg = dict(msg)
            msg["content"] = summary
            msg["tool_name"] = "tool_flow_summary"
            msg["_flow_summarized"] = True
            new_messages.append(msg)
            continue
        new_messages.append(msg)
    messages[:] = new_messages

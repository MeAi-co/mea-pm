"""skill_manager (vendored) — OOB turn classifier for the MEAI skillmgr loop.

The fork's ``core/agent/skill_manager.py`` classifies the current user turn as
reply / task / project via an LLM call, then logs the verdict (observation
mode). It rides the fork's ``tools._smart_refine._call_refinement_llm`` seam,
which stock lacks — so this vendored copy calls stock's
``agent.auxiliary_client.call_llm`` instead.

DB-only (reads the catalog + recent messages, calls the LLM, returns the
verdict) -> detachable into its own subprocess. Imports ONLY stock modules +
the vendored engine.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_RECENT_MSGS = 20
_MSG_TRUNCATE = 300

_SYSTEM_PROMPT = """You are the Skill Manager for an AI agent. Your ONLY job is to classify the current user turn as a REPLY, a TASK, or a PROJECT.

## Your Input
1. **Skill catalog** - the list of skills the agent can load (name, category, description).
2. **Current user message** - what the user just said.
3. **Recent conversation** - the last few user/assistant messages (truncated, oldest first).

## Your Output
Respond with a single compact JSON object, one of two shapes:

- **REPLY turn** (the user is chatting with no actionable work - no skill needs loading):
  {"type": "reply", "response": "<a short natural reply to the user>"}

- **TASK turn** (the user wants the agent to DO something - build, fix, debug, write, research, automate, run a procedure - where a skill likely applies):
  {"type": "task", "response": "Load skills"}

- **PROJECT turn** (the user is asking to load, switch, check, or reload a PROJECT):
  {"type": "project", "response": "Load project"}

## Core Principle: Cost of a misclassification
Skill-loaded rounds are EXPENSIVE. Replies are CHEAP. A false TASK wastes a heavy skill load for nothing. When uncertain, bias toward REPLY.

## Core Rule: Ground on the concrete referent
The question is NOT the signal - the REFERENT is. TASK = the turn works on an EXTERNAL referent (system, file, table, log, bug, code) and requires a skill. REPLY = a bare acknowledgment with no referent, OR self-modification (memory/config/rules/preferences/vault/own skills).

## Rules
- Warm-start / resume greeting is a TASK - the agent must re-orient by loading context.
- Output ONLY the JSON object. No prose, no code fences, no chain-of-thought.
- Keep the response field short (under 30 words).
"""


def _fetch_recent_messages(session_key: str) -> list:
    if not session_key:
        return []
    try:
        from jpm.core._pg import sync_conn
        with sync_conn() as conn:
            if ":" in session_key and not session_key[0].isdigit():
                row = conn.execute(
                    "SELECT id FROM sessions WHERE session_key = $1 "
                    "ORDER BY started_at DESC LIMIT 1",
                    (session_key,),
                ).fetchone()
                if row:
                    session_key = row["id"] if hasattr(row, "keys") else row[0]
            rows = conn.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = $1 AND role IN ('user','assistant') "
                "AND content != '' AND active = 1 "
                "ORDER BY id DESC LIMIT $2",
                (session_key, _RECENT_MSGS),
            ).fetchall()
        out = []
        for r in rows:
            role = r["role"] if hasattr(r, "keys") else r[0]
            content = r["content"] if hasattr(r, "keys") else r[1]
            if content:
                out.append({"role": role, "content": str(content)[:_MSG_TRUNCATE]})
        return list(reversed(out))
    except Exception as exc:
        logger.warning("skill_manager: recent fetch failed: %s", exc)
        return []


def _fetch_skill_catalog() -> list:
    try:
        from _skill_choose_tool import _catalog_rows
        rows = _catalog_rows() or []
        return [
            {"name": r.get("name"), "category": r.get("category"),
             "description": (r.get("description") or "")[:200]}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("skill_manager: catalog fetch failed: %s", exc)
        return []


def classify_turn(message_text: str, session_key: Optional[str] = None,
                  turn_id: str = "", enabled: Optional[bool] = None) -> str:
    """Classify the current user turn as reply-vs-task via an LLM call.

    Returns the JSON verdict string (task/project) or "" for reply/disabled.
    Observation-only: the verdict is logged, not injected.
    """
    t0 = time.monotonic()
    try:
        if enabled is None:
            enabled = True
        if not enabled:
            return ""

        catalog = _fetch_skill_catalog()
        recent = _fetch_recent_messages(session_key or "")

        catalog_block = "\n".join(
            f"- {s['name']} [{s.get('category') or 'uncategorized'}]: {s.get('description') or ''}"
            for s in catalog
        ) or "(no skills in catalog)"
        context_block = "\n".join(
            f"{m['role']}: {m['content']}" for m in recent
        ) or "(no recent conversation)"

        user_prompt = (
            f"## Skill catalog\n{catalog_block}\n\n"
            f"## Recent conversation\n{context_block}\n\n"
            f"## Current user message\n{message_text or ''}\n\n"
            f"Classify this turn. Reply with the JSON verdict only."
        )

        from agent.auxiliary_client import call_llm
        resp = call_llm(
            task="compression",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=500,
        )
        raw = ""
        try:
            raw = resp.choices[0].message.content or ""
        except Exception:
            raw = str(resp) if not isinstance(resp, (dict, list)) else ""
        if not raw and isinstance(resp, dict):
            raw = resp.get("content") or resp.get("text") or ""

        elapsed = time.monotonic() - t0
        if not raw:
            logger.info("skill_manager: LLM returned nothing in %.3fs", elapsed)
            return ""

        verdict = None
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and parsed.get("type") in ("reply", "task", "project"):
                verdict = parsed
        except json.JSONDecodeError:
            pass
        if verdict is None:
            logger.info("skill_manager: unparseable verdict in %.3fs raw=%r", elapsed, raw[:120])
            return ""

        vtype = verdict.get("type")
        logger.info(
            "skill_manager: verdict=%s in %.3fs catalog=%d recent=%d",
            vtype, elapsed, len(catalog), len(recent),
        )
        if vtype == "reply":
            return ""
        return json.dumps(verdict)
    except Exception as exc:
        logger.warning("skill_manager: classify failed, no-op: %s", exc)
        return ""

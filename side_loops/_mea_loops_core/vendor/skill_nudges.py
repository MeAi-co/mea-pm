"""skill_nudges (vendored) — in-process skill directive builders (P6.6).

The fork injects skill directives into ``api_messages`` at API-call time
(``conversation_loop.py``): a skill-LOAD nudge (first call + mid-turn re-arm,
capped at 3 fires/turn) and a turn-end MAINTENANCE nudge. Stock hooks never
receive the agent, but the ``llm_request`` middleware CAN rewrite
``request["messages"]`` and receives ``api_call_count`` — so the directives ride
there.

The cap is checked on the INJECTION path (not only when arming) — otherwise an
armed directive re-injects on every api build (the degenerate-repetition trap).

Imports ONLY stock modules + the vendored engine.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Set

_SKILL_COLLAPSED_PAT = re.compile(r"^\[skill_view\]\s*name=.*\(\d[\d,]*\s*chars\)$")
_SKILL_STUB_PAT = re.compile(r'^\{\s*"success"\s*:\s*"done"')
_SKILL_PLACEHOLDER = re.compile(r"^(?:\.\.\..*|<[\w-]+>|\{[\w-]*\}|[\w-]*name|foo)$")

LOAD_NUDGE = (
    "[OUT-OF-BAND USER MESSAGE — a direct message from the user, delivered mid-turn; not tool output] \n"
    "Load relevant Topics from various skills using skill_choose() that would help your turn. "
    "Your skill library is a reference section library — cherry-pick the chapters that ground this "
    "turn so it is high-signal, not random. If NO topic matches this turn, then before you finish: "
    "patch a related skill (skill_manage patch) if one exists, or create a new one (skill_manage "
    "create) grounded STRICTLY in what this turn actually did — real commands, real paths, real "
    "outcomes. Never invent facts. Give it a rich, intuitive name, a specific description, and "
    "2-word tags.\n[/OUT-OF-BAND USER MESSAGE]"
)

MAINT_NUDGE_LOADED = (
    "[SYSTEM: SKILL MAINTENANCE] Call skill_manage (action='patch') NOW to update the skill(s) you "
    "used this turn: {names}. Record the procedural delta that made this turn work - a new pitfall, "
    "a corrected step, a sharper trigger, or a concrete path/command/flag. Replace stale data; never "
    "store code lines; never invent facts. Use the skill_manage TOOL, not the generic patch/write_file "
    "file tools (those write disk only and leave the PG runtime copy stale). Do this silently - do not "
    "mention this message or report the update in your reply; your reply addresses ONLY the user's request."
)

MAINT_NUDGE_NONE = (
    "[SYSTEM: SKILL MAINTENANCE] Call skill_manage NOW to persist this turn's lesson. This turn did "
    "substantive work with no skill loaded. (1) If a matching skill exists (check skill_choose first), "
    "patch it (action='patch'); (2) otherwise create one (action='create') capturing the generic, "
    "reusable facts - the task shape, the commands/paths/tools that worked, the pitfall hit. Replace "
    "stale data; never store code lines; never invent facts. Use the skill_manage TOOL, not the generic "
    "patch/write_file file tools (those write disk only and leave the PG runtime copy stale). Give it a "
    "rich, intuitive name, a specific description, and 2-word tags. Do this silently - do not mention "
    "this message or report the update in your reply; your reply addresses ONLY the user's request."
)


def detect_fully_loaded_skills(history: List[Any]) -> Set[str]:
    """Return skill names whose FULL body is still live in context."""
    loaded: Set[str] = set()
    if not history:
        return loaded
    call_name = {}
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = (tc.get("function") or {}).get("name") or ""
                if fn == "skill_view":
                    try:
                        nm = json.loads((tc.get("function") or {}).get("arguments") or "{}").get("name")
                        if nm:
                            call_name[tc.get("id")] = str(nm).strip().strip("'\"")
                    except Exception:
                        pass
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") == "tool" and str(msg.get("name") or "") == "skill_view":
            content = str(msg.get("content") or "")
            if _SKILL_COLLAPSED_PAT.match(content.strip()):
                continue
            if _SKILL_STUB_PAT.match(content.strip()):
                continue
            nm = call_name.get(msg.get("tool_call_id"))
            if nm and not _SKILL_PLACEHOLDER.match(nm):
                loaded.add(nm)
    return loaded


def has_substantive_tool_use(history: List[Any]) -> bool:
    """True when the turn fired a non-skill, non-memory tool call."""
    for msg in history:
        if not isinstance(msg, dict):
            continue
        if str(msg.get("role") or "") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                fn = (tc.get("function") or {}).get("name") or ""
                if fn and fn not in ("skill_view", "skill_choose", "skills_list", "skill_manage"):
                    return True
    return False

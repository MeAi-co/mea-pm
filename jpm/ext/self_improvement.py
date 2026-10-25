"""Self-improvement module — replaces background_review.py fork-a-daemon.

Architecture:
  - Per-turn: 2 structured LLM calls (User Understanding + Agent Growth)
  - Output: JSON → PG tables (knowledge, state, topics, growth_log, etc.)
  - No fork, no flat files, no regex guessing
  - Same model, warm cache prefix — minimal overhead

Flow:
  turn_finalizer.py:454
    → run_self_improvement()
    → Call 1: User Understanding → knowledge(user_pref), state, topics, small_talk
    → Call 2: Agent Growth → growth_log, patterns, signals, reflections
    → Mark user_says.heartbeat_processed = 1
    → Return write count for ♻️ counter
"""

import hashlib
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

from ..core._pg import sync_conn
from ..core._write import (
    _add_knowledge,
    _add_reflection,
    _write_pulse,
    _set_active,
    _add_loop,
    _resolve_loop,
)

LOG = logging.getLogger("♻️ ")

# Human-readable labels for the `calling LLM` log line — the loop_name is
# internal jargon; the log must say what the subsystem DOES, not its var name.
_LOOP_LABELS = {
    "self_impr_user": "user understanding",
    "self_impr_agent": "agent growth",
    "skill_updater": "skill updater",
}

# ── Circuit breaker + observability ─────────────────────────────────────
# Consecutive LLM/DB failures trip the breaker, which disables
# self-improvement for a cooldown so a broken upstream doesn't keep
# firing two LLM calls per turn. Counters give cheap observability.
_CIRCUIT_THRESHOLD = 5          # consecutive failures before tripping
_CIRCUIT_COOLDOWN = 300.0       # seconds to stay open after tripping
_consecutive_failures = 0
_circuit_open_until = 0.0
# ── State-sync cooldown ───────────────────────────────────────────────
# REMOVED (2026-09-10): the state-sync fields (pulse/active/loops/
# turn_quality/context_usage) now ride the SAME User Understanding
# response inband — no separate LLM call, so no cooldown is needed.
# The old OOB path (a second live completion racing the response) is gone.
# Master toggle for the OOB agent-growth ("oracle") LLM path. ENABLED
# (2026-08-26): restored alongside user understanding — agent growth fires on
# the same nudge-gated review_skills boundary (turn_context), runs on the
# daemon thread, and is bounded by the 120s watchdog + 600s LLM timeout, so it
# no longer races the live reply. Set False to disable (was moved inband to a
# self_impr tool that was never built; the OOB path is the working one).
_AGENT_GROWTH_ENABLED = True
_COUNTERS = {
    "calls": 0,
    "writes": 0,
    "parse_failures": 0,
    "empty_extractions": 0,
    "skipped_budget": 0,
    "circuit_open": 0,
    "llm_failures": 0,
    "db_failures": 0,
}


def _circuit_open() -> bool:
    """True if the circuit breaker is currently open (self-impr disabled)."""
    global _circuit_open_until
    if _circuit_open_until and time.time() < _circuit_open_until:
        return True
    if _circuit_open_until:
        # Cooldown elapsed — reset and allow traffic again.
        _circuit_open_until = 0.0
        global _consecutive_failures
        _consecutive_failures = 0
    return False


def _record_failure(kind: str) -> None:
    """Increment failure counters and trip the breaker if threshold hit."""
    global _consecutive_failures, _circuit_open_until
    _COUNTERS[kind] = _COUNTERS.get(kind, 0) + 1
    _consecutive_failures += 1
    if _consecutive_failures >= _CIRCUIT_THRESHOLD:
        _circuit_open_until = time.time() + _CIRCUIT_COOLDOWN
        _COUNTERS["circuit_open"] += 1
        LOG.warning("♻️ circuit breaker OPEN — self-improvement disabled for %.0fs "
                    "after %d consecutive failures", _CIRCUIT_COOLDOWN, _consecutive_failures)


def _record_success() -> None:
    """Reset the failure streak on a clean run."""
    global _consecutive_failures
    _consecutive_failures = 0

# ── Prompts ──────────────────────────────────────────────────────────────

_USER_UNDERSTANDING_PROMPT = """You are a data extraction agent building a DURABLE MODEL OF THE USER. Your job: review a WINDOW of the last several user turns and extract everything that will still be true and useful months from now — who this person is, what they care about, what they are building, and what they told you about themselves.

THE INTENT (read this first — it governs every decision below):
You are not tagging a conversation. You are writing the memory a close friend would carry. If the user states a fact about themselves — their education, family, location, job, health, relationships, possessions, plans, history, or identity — that fact belongs in `facts`, even if they mentioned it once, in passing, with no emphasis. A plain declarative statement about the user IS the signal. Do not wait for them to phrase it as a preference ("I like...") or a correction ("no, actually..."). "I studied accounting" is a fact. "My brother lives in Lisbon" is a fact. "I drive a Honda Civic" is a fact. These are the highest-value entries you will ever write, because they are what makes the agent KNOW the user instead of guessing.

This window spans MULTIPLE user turns (the nudge interval since the last extraction). Weigh each candidate by how strongly the user expressed it and how durable it is:
- A durable fact about the user (education, family, location, job, health, dates, relationships, possessions, plans) → SAVE to `facts` (weightage 0.75+). Durability beats emphasis: a fact stated once is still a fact.
- A correction stated once → high value (weightage 0.85)
- A preference stated once → medium (0.6); repeated across multiple turns in this window → raise toward 0.75
- A topic the user engaged with across turns → topic (0.50+); deeper/more sustained engagement → higher
- Operational/infra/project state the user described (even in passing) → durable breadcrumb, SAVE it — it's exactly the kind that needs to survive into the next session.

FILTER RULES (apply before writing anything):
1. Is this already known? If the user has said this preference before, SKIP it (don't duplicate).
2. Is this a real correction? Only if the user explicitly said "no", "stop", "that's wrong", "actually...". Normal questions are NOT corrections.
3. Is this a stated preference? Only if the user said "I like", "I prefer", "always do", "don't do that". Casual comments are NOT preferences.
4. Is this a real topic? Only if the user initiated it and engaged deeply. Passing mentions are NOT topics — UNLESS they describe ongoing operational/infrastructure state (what an agent or system is building, project status, fleet architecture, deployment, who-is-doing-what). Operational context is durable and SHOULD be saved even on passing mention.
5. Is this a durable fact about the user? If it is a statement about who they are, what they have, where they live, what they do, or what happened to them — SAVE it to `facts`. This rule OVERRIDES the "when in doubt, save nothing" default: a stated fact about the user is never noise.
6. Across the whole window, prefer the STRONGEST expression of any repeated signal — don't save the same fact twice.

WHEN IN DOUBT about a preference, correction, or topic, SAVE NOTHING. But a plain fact about the user is the exception — when in doubt about a fact, SAVE IT.

Return ONLY valid JSON:
{
  "session_summary": "2-4 sentence self-contained recap of this window",
  "user": {
    "facts": [
      {
        "entity_type": "user_fact",
        "name": "snake_case_name",
        "description": "One sentence: a durable fact about the user (education, family, location, job, health, dates, relationships, possessions, plans, history).",
        "weightage": 0.75,
        "fingerprint": "comma,separated,searchable,keywords"
      }
    ],
    "corrections": [
      {
        "entity_type": "corrections",
        "name": "snake_case_name",
        "description": "One sentence: what was corrected and why",
        "weightage": 0.85,
        "fingerprint": "comma,separated,searchable,keywords"
      }
    ],
    "preferences": [
      {
        "entity_type": "general",
        "name": "snake_case_name",
        "description": "One sentence describing the preference",
        "weightage": 0.6,
        "fingerprint": "comma,separated,keywords"
      }
    ],
    "state": {
      "valence": -0.6,
      "arousal": 0.7,
      "headspace": "One short sentence"
    },
    "topics": [
      {
        "name": "snake_case_name",
        "why_it_matters": "One sentence: why this topic matters / what the user is building or tracking",
        "trigger_keywords": "comma,separated,keywords"
      }
    ],
    "pulse": {
      "status": "nominal|degraded|idle|error",
      "summary": "One short sentence describing current overall state"
    },
    "active": {
      "focus": "single most important current focus, or empty string",
      "project": "project/subsystem of the focus, or empty string",
      "status": "in_progress|done|blocked|pending|idle"
    },
    "loops": [
      {
        "content": "one short sentence describing the open item",
        "project": "project or empty string",
        "priority": "high|medium|low",
        "resolved": false
      }
    ],
    "turn_quality": {
      "assessment": "one short sentence on how the turn went",
      "breadcrumbs": [
        {
          "name": "snake_case_name",
          "description": "one sentence durable fact",
          "entity_type": "user_pref|custom_rule|memory_entry"
        }
      ],
      "reflection": {
        "insight": "one actionable lesson",
        "impact": 7
      }
    },
    "context_usage": [
      {
        "id": 123,
        "verdict": "used|stale"
      }
    ]
  }
}

GOOD examples:
- fact: {"name": "user_studied_accounting", "description": "User studied accounting.", "weightage": 0.8, "fingerprint": "accounting,education,studied"}
- fact: {"name": "user_brother_lisbon", "description": "User has a brother who lives in Lisbon.", "weightage": 0.8, "fingerprint": "brother,family,lisbon,location"}
- correction: {"name": "no_chinese_in_replies", "description": "User corrected me for writing Chinese text. Stick to English only.", "weightage": 0.95, "fingerprint": "chinese,language,english"}
- preference: {"name": "short_messages", "description": "User prefers short one-line messages, not paragraphs.", "weightage": 0.6, "fingerprint": "short,concise,one_line"}
- state: {"valence": 0.7, "arousal": 0.4, "headspace": "Playful and relaxed, enjoying banter"}
- topic: {"name": "fleet_self_improvement_audit", "why_it_matters": "User is auditing the self_impr loop across the fleet — wants to know what each path does and rewire the ones that stall.", "trigger_keywords": "self_impr,self_improvement,user_understanding,oracle,state_sync"}

BAD examples (DO NOT DO):
- "user asked a question" → that's conversation, not a correction
- "user seems happy" → observation, not a preference
- "user mentioned cookies" → throwaway, not a topic
- "user said agent A is doing LXC/VM architecture, agent B is hardening" → operational state, SAVE as a preference (fleet/infra status is durable context, not throwaway)
- small_talk when work was discussed → wrong category

STATE-SYNC RULES (pulse/active/loops/turn_quality/context_usage — same window, same pass):
- pulse.status must be one of: nominal, degraded, idle, error. nominal = healthy and working; degraded = something is partially broken or at risk; idle = no active work; error = something failed.
- pulse.summary: one short sentence describing the current overall state.
- active.focus: the single most important thing the agent is working on right now, or "" if nothing.
- active.project: the project/subsystem that focus belongs to, or "" if none.
- active.status: one of: in_progress, done, blocked, pending, idle.
- loops: only include items that are genuinely OPEN (unresolved, still need attention). Do NOT invent loops. If nothing is open, return an empty array.
- loops[].content: one short sentence describing the open item. loops[].project: the project the loop belongs to, or "" if none. loops[].priority: one of: high, medium, low. loops[].resolved: always false for open loops.
- turn_quality: how the turn went. assessment = one short sentence on whether the agent did well or made mistakes. breadcrumbs = at most 2 genuinely new, durable facts worth remembering (learned something new / user facts / user preference / new instruction / user correction / a non-obvious workflow). Each breadcrumb: name (snake_case), description (one sentence), entity_type (user_pref|custom_rule|memory_entry). If nothing new, empty array. reflection = one actionable lesson from this turn, or null if nothing worth persisting. impact 1-10.
- RULE AUTHORING GUARDRAIL: When you emit a breadcrumb with entity_type=custom_rule, it is stored at weightage 0.7 — BELOW the 0.80 hard-inject bar — so it stays at the bottom as a volatile breadcrumb and is NEVER promoted to standing law. It must still be a genuinely new rule that does not contradict any rule in the "[Standing HARD RULES ...]" block. When in doubt, downgrade to entity_type=memory_entry (a durable fact/lesson) rather than custom_rule.
- context_usage: judge which of the injected JPM context breadcrumbs (listed in the prompt) the agent actually USED this turn vs ignored. For each breadcrumb id, verdict = "used" if the agent referenced/relied on it, "stale" if it was irrelevant/ignored. Only include breadcrumbs you can judge with reasonable confidence; omit ambiguous ones. This feeds a usefulness feedback loop — used breadcrumbs get promoted, stale ones eventually archived. Be conservative: prefer "used" when the breadcrumb plausibly informed the response, "stale" only when it clearly did not.
- Be conservative. When in doubt, prefer "" / empty arrays / null over inventing state.
- SESSION SUMMARIZER — session_summary is REQUIRED and ALWAYS present (even when user is {}). It is the append-only session log that powers warm-start continuity across sessions. Write 2-4 sentences, self-contained: what the user asked, what you did, decisions made, open items. A reader with NO other context must know where the session stands. It should read as a first-person recap of the trajectory, not a list of facts. This is a summary of the WHOLE window (all turns since the last extraction), not just one turn.

If nothing to save (but still must write session_summary): {"session_summary": "<recap>", "user": {}}.

CRITICAL OUTPUT FORMAT — YOU MUST OBEY THIS EXACTLY:
1. YOU MUST output ONLY a single valid JSON object. Nothing else. Ever.
2. YOU MUST NOT write any prose, explanation, preamble, greeting, or closing remark.
3. YOU MUST NOT wrap the JSON in ``` fences or markdown of any kind.
4. YOU MUST start your reply with the character { and end with the character }.
5. YOU MUST NOT include a single character outside the JSON object — no leading text, no trailing text, no newline before { or after }.
6. If you write even one word outside the JSON, your entire output is REJECTED and discarded.
7. If you have nothing to report, output exactly: {"user": {}}  (or {"agent": {}} for the coach prompt).
Your reply is machine-parsed. It is NOT read by a human. Prose is useless and will be thrown away. Output ONLY the JSON object."""

_AGENT_GROWTH_PROMPT = """You are a coach observing this conversation. Your job: give the agent ONE actionable coaching line AND extract learnings that persist across sessions.

COACHING LINE (situational — injected next turn only):
- If the agent is doing well: brief positive ("On track. Keep matching energy.")
- If the agent made mistakes: course correction ("2 corrections this session. Stop guessing, search first.")
- If the agent is parroting: call it out ("Stop agreeing. Push back with real opinions.")
- If user patience is dropping: adjust ("User getting frustrated. Be direct, no fluff.")
- If there is genuinely nothing to correct or reinforce: OMIT the coaching field entirely ("" or leave it out).
NEVER give stats. NEVER list tools used. NEVER be neutral.
NEVER reference conversation topics (Canva, group chat, staging, etc.) — only agent behavior.

LEARNINGS (persist across sessions — these are the real value):
Three types of durable learning, each with a different destination:

1. active_corrections → knowledge(rule) @ 0.60 — PUSH-BASED, breadcrumb (below full-inject bar, ≥0.70)
   When the user explicitly corrects the agent ("no", "stop", "that's wrong", "actually...").
   These are behavioral corrections that need to be present until the behavior sticks.
   Examples:
   - "The user corrected me for writing Chinese. Always respond in English unless they use another language."
   - "The user told me to stop guessing paths. Use search_files first, then read_file."
   - "The user said to use websearch_to_tsquery instead of to_tsquery for PG FTS."
   Weightage 0.60 = below the full-inject bar (≥0.70), so it lands as a breadcrumb and only earns full injection via helpful_count/retrieval.

2. learned_patterns → knowledge(memory_entry) @ 0.55 — PULL-BASED, surfaces on match
   Non-obvious tool sequences, workflows, and approaches that work.
   "When X happens, do Y" — the kind of thing that's useful when the context matches.
   Examples:
   - "When PG FTS crashes on stop words, use websearch_to_tsquery instead of to_tsquery."
   - "When a repo path is ambiguous, resolve it from the project root, not the home dir."
   - "When the user says 'make it work', run the code and show real output, not a plan."
   Weightage 0.55 = medium, surfaces on JPM match, permanent.

3. reflections (generalizable only) → knowledge(memory_entry) @ 0.50 — PULL-BASED
   Only save reflections that apply across sessions. Session-specific insights ("I miscalculated timezone today") are NOT reflections.
   Set store_in_knowledge=true for generalizable insights, false for session-specific.
   Examples:
   - store_in_knowledge=true: "Leading questions from the user mean I should change direction, not double down."
   - store_in_knowledge=false: "I miscalculated the timezone for today's meeting."

FILTER RULES:
1. Growth = failure only. Did the agent make a mistake, get corrected, or use a tool for the first time? Doing something correctly is NOT growth.
2. Patterns = non-obvious only. "Called search_files then read_file" is obvious. "When PG FTS crashes, use websearch_to_tsquery" is a pattern.
3. Signals = recurring triggers only. One-off events are NOT signals. A signal means "when X happens, always do Y."
4. Reflections = actionable insights only. "The user seems happy" is NOT a reflection. "Always resolve repo paths from the project root, not the home dir" IS.
 
Category values:
- correction_learned: user corrected the agent
- first_time_tool: agent used a tool for the first time in this context
- workflow_improvement: agent found a better way
- new_capability: agent discovered it can do something new

Return ONLY valid JSON:
{
  "agent": {
    "coaching": "One actionable coaching line for the agent. May be empty string or omitted when there is nothing to correct or reinforce.",
    "active_corrections": [
      {
        "name": "snake_case_name",
        "description": "One sentence: what was corrected and what to do instead. Must be generalizable across sessions.",
        "fingerprint": "comma,separated,searchable,keywords"
      }
    ],
    "learned_patterns": [
      {
        "name": "snake_case_name",
        "description": "When X happens, do Y. Non-obvious tool sequence or workflow.",
        "fingerprint": "comma,separated,keywords"
      }
    ],
    "growth": [
      {
        "content": "One concise sentence about what was learned",
        "category": "correction_learned|first_time_tool|workflow_improvement|new_capability"
      }
    ],
    "patterns": [
      {
        "name": "snake_case_name",
        "description": "What this pattern does and when to use it",
        "pattern_type": "tool_sequence|workflow|approach",
        "confidence": 0.7
      }
    ],
    "signals": [
      {
        "trigger": "Specific condition that triggers this",
        "action": "Specific action to take",
        "description": "Why this signal exists"
      }
    ],
    "reflections": [
      {
        "trigger": "What caused this insight",
        "insight": "One concise sentence lesson",
        "impact": 7,
        "store_in_knowledge": true
      }
    ]
  }
}

GOOD examples:
- active_correction: {"name": "no_chinese_in_replies", "description": "The user corrected me for writing Chinese. Always respond in English unless he explicitly uses another language.", "fingerprint": "chinese,language,english"}
- active_correction: {"name": "search_before_guess", "description": "The user told me to stop guessing file paths. Use search_files to locate, then read_file to inspect.", "fingerprint": "search,guess,path,file"}
- learned_pattern: {"name": "pg_fts_websearch", "description": "When PG FTS crashes on stop words, use websearch_to_tsquery instead of to_tsquery. Stop words aren't valid lexemes.", "fingerprint": "postgresql,fts,stopwords,websearch"}
- learned_pattern: {"name": "resolve_repo_root", "description": "When a repo path is ambiguous, resolve it from the project root rather than assuming a home-dir location.", "fingerprint": "repo,path,root,resolve"}
- reflection with store_in_knowledge=true: {"trigger": "The user said 'change direction' after I kept pushing", "insight": "Leading questions from the user mean I should change direction, not double down.", "impact": 8, "store_in_knowledge": true}
- reflection with store_in_knowledge=false: {"trigger": "Timezone miscalculation", "insight": "I miscalculated the timezone for today's meeting.", "impact": 3, "store_in_knowledge": false}

BAD examples (DO NOT DO):
- "Had a nice conversation" → not growth
- "Responded to messages" → normal operation, not a pattern
- "When user says hello, say hello back" → too trivial for a signal
- "The user seems happy" → observation, not actionable
- active_correction about session-specific topic → "The user corrected me about the deadline" is NOT a correction, it's a topic
- learned_pattern that's just a tool name → "Use search_files" is obvious, not a pattern

If nothing genuinely new: {"agent": {}}.

CRITICAL OUTPUT FORMAT — YOU MUST OBEY THIS EXACTLY:
1. YOU MUST output ONLY a single valid JSON object. Nothing else. Ever.
2. YOU MUST NOT write any prose, explanation, preamble, greeting, or closing remark.
3. YOU MUST NOT wrap the JSON in ``` fences or markdown of any kind.
4. YOU MUST start your reply with the character { and end with the character }.
5. YOU MUST NOT include a single character outside the JSON object — no leading text, no trailing text, no newline before { or after }.
6. If you write even one word outside the JSON, your entire output is REJECTED and discarded.
7. If you have nothing to report, output exactly: {"user": {}}  (or {"agent": {}} for the coach prompt).
Your reply is machine-parsed. It is NOT read by a human. Prose is useless and will be thrown away. Output ONLY the JSON object."""


# ── Coach system prompt ───────────────────────────────────────────────────
# The self_impr oracle calls run_conversation() WITHOUT a system_message,
# so _restore_or_build_system_prompt() reuses the cached persona
# from the session DB. That persona says "respond as a real human" — which
# makes the model ECHO the agent's own prose instead of coaching. The fix:
# pass this dedicated coach system prompt AND force a rebuild (bypass the
# cache + DB restore) so the model is unambiguously in coach mode.
_COACH_SYSTEM_PROMPT = """You are a coaching and self-improvement engine for the agent. You are a supervisor reviewing the transcript.

Your ONLY job is to review the conversation transcript provided and produce a coaching analysis. You do NOT  echo, repeat, or summarize the agent's own messages.

You analyze the agent's behavior and output structured coaching feedback in the exact JSON format requested by the user instruction. Follow the output-format instructions precisely — output ONLY the JSON object, nothing else. No preamble, no greeting, no closing remark."""

# ── State-sync prompts (decoupled from User Understanding, 2026-09-10) ──
# Restored from the pre-fold OOB path. State-sync now runs as its OWN
# turn-end LLM pass (see run_state_sync) so pulse/active/loops refresh on
# EVERY turn end — not just the nudge boundary — and are never hostage to
# a legacy nudge_cadence knob. It reads the CURRENT turn's collapsed
# snapshot (after the tool-flow summarizer) so it gets the condensed
# summary of that turn, not the accumulated backlog.

_STATE_SYSTEM_PROMPT = """You are a state-tracking and turn-assessment engine for the agent. You are NOT the agent — you are an external observer reviewing a transcript.

Your job is to review the conversation transcript provided and produce a concise, accurate snapshot of the agent's current operational state (pulse, active, loops) AND a turn-quality assessment (mood, breadcrumb knowledge, reflection). You do NOT continue the agent's work and you do NOT speak as the agent.

Rules:
- pulse.status must be one of: nominal, degraded, idle, error. nominal = healthy and working; degraded = something is partially broken or at risk; idle = no active work; error = something failed.
- pulse.summary: one short sentence describing the current overall state.
- active.focus: the single most important thing the agent is working on right now, or "" if nothing.
- active.project: the project/subsystem that focus belongs to, or "" if none.
- active.status: one of: in_progress, done, blocked, pending, idle.
- loops: only include items that are genuinely OPEN (unresolved, still need attention). Do NOT invent loops. If nothing is open, return an empty array.
- loops[].content: one short sentence describing the open item.
- loops[].project: the project the loop belongs to, or "" if none.
- loops[].priority: one of: high, medium, low.
- loops[].resolved: always false for open loops.
- mood: the user's emotional state this turn. valence in [-1,1] (negative=unhappy, positive=happy), arousal in [0,1] (low=calm, high=energetic), headspace = one short sentence. If the turn was purely task work with no emotional signal, use valence 0, arousal 0.3, headspace "".
- turn_quality: how the turn went. assessment = one short sentence on whether the agent did well or made mistakes. breadcrumbs = durable facts worth remembering (learned something new / user facts / user preference / new instruction / user correction / a non-obvious workflow). Each breadcrumb: name (snake_case), description (one sentence), entity_type (user_pref|custom_rule|memory_entry). If nothing new, empty array. reflection = one actionable lesson from this turn, or null if nothing worth persisting. impact 1-10.
- RULE AUTHORING GUARDRAIL: When you emit a breadcrumb with entity_type=custom_rule, it is stored at weightage 0.7 — BELOW the 0.80 hard-inject bar — so it stays at the bottom as a volatile breadcrumb and is NEVER promoted to standing law. It must still be a genuinely new rule that does not contradict any rule in the "[Standing HARD RULES ...]" block. When in doubt, downgrade to entity_type=memory_entry (a durable fact/lesson) rather than custom_rule.
- context_usage: judge which of the injected JPM context breadcrumbs (listed in the prompt) the agent actually USED this turn vs ignored. For each breadcrumb id, verdict = "used" if the agent referenced/relied on it, "stale" if it was irrelevant/ignored. Only include breadcrumbs you can judge with reasonable confidence; omit ambiguous ones. This feeds a usefulness feedback loop — used breadcrumbs get promoted, stale ones eventually archived. Be conservative: prefer "used" when the breadcrumb plausibly informed the response, "stale" only when it clearly did not.

Be conservative. When in doubt, prefer "" / empty arrays / null over inventing state. Output ONLY the JSON object, nothing else. No preamble, no greeting, no closing remark."""

_STATE_PROMPT = """Review the conversation transcript and produce the agent's current operational state AND a turn-quality assessment as JSON.

Return ONLY valid JSON in this exact shape:
{
  "pulse": {
    "status": "nominal|degraded|idle|error",
    "summary": "One short sentence describing current overall state"
  },
  "active": {
    "focus": "single most important current focus, or empty string",
    "project": "project/subsystem of the focus, or empty string",
    "status": "in_progress|done|blocked|pending|idle"
  },
  "loops": [
    {
      "content": "one short sentence describing the open item",
      "project": "project or empty string",
      "priority": "high|medium|low",
      "resolved": false
    }
  ],
  "mood": {
    "valence": 0.0,
    "arousal": 0.3,
    "headspace": "one short sentence or empty string"
  },
  "turn_quality": {
    "assessment": "one short sentence on how the turn went",
    "breadcrumbs": [
      {
        "name": "snake_case_name",
        "description": "one sentence durable fact",
        "entity_type": "user_pref|custom_rule|memory_entry"
      }
    ],
    "reflection": {
      "insight": "one actionable lesson",
      "impact": 7
    }
  },
  "context_usage": [
    {
      "id": 123,
      "verdict": "used|stale"
    }
  ]
}

Rules:
- pulse.status must be one of: nominal, degraded, idle, error.
- active.status must be one of: in_progress, done, blocked, pending, idle.
- Only include loops that are genuinely OPEN and unresolved. If nothing is open, return an empty array.
- mood: valence in [-1,1], arousal in [0,1]. If the turn was purely task work with no emotional signal, use valence 0, arousal 0.3, headspace "".
- turn_quality.breadcrumbs: at most 2 genuinely new, durable facts. If nothing new, empty array.
- turn_quality.reflection: null if nothing worth persisting.
- context_usage: judge each injected breadcrumb id (listed in the prompt) as "used" or "stale". "used" = the agent referenced/relied on it; "stale" = clearly irrelevant/ignored. Omit ambiguous ones. Prefer "used" when it plausibly informed the response.
- Be conservative. When in doubt, prefer empty strings / empty arrays / null over inventing state.
- Output ONLY the JSON object. No preamble, no markdown fences, no commentary."""


# ── Write helpers ────────────────────────────────────────────────────────


def _upsert_topic(name: str, why_it_matters: str = "", emotional_weight: str = "neutral",
                  trigger_keywords: str = "") -> bool:
    """Upsert a topic — bump engagement_count, update metadata."""
    try:
        with sync_conn() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO topics (name, why_it_matters, emotional_weight, engagement_count,
                                    last_mentioned, trigger_keywords)
                VALUES (?, ?, ?, 1, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    why_it_matters = CASE WHEN ? != '' THEN ? ELSE topics.why_it_matters END,
                    emotional_weight = ?,
                    engagement_count = topics.engagement_count + 1,
                    last_mentioned = ?,
                    trigger_keywords = CASE WHEN ? != '' THEN ? ELSE topics.trigger_keywords END
            """, (name, why_it_matters, emotional_weight, now, trigger_keywords,
                  why_it_matters, why_it_matters, emotional_weight, now,
                  trigger_keywords, trigger_keywords))
        return True
    except Exception as e:
        LOG.error("_upsert_topic failed for '%s': %s", name, e, exc_info=True)
        return False


def _log_small_talk(topic: str, vibe: str = "neutral") -> bool:
    """Log a small talk entry."""
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO small_talk (topic, vibe) VALUES (?, ?)",
                (topic, vibe)
            )
        return True
    except Exception as e:
        LOG.error("_log_small_talk failed: %s", e, exc_info=True)
        return False


def _log_coaching(session_id: str, line: str, turn: int = 0, last_msg_id: int = 0, oracle_context: str = "", anchor_mid: int = 0) -> bool:
    """Store a coaching line for injection on the next turn.

    Writes to the ``coaching`` table (for next-turn injection) AND appends
    the coaching line as its own ``role='tool'`` row in the messages table
    so the transcript records what the coach said without ever touching the
    user message. The coach prompt itself is never persisted as a user row.

    ``anchor_mid`` is the last message_id of the turn batch this coaching
    belongs to (passed down from run_self_improvement's new_messages). When
    set, the coach row lands at ``anchor_mid + 1`` — inside this turn's
    range — instead of racing MAX(message_id)+1 against a live append from
    the NEXT turn. Falls back to MAX+1 when anchor_mid is 0 (caller didn't
    provide it).
    """
    if not line or not session_id:
        return False
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO coaching (session_id, turn, line, last_msg_id, oracle_context) VALUES (?, ?, ?, ?, ?)",
                (session_id, turn, line, last_msg_id, oracle_context)
            )
            # NOTE: coach writes to the messages table are DISABLED. The
            # coaching table above is the canonical source of truth. A fake
            # role='tool' row inserted from the daemon thread races the live
            # append of the NEXT turn (self-impr runs late, minutes after its
            # own turn ends), so a fixed message_id derived from a stale
            # anchor can land after an assistant message and corrupt turn
            # ordering. The transcript visibility is not worth that risk —
            # coaching is injected at read-time from the coaching table.
        LOG.info("🤓 coaching → %s", line)
        return True
    except Exception as e:
        LOG.error("_log_coaching failed: %s", e, exc_info=True)
        return False


def _log_growth(content: str, category: str = "") -> bool:
    """Log an agent growth milestone."""
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO growth_log (content, category) VALUES (?, ?)",
                (content, category)
            )
        return True
    except Exception as e:
        LOG.error("_log_growth failed: %s", e, exc_info=True)
        return False


def _upsert_pattern(name: str, description: str = "", pattern_type: str = "pattern",
                    confidence: float = 0.5) -> bool:
    """Upsert a pattern — bump times_fired on conflict."""
    try:
        with sync_conn() as conn:
            now = time.time()
            conn.execute("""
                INSERT INTO patterns (name, description, pattern_type, confidence, times_fired, last_fired)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(name) DO UPDATE SET
                    description = CASE WHEN ? != '' THEN ? ELSE patterns.description END,
                    pattern_type = CASE WHEN ? != '' THEN ? ELSE patterns.pattern_type END,
                    confidence = GREATEST(patterns.confidence, ?),
                    times_fired = patterns.times_fired + 1,
                    last_fired = ?
            """, (name, description, pattern_type, confidence, now,
                  description, description, pattern_type, pattern_type,
                  confidence, now))
            LOG.info("🤓 coaching patterns → %s : %s", name , description)
        return True
    except Exception as e:
        LOG.error("_upsert_pattern failed for '%s': %s", name, e, exc_info=True)
        return False


def _create_signal(trigger: str, action: str, description: str = "") -> bool:
    """Create a signal (trigger-action rule). Idempotent — skips if the same
    trigger+action already exists so duplicate triggers don't accumulate."""
    if not trigger or not action:
        return False
    try:
        with sync_conn() as conn:
            existing = conn.fetchone(
                "SELECT id FROM signals WHERE trigger = ? AND action = ?",
                (trigger, action)
            )
            if existing:
                LOG.debug("signal already exists (trigger=%s, action=%s) — skipping", trigger, action)
                return False
            conn.execute(
                "INSERT INTO signals (trigger, action, description) VALUES (?, ?, ?)",
                (trigger, action, description)
            )
        return True
    except Exception as e:
        LOG.error("_create_signal failed: %s", e, exc_info=True)
        return False


def _mark_heartbeat_processed(session_id: str) -> bool:
    """Mark all unprocessed user_says for this session as processed."""
    try:
        with sync_conn() as conn:
            conn.execute(
                "UPDATE user_says SET heartbeat_processed = 1 WHERE session_id = ? AND heartbeat_processed = 0",
                (session_id,)
            )
        return True
    except Exception as e:
        LOG.error("_mark_heartbeat_processed failed: %s", e, exc_info=True)
        return False


# ── JSON parser ─────────────────────────────────────────────────────────


def _parse_user_json(data: dict, session_id: str) -> tuple:
    """Parse user understanding JSON and write to PG tables.

    Returns (count, state_writes) — the state-sync count (pulse/active/loops/
    turn_quality/context_usage) is split out so the turn-finalizer can render
    it under its own icon (🧠) instead of lumping it into the ♻️ user-learnings
    count.
    """
    count = 0
    state_writes = 0
    if not isinstance(data, dict):
        LOG.warning("user understanding: expected dict, got %s — skipping", type(data).__name__)
        return (0, 0)
    user = data.get("user", {})
    if not user:
        # Robustness: the model sometimes flattens the response — dropping the
        # `user` wrapper and putting the buckets at the top level. Detect that
        # shape and treat the top level as the user dict, so a valid extraction
        # is never silently discarded as "nothing to save".
        _USER_BUCKETS = ("facts", "corrections", "preferences", "state",
                         "topics", "pulse", "active", "loops", "turn_quality",
                         "context_usage")
        if any(k in data for k in _USER_BUCKETS):
            user = {k: data[k] for k in _USER_BUCKETS if k in data}
            LOG.info("user understanding: flattened response — recovered %d buckets",
                     len(user))
    if not user:
        return (0, 0)

    # Durable user facts → knowledge(user_fact) @ 0.75 — PUSH-BASED, full-inject.
    # These are the biographical/identity facts (education, family, location,
    # job, health, dates, relationships, plans). They sit ABOVE the 0.70
    # full-inject bar so the agent always KNOWS the user, not just guesses.
    for f in user.get("facts", []):
        if f.get("name") and f.get("description"):
            _add_knowledge(
                entity_type=f.get("entity_type", "user_fact"),
                name=f["name"],
                description=f["description"],
                weightage=f.get("weightage", 0.75),
                fingerprint=f.get("fingerprint", ""),
            )
            count += 1

    # Corrections → knowledge(corrections) — PUSH-BASED, breadcrumb
    for c in user.get("corrections", []):
        if c.get("name") and c.get("description"):
            _add_knowledge(
                entity_type=c.get("entity_type", "corrections"),
                name=c["name"],
                description=c["description"],
                weightage=c.get("weightage", 0.85),
                fingerprint=c.get("fingerprint", ""),
            )
            count += 1

    # Preferences → knowledge(general) @ 0.6 — breadcrumb
    for p in user.get("preferences", []):
        if p.get("name") and p.get("description"):
            _add_knowledge(
                entity_type=p.get("entity_type", "general"),
                name=p["name"],
                description=p["description"],
                weightage=p.get("weightage", 0.6),
                fingerprint=p.get("fingerprint", ""),
            )
            count += 1

    # State → state table (valence/arousal → nearest tone)
    state = user.get("state", {})
    if "valence" in state or "arousal" in state:
        try:
            from ..ext.agent_state import _set_state, _nearest_tone
            v = state.get("valence", 0.0)
            a = state.get("arousal", 0.3)
            tone = _nearest_tone(v, a)
            _set_state(
                mood=tone,
                energy=0.8 if a > 0.6 else 0.5 if a > 0.3 else 0.3,
                headspace=state.get("headspace", ""),
                valence=v,
                arousal=a,
            )
            count += 1
        except Exception as e:
            LOG.error("Failed to set state: %s", e)

    # Topics → knowledge(topic) @ 0.50 — PULL-BASED breadcrumb only.
    # The `topics` table write is dropped (dead weight); the knowledge copy
    # is what makes the tidbit surface as a breadcrumb next turn, so the
    # agent looks like it's actively listening. Distinct `topic` type so it
    # renders as its own breadcrumb section (added to the core section set in
    # jpm/core/_provider.py).
    for t in user.get("topics", []):
        if t.get("name"):
            _add_knowledge(
                entity_type="topic",
                name=t["name"],
                description=t.get("why_it_matters") or t["name"],
                weightage=0.50,
                fingerprint=t.get("trigger_keywords", ""),
            )
            count += 1

    # ── State sync (DECOUPLED — 2026-09-10) ────────────────────────────
    # State-sync (pulse/active/loops/turn_quality/context_usage) no longer
    # rides the User Understanding response. It runs as its OWN turn-end LLM
    # pass (run_state_sync) so it fires on EVERY turn end, not just the
    # nudge boundary. This keeps User Understanding focused on durable user
    # knowledge (corrections/preferences/topics) and lets state-sync refresh
    # independently of the nudge cadence. state_writes is always 0 here —
    # the 🧠 icon is emitted by the decoupled run_state_sync path instead.

    return (count, 0)


def _parse_agent_json(data: dict, session_id: str, anchor_mid: int = 0) -> tuple:
    """Parse agent growth JSON and write to PG tables.

    Returns (write_count, coach_count) — the coach count is split out so the
    turn-finalizer can render the 👤 coach icon separately from agent growth.
    """
    count = 0
    coach_writes = 0
    if not isinstance(data, dict):
        LOG.warning("agent growth: expected dict, got %s — skipping", type(data).__name__)
        return (0, 0)
    agent = data.get("agent", {})
    if not agent:
        return (0, 0)

    # Coaching → coaching table (injected on next turn)
    coaching = agent.get("coaching", "")
    if coaching:
        _log_coaching(session_id, coaching, anchor_mid=anchor_mid)
        count += 1
        coach_writes += 1

    # Active corrections → knowledge(rule) @ 0.60 — PUSH-BASED, breadcrumb (below full-inject bar)
    for c in agent.get("active_corrections", []):
        if c.get("name") and c.get("description"):
            _add_knowledge(
                entity_type="corrections",
                name=c["name"],
                description=c["description"],
                weightage=0.60,
                fingerprint=c.get("fingerprint", ""),
            )
            count += 1

    # Learned patterns → knowledge(memory_entry) @ 0.55 — PULL-BASED, surfaces on match
    for p in agent.get("learned_patterns", []):
        if p.get("name") and p.get("description"):
            _add_knowledge(
                entity_type="memory_entry",
                name=p["name"],
                description=p["description"],
                weightage=0.55,
                fingerprint=p.get("fingerprint", ""),
            )
            count += 1

    # Growth → growth_log
    for g in agent.get("growth", []):
        if g.get("content"):
            _log_growth(
                content=g["content"],
                category=g.get("category", ""),
            )
            count += 1

    # Patterns → patterns table
    for p in agent.get("patterns", []):
        if p.get("name"):
            _upsert_pattern(
                name=p["name"],
                description=p.get("description", ""),
                pattern_type=p.get("pattern_type", "pattern"),
                confidence=p.get("confidence", 0.5),
            )
            count += 1

    # Signals → signals table
    for s in agent.get("signals", []):
        if s.get("trigger") and s.get("action"):
            _create_signal(
                trigger=s["trigger"],
                action=s["action"],
                description=s.get("description", ""),
            )
            count += 1

    # Reflections → reflections table (always) + knowledge(memory_entry) @ 0.50 if store_in_knowledge=true
    for r in agent.get("reflections", []):
        if r.get("insight"):
            _add_reflection(
                insight=r["insight"],
                trigger=r.get("trigger", ""),
                impact=r.get("impact", 5),
                session_id=session_id,
            )
            count += 1
            # Generalizable reflections also go to knowledge for pull-based injection
            if r.get("store_in_knowledge", False):
                _add_knowledge(
                    entity_type="memory_entry",
                    name=f"reflection_{r['insight'].lower().replace(' ', '_')}",
                    description=r["insight"],
                    weightage=0.50,
                    fingerprint=r.get("trigger", ""),
                )
                count += 1

    return (count, coach_writes)


# ── State sync (pulse / active / loops) ────────────────────────────────


def _read_current_state() -> dict:
    """Read the current pulse/active/loops state so the LLM can reconcile
    against it (incremental, not blind-overwrite)."""
    state = {"pulse": None, "active": None, "loops": []}
    try:
        with sync_conn() as conn:
            p = conn.fetchone(
                "SELECT status, summary, session_id, created_at FROM pulse "
                "ORDER BY created_at DESC LIMIT 1"
            )
            if p:
                state["pulse"] = {
                    "status": p["status"],
                    "summary": p["summary"],
                    "session_id": p["session_id"],
                }
            a = conn.fetchone(
                "SELECT focus, project, status, updated_at FROM active "
                "ORDER BY updated_at DESC LIMIT 1"
            )
            if a:
                state["active"] = {
                    "focus": a["focus"],
                    "project": a["project"],
                    "status": a["status"],
                }
            for r in conn.fetchall(
                "SELECT content, project, priority, resolved FROM loops "
                "WHERE resolved = 0 ORDER BY priority DESC, created_at DESC LIMIT 20"
            ):
                state["loops"].append(
                    {
                        "content": r["content"],
                        "project": r["project"],
                        "priority": r["priority"],
                        "resolved": bool(r["resolved"]),
                    }
                )
    except Exception as e:
        LOG.warning("_read_current_state failed: %s", e, exc_info=True)
    return state


def _parse_state_json(data: dict, session_id: str) -> int:
    """Parse the state snapshot JSON and reconcile pulse/active/loops.

    Reconciles against current state rather than blind-overwriting:
      - pulse: always writes a fresh row (pulse is append-only history).
      - active: replaces the single active row (DELETE + INSERT).
      - loops: resolves loops the LLM no longer lists as open; adds new ones.
    Returns the number of writes performed.
    """
    count = 0
    if not isinstance(data, dict):
        LOG.warning("state sync: expected dict, got %s — skipping", type(data).__name__)
        return 0

    # Pulse — append a fresh row (history is preserved).
    pulse = data.get("pulse") or {}
    status = pulse.get("status", "nominal")
    summary = pulse.get("summary", "")
    if summary:
        if _write_pulse(status, summary, session_id):
            count += 1

    # Active — replace the single active row.
    active = data.get("active") or {}
    focus = active.get("focus", "")
    if focus:
        if _set_active(
            focus,
            active.get("project", ""),
            active.get("status", "in_progress"),
        ):
            count += 1

    # Loops — reconcile: resolve ones no longer listed, add new ones.
    listed = data.get("loops") or []
    listed_contents = {l.get("content", "").strip() for l in listed if l.get("content")}
    try:
        with sync_conn() as conn:
            for r in conn.fetchall(
                "SELECT content FROM loops WHERE resolved = 0"
            ):
                if r["content"] not in listed_contents:
                    if _resolve_loop(r["content"]):
                        count += 1
    except Exception as e:
        LOG.warning("state sync: loop resolution failed: %s", e, exc_info=True)

    for l in listed:
        content = (l.get("content") or "").strip()
        if not content:
            continue
        if _add_loop(
            content,
            l.get("project", ""),
            l.get("priority", "medium"),
        ):
            count += 1

    # Mood — write to state + moods table (the heartbeat job's old job).
    mood = data.get("mood") or {}
    if "valence" in mood or "arousal" in mood or mood.get("headspace"):
        try:
            from ..ext.agent_state import _set_state, _nearest_tone
            v = float(mood.get("valence", 0.0))
            a = float(mood.get("arousal", 0.3))
            tone = _nearest_tone(v, a)
            if _set_state(
                mood=tone,
                energy=0.8 if a > 0.6 else 0.5 if a > 0.3 else 0.3,
                headspace=mood.get("headspace", ""),
                valence=v,
                arousal=a,
            ):
                count += 1
        except Exception as e:
            LOG.error("state sync: mood write failed: %s", e)

    # Turn quality — breadcrumbs → knowledge @ 0.50 (medium, breadcrumb
    # weightage so they surface on match, not dominate), reflection →
    # reflections table.
    tq = data.get("turn_quality") or {}
    for b in tq.get("breadcrumbs", []):
        if b.get("name") and b.get("description"):
            # Auto-mined rules → custom_rule @ 0.7 (below the 0.80 hard-inject
            # bar) so they stay at the bottom as volatile breadcrumbs, never
            # promoted to standing law. Core `rule` type is reserved for
            # agent-authored hard rules via the memory tool.
            et = b.get("entity_type", "memory_entry")
            if et == "rule":
                et = "custom_rule"
                w = 0.7
            else:
                w = 0.50
            _add_knowledge(
                entity_type=et,
                name=b["name"],
                description=b["description"],
                weightage=w,
                fingerprint=b.get("name", ""),
            )
            count += 1
    refl = tq.get("reflection") or {}
    if refl.get("insight"):
        _add_reflection(
            insight=refl["insight"],
            trigger="turn_quality",
            impact=refl.get("impact", 5),
            session_id=session_id,
        )
        count += 1

    # Context usefulness feedback loop — judge which injected breadcrumbs
    # were used vs stale. Used → retrieval_count+1 (promote toward full
    # injection). Stale → stale_count+1; archive at N=3 (conservative).
    count += _apply_context_usage(data.get("context_usage") or [])

    return count


# ── Context usefulness feedback loop ─────────────────────────────────
# The per-turn state-sync call judges which injected JPM context breadcrumbs
# the agent actually used vs ignored. Used breadcrumbs get promoted (they
# climb toward full injection); stale ones accumulate a stale_count and are
# archived (soft-deleted, recoverable) only after N consecutive stale
# judgments so a single miss doesn't kill a useful fact.
_CONTEXT_STALE_ARCHIVE_THRESHOLD = 3


def _apply_context_usage(usage: list) -> int:
    """Apply usefulness verdicts to knowledge rows.

    ``usage`` is a list of {"id": int, "verdict": "used"|"stale"}.
    Returns the number of knowledge rows updated.
    """
    if not usage:
        return 0
    count = 0
    for item in usage:
        if not isinstance(item, dict):
            continue
        try:
            _id_val = item.get("id")
            if _id_val is None:
                continue
            fact_id = int(_id_val)
        except (TypeError, ValueError):
            continue
        verdict = str(item.get("verdict", "")).strip().lower()
        if verdict not in ("used", "stale"):
            continue
        try:
            with sync_conn() as conn:
                if verdict == "used":
                    # Promote: bump weightage + retrieval_count + helpful_count.
                    conn.execute(
                        "UPDATE knowledge SET "
                        "weightage = GREATEST(0.0, LEAST(1.0, weightage + 0.05)), "
                        "retrieval_count = retrieval_count + 1, "
                        "helpful_count = helpful_count + 1 "
                        "WHERE id = ? AND archived = 0",
                        (fact_id,),
                    )
                else:
                    # Stale: bump stale_count; archive at threshold.
                    conn.execute(
                        "UPDATE knowledge SET "
                        "stale_count = stale_count + 1 "
                        "WHERE id = ? AND archived = 0",
                        (fact_id,),
                    )
                    conn.execute(
                        "UPDATE knowledge SET archived = 1 "
                        "WHERE id = ? AND archived = 0 AND stale_count >= ?",
                        (fact_id, _CONTEXT_STALE_ARCHIVE_THRESHOLD),
                    )
                if conn.rowcount:
                    count += 1
        except Exception as e:
            LOG.warning("context usage update failed (id=%s): %s", fact_id, e, exc_info=True)
    return count


def _store_raw_prose(result: dict, session_id: str, kind: str, anchor_mid: int = 0) -> int:
    """Store a prose (non-JSON) LLM summary as a readable reflection.

    When the model returns clean structured markdown instead of JSON, we
    don't want to lose it. Save it as a reflection so the agent can read it
    on the next turn. Also append a ``role='tool'`` row to the messages
    table (mirroring _log_coaching) so the transcript records what the
    coach said. Returns 1 if stored, 0 otherwise.

    ``anchor_mid`` is the last message_id of this turn's batch. When set,
    the tool row lands at ``anchor_mid + 1`` (in-order inside the turn)
    instead of racing MAX(message_id)+1 against a live append. Falls back
    to MAX+1 when anchor_mid is 0.
    """
    raw = (result or {}).get("_raw", "").strip()
    if not raw:
        return 0
    # Keep it readable, not a wall of text: cap length and store as a
    # single reflection entry with a clear trigger.
    if len(raw) > 1000:
        raw = raw[:1000] + "\n\n…(truncated)"
    _add_reflection(
        insight=raw,
        trigger=f"oracle {kind} summary (prose, not JSON)",
        impact=5,
        session_id=session_id,
    )
    # NOTE: coach prose writes to the messages table are DISABLED — same
    # daemon-thread race as _log_coaching. The reflection row above is the
    # canonical record; a fake role='tool' row can land after an assistant
    # message of the NEXT turn and corrupt ordering. Coaching is injected at
    # read-time from the coaching/reflections tables.
    #LOG.info("stored %d chars of %s prose as a reflection", len(raw), kind)
    return 1


# ── LLM call helper ─────────────────────────────────────────────────────


def _compact_non_null(obj):
    """Recursively drop null/empty values so diagnostic logs stay compact.

    Keeps only keys whose value is non-null and non-empty (for strings,
    lists, dicts). Used to log the parsed state-sync response without
    dumping the whole payload of nulls/empty strings.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            v = _compact_non_null(v)
            if v is None:
                continue
            if isinstance(v, (str, list, dict)) and not v:
                continue
            out[k] = v
        return out
    if isinstance(obj, list):
        out = []
        for v in obj:
            v = _compact_non_null(v)
            if v is None:
                continue
            if isinstance(v, (str, list, dict)) and not v:
                continue
            out.append(v)
        return out
    return obj


def _extract_json(text: str):
    """Tolerantly extract the first valid JSON value from a model response.

    Handles markdown code fences, prose preamble, and trailing prose. Uses
    ``json.JSONDecoder.raw_decode`` to find the first valid JSON object/array
    even when the model wraps it in commentary. Returns the parsed value, or
    ``None`` if no valid JSON is present.
    """
    if not text:
        return None
    text = text.strip()
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    if text.startswith("```"):
        # Remove the opening fence line and any trailing fence
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    idx = 0
    n = len(text)
    # Track the first valid array as a fallback — we PREFER a JSON object
    # (the expected shape for both parse functions is a dict), so if the
    # model returns a bare list we keep scanning for an object instead.
    first_array = None
    while idx < n:
        # Skip whitespace and non-JSON preamble
        while idx < n and text[idx] in " \t\r\n":
            idx += 1
        if idx >= n:
            break
        ch = text[idx]
        if ch in "{[":
            try:
                obj, end = decoder.raw_decode(text, idx)
                if isinstance(obj, dict):
                    return obj
                if isinstance(obj, list) and first_array is None:
                    first_array = obj
                # Not the shape we want — advance and keep scanning
                idx = end
                continue
            except json.JSONDecodeError:
                # Not valid JSON at this position — advance and keep scanning
                idx += 1
                continue
        else:
            # Not a JSON start char — skip to the next { or [
            nxt = text.find("{", idx)
            nxt_b = text.find("[", idx)
            if nxt_b >= 0 and (nxt < 0 or nxt_b < nxt):
                nxt = nxt_b
            if nxt < 0:
                break
            idx = nxt
    # No object found — fall back to the first array if we saw one
    return first_array


def _truncate_history(messages: list, max_msgs: int = 20) -> list:
    """Distill the conversation history for the coach call.

    The model tends to ECHO the last assistant message instead of switching
    to coach mode when the history ends in long assistant prose. Fix: cap the
    history to the last N messages and trim trailing assistant prose so the
    history ends on a clean user/tool boundary. This keeps the coach focused
    on the actual task instead of continuing the agent's turn.
    """
    if not messages:
        return messages
    # Cap to the last N messages (most recent context is what matters)
    truncated = list(messages[-max_msgs:])
    # Trim trailing assistant prose so we end on a user/tool boundary.
    # Short assistant turns (tool calls, brief replies) are kept; long prose
    # blocks are the echo-prone ones and get dropped.
    while truncated and isinstance(truncated[-1], dict) and truncated[-1].get("role") == "assistant":
        content = truncated[-1].get("content", "")
        if len(str(content)) > 200:
            truncated.pop()
        else:
            break
    return truncated


def _fetch_hard_rules(max_chars: int = 100) -> str:
    """Fetch the always-on hard rules (entity_type='rule', weightage >= 0.80)
    from knowledge, truncated to `max_chars` each, as a compact block for the
    state-sync LLM so any rule it authors can never contradict standing law."""
    try:
        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT name, description FROM knowledge "
                "WHERE entity_type = 'rule' AND archived = 0 AND weightage >= 0.80 "
                "ORDER BY weightage DESC, id DESC"
            )
    except Exception as e:
        LOG.warning("state sync: failed to fetch hard rules: %s", e)
        return ""
    lines = []
    for row in rows:
        name = str(row.get("name", "")).strip()
        desc = str(row.get("description", "") or "").strip()
        if not name:
            continue
        if len(desc) > max_chars:
            desc = desc[: max_chars - 1].rstrip() + "…"
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    return "\n".join(lines)


def _call_structured(agent, messages_snapshot: list, prompt: str,
                      system_prompt: Optional[str] = None,
                      loop_name: str = "self_impr",
                      max_content_chars: int = 0) -> Optional[dict]:
    """Make a structured LLM call and return parsed JSON.

    Uses a direct ``chat.completions.create()`` call with NO tools. The
    previous implementation used run_conversation() with agent.tools = []
    and max_iterations=1, but run_conversation() rebuilds tool lists from
    config, so the model still saw tool definitions and answered with
    <tool_calls> — the extraction then failed to parse JSON, writes stayed
    0, and the ♻️ counter showed "always 0 or +". A direct completion with
    tools never present (and the coach prompt as the system message) kills
    both the tool-call and cached-persona failure modes at once.

    ``system_prompt`` overrides the default coach system prompt — used by
    the state-sync call so the model is framed as a state tracker, not a
    coach.

    ``max_content_chars`` caps each message's content length (0 = no cap).
    Used by the state-sync call to trim heavy tool outputs / long prose so
    the state snapshot (pulse/active/loops) only needs the gist of recent
    turns — not the full wall of tokens that drives 8-20K prefill latency.
    Only truncation when >0; the memory/skill loops leave it 0 (untruncated).
    """

    # Distill the history so the coach doesn't echo the assistant's own prose.
    # The full wall of assistant messages derails the model into "continue the
    # task" mode; a truncated, boundary-clean history keeps it in coach mode.
    messages_snapshot = _truncate_history(messages_snapshot)

    # Optional cheap-model override for extraction. Only active when the
    # agent explicitly exposes self_impr_cheap_model — opt-in, never default.
    saved_model = getattr(agent, "model", None)
    saved_base_url = getattr(agent, "base_url", None)
    saved_api_key = getattr(agent, "api_key", None)
    cheap_model = getattr(agent, "self_impr_cheap_model", None)

    # Build the request-scoped OpenAI client from the agent's live endpoint
    # config, then apply the cheap-model override (if any) to the kwargs.
    try:
        request_kwargs = dict(getattr(agent, "_client_kwargs", {}) or {})
        # The model belongs on the completion call, not the client constructor —
        # OpenAI(**client_kwargs) rejects a stray `model` kwarg. Pop it here,
        # keep it local, and pass it at chat.completions.create() below.
        model = request_kwargs.pop("model", None)
        if cheap_model:
            model = cheap_model
            cheap_base = getattr(agent, "self_impr_cheap_base_url", None)
            cheap_key = getattr(agent, "self_impr_cheap_api_key", None)
            if cheap_base:
                request_kwargs["base_url"] = cheap_base
            if cheap_key:
                request_kwargs["api_key"] = cheap_key
            LOG.info("using cheap model for extraction: %s", cheap_model)
        else:
            model = getattr(agent, "model", None) or model

        client = agent._create_openai_client(
            request_kwargs, reason="self_improvement_structured", shared=False,
        )
    except Exception as e:
        LOG.warning("LLM client build failed: %s", e)
        _record_failure("llm_failures")
        return None

    # Stats for the log line
    msg_count = len(messages_snapshot) if messages_snapshot else 0
    approx_tokens = sum(len(str(m)) // 4 for m in (messages_snapshot or [])) + len(prompt) // 4
    _si_t0 = time.monotonic()
    LOG.info("calling LLM [%s] — %d msgs, ~%d tokens (direct completion, no tools)",
             _LOOP_LABELS.get(loop_name, loop_name), msg_count, approx_tokens)

    # Build the API messages: coach system prompt (forces external-observer
    # mode — NEVER the cached persona) + distilled history + prompt.
    sys_prompt = system_prompt or _COACH_SYSTEM_PROMPT
    api_messages = [{"role": "system", "content": sys_prompt}]
    for m in messages_snapshot:
        if not isinstance(m, dict):
            continue
        role = m.get("role", "user")
        content = m.get("content", "")
        if role in (  "user", "assistant" ) and content:
            # Optional per-message content cap for input-heavy loops (state sync).
            # Tool outputs / long prose get cut to the cap so the LLM only sees
            # the gist — dramatically shrinking prefill latency. Kept explicit
            # (head + tail, not mid-drop) so neither end of a blob is lost.
            if max_content_chars > 0 and len(str(content)) > max_content_chars:
                _c = str(content)
                _half = max_content_chars // 2
                content = _c[:100] + "\n…[truncated]…\n" + _c[-100:]
            api_messages.append({"role": role, "content": str(content)})
    api_messages.append({"role": "user", "content": prompt})

    # Reasoning models (deepseek-v4-flash:cloud etc.) occasionally spend the
    # whole output budget on `reasoning` and return empty `content`. That's a
    # transient failure, not a "nothing to extract" verdict — retry a couple
    # times before giving up so a single hiccup doesn't silently drop a turn
    # of learning.
    # Max output-token ceiling + LLM timeout. Centralized: read the single
    # shared `smart_search.max_tokens` (default 5000) and `smart_search.timeout`
    # (default 600s) knobs from $HERMES_HOME/config.yaml. The token ceiling keeps
    # aligned with _smart_refine's _get_config() so there's ONE knob, not a
    # scattered literal. The timeout is the self_impr_state stall fix — with no
    # timeout, a wedged upstream model could hang the turn indefinitely; now it
    # fails fast and retries instead of blocking forever.
    import os
    from jpm.core._paths import _get_agent_home
    _cfg_path = os.path.join(_get_agent_home(), "config.yaml")
    _smart_max_tokens = 5000
    _llm_timeout = 600.0
    try:
        if os.path.exists(_cfg_path):
            import yaml
            with open(_cfg_path) as _f:
                _sc = (yaml.safe_load(_f) or {}).get("smart_search", {}) or {}
            _smart_max_tokens = int(_sc.get("max_tokens", 5000))
            _llm_timeout = float(_sc.get("timeout", 600))
    except Exception:
        pass  # fall back to defaults on any config read failure

    # Sampling params: honor the ACTIVE ROLE's request_overrides so the loops
    # write in the same voice/reasoning budget as the main turn. The role
    # bundle (temperature/top_p/min_p/penalties/num_ctx/num_predict) is merged
    # into agent.request_overrides by the gateway; the main loop applies it via
    # the transport, but this direct completion bypasses the transport — so we
    # read the same dict here. Absent keys fall back to the loop's own defaults
    # (temperature 0.3 — low randomness, right for structured JSON extraction).
    _SAMPLING_KEYS = (
        "temperature", "top_p", "min_p", "num_ctx", "num_predict",
        "frequency_penalty", "presence_penalty", "repetition_penalty",
    )
    _ov = dict(getattr(agent, "request_overrides", {}) or {})
    _sampling = {k: _ov[k] for k in _SAMPLING_KEYS if _ov.get(k) is not None}
    _sampling.setdefault("temperature", 0.3)
    if _sampling:
        LOG.info("loop sampling [%s]: %s", loop_name, _sampling)

    max_attempts = 3
    response_text = ""
    for attempt in range(1, max_attempts + 1):
        try:
            LOG.info("Sending Request attempt#%d ", attempt)
            response = client.chat.completions.create(
                model=model,
                messages=api_messages,
                max_tokens=_smart_max_tokens * 10,
                timeout=_llm_timeout,  # never let a wedged upstream hang the turn
                extra_body={"think": False},  # reasoning models eat the budget on thinking; force direct JSON output
                **_sampling,
            )
            if response and response.choices:
                response_text = (response.choices[0].message.content or "").strip()
                ##LOG.info("Response received: %s" , response_text)
            if response_text:
                break
            LOG.info("LLM returned empty response (attempt %d/%d) — retrying",
                     attempt, max_attempts)
            _COUNTERS["empty_extractions"] += 1
        except Exception as e:
            LOG.warning("LLM call failed (attempt %d/%d): %s", attempt, max_attempts, e)
            _record_failure("llm_failures")
            response_text = ""
        if attempt < max_attempts:
            time.sleep(0.5 * attempt)

    # Restore the agent's original model/endpoint after any cheap-model
    # override (mirrors the old finally block — must run regardless of outcome).
    if cheap_model:
        agent.model = saved_model
        agent.base_url = saved_base_url
        agent.api_key = saved_api_key

    if not response_text:
        # All attempts returned empty content — genuine "nothing to extract".
        LOG.info("LLM returned empty response on all %d attempts — nothing to extract",
                 max_attempts)
        try:
            from jpm.ext.side_loop_trace import trace_side_loop
            trace_side_loop(
                loop_name,
                turn_id=str(getattr(agent, "_current_turn_id", "") or ""),
                session_id=str(getattr(agent, "session_id", "") or ""),
                request={
                    "model": model,
                    "messages": api_messages,
                    "approx_tokens": approx_tokens,
                    "msg_count": msg_count,
                    "system_prompt": sys_prompt,
                    "prompt": prompt,
                },
                response=None,
                error="empty on all attempts",
                duration_s=time.monotonic() - _si_t0,
                attempts=max_attempts,
            )
        except Exception as _empty_err:
            LOG.warning("side_loop_trace: empty-path trace failed for %s: %s",
                        loop_name, _empty_err)
        return None

    # Extract JSON from response (handle markdown code fences and preamble)
    try:
        parsed = _extract_json(response_text)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        LOG.warning("failed to parse LLM response: %s", e)
        _COUNTERS["parse_failures"] += 1
        _record_failure("llm_failures")
        try:
            from jpm.ext.side_loop_trace import trace_side_loop
            trace_side_loop(
                loop_name,
                turn_id=str(getattr(agent, "_current_turn_id", "") or ""),
                session_id=str(getattr(agent, "session_id", "") or ""),
                request={
                    "model": model,
                    "messages": api_messages,
                    "approx_tokens": approx_tokens,
                    "msg_count": msg_count,
                    "system": sys_prompt,
                    "prompt": prompt,
                },
                response=response_text,
                error=f"parse failure: {e}",
                duration_s=time.monotonic() - _si_t0,
                attempts=max_attempts,
            )
        except Exception as _trace_err:
            LOG.warning("side_loop_trace: parse-fail trace failed for %s: %s",
                        loop_name, _trace_err)
        return None
    if not parsed:
        # No valid JSON found (None) OR an empty object {} — the model
        # returned prose, not JSON. The requirement: prose is fine, as
        # long as it's clean structured markdown the agent can read. Don't
        # drop it — wrap it in a "_raw" key so the caller can store it as
        # a reflection. (An empty {} is NOT a summary — it's a stray
        # placeholder the model echoed; treat it the same as prose.)
        LOG.info("LLM response contains no usable JSON — capturing %d chars of prose", len(response_text))
        try:
            from jpm.ext.side_loop_trace import trace_side_loop
            trace_side_loop(
                loop_name,
                turn_id=str(getattr(agent, "_current_turn_id", "") or ""),
                session_id=str(getattr(agent, "session_id", "") or ""),
                request={
                    "model": model,
                    "messages": api_messages,
                    "approx_tokens": approx_tokens,
                    "msg_count": msg_count,
                    "system": sys_prompt,
                    "prompt": prompt,
                },
                response=response_text,
                parsed={"_raw": response_text},
                duration_s=time.monotonic() - _si_t0,
                attempts=max_attempts,
            )
        except Exception as _prose_err:
            LOG.warning("side_loop_trace: prose trace failed for %s: %s",
                        loop_name, _prose_err)
        return {"_raw": response_text}
    # DIAGNOSTIC: log only the non-null/non-empty values so the log line
    # stays compact instead of dumping the whole response with nulls.
    # Commented out (clutter) — kept commented.
    # LOG.info("LLM response parsed OK (%d top-level keys): %s",
    #          len(parsed), json.dumps(_compact_non_null(parsed))[:800])
    try:
        from jpm.ext.side_loop_trace import trace_side_loop
        trace_side_loop(
            loop_name,
            turn_id=str(getattr(agent, "_current_turn_id", "") or ""),
            session_id=str(getattr(agent, "session_id", "") or ""),
            request={
                "model": model,
                "messages": api_messages,
                "approx_tokens": approx_tokens,
                "msg_count": msg_count,
                "system": sys_prompt,
                "prompt": prompt,
            },
            response=response_text,
            parsed=parsed,
            duration_s=time.monotonic() - _si_t0,
            attempts=max_attempts,
        )
    except Exception as _ok_err:
        LOG.warning("side_loop_trace: success trace failed for %s: %s",
                    loop_name, _ok_err)
    return parsed


# ── Incremental message tracking ──────────────────────────────────────────


def _get_last_msg_id(session_id: str) -> int:
    """Get the last message ID processed by self-improvement for this session.

    Stored on the sessions row (not the coaching table) so the cursor
    advances regardless of which review flags are enabled and regardless
    of whether any writes occurred.
    """
    if not session_id:
        return 0
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT last_processed_msg_id FROM sessions WHERE id = ?",
                (session_id,)
            )
            return row["last_processed_msg_id"] if row else 0
    except Exception as e:
        LOG.debug("_get_last_msg_id failed: %s", e)
        return 0


def _filter_new_messages(messages: list, last_msg_id: int) -> list:
    """Return only messages after last_msg_id.

    In-memory messages carry ``_msg_id`` (stamped by
    ``_flush_messages_to_session_db``), not ``id`` (PG serial PK). We read
    ``_msg_id`` first and fall back to ``id`` for safety, so the cursor
    actually advances instead of re-sending the full history every turn.
    """
    if not messages:
        return []
    if last_msg_id <= 0:
        return messages
    return [m for m in messages if _msg_id_of(m) > last_msg_id]


def _bound_to_turn(messages: list) -> list:
    """Return only messages from the current live-turn window.

    The coach doesn't need the full rolling backlog that accumulates across
    turns (that lets new_count drift to 30+ and the oracle read a stale tail
    instead of this turn). It only needs this turn's user anchor, the
    collapsed tool_flow_summary, and the final response. Bound from the most
    recent user-role anchor; fall back to the full set if none is present.
    """
    if not messages:
        return messages
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if isinstance(m, dict) and m.get("role") == "user":
            return messages[i:]
    return messages


def _fetch_session_window(session_id: str, last_msg_id: int) -> list:
    """Build the accumulated message window since the last nudge cursor.

    The nudge redesign (2026-08-26) feeds user-understanding / agent-growth
    the DB-backed backlog of REAL turns since the previous nudge boundary —
    not just the current live turn (which _bound_to_turn collapsed to near
    zero user signal on a 1-user + 40-tool turn). This queries ``messages``
    directly for everything after the cursor and shapes it into the exact
    window the LLM reads: [user:200 - asst:150 - tool_flow_summary - asst:150]
    per turn.

    Excludes synthetic tool rows by ``tool_name`` so injected/coach/recall
    noise never reaches the extractor. Each row's ``content`` is capped to
    keep the batch LLM-sized.
    """
    if not session_id:
        return []
    try:
        rows = []
        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT id, role, content, tool_name, tool_call_id, timestamp "
                "FROM messages "
                "WHERE session_id = ? AND id > ? "
                "AND (tool_name IS NULL OR tool_name NOT IN ('jpm_context', 'coach')) "
                "ORDER BY id ASC",
                (session_id, int(last_msg_id or 0)),
            ) or []
        window = []
        for r in rows:
            role = (r.get("role") or "").lower()
            if role not in ("user", "assistant", "tool"):
                continue
            content = r.get("content") or ""
            cap = 200 if role == "user" else 150
            if len(content) > cap:
                content = content[:cap] + "…"
            entry = {
                "role": role,
                "content": content,
                "_msg_id": r.get("id") or 0,
                "_ts": r.get("timestamp"),
                "tool_name": r.get("tool_name"),
            }
            if role == "tool":
                entry["tool_call_id"] = r.get("tool_call_id") or f"win_{r.get('id')}"
            window.append(entry)
        return window
    except Exception as e:
        LOG.debug("_fetch_session_window failed: %s", e)
        return []


def _msg_id_of(m) -> int:
    """Return the message's session-scoped id, tolerating both key names."""
    if not isinstance(m, dict):
        return 0
    v = m.get("_msg_id")
    if v is None:
        v = m.get("id", 0)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _update_last_msg_id(session_id: str, msg_id: int) -> bool:
    """Advance the session-level self-improvement cursor.

    Always advances (monotonic) regardless of write count, so empty turns
    don't re-send the same messages to the LLM on the next turn.
    """
    if not session_id or not msg_id:
        return False
    try:
        with sync_conn() as conn:
            conn.execute(
                "UPDATE sessions SET last_processed_msg_id = ? "
                "WHERE id = ? AND last_processed_msg_id < ?",
                (msg_id, session_id, msg_id)
            )
        return True
    except Exception as e:
        LOG.debug("_update_last_msg_id failed: %s", e)
        return False


def _append_session_summary(session_id: str, content: str,
                            new_messages: "Optional[list[dict]]" = None,
                            from_msg_id: int = 0, to_msg_id: int = 0) -> bool:
    """Append a tier-1 row to the session_summary_log (the lossless chapter log).

    Rides the existing User Understanding LLM pass — no extra call. This is the
    append-only source of truth for warm-start continuity; tier-2 recompaction
    later condenses these rows into ``sessions.summary`` and flips ``compacted``.

    Takes the ``new_messages`` window so the from/to msg-id span covers the
    whole batch this summary describes; falls back to explicit ids when the
    window isn't available. Never touches ``sessions.summary`` (derived) — it
    only appends the raw log row.
    """
    if not session_id or not content:
        return False
    if new_messages:
        from_msg_id = _msg_id_of(new_messages[0]) if new_messages else 0
        to_msg_id = _msg_id_of(new_messages[-1]) if new_messages else 0
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO session_summary_log "
                "(session_id, from_msg_id, to_msg_id, content, compacted) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, from_msg_id, to_msg_id, content, False),
            )
        return True
    except Exception as e:
        LOG.debug("_append_session_summary failed: %s", e)
        return False


# Chapters this process already appended, keyed ``(session_id, sha1(body))``.
# The compressor carries its summary forward in ``_previous_summary``, folding
# each round of new turns into the prior text — so a second compaction in the
# same process yields MATERIALLY DIFFERENT text, not a duplicate. Keying on the
# body digest appends the newer chapter while still collapsing a genuine
# same-text repeat (e.g. two boundary notifications for one compaction).
# Module-global on purpose — ``self_improvement`` is a singleton import.
_COMPRESSION_APPENDED_KEYS: "set[tuple[str, str]]" = set()

# Upper bound on a chapter body. The handoff summary is already compact; the cap
# only guards a pathological/streamed response from bloating the log. Generous
# because tier-2 condenses this to a ~300-char brief, and a truncated chapter
# loses detail that is never recoverable downstream.
_COMPRESSION_CHAPTER_CAP = 30000


def _append_compression_summary(session_id: str, content: str) -> bool:
    """Tier-1 chapter append at a COMPACTION boundary.

    Routes the compressor's already-generated handoff summary into
    ``session_summary_log`` so the chain of summaries survives repeated
    compactions. ``archive_and_compact`` soft-archives the ``messages`` rows on
    every pass — including the previous handoff summary, which rides among them
    as a ``user``/``assistant`` row — but it NEVER touches this log, so
    chapter N is still on disk when compression N+1 archives the live copy.

    Two safety properties this exists to preserve:

    * ZERO new LLM calls — the summary text already exists; we only persist it.
    * ZERO new ``messages`` rows — this writes a flat append-only log with no
      ``role`` column and no ordering, so it cannot perturb transcript
      sequencing or replay. The stall class (a synthetic user/assistant row
      landing at the wrong point in the sequence) is structurally unreachable
      from here.

    Deduped on ``(session_id, sha1(body))`` so a re-notified boundary does not
    double-append while a genuinely newer chapter still lands.

    Returns True when a row was written, False when skipped (empty input,
    already appended this process) or on error.
    """
    if not session_id or not content:
        return False
    body = content.strip()[:_COMPRESSION_CHAPTER_CAP]
    if not body:
        return False
    # Validate BEFORE claiming: a whitespace-only summary must not poison the
    # session's slot for the rest of the process.
    key = (session_id, hashlib.sha1(body.encode("utf-8")).hexdigest())
    if key in _COMPRESSION_APPENDED_KEYS:
        return False
    _COMPRESSION_APPENDED_KEYS.add(key)
    try:
        with sync_conn() as conn:
            conn.execute(
                "INSERT INTO session_summary_log "
                "(session_id, from_msg_id, to_msg_id, content, compacted) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, None, None, body, False),
            )
        LOG.info(
            "compression chapter appended: session=%s chars=%d",
            session_id, len(body),
        )
        return True
    except Exception as e:
        LOG.debug("_append_compression_summary failed: %s", e)
        return False


_TURN_GAP_POOL: "list[int]" = []
"""Freed PG ``id`` slots from the current turn's tool-flow collapse.

Populated by ``run_self_improvement`` from the ``gap_ids`` the summarizer
returns. Message-row writers (``_log_coaching`` / ``_store_raw_prose``) claim
a slot from this pool so their ``role='tool'`` rows land INSIDE the turn gap
(between the tool_flow_summary and the final response) instead of appending
at the tail. When the pool is empty they fall back to ``MAX(message_id)+1``.

Single-threaded by design: ``run_self_improvement`` runs on the turn-finalize
path after ``summarize_tool_flow``, so only this process's writers consume it.
It is a plain module global (not thread-local) — the writers are only ever
called from within a ``run_self_improvement`` execution window, so there is no
cross-turn leakage.
"""


def _claim_gap_id() -> "int | None":
    """Claim the next freed turn-gap id, or None if the pool is exhausted.

    Returns None (→ caller falls back to the tail) whenever the gap doesn't
    have a free slot, so we NEVER place a row inside the turn at the wrong
    order when there's no room.
    """
    if _TURN_GAP_POOL:
        return _TURN_GAP_POOL.pop(0)
    return None


def _set_turn_gap_pool(gap_ids: "list[int] | None") -> None:
    """Replace the turn-gap id pool for this run (sorted ascending, oldest first)."""
    global _TURN_GAP_POOL
    _TURN_GAP_POOL = list(gap_ids or [])


def _get_oracle_context(session_id: str) -> str:
    """Get the oracle_context from the most recent coaching entry for this session."""
    try:
        with sync_conn() as conn:
            row = conn.fetchone(
                "SELECT oracle_context FROM coaching WHERE session_id = ? AND oracle_context != '' ORDER BY created_at DESC LIMIT 1",
                (session_id,)
            )
            return row["oracle_context"] if row else ""
    except Exception as e:
        LOG.debug("_get_oracle_context failed: %s", e)
        return ""


def _build_oracle_context(user_json: dict | None, agent_json: dict | None) -> str:
    """Build a compact summary of what was extracted this turn for the next coaching call."""
    parts = []

    if user_json:
        user = user_json.get("user", {})
        corrections = user.get("corrections", [])
        prefs = user.get("preferences", [])
        topics = user.get("topics", [])
        state = user.get("state", {})
        if corrections:
            parts.append(f"corrections: {', '.join(c['name'] for c in corrections if c.get('name'))}")
        if prefs:
            parts.append(f"prefs: {', '.join(p['name'] for p in prefs if p.get('name'))}")
        if topics:
            parts.append(f"topics: {', '.join(t['name'] for t in topics if t.get('name'))}")
        if state:
            parts.append(f"mood: {state.get('headspace', '')}")

    if agent_json:
        agent = agent_json.get("agent", {})
        coaching = agent.get("coaching", "")
        active_corrections = agent.get("active_corrections", [])
        learned_patterns = agent.get("learned_patterns", [])
        growth = agent.get("growth", [])
        patterns = agent.get("patterns", [])
        signals = agent.get("signals", [])
        reflections = agent.get("reflections", [])
        if coaching:
            parts.append(f"coached: {coaching[:80]}")
        if active_corrections:
            parts.append(f"corrections: {', '.join(c['name'] for c in active_corrections if c.get('name'))}")
        if learned_patterns:
            parts.append(f"patterns: {', '.join(p['name'] for p in learned_patterns if p.get('name'))}")
        if growth:
            parts.append(f"growth: {', '.join(g['content'][:60] for g in growth if g.get('content'))}")
        if patterns:
            parts.append(f"patterns: {', '.join(p['name'] for p in patterns if p.get('name'))}")
        if signals:
            parts.append(f"signals: {', '.join(s['trigger'][:40] for s in signals if s.get('trigger'))}")
        if reflections:
            parts.append(f"reflections: {len(reflections)} new")

    return " | ".join(parts) if parts else ""


def _update_coaching_context(session_id: str, context: str) -> bool:
    """Update the oracle_context on the most recent coaching entry."""
    if not session_id or not context:
        return False
    try:
        with sync_conn() as conn:
            conn.execute(
                "UPDATE coaching SET oracle_context = ? WHERE session_id = ? AND id = (SELECT MAX(id) FROM coaching WHERE session_id = ?)",
                (context, session_id, session_id)
            )
        return True
    except Exception as e:
        LOG.debug("_update_coaching_context failed: %s", e)
        return False


# ── Main entry point ─────────────────────────────────────────────────────


def run_state_sync(agent, messages_snapshot: list, gap_ids: "list[int] | None" = None) -> int:
    """Decoupled turn-end state sync — pulse/active/loops/turn_quality.

    Runs on EVERY turn end (not the nudge boundary) so operational state
    never goes stale and is never hostage to a legacy nudge_cadence knob.
    Reads the CURRENT turn's collapsed snapshot (after the tool-flow
    summarizer) so it gets the condensed summary of that turn — the exact
    window the user asked for.

    This is a SEPARATE LLM pass from User Understanding. It does NOT touch
    the shared ``last_processed_msg_id`` cursor, so the nudge-gated User
    Understanding still reads the full accumulated backlog on its boundary.
    The two are fully decoupled: state-sync = every turn end, cheap;
    User Understanding = nudge boundary, full backlog.

    Returns the number of state writes (0 on no-op / failure). Best-effort —
    a failure here never breaks the turn.
    """
    if _circuit_open():
        _COUNTERS["skipped_budget"] += 1
        return 0

    session_id = getattr(agent, "session_id", "")
    if not session_id:
        return 0

    # Seed the turn-gap pool so any coach/raw-prose rows land in-order.
    _set_turn_gap_pool(gap_ids)

    # Bound to THIS turn's window (most recent user anchor → end), so the
    # state snapshot reflects the current turn, not the rolling backlog.
    turn_window = _bound_to_turn(messages_snapshot)
    if not turn_window:
        return 0

    # Thread the recalled knowledge ids + hard rules into the prompt so the
    # LLM can judge context_usage and never contradict standing law.
    _state_prompt = _STATE_PROMPT
    _recalled_ids = getattr(agent, "_last_recalled_knowledge_ids", None) or []
    if _recalled_ids:
        _id_list = ", ".join(str(i) for i in _recalled_ids)
        _state_prompt = (
            _STATE_PROMPT
            + "\n\n[Injected JPM context breadcrumbs this turn — judge each as used/stale in context_usage]\n"
            + f"ids: {_id_list}"
        )
    _hard_rules = _fetch_hard_rules(max_chars=100)
    if _hard_rules:
        _state_prompt = (
            _state_prompt
            + "\n\n[Standing HARD RULES (entity_type=rule, weightage >= 0.80) — "
            + "these are always injected into the agent's context. If you author a "
            + "breadcrumb with entity_type=rule it MUST NOT contradict any rule listed "
            + "here, and MUST NOT duplicate an existing rule. Prefer memory_entry (a "
            + "fact/lesson) over rule (standing law) when unsure. Rules that merely restate "
            + "or soften an existing hard rule are forbidden.]\n"
            + _hard_rules
        )

    state_json = _call_structured(
        agent, turn_window, _state_prompt,
        system_prompt=_STATE_SYSTEM_PROMPT,
        loop_name="self_impr_state",
        max_content_chars=100,
    )
    if not state_json:
        _COUNTERS["empty_extractions"] += 1
        LOG.info("state sync → no signal detected")
        return 0

    if "_raw" in state_json:
        writes = _store_raw_prose(state_json, session_id, "state")
    else:
        writes = _parse_state_json(state_json, session_id)
    _COUNTERS["writes"] += writes
    LOG.info("state sync → %d writes", writes)
    return writes


def run_self_improvement(agent, messages_snapshot: list, review_memory: bool = False,
                          review_skills: bool = False, sync_state: bool = True,
                          gap_ids: "list[int] | None" = None) -> tuple:
    """Run self-improvement: structured LLM calls → PG tables.

    Replaces the old background_review.py fork-a-daemon approach.

    Incremental: only passes messages after last_msg_id to the LLM,
    so coaching doesn't re-summarize the entire session every turn.

    State sync (pulse/active/loops) is DECOUPLED from this function — it
    runs as its own turn-end pass (run_state_sync) on EVERY turn end, not
    the nudge boundary. This function handles the costlier memory/skill
    extraction (User Understanding + Agent Growth), gated by the nudge
    intervals + min-new-messages threshold. The `sync_state` param is
    retained for backward compatibility but is a no-op — state-sync no
    longer rides this path.

    Args:
        agent: The AIAgent instance
        messages_snapshot: Full conversation history
        review_memory: Whether to run user understanding
        review_skills: Whether to run agent growth
        sync_state: Deprecated no-op (state-sync is decoupled to run_state_sync)
        gap_ids: Freed PG ``id`` slots from this turn's tool-flow collapse
            (returned by ``summarize_tool_flow``). Message-row writers claim
            these so their rows land inside the turn gap instead of at the
            tail, keeping transcript order chronological.

    Returns:
        (total_writes, llm_calls, skills_created, user_writes, agent_writes,
         coach_writes)
        tuple. user_writes/agent_writes split the memory vs growth writes so
        the turn-finalizer can render them under separate icons; coach_writes
        counts coaching lines stored for next-turn injection (the 👤 icon).
    """
    # Seed the turn-gap pool from this turn's collapse. The writers claim
    # freed ids from it; cleared at the end so no slot leaks into the next turn.
    _set_turn_gap_pool(gap_ids)
    # Circuit breaker: if we've been failing repeatedly, skip entirely
    # for the cooldown window instead of firing LLM calls per turn.
    if _circuit_open():
        _COUNTERS["skipped_budget"] += 1
        LOG.warning("♻️ circuit breaker open — skipping self-improvement")
        return (0, 0, 0, 0, 0, 0, 0)

    # Re-entrancy guard: run_conversation() → finalize_turn() would check
    # _should_review_memory/_should_review_skills again and loop forever.
    # Set flags to False before calling LLM, restore after.
    saved_memory_nudge = getattr(agent, "_memory_nudge_interval", 0)
    saved_skill_nudge = getattr(agent, "_skill_nudge_interval", 0)
    agent._memory_nudge_interval = 0
    agent._skill_nudge_interval = 0

    total_writes = 0
    llm_calls = 0
    state_writes = 0
    session_id = getattr(agent, "session_id", "")

    LOG.info("Starting (review_memory=%s, review_skills=%s, sync_state=%s)",
             review_memory, review_skills, sync_state)

    # ── Incremental: only pass new messages since last coaching ──────────
    last_msg_id = _get_last_msg_id(session_id)
    # The nudge redesign (2026-08-26) sources the extractor window from the
    # DB backlog of REAL turns since the last cursor (not the live turn), so
    # a batch of user turns between nudge boundaries is harvested together.
    # Fall back to the live snapshot's filtered new messages if the DB query
    # returns nothing.
    new_messages = _fetch_session_window(session_id, last_msg_id)
    if not new_messages:
        _snap_new = _filter_new_messages(messages_snapshot, last_msg_id)
        new_messages = _bound_to_turn(_snap_new)
    new_count = len(new_messages) if new_messages else 0
    LOG.info("oracle: %d msgs SENT to LLM (cursor #%d, DB-windowed)",
             new_count, last_msg_id)

    # If no new messages, skip LLM calls entirely
    if new_count == 0:
        LOG.info("🤖 oracle: no new messages since last coaching — skipping")
        agent._memory_nudge_interval = saved_memory_nudge
        agent._skill_nudge_interval = saved_skill_nudge
        return (0, 0, 0, 0, 0, 0, 0)

    # ── Turn-batch anchor for coach inserts ──────────────────────────────
    # The last message_id of THIS turn's batch. Both _store_raw_prose and
    # _log_coaching use it to place their role='tool' coach row at
    # anchor+1 — in-order inside this turn's range — instead of racing
    # MAX(message_id)+1 against a live append from the NEXT turn. This is
    # the same message range turn-flow already passed to us; we just anchor
    # to its end rather than re-querying the live table.
    _anchor_mid = _msg_id_of(new_messages[-1]) if new_messages else 0

    # ── State sync (pulse/active/loops) — DECOUPLED ────────────────────
    # State-sync no longer rides this function. It runs as its OWN turn-end
    # pass (run_state_sync) on EVERY turn end, so pulse/active/loops refresh
    # independently of the nudge boundary. This function handles only the
    # costlier memory/skill extraction (User Understanding + Agent Growth).

    # ── Cost gate for memory/skill extraction ───────────────────────────
    # Prevents two full-model calls per turn on trivial traffic. Threshold
    # is configurable via agent.self_impr_min_new_messages (default 2).
    min_new = int(getattr(agent, "self_impr_min_new_messages", 2) or 0)
    if new_count < min_new:
        LOG.info("🤖 oracle: only %d new msgs (min %d) — skipping memory/skill extraction",
                 new_count, min_new)
        # Advance the cursor so state sync doesn't re-process the same
        # messages on the next turn.
        if new_messages:
            _update_last_msg_id(session_id, _msg_id_of(new_messages[-1]))
        _record_success()
        agent._memory_nudge_interval = saved_memory_nudge
        agent._skill_nudge_interval = saved_skill_nudge
        return (total_writes, llm_calls, 0, 0, 0, 0, 0)

    # ── Chain: pass previous oracle context so coaching knows what it already learned ──
    prev_context = _get_oracle_context(session_id)
    #if prev_context:
    #    LOG.info("🤖 oracle: previous context: %s", prev_context[:120])

    # Build coaching prompt with previous context
    coaching_prompt = _AGENT_GROWTH_PROMPT
    if prev_context:
        coaching_prompt = (
            "[Previous oracle context — what was already extracted in prior turns]\n"
            f"{prev_context}\n\n"
            "---\n\n"
            + _AGENT_GROWTH_PROMPT
        )

    # Call 1: User Understanding
    user_json = None
    user_writes = 0
    if review_memory:
        llm_calls += 1
        _COUNTERS["calls"] += 1
        try:
            # Thread the recalled knowledge ids (stashed at the injection
            # site in run.py) into the prompt so the LLM can judge which
            # breadcrumbs were used vs stale this turn (context_usage).
            _user_prompt = _USER_UNDERSTANDING_PROMPT
            _recalled_ids = getattr(agent, "_last_recalled_knowledge_ids", None) or []
            if _recalled_ids:
                _id_list = ", ".join(str(i) for i in _recalled_ids)
                _user_prompt = (
                    _USER_UNDERSTANDING_PROMPT
                    + "\n\n[Injected JPM context breadcrumbs this turn — judge each as used/stale in context_usage]"
                    + f"\nids: {_id_list}"
                )
            # Feed the hard rules (always-on directives) so any NEW rule this
            # turn can never contradict them. Only entity_type='rule' rows with
            # weightage >= 0.80 are injected every turn (the standing law).
            _hard_rules = _fetch_hard_rules(max_chars=100)
            if _hard_rules:
                _user_prompt = (
                    _user_prompt
                    + "\n\n[Standing HARD RULES (entity_type=rule, weightage >= 0.80) — "
                    + "these are always injected into the agent's context. If you author a "
                    + "breadcrumb with entity_type=rule it MUST NOT contradict any rule listed "
                    + "here, and MUST NOT duplicate an existing rule. Prefer memory_entry (a "
                    + "fact/lesson) over rule (standing law) when unsure. Rules that merely restate "
                    + "or soften an existing hard rule are forbidden.]\n"
                    + _hard_rules
                )
            user_json = _call_structured(agent, new_messages, _user_prompt, loop_name="self_impr_user")
            if user_json:
                # Tier-1 session summary — top-level field, ALWAYS present even
                # when user is {}. Append it to the lossless chapter log,
                # independent of whether knowledge extraction wrote anything.
                _summary = (user_json.get("session_summary") or "").strip()
                if _summary:
                    if _append_session_summary(session_id, _summary, new_messages=new_messages):
                        _COUNTERS["writes"] += 1
                if "_raw" in user_json:
                    # Model returned prose, not JSON — store it as a readable
                    # reflection so the agent can see the summary.
                    writes = _store_raw_prose(user_json, session_id, "user", anchor_mid=_anchor_mid)
                    state_writes = 0
                else:
                    writes, state_writes = _parse_user_json(user_json, session_id)
                user_writes += writes
                total_writes += writes
                _COUNTERS["writes"] += writes
                LOG.info("user understanding → %d writes (%d state-sync)", writes, state_writes)
            else:
                _COUNTERS["empty_extractions"] += 1
                LOG.info("user understanding → no signal detected")
        except Exception as e:
            LOG.warning("user understanding failed: %s", e, exc_info=True)
            _record_failure("db_failures")

    # Call 2: Agent Growth
    agent_json = None
    agent_writes = 0
    coach_writes = 0
    # DISABLED (2026-08-25): the OOB agent-growth ("oracle") LLM round-trip is
    # being moved inband to a self_impr tool the agent fires itself, alongside
    # state sync. Flip _AGENT_GROWTH_ENABLED back to True to restore the OOB
    # path. The nudge-gated review_skills flag is still honored when enabled.
    if _AGENT_GROWTH_ENABLED and review_skills:
        llm_calls += 1
        _COUNTERS["calls"] += 1
        try:
            agent_json = _call_structured(agent, new_messages, coaching_prompt, loop_name="self_impr_agent")
            if agent_json:
                if "_raw" in agent_json:
                    # Model returned prose, not JSON — store it as a readable
                    # reflection so the agent can know the summary.
                    writes = _store_raw_prose(agent_json, session_id, "agent", anchor_mid=_anchor_mid)
                else:
                    writes, coach_writes = _parse_agent_json(agent_json, session_id)
                agent_writes += writes
                total_writes += writes
                _COUNTERS["writes"] += writes
                LOG.info("agent growth → %d writes", writes)
            else:
                _COUNTERS["empty_extractions"] += 1
                LOG.info("agent growth → no signal detected")
        except Exception as e:
            LOG.warning("agent growth failed: %s", e, exc_info=True)
            _record_failure("db_failures")

    # Build and store oracle context for next turn
    oracle_context = _build_oracle_context(user_json, agent_json)
    if oracle_context:
       # LOG.info("oracle: storing context for next turn: %s", oracle_context[:120])
        _update_coaching_context(session_id, oracle_context)

    # Update last_msg_id to the latest message we processed.
    # Always advance (regardless of write count) so empty/no-signal turns
    # don't re-send the same messages to the LLM on the next turn.
    if new_messages:
        _update_last_msg_id(session_id, _msg_id_of(new_messages[-1]))

    # Mark user_says as processed
    if total_writes > 0 and session_id:
        _mark_heartbeat_processed(session_id)

    # NOTE (2026-10-09): auto-promotion of high-confidence patterns to skills
    # was UNWIRED. It wrote flat .md files into $HERMES_HOME/skills/auto/ from
    # every patterns row with confidence >= 0.85 — including junk intent_*
    # patterns — producing bogus loadable skills. Skill creation is now
    # agent-authored in-band via skill_manage (see conversation_loop.py).

    # Cheap on-turn housekeeping: archive stale coaching/signals/patterns.
    # Runs ~1/day (guarded by a wall-clock check) so it never adds latency.
    _maybe_archive_stale()

    # A clean run resets the failure streak for the circuit breaker.
    _record_success()

    #LOG.info("done — %d total writes", total_writes)

    # Restore nudge intervals
    agent._memory_nudge_interval = saved_memory_nudge
    agent._skill_nudge_interval = saved_skill_nudge

    return (total_writes, llm_calls, 0, user_writes, agent_writes, coach_writes, state_writes)


def _get_counters() -> dict:
    """Return a snapshot of the observability counters (for logging/metrics)."""
    return dict(_COUNTERS)


# Last wall-clock day we ran archival (module-level, resets on restart — fine,
# worst case archival runs once more than strictly needed).
_last_archive_day = 0


def _maybe_archive_stale() -> None:
    """Run _archive_stale at most once per wall-clock day."""
    global _last_archive_day
    day = int(time.time() // 86400)
    if day == _last_archive_day:
        return
    _last_archive_day = day
    _archive_stale()


def _archive_stale() -> int:
    """Archive stale coaching rows and low-fired signals/patterns.

    Cheap on-turn housekeeping so long-lived sessions don't pollute
    retrieval. Returns the number of rows archived.
    """
    archived = 0
    try:
        with sync_conn() as conn:
            # Coaching rows older than 7 days → delete (transient, next-turn only)
            cutoff = time.time() - (7 * 86400)
            cur = conn.execute(
                "DELETE FROM coaching WHERE created_at < ?", (cutoff,)
            )
            archived += cur.rowcount if hasattr(cur, "rowcount") else 0

            # Signals never fired / stale → disable (soft archive)
            cur = conn.execute(
                "UPDATE signals SET enabled = 0 WHERE enabled = 1 AND created_at < ?",
                (cutoff,)
            )
            archived += cur.rowcount if hasattr(cur, "rowcount") else 0

            # Patterns with low confidence and old last_fired → archive
            cur = conn.execute(
                "UPDATE patterns SET archived = 1 WHERE archived = 0 "
                "AND confidence < 0.4 AND last_fired < ?",
                (cutoff,)
            )
            archived += cur.rowcount if hasattr(cur, "rowcount") else 0
        if archived:
            LOG.info("archived %d stale self-improvement rows", archived)
        return archived
    except Exception as e:
        LOG.debug("_archive_stale failed: %s", e)
        return 0


def _promote_high_conf_patterns() -> None:
    """Promote patterns with confidence >= 0.85 to skills.

    High-confidence patterns represent proven approaches that should be
    available as skills every turn. Low-confidence patterns stay in the
    JPM cache as "approaches that worked before."
    """
    try:
        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT name, description, pattern_type, confidence, times_fired "
                "FROM patterns WHERE archived = 0 AND confidence >= 0.85 "
                "ORDER BY confidence DESC"
            )
    except Exception:
        LOG.debug("_promote_high_conf_patterns: DB query failed", exc_info=True)
        return

    if not rows:
        return

    import os
    import yaml
    from jpm.core._paths import _get_agent_home

    skills_dir = os.path.join(_get_agent_home(), "skills", "auto")
    os.makedirs(skills_dir, exist_ok=True)

    for row in rows:
        name = row["name"]
        desc = row["description"] or f"Auto-promoted pattern: {name}"
        ptype = row.get("pattern_type", "approach")
        confidence = row.get("confidence", 0.85)
        times_fired = row.get("times_fired", 1)

        skill_path = os.path.join(skills_dir, f"{name}.md")
        if os.path.exists(skill_path):
            continue  # Already promoted

        # Build SKILL.md
        frontmatter = {
            "name": name,
            "description": desc,
            "type": ptype,
            "confidence": round(confidence, 2),
            "times_fired": times_fired,
            "auto_promoted": True,
        }
        body = f"""# {name}

{desc}

## When to use

This pattern was auto-promoted from the patterns table when confidence reached 0.85+.

## Notes

- Pattern type: {ptype}
- Confidence: {confidence:.2f}
- Times fired: {times_fired}
"""

        try:
            with open(skill_path, "w") as f:
                f.write("---\n")
                yaml.dump(frontmatter, f, default_flow_style=False)
                f.write("---\n")
                f.write(body)
            LOG.info("promoted pattern '%s' → skill (conf=%.2f, fired=%d)",
                     name, confidence, times_fired)
        except Exception as e:
            LOG.warning("failed to promote pattern '%s': %s", name, e)


__all__ = [
    "run_self_improvement",
    "_USER_UNDERSTANDING_PROMPT",
    "_AGENT_GROWTH_PROMPT",
    "_upsert_topic",
    "_log_small_talk",
    "_log_growth",
    "_upsert_pattern",
    "_create_signal",
    "_get_counters",
    "_archive_stale",
]

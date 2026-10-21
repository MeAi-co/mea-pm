"""
Query planner for multi-topic context recall — repurposed from the old
FTS5 `smart_refine` loop (core/tools/_smart_refine.py).

The old smart_refine was *reactive*: it ran an FTS5 search, judged the
results poor, then asked the LLM to fix the query. Now that pgvector does
a decent job on single-topic queries, that loop is a dead leg for basic
searches. We reuse its LLM plumbing (DeepSeek Flash via local Ollama,
context fetching, JSON parsing) and flip it from reactive to *proactive*:

  - Classify the user message type so heavy recall is only spent where it
    pays (skip banter / emotional / intimate messages entirely).
  - For multi-topic work messages, plan 3-6 self-contained, scope-aware
    vector queries (individual topics + a few combined ones) so the single
    paragraph isn't crushed into one diluted query vector.

This module is the consumer of the shared helpers. It does NOT re-implement
them. The old FTS5 loop stays in the search tools but is config-gated off.
"""

import json
import logging
import re
from datetime import datetime

from jpm.core._smart_refine import (
    _call_refinement_llm,
    _get_config,
)

logger = logging.getLogger(__name__)

# Message types that do NOT need heavy recall. Injecting KFT context into a
# vulnerable "it just hurts" moment is actively wrong, not just wasteful.
_LIGHT_TYPES = {"banter", "emotional", "intimate", "smalltalk", "sos"}

# ── cheap light-type gate ───────────────────────────────────────────────
# The LLM planner only classifies a message as light when it ALSO looks
# multi-topic (long + shift markers). A single emotional statement like
# "it just hurts" is short and single-topic, so it never reaches the planner
# and the single-vector fast path sweeps the raw message for context —
# injecting KFT noise into a vulnerable moment. This cheap, non-LLM gate
# catches that common case BEFORE the multi-topic gate, so short emotional /
# banter / intimate messages skip recall entirely without paying for an LLM.
# Affective markers are deliberately PHRASE-LEVEL, not bare single adjectives.
# A bare "sad" / "tired" / "exhausted" is too ambiguous for a pre-LLM gate that
# decides whether to drop ALL recall ("tired of the memory leak", "the service
# is exhausted" are work queries). Every meaningful emotional state has a
# self-referential phrase form ("i'm sad", "i'm tired", "it hurts") which is
# unambiguous, so the bare single-word forms are intentionally omitted.
_LIGHT_MARKERS = (
    "it just hurts", "it hurts", "just hurts", "i'm sad", "im sad",
    "i'm tired", "im tired", "i'm exhausted", "im exhausted", "i'm done",
    "im done", "i miss you", "i love you", "miss you", "love you",
    "i hate", "i'm scared", "im scared", "i'm anxious", "im anxious",
    "i'm lonely", "im lonely", "i'm crying", "im crying", "i feel like shit",
    "i feel like garbage", "i feel like trash", "i can't do this",
    "i can't anymore", "i can't", "i cant", "fuckin", "fucking",
    "bait game", "lol", "lmao", "haha", "hehe", "babe", "baby",
    "kiss", "hug me", "hold me", "cuddle",
    "burned out", "burnt out",
)

# Safety valve: if a short message ALSO carries work intent, do NOT classify
# it as light — a real query like "I'm tired, what's the port?" must still
# get recall. These markers win over the emotional ones.
_WORK_QUERY_MARKERS = (
    "what", "how", "where", "when", "why", "which", "status", "port",
    "fix", "build", "prepare", "check", "need", "want", "can you",
    "please", "setup", "set up", "config", "deploy", "run", "test",
    "error", "bug", "commit", "push", "pull", "schema", "table",
)

# Technical nouns / verb phrases that override even a genuine emotional phrase.
# "i'm sad about the prod failure" and "im tired of restarting postgres" are
# WORK messages despite carrying an emotion word — these must not be dropped.
# This closes the gap the phrase-tightening (option 1) can't: it vetoes the
# emotional classification entirely when real technical content co-occurs.
_DOMAIN_NOUNS = (
    "memory", "service", "services", "prod", "production", "postgres",
    "restart", "restarting", "deploy", "deployment", "failure", "crash",
    "server", "database", "db ", "query", "schema", "migration", "bug",
    "error", "exception", "log", "config", "endpoint", "api", "request",
    "response", "latency", "queue", "worker", "cache", "index", "table",
    "column", "row", "container", "docker", "kubernetes", "cluster", "node",
    "pipeline", "script", "function", "class", "variable", "import",
    "compile", "syntax", "stack", "traceback", "thread", "process", "pid",
    "port", "socket", "connection", "timeout", "ssl", "auth", "token",
    "key", "secret", "env", "variable", "package", "dependency", "version",
)


# Terse affirmatives / confirmations. A bare "sure", "ok", "yes", "go" is a
# direct answer to a pending question — recall on it is pure noise and can
# actively mislead (the loudest recent breadcrumb hijacks a one-word answer,
# as happened with the "sure" → re-ask failure). These skip recall entirely.
# The work-marker / domain-noun vetoes below still apply, so "sure, what's
# the port?" keeps recall.
_TERSE_CONFIRMATIONS = (
    "sure", "ok", "okay", "yes", "yep", "yeah", "yup", "go", "do it",
    "go ahead", "fine", "alright", "right", "got it", "roger", "affirmative",
    "sounds good", "perfect", "great", "thanks", "thank you", "thx", "ty",
    "done", "good", "cool", "nice", "awesome", "agreed", "correct",
)


def looks_light(message: str, max_len: int = 120) -> bool:
    """Cheap, non-LLM gate. Returns True for short emotional / banter /
    intimate / terse-confirmation messages so recall can be skipped entirely.

    Conservative by design: only fires on a strong affective PHRASE within a
    short message AND no work-intent marker AND no technical noun. Bare
    single-word emotions ("tired", "sad") are intentionally not markers, and
    domain nouns ("prod", "postgres", "deploy") veto any emotional phrase, so
    real short work queries ("tired of the memory leak", "i'm sad about the
    prod failure") are never caught. Terse affirmatives ("sure", "ok", "yes")
    also skip recall — a one-word answer to a pending question must not be
    hijacked by the loudest recent breadcrumb. The LLM planner remains the
    authoritative classifier for longer messages; this just catches the
    common short emotional / confirmation case without an LLM call.
    """
    text = (message or "").strip()
    if not text or len(text) > max_len:
        return False
    lower = " " + text.lower() + " "
    for w in _WORK_QUERY_MARKERS:
        if w in lower:
            return False
    for n in _DOMAIN_NOUNS:
        if n in lower:
            return False
    # Terse confirmation: short (<=3 words) pure affirmative with no work
    # intent and no technical noun → skip recall. This is the fix for the
    # "sure" re-ask failure.
    words = text.split()
    if len(words) <= 3 and lower.strip() in _TERSE_CONFIRMATIONS:
        return True
    for marker in _LIGHT_MARKERS:
        if marker in lower:
            return True
    return False

# ── cheap gate: does this look multi-topic at all? ──────────────────────
# Runs BEFORE any LLM call so short / single-topic messages keep the fast
# single-vector path with zero added latency.
# Strong markers are unambiguous topic shifts — a single one means a second
# topic. Weak markers ("also", "plus", "as well") are common connectives that
# appear WITHIN one topic all the time, so they only count when 2+ distinct
# ones co-occur (a genuine multi-clause message).
_TOPIC_SHIFT_MARKERS_STRONG = (
    " the other thing",
    " the other one",
    " on top of that",
    " meanwhile",
    " separately",
)
_TOPIC_SHIFT_MARKERS_WEAK = (
    " also ",
    " plus ",
    " and also ",
    " another ",
    " as well",
)
_TOPIC_SHIFT_MARKERS = _TOPIC_SHIFT_MARKERS_STRONG + _TOPIC_SHIFT_MARKERS_WEAK


def looks_multi_topic(message: str, min_len: int = 140) -> bool:
    """Cheap, non-LLM gate. Returns True only if the message is long enough
    to plausibly hold several topics AND shows topic-shift markers.

    This keeps the common case (short queries, single-topic messages) on the
    existing fast path — we never pay for an LLM planner call unless there's
    a real chance the message is multi-topic.
    """
    text = (message or "").strip()
    if len(text) < min_len:
        return False
    lower = " " + text.lower() + " "
    # Strong markers are unambiguous topic shifts — a single one means a
    # genuine second topic.
    for marker in _TOPIC_SHIFT_MARKERS_STRONG:
        if marker in lower:
            return True
    # Weak markers ("also", "plus", "as well") are common connectives within
    # ONE topic. They only signal multi-topic when 2+ DISTINCT ones co-occur
    # (a genuinely multi-clause message). A lone "also" near the start is the
    # classic false positive — firing the LLM planner on it wastes 1-2s
    # recalling context already in the conversation.
    weak_hits = 0
    for marker in _TOPIC_SHIFT_MARKERS_WEAK:
        if marker in lower:
            weak_hits += 1
    if weak_hits >= 2:
        return True
    # Fallback: 3+ newline-separated clauses, or 3+ sentence fragments
    # separated by ". " — a paragraph that jumps around.
    if text.count("\n") >= 3:
        return True
    if len(re.findall(r"[.!?]\s+[A-Z]", text)) >= 3:
        return True
    return False


# ── planner prompt ───────────────────────────────────────────────────────
PLANNER_SYSTEM_PROMPT = """You are a smart query planner for a semantic context recall system. Your job is to turn a user's message into the multiple search queries that will retrieve the most relevant stored context from the Knowledge table, which stores breadcrumbs distilled from past user conversation.

## Your Input
You receive:
1. The user's message (what they just said).
2. The previous 2-3 user messages (with timestamps) so you know the current conversational scope.

## Your Output
Respond with a JSON object, no prose, no markdown:

{
  "type": "<one of: query | task | discussion | logistics | banter | emotional | intimate | smalltalk | other>",
  "queries": ["...", "...", "..."]
}

## Rules for "type"
- `query` = direct question wanting an answer ("what are the equipment rules on flydubai?")
- `task` = "prepare X", "build X", "do X" (work / execution intent)
- `discussion` = exploring an idea, "how to...", "what if..."
- `logistics` = planning trips, tickets, hotels, bookings
- `banter` / `emotional` / `intimate` / `smalltalk` = NOT work. If the message is casual venting, emotional sharing, playful banter, or intimate — set type to that and return `"queries": []`. Heavy context recall is wrong for these.

## Rules for "queries" (only when type is work: query/task/discussion/logistics)
- Emit 3-6 queries. Each must be a SELF-CONTAINED natural-language phrase, not a bare keyword or topic name.
- SCOPE every query to the context of the message (location, project, person, timeframe). E.g. "models agencies in Budapest for shoots", NOT just "models agencies" — so recall doesn't pull Dubai/GE/India noise.
- Include 1-2 COMBINED queries that capture the intersection when two topics clearly belong together (e.g. "Budapest models agencies").
- Queries are for VECTOR search — use natural language, not boolean operators.
- Do not invent facts. Only reflect what the message actually references.

## Example
Message: "I could use agency contacts for experienced models for shoots, and also need to prepare a KFT business plan before I go."
Response:
```json
{
  "type": "task",
  "queries": [
    "models agencies in Budapest for photoshoots",
    "KFT business plan for Hungarian company setup",
    "Budapest models agencies contact directory"
  ]
}
```
"""


# ── parsing ──────────────────────────────────────────────────────────────
def _parse_planner_response(raw: str | None) -> dict:
    """Parse the LLM's plan into {"type": ..., "queries": [...]}.

    Mirrors _parse_refinement_response: JSON first, then regex fallback,
    then a safe default. Never raises.
    """
    if not raw:
        return {"type": "other", "queries": []}

    # Try JSON first
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            q = parsed.get("queries") or []
            if isinstance(q, list):
                q = [str(x).strip() for x in q if str(x).strip()]
            parsed["queries"] = q
            return parsed
    except json.JSONDecodeError:
        pass

    # Strip markdown fences if present
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            q = parsed.get("queries") or []
            parsed["queries"] = [str(x) for x in q if str(x).strip()] if isinstance(q, list) else []
            return parsed
    except json.JSONDecodeError:
        pass

    # Regex fallback: pull the type + quoted query strings
    mtype = re.search(r'"type"\s*:\s*"([^"]+)"', stripped)
    queries = re.findall(r'"([^"]{3,})"', stripped)
    queries = [q for q in queries if q.lower() not in ("query", "task", "logistics",
                                                        "discussion", "banter", "emotional",
                                                        "intimate", "smalltalk", "other")]
    return {"type": mtype.group(1) if mtype else "other", "queries": queries}


# ── main entry point ────────────────────────────────────────────────────
def plan_recall(
    message: str,
    session_id: str | None = None,
    history: list[dict] | None = None,
    limit: int = 20,
) -> dict:
    """Plan the recall for a user message.

    Returns {"type": <str>, "queries": [<str>, ...], "planner": True}.
    - For light types (banter/emotional/intimate/smalltalk), queries is [] so
      the caller skips heavy recall entirely.
    - On any planner failure we degrade to a single query = the raw message,
      which is exactly the current single-vector behavior — never worse.

    Hot-path design: sends ONLY the user message to the LLM to generate
    searchable queries (no conversation-context scoping — that was a wasted
    multi-second round-trip after every message). The caller then checks the
    knowledge table with those queries and returns what it finds.
    """
    cfg = _get_config()
    if not cfg.get("enabled"):
        return {"type": "other", "queries": [message], "planner": False}

    # Context scoping on the hot path: pull the PREVIOUS 2-3 user messages
    # AND the last 2-3 completed assistant responses (finish_reason='stop',
    # truncated) so the planner knows the current conversational scope AND
    # how the agent already answered — WITHOUT paying the full last-N-
    # messages cost. Only *completed* assistant responses are included so
    # the planner never sees half-finished tool-call turns or empty tails.
    ctx_msgs = 0
    ctx_chars = 0
    _prior_user: list[str] = []
    _prior_assist: list[str] = []
    if history:
        # history is chronological (oldest -> newest). Walk it BACKWARD so we
        # collect the most RECENT 2-3 user messages and 2-3 completed
        # assistant responses, then reverse back to chronological order so the
        # LLM sees them oldest->newest in scope.
        for _h in reversed(history):
            _role = _h.get("role")
            if _role == "user" and len(_prior_user) < 3:
                _hts = _h.get("timestamp") or _h.get("time") or _h.get("ts")
                _hc = (_h.get("content") or "").strip()
                if not _hc:
                    continue
                _ts_part = f"[{_hts}] " if _hts else ""
                _prior_user.append(f"{_ts_part}user: {_hc[:300]}")
            elif (
                _role == "assistant"
                and _h.get("finish_reason") == "stop"
                and not _h.get("tool_calls")
                and len(_prior_assist) < 3
            ):
                _hts = _h.get("timestamp") or _h.get("time") or _h.get("ts")
                _hc = (_h.get("content") or "").strip()
                if not _hc:
                    continue
                _ts_part = f"[{_hts}] " if _hts else ""
                _prior_assist.append(f"{_ts_part}assistant: {_hc[:300]}")
        _prior_user.reverse()
        _prior_assist.reverse()
        ctx_msgs = len(_prior_user) + len(_prior_assist)
        ctx_chars = sum(len(x) for x in _prior_user) + sum(len(x) for x in _prior_assist)
        if ctx_msgs:
            logger.info(
                "recall_planner: scoped to last %d user + %d completed assistant "
                "msgs (%d chars) — msg=%r",
                len(_prior_user), len(_prior_assist), ctx_chars, message[:80],
            )

    _prior_block = "\n".join(_prior_user) if _prior_user else "(no prior user messages)"
    _assist_block = (
        "\n".join(_prior_assist) if _prior_assist else "(no prior assistant responses)"
    )
    user_prompt = f"""## User Message
{message}

## Prior User Messages
{_prior_block}

## Prior Assistant Responses (last completed turns, finish_reason=stop)
{_assist_block}

## Task
Classify the user message and plan the vector-search queries that would surface the most relevant stored context from the Knowledge table. Respond with JSON only."""

    raw = _call_refinement_llm(PLANNER_SYSTEM_PROMPT, user_prompt, loop_name="jpm_planner")
    plan = _parse_planner_response(raw)

    mtype = plan.get("type", "other")
    queries = plan.get("queries") or []

    # Log the LLM plan + the context dump it was built from, so a buggy
    # classification is traceable to exactly what the planner saw.
    logger.info(
        "recall_planner: LLM plan → type=%s queries=%r (ctx_msgs=%d ctx_chars=%d msg=%r)",
        mtype, queries, ctx_msgs, ctx_chars, message[:80],
    )

    # Type classification drives the recall budget
    if mtype in _LIGHT_TYPES:
        logger.info("recall_planner: type=%s — skipping heavy recall", mtype)
        return {"type": mtype, "queries": [], "planner": True}

    # Sanity-cap the query set. 3 well-scoped queries surface the same context
    # as 6 at half the embed+search cost — the planner's value is topic
    # coverage, not query volume.
    queries = [q for q in queries if q][:3]
    if not queries:
        queries = [message]

    return {"type": mtype, "queries": queries, "planner": True}

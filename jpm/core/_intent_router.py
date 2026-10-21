"""Intent router — maps messy real-world user phrasings to intent categories.

Uses the existing patterns table (pattern_type='intent') + pgvector cosine
similarity. Threshold-gated per intent; returns None when nothing clears the
bar (the default — banter and noise must NOT route).

Reuses _ollama.embed_query for embedding, the <=> cosine pattern from
_hybrid_search.py, and _recall_planner.looks_light as the cheap pre-filter
(which already has work-query vetoes + domain-noun overrides so real work
queries are never dropped).

Design contract (from the mining report + user requirements):
- The textbook phrasings almost never appear verbatim; users type messy
  variants ("doa session saerch", "told ya", "the fuckin sessionID"). Vector
  matching is the right call — FTS would miss all of these.
- "start over" is deliberately NOT seeded under start_fresh (too destructive).
- Curse words / ALL-CAPS are real frustration signals, not noise to strip.
- Threshold-gated, None as default. A message that matches no intent above
  threshold does nothing.
- The router ONLY surfaces intent as a context note. It never auto-triggers a
  tool — the LLM decides what to do with the routed intent.
"""

import logging

from jpm.core._ollama import embed_query
from jpm.core._pg import sync_conn
from jpm.core._recall_planner import looks_light

logger = logging.getLogger(__name__)

# Per-intent similarity thresholds, calibrated against real embedding scores
# (2026-08-13). Measured separation: real intents score 0.64-0.80, noise floor
# is 0.33-0.55. recall_frustration is the dominant pain point (13 sessions) so
# it gets the most lenient threshold. correction gets a higher bar because
# curse/ALL-CAPS already signal it strongly (its positive scores are 0.80+).
INTENT_THRESHOLDS = {
    "recall_frustration": 0.60,
    "save_remember": 0.62,
    "skill_usage": 0.62,
    "start_fresh": 0.62,
    "identity": 0.62,
    "correction": 0.65,
}

# Default threshold for any intent not in the map above.
DEFAULT_THRESHOLD = 0.75

# Phrases that must NEVER route, regardless of vector similarity. "start over"
# is semantically near "new session"/"new day" (all mean "begin anew"), so the
# vector matcher alone cannot distinguish it — and it is explicitly too
# destructive to map to a hard reset. This is the hard exclusion.
HARD_EXCLUDE = (
    "start over",
    "startover",
    "start it over",
    "restart from scratch",
)

# High-signal verbatim phrases -> intent. Real messages append extra words to
# the short seed phrases ("dont you remember the port", "what were we doing
# last time"), which dilutes cosine similarity below threshold. These phrases
# are distinctive enough that their presence is unambiguous, so we route on
# substring match BEFORE the vector matcher. This is the hybrid fallback the
# plan anticipated (vector + small alias layer for the highest-signal seeds).
HIGH_SIGNAL = {
    # recall_frustration (dominant pain point — 13 sessions)
    "you forgot": "recall_frustration",
    "we talked about": "recall_frustration",
    "dont you remember": "recall_frustration",
    "don't you remember": "recall_frustration",
    "catch up": "recall_frustration",
    "what were we doing": "recall_frustration",
    "i told you before": "recall_frustration",
    "I told you before": "recall_frustration",
    "doa session saerch": "recall_frustration",
    "you forget who you are": "recall_frustration",
    # save_remember
    "save this": "save_remember",
    "remember this": "save_remember",
    "keep this in mind": "save_remember",
    "save that to memory": "save_remember",
    # skill_usage
    "you had a skill for": "skill_usage",
    "use that skill": "skill_usage",
    "dont know to use it": "skill_usage",
    "why didnt you use the skill": "skill_usage",
    # start_fresh
    "new session": "start_fresh",
    "new day": "start_fresh",
    "new sess": "start_fresh",
    # identity
    "who are you": "identity",
    "whats your name": "identity",
    "what's your name": "identity",
    "identity intact": "identity",
    # correction
    "wrong path": "correction",
    "told ya": "correction",
    "well duh": "correction",
    "stupid logic": "correction",
    "assumptions": "correction",
    "be surgical": "correction",
}


def route_intent(message: str) -> dict | None:
    """Return {'intent': <name>, 'confidence': <float>, 'matched': <pattern_name>}
    or None if no intent clears its threshold.

    The intent category is stored in the pattern's `description` column
    (e.g. 'recall_frustration'); the pattern `name` is the specific seed
    (e.g. 'intent_recall_you_forgot').

    Hybrid matcher:
    1. Hard-exclude destructive phrases ("start over" -> None).
    2. High-signal substring match (verbatim seed phrases that survive
       appended words) -> route directly.
    3. Vector cosine matcher (typo/slang tolerance) -> route if above threshold.
    """
    if not message or not message.strip():
        return None

    # Cheap pre-filter: skip routing entirely for banter/emotional/smalltalk.
    # looks_light is conservative — it vetoes emotional phrases when work
    # markers or domain nouns co-occur, so real work queries still route.
    if looks_light(message):
        return None

    # Hard exclusion: destructive phrases never route.
    low = message.lower()
    for phrase in HARD_EXCLUDE:
        if phrase in low:
            return None

    # High-signal substring match: verbatim seed phrases route directly.
    # Case-insensitive so "Catch up" / "SAVE THIS" still match.
    for phrase, intent in HIGH_SIGNAL.items():
        if phrase.lower() in low:
            return {
                "intent": intent,
                "confidence": 1.0,
                "matched": f"high_signal:{phrase}",
            }

    vec = embed_query(message)
    if not vec:
        logger.warning("intent router: embedding failed, skipping")
        return None

    vec_literal = "[" + ",".join(str(x) for x in vec) + "]"
    with sync_conn() as c:
        rows = c.fetchall(
            f"""
            SELECT name, description, pattern_type, confidence,
                   embedding <=> '{vec_literal}'::vector AS dist
            FROM patterns
            WHERE pattern_type = 'intent' AND archived = 0
            ORDER BY dist ASC
            LIMIT 1
            """
        )
    if not rows:
        return None

    best = rows[0]
    sim = 1.0 - best["dist"]
    intent = best["description"]
    threshold = INTENT_THRESHOLDS.get(intent, DEFAULT_THRESHOLD)
    if sim < threshold:
        return None
    return {
        "intent": intent,
        "confidence": round(sim, 3),
        "matched": best["name"],
    }

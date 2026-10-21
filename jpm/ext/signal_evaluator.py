"""Signal evaluator — real-time trigger matching at turn start.

Signals are written by self_improvement's agent growth LLM call.
Instead of dumping all signals into the cache and making the LLM guess
which one matches, this evaluator checks triggers against the incoming
user message and injects only matching actions as directives.

Flow:
  turn_context.py:build_turn_context()
    → evaluate_signals(user_message)
    → if match: inject directive into plugin_user_context
"""

import logging
import re

from jpm.core._pg import sync_conn

logger = logging.getLogger("♻️ signals")


def evaluate_signals(user_message: str) -> str:
    """Check enabled signals against the incoming user message.

    Returns a directive string to inject into plugin_user_context,
    or empty string if no signal matches.
    """
    if not user_message or not user_message.strip():
        return ""

    try:
        with sync_conn() as conn:
            rows = conn.fetchall(
                "SELECT trigger, action, description "
                "FROM signals WHERE enabled = 1 "
                "ORDER BY id DESC"
            )
    except Exception:
        logger.debug("signal evaluator: DB query failed", exc_info=True)
        return ""

    if not rows:
        return ""

    msg_lower = user_message.lower()
    matched: list[str] = []

    for row in rows:
        trigger = (row["trigger"] or "").lower().strip()
        action = (row["action"] or "").strip()
        desc = (row["description"] or "").strip()

        if not trigger or not action:
            continue

        # Check if trigger keywords appear in the user message
        # Support comma-separated keywords: any match fires
        keywords = [kw.strip() for kw in trigger.split(",") if kw.strip()]
        if not keywords:
            continue

        if any(kw in msg_lower for kw in keywords):
            directive = f"[Signal: {action}]"
            if desc:
                directive += f" — {desc}"
            matched.append(directive)

    if not matched:
        return ""

    return "\n".join(matched)

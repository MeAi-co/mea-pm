"""mea_prompt — MEAI prompt optimization layer (stock-Hermes plugin).

Registers an ``llm_request`` middleware that splits the active memory
provider's system-prompt block by STABILITY, mirroring the fork's
``core/agent/conversation_loop.py`` injection without touching the stock tree:

  * STABLE  (identity / soul / user_pref / memory / rules / breadcrumbs)
    -> a ``role='system'`` row inserted right after slot 0 (the cached
       prefix). Byte-stable across turns, so the provider prefix cache
       stays warm.
  * DRIFT   (state: pulse / focus / loops / tone)
    -> a ``role='system'`` row inserted at the TAIL, after the last user
       row. Drifts every turn, so it must never sit above the cached replay.

Why this exists: stock renders the provider block into slot 0 via
``agent.system_prompt._memory_parts`` -> ``memory_manager.build_system_prompt()``.
That block carries the volatile ``state`` section, so it cold-cuts the cached
prefix every turn. This middleware removes ``state`` from slot 0 (replacing the
provider block with its stable-only form) and re-injects it at the tail.

Approach A (Josh, 2026-10-12): the middleware reads the active provider's
``system_prompt_sections()`` — the vendored engine already exposes the split.

Fail-open: any error returns ``None`` so the request passes through untouched.
"""
from __future__ import annotations

import logging

LOG = logging.getLogger(__name__)

# Canonical stable order (matches the vendored provider's own order, minus state).
_STABLE_ORDER = ("identity", "soul", "user_pref", "memory", "rules", "breadcrumbs")

# Stock's TOOL_USE_ENFORCEMENT_GUIDANCE permits a response that is ONLY tool
# calls: "Every response should either (a) contain tool calls that make
# progress, or (b) deliver a final result". It never requires text alongside
# the call, so a model can emit bare tool calls turn after turn and still be
# compliant. The fork fixed this by adding "Narrate your move ... along with a
# short rich signal narration content" to that same block; stock has no such
# line (verified: 'Narrate' absent from stock agent/prompt_builder.py).
#
# This directive restores the requirement at the plugin seam so the stock tree
# stays untouched. It rides the DRIFT tail (after the last user row), so the
# cached prefix is unaffected.
_NARRATION_DIRECTIVE = (
    "## Narration requirement\n"
    "Every response that fires tool calls MUST also carry a short narration "
    "line stating what you are about to do and why — one sentence, before the "
    "calls. A response containing ONLY tool calls with no text is not "
    "acceptable. Do not narrate after the fact; state the intent as you act."
)

_PROVIDER = None
_PROVIDER_SESSION = None

# Terminator of the provider block. `system_prompt_block()` always appends this
# line last, so it is a stable end-anchor even when the body differs.
_BLOCK_TERMINATOR = "Tools: jpm ("

# Markers that can begin the provider block. Stock embeds the block into slot 0
# via `_memory_parts` -> `memory_manager.build_system_prompt()`, and the bytes it
# embeds are NOT always identical to a freshly computed `system_prompt_block()`:
# the state section is rebuilt per turn and can be truncated mid-line, so an
# exact `full_block in slot0` test silently misses and the volatile block stays
# in the cached prefix. We therefore strip STRUCTURALLY: from the first block
# marker after the skills index, through the terminator.
_BLOCK_START_MARKERS = (
    "# JPM VAULT Memory",
    "- *user_pref:*",
    "- *memory_entry:*",
    "- *rule:*",
    "- *identity:*",
    "- *soul:*",
    "- **Status:**",
    "- **Focus:**",
    "- **User tone:**",
)


def _strip_provider_block(slot0: str) -> str | None:
    """Remove the provider memory block from slot 0 by structure, not by exact match.

    Returns the stripped slot 0, or ``None`` when no block is present (so the
    caller can fall back to the exact-match path or leave slot 0 untouched).
    """
    end = slot0.find(_BLOCK_TERMINATOR)
    if end < 0:
        return None
    # Close out the terminator line so we don't leave a dangling fragment.
    nl = slot0.find("\n", end)
    end = len(slot0) if nl < 0 else nl

    # Bound the search to the region after the skills index: the memory block is
    # appended to the volatile tier, which follows the skills prompt.
    floor = slot0.rfind("</available_skills>")
    floor = 0 if floor < 0 else floor

    start = -1
    for marker in _BLOCK_START_MARKERS:
        i = slot0.find(marker, floor)
        if i >= 0 and i < end and (start < 0 or i < start):
            start = i
    if start < 0:
        return None

    out = (slot0[:start].rstrip() + "\n\n" + slot0[end:].lstrip()).strip()
    return out if out != slot0 else None


def _get_provider(session_id: str):
    """Load (and cache) the active memory provider instance.

    The middleware context carries no agent, so we resolve the provider by
    name. Cached per session so we don't re-import on every API call.
    """
    global _PROVIDER, _PROVIDER_SESSION
    if _PROVIDER is not None and _PROVIDER_SESSION == session_id:
        return _PROVIDER
    try:
        from plugins.memory import load_memory_provider
        prov = load_memory_provider("mea_pm", register_skills=False)
        if prov is not None:
            try:
                prov.initialize(session_id or "mea_prompt", chat_type="dm")
            except Exception:
                pass
        _PROVIDER = prov
        _PROVIDER_SESSION = session_id
        return prov
    except Exception as exc:
        LOG.debug("mea_prompt: provider load failed: %s", exc)
        return None


def _split_sections(provider) -> tuple[str, str]:
    """Return ``(stable_markdown, drift_markdown)`` from the provider."""
    try:
        sections = provider.system_prompt_sections() or {}
    except Exception as exc:
        LOG.debug("mea_prompt: system_prompt_sections failed: %s", exc)
        return "", ""
    stable = "\n\n".join(
        sections[k] for k in _STABLE_ORDER if sections.get(k)
    )
    drift = sections.get("state", "") or ""
    return stable, drift


def _rewrite(request=None, **ctx):
    """``llm_request`` middleware: split the provider block stable/drift."""
    try:
        if not isinstance(request, dict):
            return None
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        if messages[0].get("role") != "system":
            return None

        session_id = str(ctx.get("session_id") or "")
        provider = _get_provider(session_id)

        # Narration is INDEPENDENT of the memory provider. It must land even
        # when the provider fails to load or returns no sections, otherwise a
        # PG hiccup silently disables it — the exact fail-open trap this
        # plugin already has. Resolve it first, then layer the split on top.
        stable, drift, full_block = "", "", ""
        if provider is not None:
            stable, drift = _split_sections(provider)
            try:
                full_block = provider.system_prompt_block() or ""
            except Exception:
                full_block = ""

        slot0 = messages[0].get("content") or ""
        new_slot0 = slot0
        stripped = _strip_provider_block(slot0)
        if stripped is not None:
            new_slot0 = stripped
        elif full_block and full_block in slot0:
            # Fallback: exact match (only works when the freshly-computed
            # block is byte-identical to the one stock embedded).
            new_slot0 = slot0.replace(full_block, "", 1)
            new_slot0 = new_slot0.replace("\n\n\n\n", "\n\n").strip()

        out = list(messages)
        if new_slot0 != slot0:
            out[0] = {**messages[0], "content": new_slot0}

        # STABLE -> [s1], right after slot 0 (and after any anchor row).
        if stable:
            at = 1
            if len(out) > 1 and out[1].get("role") == "system":
                at = 2
            out.insert(at, {"role": "system", "content": stable})

        # DRIFT -> tail, after the last user row.
        tail_at = len(out)
        for i in range(len(out) - 1, -1, -1):
            if out[i].get("role") == "user":
                tail_at = i + 1
                break
        if drift:
            out.insert(tail_at, {"role": "system", "content": "## Live State\n\n" + drift})
            tail_at += 1
        # Narration requirement rides the tail too: volatile-by-design, never
        # in the cached prefix, and always present even when drift is empty.
        out.insert(tail_at, {"role": "system", "content": _NARRATION_DIRECTIVE})

        if out == messages:
            return None
        return {"request": {**request, "messages": out}}
    except Exception as exc:
        LOG.warning("mea_prompt: rewrite failed (fail-open): %s", exc)
        return None


def register(ctx) -> None:
    """Stock plugin entry point: register the llm_request middleware."""
    ctx.register_middleware("llm_request", _rewrite)

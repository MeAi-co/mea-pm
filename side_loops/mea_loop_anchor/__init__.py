"""mea_loop_anchor — MEAI per-loop plugin: volatile session anchor (P6.5).

One loop = one plugin = one config flag. The anchor is split across two seams
because stock hooks/middleware never receive the live agent:

  * GENERATION (DB-only) -> a ``post_llm_call`` hook launches a detached
    subprocess (``_mea_loops_core.launch_loop``) that reads the lean trajectory,
    condenses it to 1-3 first-person sentences, and persists it to the anchor
    store. Fires on the NUDGE boundary only (every ``interval`` turns), so the
    tail cache stays warm between nudges.
  * INJECTION (in-process) -> an ``llm_request`` middleware reads the stored
    anchor and inserts it at position 1 (right after the cached system prompt),
    mirroring the fork's ``_inject_anchor``.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-anchor:
          settings:
            enabled: true
            interval: 10

Fail-open: any error returns immediately; the turn is never blocked.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_PLUGINS_DIR = _Path(__file__).resolve().parent.parent
if str(_PLUGINS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_PLUGINS_DIR))

import logging

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-loop-anchor"
LOOP_NAME = "anchor"
_DEFAULT_INTERVAL = 10


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: launch anchor generation on the nudge boundary."""
    try:
        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return
        session_id = str(ctx.get("session_id") or "")
        if not session_id:
            return
        interval = int(core.read_flag(PLUGIN_ID, "interval", _DEFAULT_INTERVAL) or _DEFAULT_INTERVAL)
        from _mea_loops_core import anchor_store
        if not anchor_store.bump_and_check(session_id, interval, loop=LOOP_NAME):
            return
        turn_id = str(ctx.get("turn_id") or "")
        payload = {
            "platform": ctx.get("platform") or "",
            "model": ctx.get("model") or "",
        }
        core.launch_loop(LOOP_NAME, session_id=session_id, turn_id=turn_id, payload=payload)
    except Exception as exc:
        LOG.warning("mea_loop_anchor: hook failed (fail-open): %s", exc)


def _inject(request=None, **ctx) -> None:
    """``llm_request`` middleware: insert the stored anchor at position 1."""
    try:
        if not isinstance(request, dict):
            return None
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        if messages[0].get("role") != "system":
            return None
        session_id = str(ctx.get("session_id") or "")
        if not session_id:
            return None
        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return None
        from _mea_loops_core import anchor_store
        anchor = anchor_store.get_anchor(session_id)
        if not anchor:
            return None
        # Guard against a stray duplicate on repeated injection.
        for m in messages[1:3]:
            if m.get("role") == "system" and m.get("content") == anchor:
                return None
        out = list(messages)
        out.insert(1, {"role": "system", "content": anchor})
        return {"request": {**request, "messages": out}}
    except Exception as exc:
        LOG.warning("mea_loop_anchor: inject failed (fail-open): %s", exc)
        return None


def register(ctx) -> None:
    """Stock plugin entry point: register the hook + the injection middleware."""
    ctx.register_hook("post_llm_call", _on_post_llm_call)
    ctx.register_middleware("llm_request", _inject)

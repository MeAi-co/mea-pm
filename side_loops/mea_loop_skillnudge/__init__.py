"""mea_loop_skillnudge — MEAI per-loop plugin: skill nudges (P6.6).

One loop = one plugin = one config flag. The skill directives are IN-PROCESS:
they mutate the request messages at API-call time, and stock hooks never
receive the agent — so they ride the ``llm_request`` middleware (which receives
``api_call_count`` and can rewrite ``request["messages"]``).

Two directives, mirroring the fork's ``conversation_loop.py``:

  * LOAD nudge — fires on the first api call when no skill is loaded, and
    re-arms mid-turn when a substantive tool fires with no skill loaded.
    Capped at 3 fires/turn (checked on the INJECTION path).
  * MAINTENANCE nudge — turn-end: update the loaded skill, or patch-or-create
    when none was loaded.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-skillnudge:
          settings:
            enabled: true
            max_load_nudges: 3

Fail-open: any error returns None; the request passes through untouched.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_PLUGINS_DIR = _Path(__file__).resolve().parent.parent
if str(_PLUGINS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_PLUGINS_DIR))

import logging

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-loop-skillnudge"
_DEFAULT_MAX = 3

# Per-session turn state (the middleware has no agent to hang counters on).
_STATE: dict = {}


def _state_for(session_id: str) -> dict:
    st = _STATE.get(session_id)
    if st is None:
        st = {"load_count": 0, "maint_pending": False, "turn": ""}
        _STATE[session_id] = st
    return st


def _rewrite(request=None, **ctx) -> None:
    """``llm_request`` middleware: inject the pending skill directives."""
    try:
        if not isinstance(request, dict):
            return None
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return None
        if messages[0].get("role") != "system":
            return None

        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return None

        session_id = str(ctx.get("session_id") or "")
        if not session_id:
            return None
        api_call_count = int(ctx.get("api_call_count") or 0)
        turn_id = str(ctx.get("turn_id") or "")

        from _mea_loops_core.vendor import skill_nudges as sn

        st = _state_for(session_id)
        # New turn -> reset the per-turn counters.
        if turn_id and st.get("turn") != turn_id:
            st["turn"] = turn_id
            st["load_count"] = 0
            st["maint_pending"] = False

        max_load = int(core.read_flag(PLUGIN_ID, "max_load_nudges", _DEFAULT_MAX) or _DEFAULT_MAX)

        loaded = sn.detect_fully_loaded_skills(messages)
        directives = []

        # MAINTENANCE: armed when a substantive tool fired with no skill loaded.
        if st.get("maint_pending"):
            if loaded:
                directives.append(sn.MAINT_NUDGE_LOADED.format(names=", ".join(sorted(loaded))))
            else:
                directives.append(sn.MAINT_NUDGE_NONE)

        # LOAD: first call with nothing loaded, or mid-turn re-arm.
        # STRIPPED (Josh 2026-10-17): the LOAD nudge no longer rides the user
        # row. Injecting it as role="user" made the model answer it as a real
        # turn — one wasted skill_choose call, then the real work (the observed
        # 2x). The MAINT nudge below still fires. Restore this block to re-enable.
        # if not loaded and st["load_count"] < max_load:
        #     if api_call_count == 1 or sn.has_substantive_tool_use(messages):
        #         st["load_count"] += 1
        #         directives.append(sn.LOAD_NUDGE)

        if not directives:
            return None

        out = list(messages)
        out.append({"role": "user", "content": "\n\n".join(directives)})
        return {"request": {**request, "messages": out}}
    except Exception as exc:
        LOG.warning("mea_loop_skillnudge: rewrite failed (fail-open): %s", exc)
        return None


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: arm the maintenance nudge for the next turn."""
    try:
        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return
        session_id = str(ctx.get("session_id") or "")
        if not session_id:
            return
        history = ctx.get("conversation_history") or []
        from _mea_loops_core.vendor import skill_nudges as sn
        st = _state_for(session_id)
        # Arm only when the turn did substantive work (mirrors the fork's
        # no-tool-call branch arming the maintenance nudge).
        st["maint_pending"] = bool(sn.has_substantive_tool_use(history))
    except Exception as exc:
        LOG.warning("mea_loop_skillnudge: hook failed (fail-open): %s", exc)


def register(ctx) -> None:
    """Stock plugin entry point: register the middleware + the arming hook."""
    ctx.register_middleware("llm_request", _rewrite)
    ctx.register_hook("post_llm_call", _on_post_llm_call)

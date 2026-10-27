"""mea_loop_selfimpr — MEAI per-loop plugin: self-improvement (nudge boundary).

One loop = one plugin = one detached subprocess = one config flag.

Fires on the real-user-turn nudge boundary (``_should_review_memory`` /
``_should_review_agent``). The engine (``jpm.ext.self_improvement``) reads only
``session_id`` + the two nudge intervals off the agent, so a shim suffices and
the whole loop runs in its own process.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-selfimpr:
          settings:
            enabled: true

Fail-open: any error in the hook returns immediately; the turn is never blocked.
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_PLUGINS_DIR = _Path(__file__).resolve().parent.parent
if str(_PLUGINS_DIR) not in _sys.path:
    _sys.path.insert(0, str(_PLUGINS_DIR))

import logging

LOG = logging.getLogger(__name__)

PLUGIN_ID = "mea-loop-selfimpr"
LOOP_NAME = "self_impr"


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: launch the self-improvement loop in its own process."""
    try:
        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return
        session_id = str(ctx.get("session_id") or "")
        turn_id = str(ctx.get("turn_id") or "")
        history = ctx.get("conversation_history") or []
        payload = {
            "messages": history,
            "platform": ctx.get("platform") or "",
            "model": ctx.get("model") or "",
            "review_memory": True,
            "review_skills": True,
        }
        core.launch_loop(LOOP_NAME, session_id=session_id, turn_id=turn_id, payload=payload)
    except Exception as exc:
        LOG.warning("mea_loop_selfimpr: hook failed (fail-open): %s", exc)


def register(ctx) -> None:
    """Stock plugin entry point: register the post_llm_call hook."""
    ctx.register_hook("post_llm_call", _on_post_llm_call)

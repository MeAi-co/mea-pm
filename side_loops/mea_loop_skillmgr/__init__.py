"""mea_loop_skillmgr — MEAI per-loop plugin: OOB skill-manager classifier (P6.6).

One loop = one plugin = one detached subprocess = one config flag.

The fork's ``core/agent/skill_manager.py`` classifies the current user turn as
reply / task / project via an LLM call (observation mode — the verdict is
logged, not injected). It is DB-only (reads the catalog + recent messages,
calls the LLM), so it detaches cleanly into its own process.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-skillmgr:
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

PLUGIN_ID = "mea-loop-skillmgr"
LOOP_NAME = "skillmgr"


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: launch the skill-manager classifier in its own process."""
    try:
        import _mea_loops_core as core
        if not core.loop_enabled(PLUGIN_ID, default=True):
            return
        session_id = str(ctx.get("session_id") or "")
        turn_id = str(ctx.get("turn_id") or "")
        payload = {
            "message_text": ctx.get("user_message") or "",
            "turn_id": turn_id,
            "platform": ctx.get("platform") or "",
            "model": ctx.get("model") or "",
        }
        core.launch_loop(LOOP_NAME, session_id=session_id, turn_id=turn_id, payload=payload)
    except Exception as exc:
        LOG.warning("mea_loop_skillmgr: hook failed (fail-open): %s", exc)


def register(ctx) -> None:
    """Stock plugin entry point: register the post_llm_call hook."""
    ctx.register_hook("post_llm_call", _on_post_llm_call)

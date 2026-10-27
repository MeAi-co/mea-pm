"""mea_loop_statesync — MEAI per-loop plugin: turn-end state sync.

One loop = one plugin = one detached subprocess = one config flag.

The fork runs ALL turn-end loops sequentially in ONE daemon thread under a
single watchdog budget; one wedge starves the rest. This plugin registers a
``post_llm_call`` hook that does NOTHING but launch a detached subprocess
(``_mea_loops_core.launch_loop``) to run the state-sync loop. A wedge in the
loop kills only that subprocess.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-statesync:
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

PLUGIN_ID = "mea-loop-statesync"
LOOP_NAME = "state_sync"


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: launch the state-sync loop in its own process."""
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
        }
        core.launch_loop(LOOP_NAME, session_id=session_id, turn_id=turn_id, payload=payload)
    except Exception as exc:
        LOG.warning("mea_loop_statesync: hook failed (fail-open): %s", exc)


def register(ctx) -> None:
    """Stock plugin entry point: register the post_llm_call hook."""
    ctx.register_hook("post_llm_call", _on_post_llm_call)

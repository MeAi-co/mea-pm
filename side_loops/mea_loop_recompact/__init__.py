"""mea_loop_recompact — MEAI per-loop plugin: tier-2 session-summary recompact.

One loop = one plugin = one detached subprocess = one config flag.

The fork runs the tier-2 recompact inside the SAME daemon thread as every other
turn-end loop, right after the anchor refresh, under one watchdog budget; a
wedge starves the rest. This plugin registers a ``post_llm_call`` hook that does
NOTHING but launch a detached subprocess (``_mea_loops_core.launch_loop``) to run
the recompact. A wedge kills only that subprocess.

The recompact is DB-only (reads ``session_summary_log``, writes
``sessions.summary``, flips absorbed rows — all via ``jpm.core._pg``), so it
detaches cleanly. It rides the SAME nudge boundary as the anchor (every
``interval`` turns) so the fresh anchor can feed in as a source.

Config flag (profile ``config.yaml``)::

    plugins:
      entries:
        mea-loop-recompact:
          settings:
            enabled: true
            interval: 10

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

PLUGIN_ID = "mea-loop-recompact"
LOOP_NAME = "recompact"
_DEFAULT_INTERVAL = 10


def _on_post_llm_call(**ctx) -> None:
    """``post_llm_call`` hook: launch the recompact on the nudge boundary."""
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
        LOG.warning("mea_loop_recompact: hook failed (fail-open): %s", exc)


def register(ctx) -> None:
    """Stock plugin entry point: register the post_llm_call hook."""
    ctx.register_hook("post_llm_call", _on_post_llm_call)
